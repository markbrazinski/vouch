"""Gatehouse authoritative state model.

Manufacturing truth lives here, never in agent memory. Agents propose; only the
authority gate mutates, and only through the idempotent mutators in tools.py.

The store interface is deliberately tiny so the DynamoDB implementation is a
drop-in swap: get/put/scan over (entity_type, id).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------
# state machines
# --------------------------------------------------------------------------


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    PENDING_QA = "PENDING_QA"


# Explicit: what may follow what. Anything else is rejected by the store.
LOT_TRANSITIONS: dict[LotStatus, set[LotStatus]] = {
    LotStatus.RECEIVED: {LotStatus.RELEASED, LotStatus.QUARANTINED, LotStatus.PENDING_QA},
    LotStatus.PENDING_QA: {LotStatus.RELEASED, LotStatus.QUARANTINED, LotStatus.PENDING_QA},
    # terminal-ish: a released lot is not re-released, a quarantined lot needs a
    # new case to move. Keeps replay from double-applying.
    LotStatus.RELEASED: set(),
    LotStatus.QUARANTINED: set(),
}


class OrderStatus(str, Enum):
    READY = "READY"
    HOLD = "HOLD"
    COMPLETE = "COMPLETE"


ORDER_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.READY: {OrderStatus.HOLD, OrderStatus.COMPLETE},
    OrderStatus.HOLD: {OrderStatus.READY, OrderStatus.COMPLETE},
    OrderStatus.COMPLETE: set(),
}


class Usability(str, Enum):
    USABLE = "USABLE"
    NOT_USABLE = "NOT_USABLE"


class Disposition(str, Enum):
    RELEASE = "RELEASE"
    QUARANTINE = "QUARANTINE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class VerifierOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class RecoveryAction(str, Enum):
    RESEQUENCE = "RESEQUENCE"
    SUBSTITUTE = "SUBSTITUTE"
    USE_EXISTING = "USE_EXISTING"
    REFUSE = "REFUSE"
    ESCALATE = "ESCALATE"


# --------------------------------------------------------------------------
# entities
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Material:
    material_id: str
    name: str
    governing_spec_id: str
    governing_spec_revision: str


@dataclass(frozen=True)
class Characteristic:
    """One spec requirement. `method` and `condition` are what S6 turns on:
    evidence for the right characteristic by the wrong method proves nothing."""

    name: str
    method: str
    condition: str
    min_value: float | None = None
    max_value: float | None = None
    units: str = ""


@dataclass(frozen=True)
class MaterialSpecification:
    spec_id: str
    revision: str
    status: str
    characteristics: tuple[Characteristic, ...]


@dataclass(frozen=True)
class SupplierQualification:
    supplier: str
    material_id: str
    status: str
    effective_date: str
    expiry_date: str | None = None


@dataclass(frozen=True)
class Lot:
    lot_id: str
    supplier: str
    material_id: str
    po_reference: str
    quantity: float
    status: LotStatus = LotStatus.RECEIVED
    units: str = "kg"


@dataclass(frozen=True)
class EvidenceMeasurement:
    characteristic: str
    method: str
    condition: str
    value: float | None
    units: str = ""


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    evidence_type: str
    source: str
    s3_ref: str
    lot_id: str | None = None
    material_id: str | None = None
    measurements: tuple[EvidenceMeasurement, ...] = ()


@dataclass(frozen=True)
class InventoryRecord:
    material_id: str
    lot_id: str
    quantity: float
    usability: Usability


@dataclass(frozen=True)
class MaterialRequirement:
    material_id: str
    quantity: float


@dataclass(frozen=True)
class ProductionOrder:
    order_id: str
    product: str
    quantity: float
    requirements: tuple[MaterialRequirement, ...]
    resource: str
    planned_slot: str
    status: OrderStatus = OrderStatus.READY


@dataclass(frozen=True)
class ApprovedSubstitution:
    product: str
    original_material_id: str
    substitute_material_id: str
    approved: bool


@dataclass(frozen=True)
class QAReview:
    review_id: str
    case_id: str
    lot_id: str
    reason: str
    evidence_refs: tuple[str, ...]
    status: str = "OPEN"
    created_at: str = field(default_factory=utcnow)


@dataclass(frozen=True)
class AuthorityRecord:
    """The audit artifact. Typed outputs + evidence refs + real state change.
    Never hidden chain-of-thought."""

    case_id: str
    evidence_refs: tuple[str, ...]
    actor_disposition: str
    actor_rationale: str
    verifier_outcome: str
    verifier_rationale: str
    authority_source: str
    authority_result: str
    requested_tool: str
    mutation_result: str
    state_before: str
    state_after: str
    timestamp: str = field(default_factory=utcnow)
    idempotency_key: str = ""


class TransitionError(RuntimeError):
    """Illegal state machine transition."""


# --------------------------------------------------------------------------
# store
# --------------------------------------------------------------------------


class StateStore:
    """In-memory authoritative store.

    ponytail: dict-backed, not DynamoDB. The interface (get/put/all/append) is
    what a DynamoDB adapter implements; swap the backend when credentials land.
    Mutations go through the guarded helpers below so the state machine and
    idempotency hold regardless of backend.
    """

    def __init__(self) -> None:
        self._t: dict[str, dict[str, Any]] = {}
        self.authority_log: list[AuthorityRecord] = []
        # idempotency_key -> result string, so replays return the first result
        self._applied: dict[str, str] = {}

    # -- generic ----------------------------------------------------------
    def put(self, kind: str, key: str, value: Any) -> None:
        self._t.setdefault(kind, {})[key] = value

    def get(self, kind: str, key: str) -> Any:
        return self._t.get(kind, {}).get(key)

    def all(self, kind: str) -> list[Any]:
        return list(self._t.get(kind, {}).values())

    # -- idempotency ------------------------------------------------------
    def already_applied(self, idempotency_key: str) -> str | None:
        return self._applied.get(idempotency_key)

    def mark_applied(self, idempotency_key: str, result: str) -> None:
        self._applied[idempotency_key] = result

    # -- guarded transitions ---------------------------------------------
    def set_lot_status(self, lot_id: str, new: LotStatus) -> Lot:
        lot: Lot = self.get("lot", lot_id)
        if lot is None:
            raise KeyError(f"unknown lot {lot_id}")
        if new not in LOT_TRANSITIONS[lot.status]:
            raise TransitionError(f"lot {lot_id}: {lot.status.value} -> {new.value} not permitted")
        updated = replace(lot, status=new)
        self.put("lot", lot_id, updated)
        return updated

    def set_order_status(self, order_id: str, new: OrderStatus) -> ProductionOrder:
        order: ProductionOrder = self.get("production_order", order_id)
        if order is None:
            raise KeyError(f"unknown production order {order_id}")
        if new not in ORDER_TRANSITIONS[order.status]:
            raise TransitionError(
                f"order {order_id}: {order.status.value} -> {new.value} not permitted"
            )
        updated = replace(order, status=new)
        self.put("production_order", order_id, updated)
        return updated

    def set_inventory_usability(self, lot_id: str, usability: Usability) -> None:
        rec: InventoryRecord = self.get("inventory", lot_id)
        if rec is None:
            raise KeyError(f"unknown inventory for lot {lot_id}")
        self.put("inventory", lot_id, replace(rec, usability=usability))

    def record_authority(self, record: AuthorityRecord) -> None:
        self.authority_log.append(record)
