"""The authoritative corpus — the internal system of record.

Everything here is `AUTHORITATIVE_INTERNAL`. These objects are the ONLY things
that may establish governing basis, method equivalence, approved deviation, or
supplier qualification.

The scoping fields are load-bearing, not decoration. `basis_checks` enforces
currency/supersession/effective-date/site/material/customer/condition scope
deterministically, so "the models agreed" can never substitute for "the
deviation actually covers this site".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterable


def _in_window(when: str, effective: str, expires: str | None) -> bool:
    """Half-open [effective, expires). Dates are ISO strings, so lexical
    comparison is chronological."""
    if when < effective:
        return False
    return expires is None or when < expires


@dataclass(frozen=True)
class Material:
    material_id: str
    name: str
    family: str = ""
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Supplier:
    supplier_id: str
    name: str


@dataclass(frozen=True)
class SupplierSite:
    site_id: str
    supplier_id: str
    name: str = ""


@dataclass(frozen=True)
class SupplierQualification:
    qualification_id: str
    supplier_id: str
    material_id: str
    status: str  # QUALIFIED | SUSPENDED | WITHDRAWN
    effective_date: str
    expiry_date: str | None = None
    #: Empty means "all sites of this supplier". Non-empty is an explicit
    #: allow-list — a lot from an unlisted site is out of scope.
    site_scope: tuple[str, ...] = ()

    def covers(self, *, when: str, site_id: str = "") -> bool:
        if self.status != "QUALIFIED":
            return False
        if not _in_window(when, self.effective_date, self.expiry_date):
            return False
        if self.site_scope and site_id not in self.site_scope:
            return False
        return True


@dataclass(frozen=True)
class Requirement:
    """One test the spec revision requires."""

    requirement_id: str
    characteristic: str
    method: str
    condition: str
    min_value: float | None = None
    max_value: float | None = None
    units: str = ""

    def in_limits(self, value: float) -> bool:
        if self.min_value is not None and value < self.min_value:
            return False
        if self.max_value is not None and value > self.max_value:
            return False
        return True

    def threshold_text(self) -> str:
        if self.min_value is not None and self.max_value is not None:
            return f"[{self.min_value}, {self.max_value}] {self.units}".strip()
        if self.min_value is not None:
            return f">= {self.min_value} {self.units}".strip()
        if self.max_value is not None:
            return f"<= {self.max_value} {self.units}".strip()
        return "reported"


@dataclass(frozen=True)
class SpecificationRevision:
    """A specification at one revision.

    `effective_basis` is the field V1 had nowhere and the eval cases turn on:
    whether the revision keys on date of manufacture or date of receipt. When it
    is None the basis is genuinely unstated and no deterministic rule can pick a
    revision — which is precisely a case for abstention, not a guess.
    """

    spec_id: str
    revision: str
    status: str  # ACTIVE | SUPERSEDED | DRAFT | WITHDRAWN
    effective_date: str
    requirements: tuple[Requirement, ...] = ()
    superseded_by: str | None = None  # revision label
    effective_basis: str | None = None  # "date_of_manufacture" | "date_of_receipt" | None
    material_scope: tuple[str, ...] = ()  # empty = all materials governed by spec_id
    #: Incorporation by reference — other authoritative docs that ADD requirements.
    incorporates: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.spec_id}:{self.revision}"

    @property
    def is_current(self) -> bool:
        return self.status == "ACTIVE" and self.superseded_by is None

    def covers_material(self, material_id: str) -> bool:
        return not self.material_scope or material_id in self.material_scope


@dataclass(frozen=True)
class CustomerOverlay:
    """A customer-specific requirement layered on top of a spec revision."""

    overlay_id: str
    customer_id: str
    spec_id: str
    material_id: str
    requirements: tuple[Requirement, ...] = ()
    effective_date: str = "0000-01-01"
    expiry_date: str | None = None

    def covers(self, *, customer_id: str, material_id: str, when: str) -> bool:
        return (
            self.customer_id == customer_id
            and self.material_id == material_id
            and _in_window(when, self.effective_date, self.expiry_date)
        )


@dataclass(frozen=True)
class ApprovedDeviation:
    """Permission to accept something that would otherwise fail.

    Scope is what makes this safe: a deviation approved for one PO at one site
    does not silently cover a different lot.
    """

    deviation_id: str
    material_id: str
    characteristic: str
    status: str  # APPROVED | EXPIRED | WITHDRAWN
    effective_date: str
    expiry_date: str | None = None
    site_scope: tuple[str, ...] = ()
    po_scope: tuple[str, ...] = ()
    lot_scope: tuple[str, ...] = ()
    accepts_min: float | None = None
    accepts_max: float | None = None
    note: str = ""

    def covers(
        self, *, material_id: str, characteristic: str, when: str,
        site_id: str = "", po: str = "", lot_id: str = "",
    ) -> bool:
        if self.status != "APPROVED":
            return False
        if self.material_id != material_id or self.characteristic != characteristic:
            return False
        if not _in_window(when, self.effective_date, self.expiry_date):
            return False
        if self.site_scope and site_id not in self.site_scope:
            return False
        if self.po_scope and po not in self.po_scope:
            return False
        if self.lot_scope and lot_id not in self.lot_scope:
            return False
        return True

    def accepts(self, value: float) -> bool:
        if self.accepts_min is not None and value < self.accepts_min:
            return False
        if self.accepts_max is not None and value > self.accepts_max:
            return False
        return True


@dataclass(frozen=True)
class MethodEquivalence:
    """An authoritative record that method B may stand in for method A.

    `condition_scope` is the subtle one: an equivalence valid only at room
    temperature does not cover a test run at 80C, and no model assertion can
    widen it.
    """

    equivalence_id: str
    required_method: str
    alternate_method: str
    status: str  # APPROVED | WITHDRAWN | DRAFT
    effective_date: str
    expiry_date: str | None = None
    material_scope: tuple[str, ...] = ()
    condition_scope: tuple[str, ...] = ()  # empty = all conditions
    characteristic_scope: tuple[str, ...] = ()

    def covers(
        self, *, required_method: str, used_method: str, when: str,
        material_id: str = "", condition: str = "", characteristic: str = "",
    ) -> bool:
        if self.status != "APPROVED":
            return False
        if self.required_method != required_method or self.alternate_method != used_method:
            return False
        if not _in_window(when, self.effective_date, self.expiry_date):
            return False
        if self.material_scope and material_id not in self.material_scope:
            return False
        if self.condition_scope and condition not in self.condition_scope:
            return False
        if self.characteristic_scope and characteristic not in self.characteristic_scope:
            return False
        return True


@dataclass(frozen=True)
class MaterialRequirementLine:
    material_id: str
    quantity: float


@dataclass(frozen=True)
class ProductionOrder:
    order_id: str
    product: str
    quantity: float
    requirements: tuple[MaterialRequirementLine, ...]
    resource: str
    planned_slot: str
    status: str = "READY"  # READY | AT_RISK | BLOCKED | COMPLETE
    customer_id: str = ""
    customer_committed: bool = False
    need_by: str = ""
    state_version: int = 1


@dataclass(frozen=True)
class Lot:
    lot_id: str
    supplier_id: str
    material_id: str
    po_reference: str
    quantity: float
    status: str = "RECEIVED"  # RECEIVED | RELEASED | QUARANTINED | PENDING_QA | REJECTED
    units: str = "kg"
    supplier_site: str = ""
    customer_id: str = ""
    manufactured_at: str = ""
    received_at: str = ""
    state_version: int = 1


@dataclass(frozen=True)
class InventoryRecord:
    material_id: str
    lot_id: str
    quantity: float
    usable: bool = False


@dataclass(frozen=True)
class ApprovedSubstitution:
    product: str
    original_material_id: str
    substitute_material_id: str
    approved: bool


class Corpus:
    """In-memory authoritative corpus.

    ponytail: dict-of-dicts, not a repository-per-entity abstraction. The read
    surface below is what the Strands tools and deterministic checks consume;
    the DynamoDB adapter implements the same `get`/`all` pair.
    """

    def __init__(self) -> None:
        self._t: dict[str, dict[str, Any]] = {}

    # -- generic ----------------------------------------------------------
    def put(self, kind: str, key: str, value: Any) -> None:
        self._t.setdefault(kind, {})[key] = value

    def get(self, kind: str, key: str) -> Any:
        return self._t.get(kind, {}).get(key)

    def all(self, kind: str) -> list[Any]:
        return list(self._t.get(kind, {}).values())

    # -- typed reads used by tools and deterministic checks ---------------
    def material(self, material_id: str) -> Material | None:
        return self.get("material", material_id)

    def lot(self, lot_id: str) -> Lot | None:
        return self.get("lot", lot_id)

    def order(self, order_id: str) -> ProductionOrder | None:
        return self.get("production_order", order_id)

    def spec_revision(self, spec_id: str, revision: str) -> SpecificationRevision | None:
        return self.get("spec_revision", f"{spec_id}:{revision}")

    def candidate_specs(self, material_id: str) -> list[SpecificationRevision]:
        """Every revision that could plausibly govern this material.

        Deliberately does NOT pick one — choosing among these is the model's
        job. Returning a single answer here is exactly the V1 mistake of
        handing the model a precomputed conclusion.
        """
        out = [
            r
            for r in self.all("spec_revision")
            if r.covers_material(material_id) and r.status in ("ACTIVE", "SUPERSEDED")
        ]
        return sorted(out, key=lambda r: (r.spec_id, r.revision))

    def deviations_for(self, material_id: str) -> list[ApprovedDeviation]:
        return [d for d in self.all("deviation") if d.material_id == material_id]

    def equivalences_for(self, material_id: str) -> list[MethodEquivalence]:
        return [
            e
            for e in self.all("equivalence")
            if not e.material_scope or material_id in e.material_scope
        ]

    def qualification(self, supplier_id: str, material_id: str) -> SupplierQualification | None:
        for q in self.all("supplier_qualification"):
            if q.supplier_id == supplier_id and q.material_id == material_id:
                return q
        return None

    def overlays_for(self, material_id: str, customer_id: str) -> list[CustomerOverlay]:
        return [
            o
            for o in self.all("customer_overlay")
            if o.material_id == material_id and o.customer_id == customer_id
        ]

    def usable_inventory(self, material_id: str) -> float:
        return sum(
            r.quantity
            for r in self.all("inventory")
            if r.material_id == material_id and r.usable
        )

    def substitutions_for(self, product: str) -> list[ApprovedSubstitution]:
        return [s for s in self.all("substitution") if s.product == product]

    # -- optimistic concurrency ------------------------------------------
    def bump(self, kind: str, key: str, **changes: Any) -> Any:
        """Apply changes and increment state_version in one step.

        Callers must have already validated the expected version; the
        capability consume path (authority.py) is what enforces that.
        """
        current = self.get(kind, key)
        if current is None:
            raise KeyError(f"unknown {kind} {key}")
        updated = replace(current, state_version=current.state_version + 1, **changes)
        self.put(kind, key, updated)
        return updated

    def version_of(self, kind: str, key: str) -> int:
        obj = self.get(kind, key)
        return getattr(obj, "state_version", 0) if obj is not None else 0


__all__ = [
    "ApprovedDeviation",
    "ApprovedSubstitution",
    "Corpus",
    "CustomerOverlay",
    "InventoryRecord",
    "Lot",
    "Material",
    "MaterialRequirementLine",
    "MethodEquivalence",
    "ProductionOrder",
    "Requirement",
    "SpecificationRevision",
    "Supplier",
    "SupplierQualification",
    "SupplierSite",
]
