"""Capability records, the Policy Engine, and gated mutation (contract D12).

V1's `AuthorityToken` was an unsigned frozen dataclass. Any caller could
construct one with `authority_source="i_made_this_up"` and release a lot. That
is deleted. It is not refactored, because the flaw was the design.

V2 mechanism: an issuer-authenticated capability RECORD, written only by the
Policy Engine, consumed by a single atomic conditional write.

    consume iff  the row exists
            and  it was written by an authorized issuer
            and  it is unused
            and  it is unexpired
            and  target and action match exactly
            and  it belongs to this DecisionRecord
            and  the target's CURRENT state_version equals the bound version

Then, in the same atomic step: perform the transition, mark consumed, append to
the ledger.

Two properties this module must enforce, both proven by the audit to have been
missing at b8f54b0:

**Issuance is authorized, not merely conventional (P0-1, audit-2 F1).** The
capability store can VERIFY a proof and cannot CREATE one. Signing authority
lives in `issuance.py`, which exports no signer; `PolicyEngine` obtains a
one-shot `IssuanceAuthority` by class identity, and nothing else can. Holding
the store object grants no path to a valid capability — there is no
`_mint_issuer`, and `issue()` without an `IssuanceAuthority` is a refusal.

**Consumption dispatches internally (P0-2).** `consume()` takes a capability id
and NOTHING executable. The mutation is looked up from a closed table keyed by
the capability's own bound action, applied to the capability's own bound target,
using the capability's own SIGNED parameters (audit-2 F7). There is no
parameter through which a caller can supply a callable, redirect a target, or
choose a different slot at execution time.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import uuid
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

from .contracts import Disposition, FailureCategory, VouchFailure
from .corpus import Corpus
from .issuance import (
    PROOF_VERSION,
    IssuanceAuthority,
    IssuanceViolation,
)
from .issuance import authority as _claim_issuance_authority
from .issuance import verify as verify_proof
from .lifecycle import EventLog, EventType, utcnow
from .reconcile import POLICY_VERSION

CAPABILITY_TTL_SECONDS = 300


class Action(str, Enum):
    RELEASE_LOT = "release_lot"
    QUARANTINE_LOT = "quarantine_lot"
    CREATE_QA_REVIEW = "create_qa_review"
    HOLD_PRODUCTION_ORDER = "hold_production_order"
    RESEQUENCE_PRODUCTION_ORDER = "resequence_production_order"
    #: Readiness is a persisted state transition, not a computed view (P1-6).
    SET_ORDER_READINESS = "set_order_readiness"


class TargetType(str, Enum):
    LOT = "lot"
    PRODUCTION_ORDER = "production_order"


@dataclass(frozen=True)
class CapabilityRecord:
    """Server-controlled authority to perform exactly one mutation, once.

    `issuer_proof` is an HMAC over the COMPLETE binding — including
    `parameters` (audit-2 F7) — produced by the `issuance` module's private
    key. The capability store can check it and cannot produce it, so a record
    hand-constructed by any caller, however syntactically correct, fails
    verification.

    `parameters` carries the action-specific values the Policy Engine committed
    to at authorization time: the target slot for a resequence, the readiness
    state for a readiness transition. They are signed, and consumption reads
    them from HERE rather than from anything the caller passes.
    """

    capability_id: str
    decision_record_id: str
    target_type: TargetType
    target_id: str
    action: Action
    observed_state_version: int
    policy_version: str
    expires_at: str
    nonce: str
    issuer_proof: str
    #: Which authorized issuer created this row. Covered by the signature, so
    #: it is trustworthy provenance rather than a self-asserted label.
    issuer_identity: str = ""
    #: Signed, immutable action parameters (audit-2 F7).
    parameters: tuple[tuple[str, str], ...] = ()
    used: bool = False
    consumed_at: str = ""

    def binding(self) -> dict:
        """Everything the proof covers.

        A dict rather than a delimiter-joined string: joining on "|" means a
        value containing "|" could shift a field boundary, and adding a field
        to a positional string is a silent compatibility break. Keys are
        explicit and the canonical form is sorted JSON.
        """
        return {
            "v": PROOF_VERSION,
            "capability_id": self.capability_id,
            "decision_record_id": self.decision_record_id,
            "target_type": self.target_type.value,
            "target_id": self.target_id,
            "action": self.action.value,
            "observed_state_version": self.observed_state_version,
            "policy_version": self.policy_version,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
            "issuer_identity": self.issuer_identity,
            "parameters": dict(self.parameters),
        }

    @property
    def params(self) -> dict[str, str]:
        """The signed parameters as a plain dict."""
        return dict(self.parameters)

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now > datetime.fromisoformat(self.expires_at)


def freeze_parameters(params: dict | None) -> tuple[tuple[str, str], ...]:
    """Normalize action parameters into a hashable, signable, ordered form."""
    return tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))


class IssuerViolation(PermissionError):
    """Something other than an authorized issuer tried to create authority."""


class CapabilityStore:
    """Persisted capability rows with atomic conditional consumption.

    The lock is what DynamoDB's ConditionExpression provides in production; the
    semantics proven here are identical. `consume` is the single place a
    capability is spent, and it is the single place state mutates.

    This class holds **no signing key and no minting method** (audit-2 F1). It
    imports `issuance.verify` and nothing else, so possession of a store is
    possession of a verifier — never of an issuer.

    ponytail: threading.Lock, not a distributed lock. Single-process semantics
    match the conditional-write guarantee; the DynamoDB adapter (aws.py) swaps
    this for a TransactWriteItems with the same conditions.
    """

    def __init__(self) -> None:
        self._rows: dict[str, CapabilityRecord] = {}
        self._lock = threading.RLock()
        self._ledger: list[dict] = []

    # -- issuance (authorized issuers only) --------------------------------
    def issue(
        self,
        issuer: IssuanceAuthority,
        *,
        decision_record_id: str,
        target_type: TargetType,
        target_id: str,
        action: Action,
        observed_state_version: int,
        parameters: dict | None = None,
        ttl_seconds: int = CAPABILITY_TTL_SECONDS,
    ) -> CapabilityRecord:
        """Write a capability row. Requires a real `IssuanceAuthority`.

        The store does not decide whether the issuer is legitimate by looking
        at a name it was handed; it asks the issuer to SIGN, then verifies that
        signature with the public verifier. Only the Policy Engine's authority
        can produce a signature that verifies, so an impostor's row is refused
        before it is ever stored.
        """
        if not isinstance(issuer, IssuanceAuthority):
            identity = getattr(issuer, "identity", type(issuer).__name__)
            raise IssuerViolation(
                f"{identity!r} is not authorized to issue capabilities; "
                "only the Policy Engine may create authority"
            )

        capability_id = f"CAP-{uuid.uuid4().hex[:16]}"
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        ).isoformat()
        skeleton = CapabilityRecord(
            capability_id=capability_id,
            decision_record_id=decision_record_id,
            target_type=target_type,
            target_id=target_id,
            action=action,
            observed_state_version=observed_state_version,
            policy_version=POLICY_VERSION,
            expires_at=expires_at,
            nonce=secrets.token_hex(16),
            issuer_proof="",
            issuer_identity=issuer.identity,
            parameters=freeze_parameters(parameters),
        )
        record = replace(skeleton, issuer_proof=issuer.sign(skeleton.binding()))

        # Verify before storing. A forged authority object whose `sign` returns
        # junk gets its row rejected here rather than at consume time, so an
        # unauthorized path produces ZERO capability rows (F1 pass condition).
        if not verify_proof(record.binding(), record.issuer_proof):
            raise IssuerViolation(
                f"{issuer.identity!r} produced an invalid issuer proof; "
                "refusing to store a capability"
            )

        with self._lock:
            self._rows[capability_id] = record
        return record

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._rows.get(capability_id)

    def _authentic(self, record: CapabilityRecord) -> bool:
        return verify_proof(record.binding(), record.issuer_proof)

    # -- consumption -------------------------------------------------------
    def consume(
        self,
        capability_id: str,
        corpus: Corpus,
        *,
        params: dict | None = None,
    ) -> dict:
        """The ONLY path to a state mutation (P0-2).

        Takes an ID — never a callable, and never execution parameters that
        matter. The mutation is resolved from the closed `MUTATIONS` table
        using the STORED record's own action, applied to the STORED record's
        own target, with the STORED record's own SIGNED parameters (F7). The
        `params` argument is accepted only for interface symmetry with callers
        that pass nothing meaningful; it is discarded.

        Every check happens inside the lock, together with the transition and
        the ledger append. There is no window between validating and acting.
        """
        with self._lock:
            stored = self._rows.get(capability_id)

            # 1. unforgeability + issuer authenticity
            if stored is None:
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    "no Policy-Engine-issued capability for this id",
                )
            if not self._authentic(stored):
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL, "capability failed issuer authentication"
                )

            # 2. single use
            if stored.used:
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    f"capability {stored.capability_id} already consumed at {stored.consumed_at}",
                )

            # 3. expiry
            if stored.is_expired():
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL, "capability has expired"
                )

            # 4. the action must resolve in the closed dispatch table
            apply_change = MUTATIONS.get(stored.action)
            if apply_change is None:
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    f"no mutation is bound to {stored.action.value}; refusing",
                )

            # 5. action must be legal for the bound target TYPE (F6). A lot
            #    action against an order target is refused independently of
            #    whatever the mutation function would have done.
            if stored.action not in ACTION_TARGET_TYPES.get(stored.target_type, frozenset()):
                raise VouchFailure(
                    FailureCategory.POLICY_REFUSAL,
                    f"{stored.action.value} is not a {stored.target_type.value} action",
                )

            # 6. the bound target must exist and be of the bound type
            if corpus.get(stored.target_type.value, stored.target_id) is None:
                raise VouchFailure(
                    FailureCategory.STATE_CONFLICT,
                    f"{stored.target_type.value} {stored.target_id} does not exist",
                )

            # 7. state-version binding — kills TOCTOU
            current_version = corpus.version_of(stored.target_type.value, stored.target_id)
            if current_version != stored.observed_state_version:
                raise VouchFailure(
                    FailureCategory.STATE_CONFLICT,
                    f"{stored.target_id} moved from version "
                    f"{stored.observed_state_version} to {current_version}; re-evaluate",
                )

            # 8. legal source-state transition, checked HERE and not only at
            #    authorization time (F6): state may have moved, and the gate
            #    that mutates is the gate that must be sure.
            before_state = _state_of(corpus, stored.target_type, stored.target_id)
            _assert_legal_transition(corpus, stored)

            # 9. transition + consume + ledger, atomically
            before = current_version
            outcome = apply_change(corpus, stored)
            after = corpus.version_of(stored.target_type.value, stored.target_id)
            after_state = _state_of(corpus, stored.target_type, stored.target_id)

            self._rows[stored.capability_id] = replace(
                stored, used=True, consumed_at=utcnow()
            )
            sequence = len(self._ledger) + 1
            entry = {
                "sequence": sequence,
                "capability_id": stored.capability_id,
                "decision_record_id": stored.decision_record_id,
                "issuer_identity": stored.issuer_identity,
                "action": stored.action.value,
                "target_type": stored.target_type.value,
                "target_id": stored.target_id,
                "parameters": stored.params,
                "before_version": before,
                "after_version": after,
                # F6: the ledger records the ACTUAL before/after domain state,
                # not only opaque version numbers.
                "before_state": before_state,
                "after_state": after_state,
                "result": outcome.get("result", ""),
                "inventory_delta": outcome.get("inventory_delta", 0.0),
                "inventory_before": outcome.get("inventory_before"),
                "inventory_after": outcome.get("inventory_after"),
                "side_effects": outcome.get("side_effects", {}),
                "at": utcnow(),
            }
            self._ledger.append(entry)
            return entry

    @property
    def ledger(self) -> list[dict]:
        return list(self._ledger)


def _state_of(corpus: Corpus, target_type: TargetType, target_id: str) -> dict:
    """A snapshot of the authoritative fields an action can change (F6)."""
    obj = corpus.get(target_type.value, target_id)
    if obj is None:
        return {}
    snapshot = {
        "status": getattr(obj, "status", ""),
        "state_version": getattr(obj, "state_version", 0),
    }
    if target_type is TargetType.PRODUCTION_ORDER:
        snapshot["planned_slot"] = getattr(obj, "planned_slot", "")
    else:
        inventory = corpus.get("inventory", target_id)
        if inventory is not None:
            snapshot["inventory_usable"] = inventory.usable
            snapshot["inventory_quantity"] = inventory.quantity
    return snapshot


# ==========================================================================
# Policy Engine — the only issuer
# ==========================================================================


@dataclass
class PolicyDecision:
    allowed: bool
    action: Action | None
    reason: str
    capability: CapabilityRecord | None = None


#: Legal lot transitions. A released lot is not re-released; a quarantined lot
#: needs a new case to move. Kept from V1 — this part was well-built.
LOT_TRANSITIONS: dict[str, set[str]] = {
    "RECEIVED": {"RELEASED", "QUARANTINED", "PENDING_QA"},
    "PENDING_QA": {"RELEASED", "QUARANTINED", "PENDING_QA", "REJECTED"},
    "RELEASED": set(),
    "QUARANTINED": {"REJECTED"},
    "REJECTED": set(),
}

ORDER_TRANSITIONS: dict[str, set[str]] = {
    "READY": {"AT_RISK", "BLOCKED", "COMPLETE"},
    "AT_RISK": {"READY", "BLOCKED", "COMPLETE"},
    "BLOCKED": {"READY", "AT_RISK", "COMPLETE"},
    "COMPLETE": set(),
}

_ACTION_TARGET_STATUS = {
    Action.RELEASE_LOT: "RELEASED",
    Action.QUARANTINE_LOT: "QUARANTINED",
    Action.CREATE_QA_REVIEW: "PENDING_QA",
}


class PolicyEngine:
    """Deterministic authorization. The only component that may issue authority.

    Everything it enforces is a lookup, a boolean, a set membership or an
    interval containment — never model discretion.
    """

    IDENTITY = "vouch.policy-engine"

    def __init__(self, corpus: Corpus, capabilities) -> None:
        self._corpus = corpus
        self._capabilities = capabilities
        # The single issuance authority in the system (audit-2 F1). It comes
        # from the `issuance` module, NOT from the store: the store cannot mint
        # one, so holding the store grants nothing. The claim is by class
        # identity and is one-shot per process.
        self._issuer = _claim_issuance_authority(PolicyEngine, self.IDENTITY)

    def evaluate_lot_disposition(
        self,
        *,
        decision_record_id: str,
        lot_id: str,
        disposition: Disposition,
        reconciliation_ok: bool,
        basis_checks_ok: bool,
        observed_state_version: int,
        events: EventLog,
    ) -> PolicyDecision:
        """Deny by default. Every precondition is explicit."""
        lot = self._corpus.lot(lot_id)

        def refuse(reason: str) -> PolicyDecision:
            events.emit(
                EventType.POLICY_EVALUATED, decision_record_id,
                policy_version=POLICY_VERSION, gate_decision="REFUSED", reason=reason,
            )
            return PolicyDecision(False, None, reason)

        if lot is None:
            return refuse(f"lot {lot_id} does not exist")

        # -- required verification state --------------------------------
        if not reconciliation_ok:
            return refuse("reconciliation did not establish agreement")
        if not basis_checks_ok:
            return refuse("deterministic basis checks failed")

        # -- freshness: the decision must be judged against current state -
        current_version = self._corpus.version_of("lot", lot_id)
        if current_version != observed_state_version:
            return refuse(
                f"stale decision: lot moved from version {observed_state_version} "
                f"to {current_version}"
            )

        # -- what action does this disposition imply? --------------------
        if disposition is Disposition.RELEASE:
            action = Action.RELEASE_LOT
        elif disposition is Disposition.QUARANTINE:
            action = Action.QUARANTINE_LOT
        elif disposition is Disposition.INSUFFICIENT_EVIDENCE:
            action = Action.CREATE_QA_REVIEW
        else:
            return refuse(f"{disposition.value} is not an autonomously authorizable action")

        # -- supplier qualification, only where it gates release ---------
        if action is Action.RELEASE_LOT:
            qualification = self._corpus.qualification(lot.supplier_id, lot.material_id)
            when = lot.received_at or lot.manufactured_at
            if qualification is None:
                return refuse(
                    f"no supplier qualification on record for {lot.supplier_id}/{lot.material_id}"
                )
            if not qualification.covers(when=when, site_id=lot.supplier_site):
                return refuse(
                    f"supplier qualification {qualification.qualification_id} does not cover "
                    f"site {lot.supplier_site} at {when}"
                )

        # -- state transition legality -----------------------------------
        target_status = _ACTION_TARGET_STATUS[action]
        if target_status not in LOT_TRANSITIONS.get(lot.status, set()):
            return refuse(
                f"transition {lot.status} -> {target_status} is not permitted"
            )

        capability = self._capabilities.issue(
            self._issuer,
            decision_record_id=decision_record_id,
            target_type=TargetType.LOT,
            target_id=lot_id,
            action=action,
            observed_state_version=observed_state_version,
            parameters={},
        )
        events.emit(
            EventType.POLICY_EVALUATED, decision_record_id,
            policy_version=POLICY_VERSION, gate_decision="ALLOWED", action=action.value,
        )
        events.emit(
            EventType.CAPABILITY_ISSUED, decision_record_id,
            capability_id=capability.capability_id, target=lot_id,
            action=action.value, expiry=capability.expires_at,
        )
        return PolicyDecision(True, action, "authorized", capability)

    def authorize_order_action(
        self,
        *,
        decision_record_id: str,
        order_id: str,
        action: Action,
        observed_state_version: int,
        events: EventLog,
        parameters: dict | None = None,
    ) -> PolicyDecision:
        """Order-side authority (hold / resequence / readiness).

        Same deny-by-default shape. Action-specific parameters are validated
        HERE and then SIGNED into the capability (audit-2 F7), so the caller
        that spends the capability cannot choose a different slot or a
        different readiness state than the one policy approved.
        """
        parameters = dict(parameters or {})
        order = self._corpus.order(order_id)

        def refuse(reason: str) -> PolicyDecision:
            events.emit(
                EventType.POLICY_EVALUATED, decision_record_id,
                policy_version=POLICY_VERSION, gate_decision="REFUSED", reason=reason,
            )
            return PolicyDecision(False, None, reason)

        if order is None:
            return refuse(f"order {order_id} does not exist")

        current_version = self._corpus.version_of("production_order", order_id)
        if current_version != observed_state_version:
            return refuse(
                f"stale decision: order moved from version {observed_state_version} "
                f"to {current_version}"
            )

        if action not in ACTION_TARGET_TYPES[TargetType.PRODUCTION_ORDER]:
            return refuse(f"{action.value} is not an order action")

        if action is Action.HOLD_PRODUCTION_ORDER:
            if "BLOCKED" not in ORDER_TRANSITIONS.get(order.status, set()):
                return refuse(f"transition {order.status} -> BLOCKED is not permitted")
        elif action is Action.SET_ORDER_READINESS:
            # F7: the readiness state is decided HERE and signed in, not chosen
            # by whoever consumes the capability.
            readiness = str(parameters.get("readiness", ""))
            if readiness not in ORDER_TRANSITIONS:
                return refuse(f"{readiness!r} is not a readiness state")
            if readiness not in ORDER_TRANSITIONS.get(order.status, set()):
                return refuse(
                    f"transition {order.status} -> {readiness} is not permitted"
                )
        elif action is Action.RESEQUENCE_PRODUCTION_ORDER:
            # F7: both the slot the order moves TO and the slot it moves FROM
            # are part of the authorization and are signed into the capability.
            target_slot = str(parameters.get("target_slot", ""))
            if not target_slot:
                return refuse("resequence requires a target_slot to authorize")
            if target_slot == order.planned_slot:
                return refuse(f"order {order_id} is already in slot {target_slot}")
            occupied = [
                o
                for o in self._corpus.all("production_order")
                if o.order_id != order_id
                and o.resource == order.resource
                and o.planned_slot == target_slot
                and o.status != "BLOCKED"
            ]
            if occupied:
                return refuse(
                    f"slot {target_slot} on {order.resource} is occupied by "
                    f"{occupied[0].order_id}"
                )
            parameters["from_slot"] = order.planned_slot

        capability = self._capabilities.issue(
            self._issuer,
            decision_record_id=decision_record_id,
            target_type=TargetType.PRODUCTION_ORDER,
            target_id=order_id,
            action=action,
            observed_state_version=observed_state_version,
            parameters=parameters,
        )
        events.emit(
            EventType.POLICY_EVALUATED, decision_record_id,
            policy_version=POLICY_VERSION, gate_decision="ALLOWED", action=action.value,
        )
        events.emit(
            EventType.CAPABILITY_ISSUED, decision_record_id,
            capability_id=capability.capability_id, target=order_id,
            action=action.value, expiry=capability.expires_at,
        )
        return PolicyDecision(True, action, "authorized", capability)


# ==========================================================================
# mutations — invoked only through consume_atomically
# ==========================================================================


def _set_inventory_usable(corpus: Corpus, lot_id: str, usable: bool) -> tuple[float, dict, dict]:
    """Flip usability of a lot's inventory. Returns (delta, before, after).

    F6: the caller records the actual before/after inventory facts in the
    ledger, so a mutation is auditable against real quantities rather than an
    unexplained delta.
    """
    record = corpus.get("inventory", lot_id)
    if record is None:
        return 0.0, {}, {}
    before = {"usable": record.usable, "quantity": record.quantity}
    if record.usable == usable:
        return 0.0, before, dict(before)
    corpus.put("inventory", lot_id, replace(record, usable=usable))
    after = {"usable": usable, "quantity": record.quantity}
    return (record.quantity if usable else -record.quantity), before, after


def apply_release(corpus: Corpus, capability: CapabilityRecord) -> dict:
    corpus.bump("lot", capability.target_id, status="RELEASED")
    delta, before, after = _set_inventory_usable(corpus, capability.target_id, True)
    return {
        "result": f"lot {capability.target_id} RELEASED",
        "inventory_delta": delta,
        "inventory_before": before,
        "inventory_after": after,
    }


def apply_quarantine(corpus: Corpus, capability: CapabilityRecord) -> dict:
    corpus.bump("lot", capability.target_id, status="QUARANTINED")
    delta, before, after = _set_inventory_usable(corpus, capability.target_id, False)
    return {
        "result": f"lot {capability.target_id} QUARANTINED",
        "inventory_delta": delta,
        "inventory_before": before,
        "inventory_after": after,
    }


def apply_qa_review(corpus: Corpus, capability: CapabilityRecord) -> dict:
    """Escalation, not a defect finding. A lot pending QA is not defective."""
    lot = corpus.lot(capability.target_id)
    if lot is not None and lot.status == "RECEIVED":
        corpus.bump("lot", capability.target_id, status="PENDING_QA")
    review_id = f"QA-{capability.decision_record_id}"
    corpus.put(
        "qa_review", review_id,
        {
            "review_id": review_id,
            "decision_record_id": capability.decision_record_id,
            "lot_id": capability.target_id,
            "status": "OPEN",
            "created_at": utcnow(),
        },
    )
    return {
        "result": f"QA review {review_id} created",
        "inventory_delta": 0.0,
        "side_effects": {"qa_review_id": review_id},
    }


def apply_hold(corpus: Corpus, capability: CapabilityRecord) -> dict:
    corpus.bump("production_order", capability.target_id, status="BLOCKED")
    return {"result": f"order {capability.target_id} BLOCKED", "inventory_delta": 0.0}


def apply_resequence(corpus: Corpus, capability: CapabilityRecord) -> dict:
    """Resequence the bound order into its SIGNED target slot (audit-2 F7).

    The slot comes from the capability's authenticated binding, never from an
    execution parameter, so a caller who obtained a legitimate capability for
    slot B cannot spend it on slot C.

    The slot is re-verified HERE, at execution, not merely when the recovery
    option was enumerated: another order may have taken it in between. A
    conflict is a STATE_CONFLICT, not a silent overwrite.
    """
    bound = capability.params
    target_slot = bound.get("target_slot", "")
    if not target_slot:
        raise VouchFailure(
            FailureCategory.POLICY_REFUSAL,
            "resequence capability carries no bound target_slot",
        )

    order = corpus.order(capability.target_id)
    if order is None:
        raise VouchFailure(
            FailureCategory.STATE_CONFLICT, f"order {capability.target_id} does not exist"
        )

    # F7: the slot the order is moving FROM is also bound. If it changed since
    # authorization, this is not the move that was authorized.
    from_slot = bound.get("from_slot", "")
    if from_slot and order.planned_slot != from_slot:
        raise VouchFailure(
            FailureCategory.STATE_CONFLICT,
            f"order {capability.target_id} is in slot {order.planned_slot}, "
            f"not the authorized {from_slot}; re-evaluate",
        )

    conflict = [
        o
        for o in corpus.all("production_order")
        if o.order_id != capability.target_id
        and o.resource == order.resource
        and o.planned_slot == target_slot
        and o.status != "BLOCKED"
    ]
    if conflict:
        raise VouchFailure(
            FailureCategory.STATE_CONFLICT,
            f"slot {target_slot} on {order.resource} is occupied by "
            f"{conflict[0].order_id}; refusing to resequence",
        )

    corpus.bump("production_order", capability.target_id, planned_slot=target_slot)
    return {
        "result": (
            f"order {capability.target_id} resequenced from {order.planned_slot} "
            f"to {target_slot}"
        ),
        "inventory_delta": 0.0,
        "from_slot": order.planned_slot,
        "target_slot": target_slot,
    }


def apply_set_readiness(corpus: Corpus, capability: CapabilityRecord) -> dict:
    """Persist a deterministically-computed readiness state (P1-6).

    Readiness is not a view. A recomputation that changes it performs a real,
    authorized, version-checked transition through this path like any other
    mutation. The target state is SIGNED into the capability (F7).
    """
    bound = capability.params
    to_status = bound.get("readiness", "")
    if to_status not in ORDER_TRANSITIONS:
        raise VouchFailure(
            FailureCategory.POLICY_REFUSAL, f"{to_status!r} is not a readiness state"
        )
    order = corpus.order(capability.target_id)
    if order is None:
        raise VouchFailure(
            FailureCategory.STATE_CONFLICT, f"order {capability.target_id} does not exist"
        )
    from_status = order.status
    corpus.bump("production_order", capability.target_id, status=to_status)
    return {
        "result": f"order {capability.target_id} {from_status} -> {to_status}",
        "inventory_delta": 0.0,
        "from_status": from_status,
        "to_status": to_status,
        "caused_by": bound.get("caused_by", ""),
    }


#: The CLOSED dispatch table (P0-2). A capability's bound action selects its
#: mutation here; nothing a caller passes can add to, replace, or redirect an
#: entry. An action with no entry fails closed in `consume`.
MUTATIONS = {
    Action.RELEASE_LOT: apply_release,
    Action.QUARANTINE_LOT: apply_quarantine,
    Action.CREATE_QA_REVIEW: apply_qa_review,
    Action.HOLD_PRODUCTION_ORDER: apply_hold,
    Action.RESEQUENCE_PRODUCTION_ORDER: apply_resequence,
    Action.SET_ORDER_READINESS: apply_set_readiness,
}


#: Which actions may target which entity type (audit-2 F6). Enforced in
#: `consume` independently of the mutation function, so a capability whose
#: action and target type disagree is refused before anything runs.
ACTION_TARGET_TYPES: dict[TargetType, frozenset[Action]] = {
    TargetType.LOT: frozenset(
        {Action.RELEASE_LOT, Action.QUARANTINE_LOT, Action.CREATE_QA_REVIEW}
    ),
    TargetType.PRODUCTION_ORDER: frozenset(
        {
            Action.HOLD_PRODUCTION_ORDER,
            Action.RESEQUENCE_PRODUCTION_ORDER,
            Action.SET_ORDER_READINESS,
        }
    ),
}


def target_status_for(capability: CapabilityRecord) -> str:
    """The status this capability's action moves its target to, if any.

    Returns "" for actions that do not change status (resequence moves a slot).
    """
    if capability.target_type is TargetType.LOT:
        return _ACTION_TARGET_STATUS.get(capability.action, "")
    if capability.action is Action.HOLD_PRODUCTION_ORDER:
        return "BLOCKED"
    if capability.action is Action.SET_ORDER_READINESS:
        return capability.params.get("readiness", "")
    return ""


def _assert_legal_transition(corpus: Corpus, capability: CapabilityRecord) -> None:
    """Refuse a capability whose transition is illegal from CURRENT state (F6).

    Authorization already checked this, but authorization happened earlier.
    Checking again inside the consume lock is what makes the guarantee hold
    when state moved in between — and it is cheap.

    CREATE_QA_REVIEW is the one action that legitimately applies to a lot in a
    state it does not move (a PENDING_QA lot stays PENDING_QA); it is exempt
    from the transition table but not from the type check above.
    """
    to_status = target_status_for(capability)
    if not to_status:
        return
    obj = corpus.get(capability.target_type.value, capability.target_id)
    current = getattr(obj, "status", "")
    if capability.action is Action.CREATE_QA_REVIEW and current == to_status:
        return
    table = (
        LOT_TRANSITIONS
        if capability.target_type is TargetType.LOT
        else ORDER_TRANSITIONS
    )
    if to_status not in table.get(current, set()):
        raise VouchFailure(
            FailureCategory.POLICY_REFUSAL,
            f"transition {current} -> {to_status} is not permitted for "
            f"{capability.target_id}",
        )


def execute(
    capability: CapabilityRecord,
    corpus: Corpus,
    capabilities,
    events: EventLog,
) -> dict:
    """Consume the capability and perform its bound mutation atomically.

    Only the capability ID crosses into the store. The mutation is chosen there
    from the stored record's own action and driven by the stored record's own
    SIGNED parameters — there is no execution-parameter channel at all
    (audit-2 F7).
    """
    entry = capabilities.consume(capability.capability_id, corpus)

    # A durable store commits the transition inside DynamoDB, writing THROUGH
    # any objects this process has already read. Without dropping them, the
    # very next read returns the pre-mutation lot or order: consequences would
    # be computed against state the authority just changed, and a vacated slot
    # would still look occupied. The local store mutates the corpus in place
    # and has nothing to drop, so this is a no-op there.
    invalidate = getattr(corpus, "refresh", None)
    if callable(invalidate):
        invalidate()

    events.emit(
        EventType.MUTATION_COMPLETED, capability.decision_record_id,
        before_version=entry["before_version"], after_version=entry["after_version"],
        ledger_seq=entry["sequence"], action=entry["action"], target=entry["target_id"],
    )
    return entry


__all__ = [
    "ACTION_TARGET_TYPES",
    "Action",
    "CAPABILITY_TTL_SECONDS",
    "CapabilityRecord",
    "CapabilityStore",
    "IssuanceAuthority",
    "IssuanceViolation",
    "IssuerViolation",
    "freeze_parameters",
    "target_status_for",
    "LOT_TRANSITIONS",
    "MUTATIONS",
    "ORDER_TRANSITIONS",
    "PolicyDecision",
    "PolicyEngine",
    "TargetType",
    "execute",
]
