"""Gatehouse tools: read, deterministic evaluation, and gated mutation.

Three rules enforced here rather than by prompt:
  1. Read tools never mutate.
  2. Deterministic evaluation tools do all arithmetic. No LLM does inventory math.
  3. Mutation tools require an AuthorityToken minted by a deterministic gate.
     A direct call without one raises. Verifiers never hold mutation tools.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .state import (
    ApprovedSubstitution,
    AuthorityRecord,
    Evidence,
    InventoryRecord,
    Lot,
    LotStatus,
    Material,
    MaterialSpecification,
    OrderStatus,
    ProductionOrder,
    QAReview,
    StateStore,
    SupplierQualification,
    Usability,
)


class AuthorityError(PermissionError):
    """A mutation was attempted without valid deterministic authority."""


@dataclass(frozen=True)
class AuthorityToken:
    """Proof that a deterministic gate authorized one specific mutation.

    Minted only by gates.py. Bound to (case_id, tool, target) so a token for one
    mutation cannot authorize another, and carries the idempotency key so
    replays collapse.
    """

    case_id: str
    tool: str
    target: str
    idempotency_key: str
    authority_source: str

    def check(self, tool: str, target: str) -> None:
        if self.tool != tool or self.target != target:
            raise AuthorityError(
                f"authority token is for {self.tool}/{self.target}, not {tool}/{target}"
            )


def make_idempotency_key(case_id: str, tool: str, target: str) -> str:
    return hashlib.sha256(f"{case_id}|{tool}|{target}".encode()).hexdigest()[:16]


# ==========================================================================
# READ TOOLS  (safe for actors and verifiers)
# ==========================================================================


class ReadTools:
    """Read-only view of authoritative state. Verifiers get exactly this."""

    def __init__(self, store: StateStore) -> None:
        self._s = store

    def get_lot(self, lot_id: str) -> Lot | None:
        return self._s.get("lot", lot_id)

    def get_material(self, material_id: str) -> Material | None:
        return self._s.get("material", material_id)

    def get_governing_spec(self, material_id: str) -> MaterialSpecification | None:
        """The governing PLANT spec for a material — not whatever spec a
        supplier document happens to cite. S2 turns on this distinction."""
        material = self.get_material(material_id)
        if material is None:
            return None
        return self._s.get("spec", f"{material.governing_spec_id}:{material.governing_spec_revision}")

    def get_supplier_qualification(
        self, supplier: str, material_id: str
    ) -> SupplierQualification | None:
        return self._s.get("supplier_qualification", f"{supplier}:{material_id}")

    def get_evidence(self, lot_id: str) -> list[Evidence]:
        return [e for e in self._s.all("evidence") if e.lot_id == lot_id]

    def get_usable_inventory(self, material_id: str) -> float:
        return sum(
            r.quantity
            for r in self._s.all("inventory")
            if r.material_id == material_id and r.usability is Usability.USABLE
        )

    def get_production_order(self, order_id: str) -> ProductionOrder | None:
        return self._s.get("production_order", order_id)

    def get_material_requirements(self, order_id: str) -> list[dict]:
        order = self.get_production_order(order_id)
        if order is None:
            return []
        return [{"material_id": r.material_id, "quantity": r.quantity} for r in order.requirements]

    def get_approved_substitutions(self, product: str) -> list[ApprovedSubstitution]:
        return [s for s in self._s.all("substitution") if s.product == product]

    def get_production_schedule(self) -> list[dict]:
        return sorted(
            (
                {
                    "order_id": o.order_id,
                    "resource": o.resource,
                    "planned_slot": o.planned_slot,
                    "status": o.status.value,
                }
                for o in self._s.all("production_order")
            ),
            key=lambda d: (d["planned_slot"], d["order_id"]),
        )


# ==========================================================================
# DETERMINISTIC EVALUATION TOOLS  (no LLM ever does this arithmetic)
# ==========================================================================


class EvalTools:
    def __init__(self, store: StateStore) -> None:
        self._s = store
        self._r = ReadTools(store)

    def calculate_material_shortage(self, order_id: str) -> dict:
        """Pure arithmetic: required vs usable inventory, per material."""
        order = self._r.get_production_order(order_id)
        if order is None:
            return {"order_id": order_id, "found": False, "shortages": []}

        shortages = []
        for req in order.requirements:
            available = self._r.get_usable_inventory(req.material_id)
            if available < req.quantity:
                shortages.append(
                    {
                        "material_id": req.material_id,
                        "required": req.quantity,
                        "available": available,
                        "short_by": round(req.quantity - available, 6),
                    }
                )
        return {
            "order_id": order_id,
            "found": True,
            "has_shortage": bool(shortages),
            "shortages": shortages,
        }

    def check_schedule_slot(self, order_id: str, target_slot: str) -> dict:
        """Is target_slot free for this order's resource?"""
        order = self._r.get_production_order(order_id)
        if order is None:
            return {"available": False, "reason": "unknown order"}

        conflicts = [
            o
            for o in self._s.all("production_order")
            if o.order_id != order_id
            and o.resource == order.resource
            and o.planned_slot == target_slot
            and o.status is not OrderStatus.HOLD
        ]
        return {
            "order_id": order_id,
            "resource": order.resource,
            "target_slot": target_slot,
            "available": not conflicts,
            "conflicting_orders": [o.order_id for o in conflicts],
        }

    def check_substitution_approval(
        self, product: str, original_material_id: str, substitute_material_id: str
    ) -> dict:
        """Approved substitutions come from the table. Never from an agent."""
        for s in self._r.get_approved_substitutions(product):
            if (
                s.original_material_id == original_material_id
                and s.substitute_material_id == substitute_material_id
            ):
                return {"approved": s.approved, "found": True}
        return {"approved": False, "found": False}

    def evaluate_evidence_against_spec(self, lot_id: str) -> dict:
        """Reconcile lot evidence against the governing plant spec.

        Deterministic fact-finding the agents reason ABOUT. Returns, per spec
        characteristic, whether evidence exists by the required method and
        condition, and whether the value is in limits. This is what makes S2
        (right characteristic, wrong spec limit) and S6 (right characteristic,
        wrong method) separable without hard-coding fixture outcomes.
        """
        lot = self._r.get_lot(lot_id)
        if lot is None:
            return {"lot_id": lot_id, "found": False}

        spec = self._r.get_governing_spec(lot.material_id)
        if spec is None:
            return {"lot_id": lot_id, "found": False, "reason": "no governing spec"}

        evidence = self._r.get_evidence(lot_id)
        findings = []
        for char in spec.characteristics:
            matching = [
                (e, m)
                for e in evidence
                for m in e.measurements
                if m.characteristic == char.name
            ]
            by_method = [
                (e, m)
                for (e, m) in matching
                if m.method == char.method and m.condition == char.condition
            ]

            if not matching:
                findings.append(
                    {
                        "characteristic": char.name,
                        "status": "NO_EVIDENCE",
                        "required_method": char.method,
                        "required_condition": char.condition,
                        "evidence_refs": [],
                    }
                )
                continue

            if not by_method:
                e, m = matching[0]
                findings.append(
                    {
                        "characteristic": char.name,
                        "status": "METHOD_MISMATCH",
                        "required_method": char.method,
                        "required_condition": char.condition,
                        "observed_method": m.method,
                        "observed_condition": m.condition,
                        "evidence_refs": [e.evidence_id for e, _ in matching],
                    }
                )
                continue

            e, m = by_method[0]
            in_limits = True
            if m.value is None:
                in_limits = False
            else:
                if char.min_value is not None and m.value < char.min_value:
                    in_limits = False
                if char.max_value is not None and m.value > char.max_value:
                    in_limits = False

            findings.append(
                {
                    "characteristic": char.name,
                    "status": "IN_LIMITS" if in_limits else "OUT_OF_LIMITS",
                    "required_method": char.method,
                    "required_condition": char.condition,
                    "observed_value": m.value,
                    "limit_min": char.min_value,
                    "limit_max": char.max_value,
                    "units": char.units,
                    "evidence_refs": [e.evidence_id],
                }
            )

        return {
            "lot_id": lot_id,
            "found": True,
            "governing_spec": f"{spec.spec_id} rev {spec.revision}",
            "supplier": lot.supplier,
            "material_id": lot.material_id,
            "findings": findings,
            "evidence_refs": [e.evidence_id for e in evidence],
        }


# ==========================================================================
# MUTATION TOOLS  (gate-authorized only, idempotent)
# ==========================================================================


class MutationTools:
    """Every method demands an AuthorityToken. Verifiers never receive this."""

    def __init__(self, store: StateStore) -> None:
        self._s = store

    def _guard(self, token: AuthorityToken | None, tool: str, target: str) -> None:
        if not isinstance(token, AuthorityToken):
            raise AuthorityError(f"{tool} requires deterministic gate authority; none supplied")
        token.check(tool, target)

    def release_lot(self, lot_id: str, token: AuthorityToken | None = None) -> str:
        self._guard(token, "release_lot", lot_id)
        prior = self._s.already_applied(token.idempotency_key)
        if prior:
            return prior  # replay: no double-release

        self._s.set_lot_status(lot_id, LotStatus.RELEASED)
        self._s.set_inventory_usability(lot_id, Usability.USABLE)
        result = f"lot {lot_id} RELEASED"
        self._s.mark_applied(token.idempotency_key, result)
        return result

    def quarantine_lot(self, lot_id: str, token: AuthorityToken | None = None) -> str:
        self._guard(token, "quarantine_lot", lot_id)
        prior = self._s.already_applied(token.idempotency_key)
        if prior:
            return prior

        self._s.set_lot_status(lot_id, LotStatus.QUARANTINED)
        self._s.set_inventory_usability(lot_id, Usability.NOT_USABLE)
        result = f"lot {lot_id} QUARANTINED"
        self._s.mark_applied(token.idempotency_key, result)
        return result

    def create_qa_review(
        self,
        lot_id: str,
        case_id: str,
        reason: str,
        evidence_refs: tuple[str, ...],
        token: AuthorityToken | None = None,
    ) -> str:
        self._guard(token, "create_qa_review", lot_id)
        prior = self._s.already_applied(token.idempotency_key)
        if prior:
            return prior

        review_id = f"QA-{case_id}"
        self._s.put(
            "qa_review",
            review_id,
            QAReview(
                review_id=review_id,
                case_id=case_id,
                lot_id=lot_id,
                reason=reason,
                evidence_refs=evidence_refs,
            ),
        )
        # Pending QA is an escalation, NOT a defect finding.
        lot = self._s.get("lot", lot_id)
        if lot is not None and lot.status is LotStatus.RECEIVED:
            self._s.set_lot_status(lot_id, LotStatus.PENDING_QA)
        result = f"QA review {review_id} created for lot {lot_id}"
        self._s.mark_applied(token.idempotency_key, result)
        return result

    def hold_production_order(self, order_id: str, token: AuthorityToken | None = None) -> str:
        self._guard(token, "hold_production_order", order_id)
        prior = self._s.already_applied(token.idempotency_key)
        if prior:
            return prior

        self._s.set_order_status(order_id, OrderStatus.HOLD)
        result = f"order {order_id} HOLD"
        self._s.mark_applied(token.idempotency_key, result)
        return result

    def resequence_production_order(
        self, order_id: str, target_slot: str, token: AuthorityToken | None = None
    ) -> str:
        self._guard(token, "resequence_production_order", order_id)
        prior = self._s.already_applied(token.idempotency_key)
        if prior:
            return prior

        from dataclasses import replace as _replace

        order = self._s.get("production_order", order_id)
        if order is None:
            raise KeyError(f"unknown production order {order_id}")
        self._s.put("production_order", order_id, _replace(order, planned_slot=target_slot))
        result = f"order {order_id} resequenced to {target_slot}"
        self._s.mark_applied(token.idempotency_key, result)
        return result
