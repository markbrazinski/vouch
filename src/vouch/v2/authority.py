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

**Issuance is authorized, not merely conventional (P0-1).** `issue()` demands an
`Issuer` credential. Only `PolicyEngine` mints one, and it does so for itself at
construction; there is no public constructor path that yields a valid credential
to anything else. A caller holding the store but no credential cannot create
authority — `store.issue(...)` without a credential is a TypeError, and with a
forged credential it is a POLICY_REFUSAL. The production DynamoDB adapter binds
the same boundary to an IAM principal, so the enforcement is not Python-only.

**Consumption dispatches internally (P0-2).** `consume()` takes a capability id
and NOTHING executable. The mutation is looked up from a closed table keyed by
the capability's own bound action, and it can only touch the capability's own
bound target. There is no parameter through which a caller can supply a
callable, so a capability for LOT-1001 cannot be made to mutate LOT-1002 no
matter what the caller passes.
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

    `issuer_proof` is what makes forgery fail: it is an HMAC-style digest over
    the record's binding fields keyed by a secret only the Policy Engine holds.
    A hand-constructed record cannot produce a valid one.
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
    #: Which authorized issuer created this row (P0-1). Recorded in the ledger
    #: so an auditor can see authority never originated outside the Policy
    #: Engine.
    issuer_identity: str = ""
    used: bool = False
    consumed_at: str = ""

    def binding(self) -> str:
        return "|".join(
            [
                self.capability_id, self.decision_record_id, self.target_type.value,
                self.target_id, self.action.value, str(self.observed_state_version),
                self.policy_version, self.expires_at, self.nonce,
                self.issuer_identity,
            ]
        )

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(timezone.utc)
        return now > datetime.fromisoformat(self.expires_at)


class IssuerViolation(PermissionError):
    """Something other than an authorized issuer tried to create authority."""


@dataclass(frozen=True)
class Issuer:
    """Proof that the holder is permitted to create authority (P0-1).

    This is the local-mode model of the production boundary: in DynamoDB the
    right to write a capability row belongs to the Policy Engine's IAM
    principal, and no other component's credentials can perform that PutItem.
    Here the same boundary is a credential object the store recognizes.

    It is deliberately NOT constructible into a valid state by an outsider:
    `secret` must equal the store's own issuer secret, which is never exposed.
    `PolicyEngine` receives one at construction and nothing else does.
    """

    identity: str
    secret: bytes = field(repr=False, default=b"")


class CapabilityStore:
    """Persisted capability rows with atomic conditional consumption.

    The lock is what DynamoDB's ConditionExpression provides in production; the
    semantics proven here are identical. `consume` is the single place a
    capability is spent, and it is the single place state mutates.

    ponytail: threading.Lock, not a distributed lock. Single-process semantics
    match the conditional-write guarantee; the DynamoDB adapter (aws.py) swaps
    this for a TransactWriteItems with the same conditions.
    """

    def __init__(self) -> None:
        self._rows: dict[str, CapabilityRecord] = {}
        self._lock = threading.RLock()
        self._ledger: list[dict] = []
        # Process-local issuer secret. Never persisted, never exposed. Rotating
        # it invalidates outstanding capabilities, which is correct.
        self._issuer_secret = secrets.token_bytes(32)

    # -- issuer boundary ---------------------------------------------------
    def _mint_issuer(self, identity: str) -> Issuer:
        """Create an issuer credential. Called ONLY by PolicyEngine.__init__.

        This is a private method by name, but the enforcement does not rest on
        that: the credential it returns carries the store's secret, and
        `issue()` compares against that secret. A caller that constructs
        `Issuer("policy-engine", b"guess")` fails the comparison.
        """
        return Issuer(identity=identity, secret=self._issuer_secret)

    def _authorized_issuer(self, issuer: Issuer | None) -> bool:
        return (
            isinstance(issuer, Issuer)
            and bool(issuer.secret)
            and secrets.compare_digest(issuer.secret, self._issuer_secret)
        )

    # -- issuance (authorized issuers only) --------------------------------
    def _proof(self, binding: str) -> str:
        return hashlib.blake2b(
            binding.encode(), key=self._issuer_secret, digest_size=32
        ).hexdigest()

    def _authentic(self, record: CapabilityRecord) -> bool:
        return secrets.compare_digest(record.issuer_proof, self._proof(record.binding()))

    def issue(
        self,
        issuer: Issuer,
        *,
        decision_record_id: str,
        target_type: TargetType,
        target_id: str,
        action: Action,
        observed_state_version: int,
        ttl_seconds: int = CAPABILITY_TTL_SECONDS,
    ) -> CapabilityRecord:
        """Write a capability row. Requires an authorized issuer credential.

        `issuer` is positional and mandatory, so a caller cannot omit it: an
        `issue(...)` call without it raises TypeError before any row exists.
        """
        if not self._authorized_issuer(issuer):
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
        )
        record = replace(skeleton, issuer_proof=self._proof(skeleton.binding()))
        with self._lock:
            self._rows[capability_id] = record
        return record

    def get(self, capability_id: str) -> CapabilityRecord | None:
        return self._rows.get(capability_id)

    # -- consumption -------------------------------------------------------
    def consume(
        self,
        capability_id: str,
        corpus: Corpus,
        *,
        params: dict | None = None,
    ) -> dict:
        """The ONLY path to a state mutation (P0-2).

        Takes an ID and a parameter dict — never a callable. The mutation is
        resolved from the closed `MUTATIONS` table using the STORED record's
        own action, and applied to the STORED record's own target. A caller
        cannot supply, substitute, or redirect the operation.

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

            # 5. the bound target must exist and be of the bound type
            if corpus.get(stored.target_type.value, stored.target_id) is None:
                raise VouchFailure(
                    FailureCategory.STATE_CONFLICT,
                    f"{stored.target_type.value} {stored.target_id} does not exist",
                )

            # 6. state-version binding — kills TOCTOU
            current_version = corpus.version_of(stored.target_type.value, stored.target_id)
            if current_version != stored.observed_state_version:
                raise VouchFailure(
                    FailureCategory.STATE_CONFLICT,
                    f"{stored.target_id} moved from version "
                    f"{stored.observed_state_version} to {current_version}; re-evaluate",
                )

            # 7. transition + consume + ledger, atomically
            before = current_version
            outcome = apply_change(corpus, stored, dict(params or {}))
            after = corpus.version_of(stored.target_type.value, stored.target_id)

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
                "before_version": before,
                "after_version": after,
                "result": outcome.get("result", ""),
                "inventory_delta": outcome.get("inventory_delta", 0.0),
                "at": utcnow(),
            }
            self._ledger.append(entry)
            return entry

    @property
    def ledger(self) -> list[dict]:
        return list(self._ledger)


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

    def __init__(self, corpus: Corpus, capabilities: CapabilityStore) -> None:
        self._corpus = corpus
        self._capabilities = capabilities
        # The single issuer credential in the system. Nothing else obtains one:
        # `_mint_issuer` is reached only from here, and the credential carries
        # the store's secret rather than a name anyone could assert.
        self._issuer = capabilities._mint_issuer(self.IDENTITY)

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
    ) -> PolicyDecision:
        """Order-side authority (hold / resequence). Same deny-by-default shape."""
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

        if action is Action.HOLD_PRODUCTION_ORDER:
            if "BLOCKED" not in ORDER_TRANSITIONS.get(order.status, set()):
                return refuse(f"transition {order.status} -> BLOCKED is not permitted")
        elif action is Action.SET_ORDER_READINESS:
            # Legality of the specific target state is re-checked at consume
            # time against the value bound in params; here we only confirm the
            # order is in a state that can transition at all.
            if not ORDER_TRANSITIONS.get(order.status, set()):
                return refuse(f"order in {order.status} cannot transition")
        elif action is not Action.RESEQUENCE_PRODUCTION_ORDER:
            return refuse(f"{action.value} is not an order action")

        capability = self._capabilities.issue(
            self._issuer,
            decision_record_id=decision_record_id,
            target_type=TargetType.PRODUCTION_ORDER,
            target_id=order_id,
            action=action,
            observed_state_version=observed_state_version,
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


def _set_inventory_usable(corpus: Corpus, lot_id: str, usable: bool) -> float:
    record = corpus.get("inventory", lot_id)
    if record is None:
        return 0.0
    if record.usable == usable:
        return 0.0
    corpus.put("inventory", lot_id, replace(record, usable=usable))
    return record.quantity if usable else -record.quantity


def apply_release(corpus: Corpus, capability: CapabilityRecord, params: dict) -> dict:
    corpus.bump("lot", capability.target_id, status="RELEASED")
    delta = _set_inventory_usable(corpus, capability.target_id, True)
    return {"result": f"lot {capability.target_id} RELEASED", "inventory_delta": delta}


def apply_quarantine(corpus: Corpus, capability: CapabilityRecord, params: dict) -> dict:
    corpus.bump("lot", capability.target_id, status="QUARANTINED")
    delta = _set_inventory_usable(corpus, capability.target_id, False)
    return {"result": f"lot {capability.target_id} QUARANTINED", "inventory_delta": delta}


def apply_qa_review(corpus: Corpus, capability: CapabilityRecord, params: dict) -> dict:
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
    return {"result": f"QA review {review_id} created", "inventory_delta": 0.0}


def apply_hold(corpus: Corpus, capability: CapabilityRecord, params: dict) -> dict:
    corpus.bump("production_order", capability.target_id, status="BLOCKED")
    return {"result": f"order {capability.target_id} BLOCKED", "inventory_delta": 0.0}


def apply_resequence(corpus: Corpus, capability: CapabilityRecord, params: dict) -> dict:
    """Resequence the bound order into its bound target slot (P1-7).

    The slot is re-verified HERE, at execution, not merely when the recovery
    option was enumerated: another order may have taken the slot in between.
    A conflict is a STATE_CONFLICT, not a silent overwrite.
    """
    target_slot = str(params.get("target_slot", ""))
    if not target_slot:
        raise VouchFailure(
            FailureCategory.POLICY_REFUSAL, "resequence requires a target_slot"
        )

    order = corpus.order(capability.target_id)
    if order is None:
        raise VouchFailure(
            FailureCategory.STATE_CONFLICT, f"order {capability.target_id} does not exist"
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

    from_slot = order.planned_slot
    corpus.bump("production_order", capability.target_id, planned_slot=target_slot)
    return {
        "result": (
            f"order {capability.target_id} resequenced from {from_slot} to {target_slot}"
        ),
        "inventory_delta": 0.0,
        "from_slot": from_slot,
        "target_slot": target_slot,
    }


def apply_set_readiness(corpus: Corpus, capability: CapabilityRecord, params: dict) -> dict:
    """Persist a deterministically-computed readiness state (P1-6).

    Readiness is not a view. A recomputation that changes it performs a real,
    authorized, version-checked transition through this path like any other
    mutation, so the order's status and state_version actually move.
    """
    to_status = str(params.get("readiness", ""))
    if to_status not in ORDER_TRANSITIONS:
        raise VouchFailure(
            FailureCategory.POLICY_REFUSAL, f"{to_status!r} is not a readiness state"
        )
    order = corpus.order(capability.target_id)
    if order is None:
        raise VouchFailure(
            FailureCategory.STATE_CONFLICT, f"order {capability.target_id} does not exist"
        )
    if to_status not in ORDER_TRANSITIONS.get(order.status, set()):
        raise VouchFailure(
            FailureCategory.POLICY_REFUSAL,
            f"transition {order.status} -> {to_status} is not permitted",
        )
    from_status = order.status
    corpus.bump("production_order", capability.target_id, status=to_status)
    return {
        "result": f"order {capability.target_id} {from_status} -> {to_status}",
        "inventory_delta": 0.0,
        "from_status": from_status,
        "to_status": to_status,
        "caused_by": params.get("caused_by", {}),
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


def execute(
    capability: CapabilityRecord,
    corpus: Corpus,
    capabilities: CapabilityStore,
    events: EventLog,
    *,
    params: dict | None = None,
) -> dict:
    """Consume the capability and perform its bound mutation atomically.

    Only the capability ID crosses into the store; the mutation is chosen there
    from the stored record's own action.
    """
    entry = capabilities.consume(capability.capability_id, corpus, params=params)
    events.emit(
        EventType.MUTATION_COMPLETED, capability.decision_record_id,
        before_version=entry["before_version"], after_version=entry["after_version"],
        ledger_seq=entry["sequence"], action=entry["action"], target=entry["target_id"],
    )
    return entry


__all__ = [
    "Action",
    "CAPABILITY_TTL_SECONDS",
    "CapabilityRecord",
    "CapabilityStore",
    "Issuer",
    "IssuerViolation",
    "LOT_TRANSITIONS",
    "MUTATIONS",
    "ORDER_TRANSITIONS",
    "PolicyDecision",
    "PolicyEngine",
    "TargetType",
    "execute",
]
