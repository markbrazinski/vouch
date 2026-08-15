"""Smoke-test fixtures: one small, adversarial-ready world.

Designed so each scenario turns on a different failure mode:
  LOT-1001  clean            -> release is defensible
  LOT-1002  hero             -> supplier CoA looks fine against ITS OWN cited
                                spec, but the governing plant spec rev C is
                                tighter, so release cannot be defended
  LOT-1003  ambiguous        -> right characteristic, wrong method/condition
  MAT-SUB-9 unapproved sub   -> plenty of stock, not approved for P-417
"""

from __future__ import annotations

from .state import (
    ApprovedSubstitution,
    Characteristic,
    Evidence,
    EvidenceMeasurement,
    InventoryRecord,
    Lot,
    LotStatus,
    Material,
    MaterialRequirement,
    MaterialSpecification,
    OrderStatus,
    ProductionOrder,
    StateStore,
    SupplierQualification,
    Usability,
)

BUCKET = "s3://gatehouse-evidence"


def build_store() -> StateStore:
    s = StateStore()

    # -- materials ------------------------------------------------------
    s.put("material", "MAT-ALLOY-7", Material("MAT-ALLOY-7", "Alloy 7 billet", "SPEC-A7", "C"))
    s.put("material", "MAT-RESIN-3", Material("MAT-RESIN-3", "Resin 3", "SPEC-R3", "A"))
    s.put("material", "MAT-SUB-9", Material("MAT-SUB-9", "Alloy 9 billet", "SPEC-A9", "A"))

    # Governing plant spec rev C: tensile >= 480 MPa.
    # The supplier CoA for LOT-1002 cites rev B (>= 450), which it passes.
    # Reconciliation against rev C is what makes the hero lot indefensible.
    s.put(
        "spec",
        "SPEC-A7:C",
        MaterialSpecification(
            spec_id="SPEC-A7",
            revision="C",
            status="ACTIVE",
            characteristics=(
                Characteristic("tensile_strength", "ASTM-E8", "room_temp", 480.0, None, "MPa"),
                Characteristic("hardness", "HRC", "as_received", 28.0, 36.0, "HRC"),
            ),
        ),
    )
    s.put(
        "spec",
        "SPEC-R3:A",
        MaterialSpecification(
            spec_id="SPEC-R3",
            revision="A",
            status="ACTIVE",
            characteristics=(
                Characteristic("viscosity", "ASTM-D2196", "25C", 200.0, 400.0, "cP"),
            ),
        ),
    )
    s.put(
        "spec",
        "SPEC-A9:A",
        MaterialSpecification(
            spec_id="SPEC-A9",
            revision="A",
            status="ACTIVE",
            characteristics=(
                Characteristic("tensile_strength", "ASTM-E8", "room_temp", 470.0, None, "MPa"),
            ),
        ),
    )

    # -- supplier qualification ----------------------------------------
    for supplier, material in [
        ("SUP-NORTH", "MAT-ALLOY-7"),
        ("SUP-EAST", "MAT-ALLOY-7"),
        ("SUP-WEST", "MAT-RESIN-3"),
        ("SUP-NORTH", "MAT-SUB-9"),
    ]:
        s.put(
            "supplier_qualification",
            f"{supplier}:{material}",
            SupplierQualification(supplier, material, "QUALIFIED", "2024-01-01", None),
        )

    # -- lots -----------------------------------------------------------
    s.put("lot", "LOT-1001", Lot("LOT-1001", "SUP-NORTH", "MAT-ALLOY-7", "PO-77", 500.0))
    s.put("lot", "LOT-1002", Lot("LOT-1002", "SUP-EAST", "MAT-ALLOY-7", "PO-78", 400.0))
    s.put("lot", "LOT-1003", Lot("LOT-1003", "SUP-WEST", "MAT-RESIN-3", "PO-79", 300.0))

    # -- evidence -------------------------------------------------------
    # LOT-1001: complete, correct method, within governing rev C limits.
    s.put(
        "evidence",
        "EV-1001-CoA",
        Evidence(
            "EV-1001-CoA", "certificate_of_analysis", "SUP-NORTH",
            f"{BUCKET}/LOT-1001/coa.pdf", "LOT-1001", "MAT-ALLOY-7",
            (
                EvidenceMeasurement("tensile_strength", "ASTM-E8", "room_temp", 512.0, "MPa"),
                EvidenceMeasurement("hardness", "HRC", "as_received", 31.0, "HRC"),
            ),
        ),
    )

    # LOT-1002 (HERO): CoA cites SPEC-A7 rev B (>=450) and reads 462 MPa.
    # Defensible against rev B. NOT defensible against governing rev C (>=480).
    s.put(
        "evidence",
        "EV-1002-CoA",
        Evidence(
            "EV-1002-CoA", "certificate_of_analysis", "SUP-EAST",
            f"{BUCKET}/LOT-1002/coa.pdf", "LOT-1002", "MAT-ALLOY-7",
            (
                EvidenceMeasurement("tensile_strength", "ASTM-E8", "room_temp", 462.0, "MPa"),
                EvidenceMeasurement("hardness", "HRC", "as_received", 30.0, "HRC"),
            ),
        ),
    )

    # LOT-1003 (AMBIGUOUS): viscosity measured, but by a different method at a
    # different temperature. Related to the characteristic; does not establish it.
    s.put(
        "evidence",
        "EV-1003-CoA",
        Evidence(
            "EV-1003-CoA", "certificate_of_analysis", "SUP-WEST",
            f"{BUCKET}/LOT-1003/coa.pdf", "LOT-1003", "MAT-RESIN-3",
            (
                EvidenceMeasurement("viscosity", "ASTM-D445", "40C", 268.0, "cP"),
            ),
        ),
    )

    # -- inventory ------------------------------------------------------
    # Incoming lots are NOT usable until released.
    s.put("inventory", "LOT-1001", InventoryRecord("MAT-ALLOY-7", "LOT-1001", 500.0, Usability.NOT_USABLE))
    s.put("inventory", "LOT-1002", InventoryRecord("MAT-ALLOY-7", "LOT-1002", 400.0, Usability.NOT_USABLE))
    s.put("inventory", "LOT-1003", InventoryRecord("MAT-RESIN-3", "LOT-1003", 300.0, Usability.NOT_USABLE))
    # Unapproved substitute: plenty on hand. Availability is not authority.
    s.put("inventory", "LOT-9001", InventoryRecord("MAT-SUB-9", "LOT-9001", 900.0, Usability.USABLE))
    # C-418's material, already released.
    s.put("inventory", "LOT-8001", InventoryRecord("MAT-RESIN-3", "LOT-8001", 600.0, Usability.USABLE))
    s.put("lot", "LOT-8001", Lot("LOT-8001", "SUP-WEST", "MAT-RESIN-3", "PO-60", 600.0, LotStatus.RELEASED))
    s.put("lot", "LOT-9001", Lot("LOT-9001", "SUP-NORTH", "MAT-SUB-9", "PO-61", 900.0, LotStatus.RELEASED))

    # -- production orders ----------------------------------------------
    # C-417 needs 800 of MAT-ALLOY-7. LOT-1001 (500) + LOT-1002 (400) = 900.
    # Quarantining LOT-1002 leaves 500 -> short by 300.
    s.put(
        "production_order",
        "C-417",
        ProductionOrder(
            "C-417", "P-417", 100.0,
            (MaterialRequirement("MAT-ALLOY-7", 800.0),),
            "LINE-1", "2026-08-15T08:00", OrderStatus.READY,
        ),
    )
    # C-418: material released, same resource, can take the vacated slot.
    s.put(
        "production_order",
        "C-418",
        ProductionOrder(
            "C-418", "P-418", 80.0,
            (MaterialRequirement("MAT-RESIN-3", 400.0),),
            "LINE-1", "2026-08-15T14:00", OrderStatus.READY,
        ),
    )
    # C-419: different resource, so not a compatible resequence candidate.
    s.put(
        "production_order",
        "C-419",
        ProductionOrder(
            "C-419", "P-419", 50.0,
            (MaterialRequirement("MAT-RESIN-3", 200.0),),
            "LINE-2", "2026-08-15T09:00", OrderStatus.READY,
        ),
    )

    # -- substitutions ---------------------------------------------------
    # MAT-SUB-9 is explicitly NOT approved for P-417.
    s.put(
        "substitution",
        "P-417:MAT-ALLOY-7:MAT-SUB-9",
        ApprovedSubstitution("P-417", "MAT-ALLOY-7", "MAT-SUB-9", approved=False),
    )

    return s


def add_qa_evidence(store: StateStore, lot_id: str = "LOT-1003") -> str:
    """S7: QA supplies the missing correct-method evidence."""
    evidence_id = f"EV-{lot_id.split('-')[1]}-QA"
    store.put(
        "evidence",
        evidence_id,
        Evidence(
            evidence_id, "qa_retest", "PLANT-QA-LAB",
            f"{BUCKET}/{lot_id}/qa_retest.pdf", lot_id, "MAT-RESIN-3",
            (EvidenceMeasurement("viscosity", "ASTM-D2196", "25C", 305.0, "cP"),),
        ),
    )
    return evidence_id
