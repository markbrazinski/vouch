"""V2 load-bearing evaluation corpus (contract D21).

WHY THIS EXISTS RATHER THAN REUSING adversarial.py
==================================================

V1's `adversarial.py` is a good adversarial set and is kept. But it cannot
measure the V2 load-bearing gate, because each case's `structured` dict encodes
the case's own ambiguity as an explicit field:

    TC-01  "correlation": {"corrected_value_cp": 305.0}   <- the answer
    GS-03  "rev_c_basis": None                            <- the answer
    ME-02  "equivalence": {"conditions": "room_temp_only"} <- the answer

A deterministic baseline reading those fields is not solving the interpretive
problem; it is reading a pre-solved answer. Measured on V1: the raw-document
baseline scored 8/8 on the `rule_solvable=False` slice while Nova scored 6/8,
7/8 and 4/8. The baseline was at ceiling, so no agent could "materially beat"
it, and the gate could only ever fail — for a fixture reason, not an
architectural one.

THE V2 RULE, applied to every case below
========================================

`erp` contains ONLY what a real ERP/LIMS genuinely holds as structured data:
identifiers, dates, quantities, numbers, status flags. It NEVER contains a
resolved basis, a scope interpretation, a correlation factor, or an
applicability verdict.

The interpretive material lives in `corpus_objects` (authoritative documents the
tools return) and `documents` (supplier text). Establishing what governs and
what applies requires reading those and reasoning over them.

This is what makes segment `AGENT_VALUABLE` meaningful: a deterministic
basis-selector working from `erp` alone genuinely cannot resolve these, so if
the agents can, the gap is real rather than manufactured.

Ground truth is `gold_basis` (spec_id + revision) and `gold_applicability` (per
test: APPLIES | NOT_APPLICABLE | ABSENT), plus `gold_disposition` for
end-to-end checking. The gate is measured on BASIS and APPLICABILITY accuracy —
not on disposition, which is deterministic by design (contract D21).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Segment = Literal["RULE_SOLVABLE", "AGENT_VALUABLE", "HUMAN_ONLY"]
Applicability = Literal["APPLIES", "NOT_APPLICABLE", "ABSENT"]


@dataclass
class EvalCase:
    case_id: str
    segment: Segment
    ambiguity_type: str
    description: str

    #: What a conventional system genuinely has as structured data.
    erp: dict

    #: Authoritative corpus objects the read tools will surface.
    corpus_objects: dict

    #: Supplier document text (untrusted).
    documents: list[str]

    #: Ground truth, authored from manufacturing logic before any run.
    gold_basis: tuple[str, str]
    gold_applicability: dict[str, Applicability]
    gold_disposition: str  # RELEASE | QUARANTINE | ABSTAIN

    why: str = ""
    tags: list[str] = field(default_factory=list)


# ==========================================================================
# helpers to keep case definitions readable
# ==========================================================================


def _spec(spec_id, revision, status, effective, basis, reqs, superseded_by=None,
          incorporates=(), material_scope=("MAT-ALLOY-7",)):
    return {
        "kind": "spec_revision", "spec_id": spec_id, "revision": revision,
        "status": status, "effective_date": effective, "effective_basis": basis,
        "superseded_by": superseded_by, "incorporates": incorporates,
        "material_scope": material_scope, "requirements": reqs,
    }


def _req(rid, characteristic, method, condition, lo=None, hi=None, units=""):
    return {
        "requirement_id": rid, "characteristic": characteristic, "method": method,
        "condition": condition, "min_value": lo, "max_value": hi, "units": units,
    }


TENSILE_480 = _req("REQ-C-1", "tensile_strength", "ASTM-E8", "room_temp", 480.0, None, "MPa")
TENSILE_450 = _req("REQ-B-1", "tensile_strength", "ASTM-E8", "room_temp", 450.0, None, "MPa")
VISCOSITY = _req("REQ-R-1", "viscosity", "ASTM-D2196", "25C", 200.0, 400.0, "cP")


CASES: list[EvalCase] = [

    # ==================================================================
    # RULE_SOLVABLE — basis is unambiguous; disposition is arithmetic.
    # A deterministic baseline is EXPECTED to match or win here.
    # ==================================================================

    EvalCase(
        case_id="RS-01",
        segment="RULE_SOLVABLE",
        ambiguity_type="none",
        description="Single active revision, method matches, value passes",
        erp={
            "lot_id": "LOT-RS01", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-1",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-RS01\n"
            "tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="RELEASE",
        why="One active revision, exact method match, 512 >= 480.",
        tags=["baseline-should-win"],
    ),

    EvalCase(
        case_id="RS-02",
        segment="RULE_SOLVABLE",
        ambiguity_type="none",
        description="Single active revision, value fails",
        erp={
            "lot_id": "LOT-RS02", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-2",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-RS02\n"
            "tensile_strength: 431 MPa (ASTM-E8, room_temp)\n"
            "Result: CONFORMS to the referenced specification.\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="QUARANTINE",
        why="431 < 480. The supplier's CONFORMS statement is not authority.",
        tags=["baseline-should-win", "false-conformance-claim"],
    ),

    EvalCase(
        case_id="RS-03",
        segment="RULE_SOLVABLE",
        ambiguity_type="supersession",
        description="Explicit supersession with a stated receipt basis",
        erp={
            "lot_id": "LOT-RS03", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-02", "manufactured_at": "2026-02-05",
            "po_reference": "PO-3",
        },
        corpus_objects={
            "specs": [
                _spec("SPEC-A7", "B", "SUPERSEDED", "2024-01-01", "date_of_receipt",
                      [TENSILE_450], superseded_by="C"),
                _spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                      [TENSILE_480]),
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-RS03\n"
            "Specification SPEC-A7 Revision B\n"
            "tensile_strength: 462 MPa (ASTM-E8, room_temp)\n"
            "Result: CONFORMS to the referenced specification.\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="QUARANTINE",
        why="Rev C keys on receipt; received 2026-03-02 >= 2026-01-01, so C governs; 462 < 480.",
        tags=["baseline-should-win", "supersession"],
    ),

    EvalCase(
        case_id="RS-04",
        segment="RULE_SOLVABLE",
        ambiguity_type="missing_test",
        description="A required test is simply not reported",
        erp={
            "lot_id": "LOT-RS04", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-4",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480,
                             _req("REQ-C-2", "hardness", "HRC", "as_received", 28.0, 36.0, "HRC")])],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-RS04\n"
            "tensile_strength: 495 MPa (ASTM-E8, room_temp)\n"
            "All specified requirements CONFORM.\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES", "hardness": "ABSENT"},
        gold_disposition="ABSTAIN",
        why="Hardness is required and not reported. A blanket CONFORMS does not establish it.",
        tags=["baseline-should-win", "blanket-conformance"],
    ),

    # ==================================================================
    # AGENT_VALUABLE — basis/applicability is genuinely interpretive.
    #
    # The discipline for every case here: `erp` contains NO field that
    # encodes the answer. The interpretive material is in the documents
    # and the authoritative objects, and must be reasoned over.
    # ==================================================================

    EvalCase(
        case_id="AV-01",
        segment="AGENT_VALUABLE",
        ambiguity_type="incorporation_by_reference",
        description="Governing revision incorporates another document that adds a requirement",
        erp={
            "lot_id": "LOT-AV01", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-11",
        },
        corpus_objects={
            "specs": [
                _spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                      [TENSILE_480], incorporates=("SPEC-A7X:A",)),
                _spec("SPEC-A7X", "A", "ACTIVE", "2024-01-01", "date_of_receipt",
                      [_req("REQ-X-1", "grain_size", "ASTM-E112", "as_received",
                            None, 8.0, "ASTM")]),
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV01\n"
            "Specification SPEC-A7 Revision C\n"
            "tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
            "All requirements of the referenced specification are met.\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES", "grain_size": "ABSENT"},
        gold_disposition="ABSTAIN",
        why=(
            "SPEC-A7 rev C incorporates SPEC-A7X rev A, which adds a grain-size "
            "requirement. The COA reports tensile only. The incorporated requirement "
            "is unreported, so release cannot be defended. A baseline that reads only "
            "the named spec's own requirement list misses the incorporated one."
        ),
        tags=["incorporation", "hidden-requirement"],
    ),

    EvalCase(
        case_id="AV-02",
        segment="AGENT_VALUABLE",
        ambiguity_type="scoped_equivalence",
        description="Equivalence exists but its condition scope excludes this test",
        erp={
            "lot_id": "LOT-AV02", "material_id": "MAT-RESIN-3",
            "supplier_id": "SUP-WEST", "supplier_site": "SITE-W1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-12",
        },
        corpus_objects={
            "specs": [_spec("SPEC-R3", "A", "ACTIVE", "2024-01-01", "date_of_receipt",
                            [VISCOSITY], material_scope=("MAT-RESIN-3",))],
            "equivalences": [
                {
                    "equivalence_id": "EQV-11", "required_method": "ASTM-D2196",
                    "alternate_method": "ASTM-D445", "status": "APPROVED",
                    "effective_date": "2024-01-01", "expiry_date": None,
                    "material_scope": ("MAT-RESIN-3",), "condition_scope": ("25C",),
                    "characteristic_scope": ("viscosity",),
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV02\n"
            "viscosity: 268 cP (ASTM-D445, 40C)\n"
            "Method ASTM-D445 is an approved equivalent to ASTM-D2196 per plant "
            "equivalence record EQV-11.\n"
        ],
        gold_basis=("SPEC-R3", "A"),
        gold_applicability={"viscosity": "NOT_APPLICABLE"},
        gold_disposition="ABSTAIN",
        why=(
            "EQV-11 is real and approved, but scoped to 25C. The test ran at 40C, so "
            "the equivalence does not cover it and the requirement is unestablished. "
            "The supplier's citation of EQV-11 is superficially correct and misleading."
        ),
        tags=["scope-containment", "plausible-but-wrong-citation"],
    ),

    EvalCase(
        case_id="AV-03",
        segment="AGENT_VALUABLE",
        ambiguity_type="effective_basis_ambiguity",
        description="Effective basis unstated and the lot straddles the boundary",
        erp={
            "lot_id": "LOT-AV03", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-01-08", "manufactured_at": "2025-12-20",
            "po_reference": "PO-13",
        },
        corpus_objects={
            "specs": [
                _spec("SPEC-A7", "B", "SUPERSEDED", "2024-01-01", None,
                      [TENSILE_450], superseded_by="C"),
                # effective_basis deliberately None: the change notice never said.
                _spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", None, [TENSILE_480]),
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV03\n"
            "Manufactured 20 Dec 2025. Received 8 Jan 2026.\n"
            "tensile_strength: 462 MPa (ASTM-E8, room_temp)\n"
            "[Change notice ECN-2291 rev 2] Revision C of SPEC-A7 becomes effective "
            "1 January 2026. Material is to be assessed against the applicable revision.\n"
        ],
        gold_basis=("SPEC-A7", "B"),  # convention: cannot advance without a stated basis
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="ABSTAIN",
        why=(
            "The notice does not state whether the effective date keys on manufacture "
            "or receipt, and the lot straddles 2026-01-01. Under rev B (462>=450) it "
            "passes; under rev C (462<480) it fails. The basis cannot be established, "
            "so no autonomous disposition is defensible."
        ),
        tags=["straddles-boundary", "unstated-basis"],
    ),

    EvalCase(
        case_id="AV-04",
        segment="AGENT_VALUABLE",
        ambiguity_type="customer_overlay",
        description="Customer overlay tightens the plant requirement",
        erp={
            "lot_id": "LOT-AV04", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-14", "customer_id": "CUST-AERO",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
            "overlays": [
                {
                    "overlay_id": "OVL-AERO-1", "customer_id": "CUST-AERO",
                    "spec_id": "SPEC-A7", "material_id": "MAT-ALLOY-7",
                    "effective_date": "2025-06-01", "expiry_date": None,
                    "requirements": [
                        _req("REQ-OVL-1", "tensile_strength", "ASTM-E8", "room_temp",
                             520.0, None, "MPa"),
                    ],
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV04\n"
            "Specification SPEC-A7 Revision C\n"
            "tensile_strength: 495 MPa (ASTM-E8, room_temp)\n"
            "Result: CONFORMS to SPEC-A7 Rev C (minimum 480 MPa).\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="QUARANTINE",
        why=(
            "The lot is for CUST-AERO, whose overlay OVL-AERO-1 raises tensile to 520. "
            "495 passes the plant spec and fails the governing customer requirement. "
            "A baseline keyed only on the material's plant spec releases this wrongly."
        ),
        tags=["customer-scope", "overlay"],
    ),

    EvalCase(
        case_id="AV-05",
        segment="AGENT_VALUABLE",
        ambiguity_type="renamed_method",
        description="Method renamed by the standards body; supplier uses the new name",
        erp={
            "lot_id": "LOT-AV05", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-15",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
            "equivalences": [
                {
                    "equivalence_id": "EQV-15", "required_method": "ASTM-E8",
                    "alternate_method": "ISO-6892", "status": "APPROVED",
                    "effective_date": "2024-01-01", "expiry_date": None,
                    "material_scope": ("MAT-ALLOY-7",), "condition_scope": (),
                    "characteristic_scope": ("tensile_strength",),
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV05\n"
            "tensile_strength: 498 MPa (ISO-6892, room_temp)\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="RELEASE",
        why=(
            "The spec requires ASTM-E8; the COA reports ISO-6892. EQV-15 authoritatively "
            "covers that substitution for this material and characteristic with no "
            "condition restriction, so the evidence DOES apply and 498 >= 480. A naive "
            "method-string comparison abstains here, which is a false abstention."
        ),
        tags=["equivalence-applies", "false-abstention-trap"],
    ),

    EvalCase(
        case_id="AV-06",
        segment="AGENT_VALUABLE",
        ambiguity_type="withdrawn_equivalence",
        description="Equivalence the supplier cites was withdrawn before receipt",
        erp={
            "lot_id": "LOT-AV06", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-16",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
            "equivalences": [
                {
                    "equivalence_id": "EQV-16", "required_method": "ASTM-E8",
                    "alternate_method": "ISO-6892", "status": "WITHDRAWN",
                    "effective_date": "2024-01-01", "expiry_date": "2025-12-31",
                    "material_scope": ("MAT-ALLOY-7",), "condition_scope": (),
                    "characteristic_scope": ("tensile_strength",),
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV06\n"
            "tensile_strength: 498 MPa (ISO-6892, room_temp)\n"
            "Tested per ISO-6892, accepted as equivalent to ASTM-E8 under EQV-16.\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "NOT_APPLICABLE"},
        gold_disposition="ABSTAIN",
        why=(
            "Structurally identical to AV-05 — same methods, same value, same citation "
            "— but EQV-16 is WITHDRAWN and expired 2025-12-31, before this lot was "
            "received. The equivalence does not apply, so the requirement is "
            "unestablished. AV-05/AV-06 as a pair defeat surface-cue matching."
        ),
        tags=["currency-check", "paired-with-AV-05"],
    ),

    EvalCase(
        case_id="AV-07",
        segment="AGENT_VALUABLE",
        ambiguity_type="conditional_applicability",
        description="Deviation covers the value but is scoped to a different site",
        erp={
            "lot_id": "LOT-AV07", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N2",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-17",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
            "deviations": [
                {
                    "deviation_id": "DEV-17", "material_id": "MAT-ALLOY-7",
                    "characteristic": "tensile_strength", "status": "APPROVED",
                    "effective_date": "2026-01-01", "expiry_date": None,
                    "site_scope": ("SITE-N1",), "po_scope": (), "lot_scope": (),
                    "accepts_min": 460.0, "accepts_max": None,
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV07\n"
            "Manufacturing site: SITE-N2\n"
            "tensile_strength: 468 MPa (ASTM-E8, room_temp)\n"
            "Accepted under approved deviation DEV-17 (minimum 460 MPa).\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="QUARANTINE",
        why=(
            "DEV-17 is current and would accept 468, but it is scoped to SITE-N1 and "
            "this lot came from SITE-N2. The deviation does not cover this lot, so "
            "468 < 480 stands as a genuine non-conformance."
        ),
        tags=["site-scope", "deviation-scope"],
    ),

    EvalCase(
        case_id="AV-08",
        segment="AGENT_VALUABLE",
        ambiguity_type="conflicting_authorities",
        description="Two plausible governing revisions with different material scopes",
        erp={
            "lot_id": "LOT-AV08", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-18",
        },
        corpus_objects={
            "specs": [
                # Newer and active, but scoped to a DIFFERENT material.
                _spec("SPEC-A7", "D", "ACTIVE", "2026-02-01", "date_of_receipt",
                      [_req("REQ-D-1", "tensile_strength", "ASTM-E8", "room_temp",
                            520.0, None, "MPa")],
                      material_scope=("MAT-ALLOY-9",)),
                _spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                      [TENSILE_480], material_scope=("MAT-ALLOY-7",)),
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV08\n"
            "tensile_strength: 495 MPa (ASTM-E8, room_temp)\n"
            "Specification SPEC-A7 (latest revision).\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="RELEASE",
        why=(
            "Rev D is newer and active but scoped to MAT-ALLOY-9. This lot is "
            "MAT-ALLOY-7, so rev C governs and 495 >= 480 passes. A baseline that "
            "picks 'the latest revision' quarantines this wrongly at 495 < 520."
        ),
        tags=["material-scope", "latest-is-wrong"],
    ),

    EvalCase(
        case_id="AV-09",
        segment="AGENT_VALUABLE",
        ambiguity_type="incorporation_by_reference",
        description="Incorporated document is satisfied by the reported evidence",
        erp={
            "lot_id": "LOT-AV09", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-19",
        },
        corpus_objects={
            "specs": [
                _spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                      [TENSILE_480], incorporates=("SPEC-A7X:A",)),
                _spec("SPEC-A7X", "A", "ACTIVE", "2024-01-01", "date_of_receipt",
                      [_req("REQ-X-1", "grain_size", "ASTM-E112", "as_received",
                            None, 8.0, "ASTM")]),
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV09\n"
            "Specification SPEC-A7 Revision C\n"
            "tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
            "grain_size: 6 ASTM (ASTM-E112, as_received)\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES", "grain_size": "APPLIES"},
        gold_disposition="RELEASE",
        why=(
            "Pairs with AV-01: the same incorporation, but here the incorporated "
            "grain-size requirement IS reported and passes (6 <= 8). Correct handling "
            "means releasing, so a system that blanket-abstains on incorporation gets "
            "this wrong."
        ),
        tags=["incorporation", "paired-with-AV-01"],
    ),

    EvalCase(
        case_id="AV-10",
        segment="AGENT_VALUABLE",
        ambiguity_type="supersession_chain",
        description="Two-step supersession where the middle revision is withdrawn",
        erp={
            "lot_id": "LOT-AV10", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-20",
        },
        corpus_objects={
            "specs": [
                _spec("SPEC-A7", "B", "SUPERSEDED", "2024-01-01", "date_of_receipt",
                      [TENSILE_450], superseded_by="C"),
                # C was withdrawn (a bad revision), so it cannot govern.
                _spec("SPEC-A7", "C", "WITHDRAWN", "2026-01-01", "date_of_receipt",
                      [TENSILE_480], superseded_by="D"),
                _spec("SPEC-A7", "D", "ACTIVE", "2026-02-15", "date_of_receipt",
                      [_req("REQ-D2-1", "tensile_strength", "ASTM-E8", "room_temp",
                            470.0, None, "MPa")]),
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV10\n"
            "Specification SPEC-A7 Revision C\n"
            "tensile_strength: 475 MPa (ASTM-E8, room_temp)\n"
            "Result: does not meet Revision C minimum of 480 MPa.\n"
        ],
        gold_basis=("SPEC-A7", "D"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="RELEASE",
        why=(
            "Rev C is WITHDRAWN and cannot govern. Rev D is active and effective "
            "2026-02-15, before this lot's 2026-03-01 receipt, so D governs at 470 "
            "and 475 passes. The supplier's own document argues for rejection against "
            "a revision that is not in force."
        ),
        tags=["withdrawn-revision", "supplier-argues-wrong-way"],
    ),

    EvalCase(
        case_id="AV-11",
        segment="AGENT_VALUABLE",
        ambiguity_type="scoped_equivalence",
        description="Equivalence applies to one characteristic but not the other",
        erp={
            "lot_id": "LOT-AV11", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-21",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480,
                             _req("REQ-C-2", "hardness", "HRC", "as_received",
                                  28.0, 36.0, "HRC")])],
            "equivalences": [
                {
                    "equivalence_id": "EQV-21", "required_method": "ASTM-E8",
                    "alternate_method": "ISO-6892", "status": "APPROVED",
                    "effective_date": "2024-01-01", "expiry_date": None,
                    "material_scope": ("MAT-ALLOY-7",), "condition_scope": (),
                    # Scoped to tensile only — NOT hardness.
                    "characteristic_scope": ("tensile_strength",),
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-AV11\n"
            "tensile_strength: 498 MPa (ISO-6892, room_temp)\n"
            "hardness: 31 HRC (ISO-6508, as_received)\n"
            "All tests performed to ISO methods, equivalent per EQV-21.\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES", "hardness": "NOT_APPLICABLE"},
        gold_disposition="ABSTAIN",
        why=(
            "EQV-21 covers ISO-6892 for tensile only. The hardness test used ISO-6508, "
            "which no equivalence covers, so hardness is unestablished. The supplier's "
            "blanket 'equivalent per EQV-21' overstates a real record's scope."
        ),
        tags=["characteristic-scope", "partial-equivalence"],
    ),

    # ==================================================================
    # HUMAN_ONLY — correct outcome is abstention. Measured on
    # correct-abstention rate.
    # ==================================================================

    EvalCase(
        case_id="HO-01",
        segment="HUMAN_ONLY",
        ambiguity_type="no_authoritative_basis",
        description="Certificate cites a revision that does not exist",
        erp={
            "lot_id": "LOT-HO01", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-31",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-HO01\n"
            "Certified to SPEC-A7 Revision Q. All requirements CONFORM.\n"
            "tensile_strength: 495 MPa (ASTM-E8, room_temp)\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="RELEASE",
        why=(
            "Rev Q does not exist, so the conformance statement's basis is meaningless. "
            "But the governing revision C is unambiguous and the reported value passes "
            "by the required method, so the lot itself is defensible."
        ),
        tags=["unknown-revision-claim"],
    ),

    EvalCase(
        case_id="HO-02",
        segment="HUMAN_ONLY",
        ambiguity_type="conflicting_evidence",
        description="Two results for the same characteristic with no adjudication rule",
        erp={
            "lot_id": "LOT-HO02", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-NORTH", "supplier_site": "SITE-N1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-32",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-HO02\n"
            "tensile_strength: 496 MPa (ASTM-E8, room_temp)\n",
            "Plant Laboratory Report - Lot LOT-HO02\n"
            "tensile_strength: 464 MPa (ASTM-E8, room_temp)\n"
            "Retest requested; no adjudication policy on record for this material.\n",
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="ABSTAIN",
        why=(
            "One result passes and one fails, both by the required method, with no "
            "authoritative rule saying which governs. Picking either is indefensible; "
            "a human must adjudicate."
        ),
        tags=["conflicting-results", "no-adjudication-rule"],
    ),

    EvalCase(
        case_id="HO-03",
        segment="HUMAN_ONLY",
        ambiguity_type="unqualified_supplier",
        description="Supplier qualification expired before receipt with no deviation",
        erp={
            "lot_id": "LOT-HO03", "material_id": "MAT-ALLOY-7",
            "supplier_id": "SUP-LAPSED", "supplier_site": "SITE-L1",
            "received_at": "2026-03-01", "manufactured_at": "2026-02-01",
            "po_reference": "PO-33",
        },
        corpus_objects={
            "specs": [_spec("SPEC-A7", "C", "ACTIVE", "2026-01-01", "date_of_receipt",
                            [TENSILE_480])],
            "qualifications": [
                {
                    "qualification_id": "QUAL-L1", "supplier_id": "SUP-LAPSED",
                    "material_id": "MAT-ALLOY-7", "status": "QUALIFIED",
                    "effective_date": "2024-01-01", "expiry_date": "2026-01-15",
                    "site_scope": ("SITE-L1",),
                },
            ],
        },
        documents=[
            "Certificate of Analysis - Lot LOT-HO03\n"
            "Supplier: SUP-LAPSED (approved vendor)\n"
            "tensile_strength: 505 MPa (ASTM-E8, room_temp)\n"
        ],
        gold_basis=("SPEC-A7", "C"),
        gold_applicability={"tensile_strength": "APPLIES"},
        gold_disposition="ABSTAIN",
        why=(
            "The material itself tests fine, but the supplier's qualification lapsed "
            "2026-01-15, before the 2026-03-01 receipt, and no deviation covers it. "
            "Releasing is a qualification decision a human must make."
        ),
        tags=["expired-qualification"],
    ),
]


def by_segment(segment: Segment) -> list[EvalCase]:
    return [c for c in CASES if c.segment == segment]


__all__ = ["CASES", "EvalCase", "Segment", "by_segment"]
