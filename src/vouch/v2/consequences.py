"""Consequence Engine and deterministic Recovery (contracts D15, §19-20).

After a mutation, reality changed. This recomputes what that means and records
the causal chain so an auditor can follow:

    lot disposition -> inventory delta -> requirement coverage -> order readiness

Recovery is fully deterministic in Milestone 1. There is no recovery agent and
no fake "actor"/"verifier" keys — V1 had both, and they read as theatre.

Two product-level corrections from the contract:
  * readiness is READY | AT_RISK | BLOCKED, not V1's binary READY/HOLD;
  * recovery returns EVERY candidate with a verdict and reason code, so
    "refused" and "not feasible" are visibly different things.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .contracts import VouchFailure
from .corpus import Corpus
from .lifecycle import EventLog, EventType


class Readiness(str, Enum):
    READY = "READY"
    AT_RISK = "AT_RISK"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


#: A requirement covered at or above this fraction, but below full, is AT_RISK
#: rather than BLOCKED: the order can plausibly still run if more material
#: clears, so it is a warning, not a stop.
AT_RISK_THRESHOLD = 0.9


@dataclass
class CoverageLine:
    material_id: str
    required: float
    available: float

    @property
    def short_by(self) -> float:
        return round(max(0.0, self.required - self.available), 6)

    @property
    def ratio(self) -> float:
        return 1.0 if self.required <= 0 else self.available / self.required

    def as_dict(self) -> dict:
        return {
            "material_id": self.material_id, "required": self.required,
            "available": self.available, "short_by": self.short_by,
            "ratio": round(self.ratio, 4),
        }


@dataclass
class ReadinessResult:
    order_id: str
    readiness: Readiness
    coverage: list[CoverageLine] = field(default_factory=list)
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "order_id": self.order_id, "readiness": self.readiness.value,
            "coverage": [c.as_dict() for c in self.coverage], "reason": self.reason,
        }


def compute_readiness(corpus: Corpus, order_id: str) -> ReadinessResult:
    """Deterministic arithmetic. No model computes inventory (contract §6)."""
    order = corpus.order(order_id)
    if order is None:
        return ReadinessResult(order_id, Readiness.BLOCKED, reason="order does not exist")
    if order.status == "COMPLETE":
        return ReadinessResult(order_id, Readiness.COMPLETE, reason="order is complete")

    coverage = [
        CoverageLine(
            material_id=line.material_id,
            required=line.quantity,
            available=corpus.usable_inventory(line.material_id),
        )
        for line in order.requirements
    ]

    shortfalls = [c for c in coverage if c.short_by > 0]
    if not shortfalls:
        return ReadinessResult(order_id, Readiness.READY, coverage, "all materials available")

    worst = min(c.ratio for c in shortfalls)
    detail = "; ".join(
        f"{c.material_id} short by {c.short_by} (need {c.required}, have {c.available})"
        for c in shortfalls
    )
    readiness = Readiness.AT_RISK if worst >= AT_RISK_THRESHOLD else Readiness.BLOCKED
    return ReadinessResult(order_id, readiness, coverage, detail)


def recalculate_consequences(
    corpus: Corpus,
    *,
    decision_record_id: str,
    lot_id: str,
    inventory_delta: float,
    events: EventLog,
    policy=None,
    capabilities=None,
) -> dict:
    """Recompute coverage and readiness, and PERSIST readiness changes (P1-6).

    The audit found readiness computed and returned but never written: the
    order's status and state_version never moved, so "production HOLD" was a
    view, not a fact. A recomputation that changes readiness now performs a
    real authorized state transition through the capability path like any other
    mutation — deterministic decision, policy authorization, atomic consume,
    ledger entry.

    `policy`/`capabilities` are optional so the pure calculation remains
    callable on its own; when they are absent the readiness change is reported
    but explicitly NOT persisted, and `persisted` says so rather than implying
    a write happened.
    """
    lot = corpus.lot(lot_id)
    if lot is None:
        return {
            "coverage_changes": [], "readiness_changes": [], "caused_by": [],
            "persisted": False,
        }

    affected = [
        order
        for order in corpus.all("production_order")
        if any(line.material_id == lot.material_id for line in order.requirements)
    ]

    coverage_changes: list[dict] = []
    readiness_changes: list[dict] = []
    caused_by: list[dict] = []

    for order in affected:
        result = compute_readiness(corpus, order.order_id)
        coverage_changes.append(
            {"order_id": order.order_id, "coverage": [c.as_dict() for c in result.coverage]}
        )
        if result.readiness.value != order.status:
            causal = {
                "cause": "lot_disposition",
                "lot_id": lot_id,
                "inventory_delta": inventory_delta,
                "material_id": lot.material_id,
                "effect": "order_readiness",
                "order_id": order.order_id,
                "from": order.status,
                "to": result.readiness.value,
                "decision_record_id": decision_record_id,
            }
            change = {
                "order_id": order.order_id,
                "from": order.status,
                "to": result.readiness.value,
                "reason": result.reason,
                "persisted": False,
                "state_version": order.state_version,
            }

            persisted = _persist_readiness(
                corpus, order, result, decision_record_id, events, policy,
                capabilities, causal,
            )
            if persisted is not None:
                change["persisted"] = True
                change["state_version"] = persisted["after_version"]
                change["ledger_sequence"] = persisted["sequence"]
                causal["ledger_sequence"] = persisted["sequence"]

            readiness_changes.append(change)
            caused_by.append(causal)

        events.emit(
            EventType.CONSEQUENCE_RECALCULATED, decision_record_id,
            order_id=order.order_id, order_readiness=result.readiness.value,
            coverage_delta=inventory_delta,
        )

    return {
        "coverage_changes": coverage_changes,
        "readiness_changes": readiness_changes,
        "caused_by": caused_by,
        "persisted": all(c["persisted"] for c in readiness_changes) if readiness_changes else True,
    }


def _persist_readiness(
    corpus: Corpus, order, result, decision_record_id: str, events: EventLog,
    policy, capabilities, causal: dict,
) -> dict | None:
    """Authorize and apply one readiness transition. Returns the ledger entry.

    Deliberately routed through the SAME policy + capability + atomic consume
    path as every other mutation. There is no side door for readiness just
    because it is computed deterministically — a deterministic decision still
    needs authority to change state.
    """
    if policy is None or capabilities is None:
        return None

    from .authority import Action, execute

    decision = policy.authorize_order_action(
        decision_record_id=decision_record_id,
        order_id=order.order_id,
        action=Action.SET_ORDER_READINESS,
        observed_state_version=order.state_version,
        events=events,
    )
    if not decision.allowed or decision.capability is None:
        return None

    try:
        entry = execute(
            decision.capability, corpus, capabilities, events,
            params={"readiness": result.readiness.value, "caused_by": causal},
        )
    except VouchFailure:
        # A concurrent change moved the order; the recomputation is stale and
        # will be redone. Never force the write.
        return None

    events.emit(
        EventType.READINESS_TRANSITIONED, decision_record_id,
        order_id=order.order_id, **{"from": causal["from"]}, to=causal["to"],
        ledger_seq=entry["sequence"], caused_by_lot=causal["lot_id"],
    )
    return entry


# ==========================================================================
# deterministic recovery
# ==========================================================================


class Verdict(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_FEASIBLE = "NOT_FEASIBLE"
    #: Deliberately distinct from NOT_FEASIBLE. A refused option is one the
    #: plant COULD physically do but is not permitted to — availability is not
    #: authority. Collapsing these two hides the safety story.
    REFUSED = "REFUSED"


class ReasonCode(str, Enum):
    FEASIBLE = "FEASIBLE"
    INSUFFICIENT_QUANTITY = "INSUFFICIENT_QUANTITY"
    NOT_APPROVED = "NOT_APPROVED"
    SLOT_OCCUPIED = "SLOT_OCCUPIED"
    RESOURCE_INCOMPATIBLE = "RESOURCE_INCOMPATIBLE"
    MATERIALS_NOT_RELEASED = "MATERIALS_NOT_RELEASED"
    NO_CANDIDATE = "NO_CANDIDATE"


@dataclass
class RecoveryOption:
    kind: str  # EXISTING_INVENTORY | SUBSTITUTE | RESEQUENCE
    candidate_id: str
    verdict: Verdict
    reason_code: ReasonCode
    facts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "kind": self.kind, "candidate_id": self.candidate_id,
            "verdict": self.verdict.value, "reason_code": self.reason_code.value,
            "facts": self.facts,
        }


def _resequence_priority(corpus: Corpus, option: RecoveryOption) -> tuple:
    """Explicit business priority (contract D15).

    V1 used min(admissible, key=order_id) — alphabetical order, which is a
    policy decision disguised as an implementation detail. The real rule:
    protect customer-committed orders first, then earliest need-by, and only
    then order_id as a stable final tiebreak.
    """
    order = corpus.order(option.candidate_id)
    if order is None:
        return (1, "9999", option.candidate_id)
    return (
        0 if order.customer_committed else 1,
        order.need_by or "9999",
        option.candidate_id,
    )


def enumerate_recovery(
    corpus: Corpus, blocked_order_id: str
) -> tuple[list[RecoveryOption], RecoveryOption | None]:
    """Enumerate EVERY candidate with its verdict, then pick by explicit policy.

    Returns (all_options, selected). Selected is None when nothing is lawful —
    the system never invents an option.
    """
    order = corpus.order(blocked_order_id)
    if order is None:
        return [], None

    readiness = compute_readiness(corpus, blocked_order_id)
    short = {c.material_id: c for c in readiness.coverage if c.short_by > 0}
    options: list[RecoveryOption] = []

    # -- 1. existing inventory -------------------------------------------
    for material_id, line in short.items():
        options.append(
            RecoveryOption(
                kind="EXISTING_INVENTORY",
                candidate_id=material_id,
                verdict=Verdict.NOT_FEASIBLE,
                reason_code=ReasonCode.INSUFFICIENT_QUANTITY,
                facts={
                    "required": line.required, "available": line.available,
                    "short_by": line.short_by,
                },
            )
        )

    # -- 2. substitutions -------------------------------------------------
    for substitution in corpus.substitutions_for(order.product):
        if substitution.original_material_id not in short:
            continue
        available = corpus.usable_inventory(substitution.substitute_material_id)
        needed = short[substitution.original_material_id].short_by
        if not substitution.approved:
            # Stock exists but authority does not. REFUSED, not NOT_FEASIBLE.
            options.append(
                RecoveryOption(
                    kind="SUBSTITUTE",
                    candidate_id=substitution.substitute_material_id,
                    verdict=Verdict.REFUSED,
                    reason_code=ReasonCode.NOT_APPROVED,
                    facts={
                        "available": available, "needed": needed,
                        "approved": False, "product": order.product,
                    },
                )
            )
        elif available < needed:
            options.append(
                RecoveryOption(
                    kind="SUBSTITUTE",
                    candidate_id=substitution.substitute_material_id,
                    verdict=Verdict.NOT_FEASIBLE,
                    reason_code=ReasonCode.INSUFFICIENT_QUANTITY,
                    facts={"available": available, "needed": needed, "approved": True},
                )
            )
        else:
            options.append(
                RecoveryOption(
                    kind="SUBSTITUTE",
                    candidate_id=substitution.substitute_material_id,
                    verdict=Verdict.ELIGIBLE,
                    reason_code=ReasonCode.FEASIBLE,
                    facts={"available": available, "needed": needed, "approved": True},
                )
            )

    # -- 3. resequence ----------------------------------------------------
    for other in corpus.all("production_order"):
        if other.order_id == blocked_order_id or other.status == "COMPLETE":
            continue

        other_readiness = compute_readiness(corpus, other.order_id)
        slot_conflict = [
            o
            for o in corpus.all("production_order")
            if o.order_id not in (other.order_id, blocked_order_id)
            and o.resource == other.resource
            and o.planned_slot == order.planned_slot
            and o.status != "BLOCKED"
        ]
        facts = {
            "current_slot": other.planned_slot,
            "target_slot": order.planned_slot,
            "resource": other.resource,
            "materials_ready": other_readiness.readiness is Readiness.READY,
            "slot_free": not slot_conflict,
        }

        if other.resource != order.resource:
            verdict, reason = Verdict.NOT_FEASIBLE, ReasonCode.RESOURCE_INCOMPATIBLE
        elif slot_conflict:
            verdict, reason = Verdict.NOT_FEASIBLE, ReasonCode.SLOT_OCCUPIED
        elif other_readiness.readiness is not Readiness.READY:
            verdict, reason = Verdict.NOT_FEASIBLE, ReasonCode.MATERIALS_NOT_RELEASED
        else:
            verdict, reason = Verdict.ELIGIBLE, ReasonCode.FEASIBLE

        options.append(
            RecoveryOption("RESEQUENCE", other.order_id, verdict, reason, facts)
        )

    eligible = [o for o in options if o.verdict is Verdict.ELIGIBLE]
    if not eligible:
        return options, None

    # Explicit policy: prefer resequencing (no material risk) over substitution,
    # then apply the business priority within resequence candidates.
    resequences = sorted(
        (o for o in eligible if o.kind == "RESEQUENCE"),
        key=lambda o: _resequence_priority(corpus, o),
    )
    selected = resequences[0] if resequences else eligible[0]
    return options, selected


__all__ = [
    "AT_RISK_THRESHOLD",
    "CoverageLine",
    "Readiness",
    "ReadinessResult",
    "ReasonCode",
    "RecoveryOption",
    "Verdict",
    "compute_readiness",
    "enumerate_recovery",
    "recalculate_consequences",
]
