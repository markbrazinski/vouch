"""Adversarial strip-test dataset (Part B).

Authored BEFORE running any model, and not modified after seeing results.

Design rules:
  - Ground truth is derived from manufacturing logic, not from model behaviour.
  - No case is winnable from keywords: the words "conforms", "approved",
    "qualified", "equivalent" appear in cases whose truth is RELEASE, QUARANTINE
    and ABSTAIN alike, so surface cues do not predict the answer.
  - Each case declares `rule_solvable`: whether a competent deterministic system
    could resolve it safely from STRUCTURED facts alone. That flag is the strip
    test, and it is set by the case author, not by observed results.

`evidence_text` is the unstructured document a human would read. `structured`
is what a conventional system could reasonably have in its database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Truth = Literal["RELEASE", "QUARANTINE", "ABSTAIN"]
Family = Literal[
    "governing_spec", "identity", "method_equivalence", "test_condition",
    "supplier_qualification", "hidden_gap", "conflicting_evidence", "paraphrase",
]


@dataclass
class Case:
    case_id: str
    family: Family
    ambiguity: str
    truth: Truth
    why: str
    structured: dict
    evidence_text: str
    rule_solvable: bool
    paraphrase_of: str | None = None
    tags: list[str] = field(default_factory=list)


CASES: list[Case] = [

    # ================= FAMILY 1: governing-spec ambiguity =================
    Case(
        "GS-01", "governing_spec",
        "PO cites SPEC-A7 rev B; material master says rev C is current",
        "QUARANTINE",
        "Change control note states rev C applies to all lots RECEIVED after 2026-01-01. "
        "This lot was received 2026-03-02, so rev C governs and 462 < 480 MPa fails.",
        {"po_spec_rev": "B", "master_spec_rev": "C", "received": "2026-03-02",
         "rev_c_effective": "2026-01-01", "tensile_mpa": 462.0,
         "rev_b_min": 450.0, "rev_c_min": 480.0},
        "Certificate of Analysis — Lot NX-4471\nPurchase Order PO-8812 references "
        "Specification A7 Revision B.\nTensile strength: 462 MPa.\nResult: CONFORMS to "
        "the referenced specification.\n\n[Plant change notice ECN-2291] Revision C of "
        "SPEC-A7 supersedes Revision B for all material RECEIVED on or after 1 Jan 2026. "
        "Revision C raises the minimum tensile requirement to 480 MPa.",
        rule_solvable=True,
        tags=["date-driven", "supersession"],
    ),
    Case(
        "GS-02", "governing_spec",
        "Newer revision exists but explicitly does not apply retroactively",
        "RELEASE",
        "Rev C applies to lots MANUFACTURED after its effective date. This lot was "
        "manufactured 2025-11-14, before it, so rev B genuinely still governs; 462 > 450.",
        {"po_spec_rev": "B", "master_spec_rev": "C", "manufactured": "2025-11-14",
         "rev_c_effective": "2026-01-01", "rev_c_basis": "date_of_manufacture",
         "tensile_mpa": 462.0, "rev_b_min": 450.0, "rev_c_min": 480.0},
        "Certificate of Analysis — Lot NX-5150\nDate of manufacture: 14 November 2025.\n"
        "Tensile strength: 462 MPa.\nSpecification A7 Rev B: minimum 450 MPa. CONFORMS.\n\n"
        "[Plant change notice ECN-2291] Revision C applies to material MANUFACTURED on or "
        "after 1 Jan 2026. Material manufactured before that date remains governed by "
        "Revision B.",
        rule_solvable=True,
        tags=["date-driven", "old-rev-still-governs"],
    ),
    Case(
        "GS-03", "governing_spec",
        "Effective-date basis is ambiguous between receipt and manufacture",
        "ABSTAIN",
        "The change notice does not state whether the effective date keys on manufacture "
        "or receipt, and the lot straddles the boundary. Applicability cannot be "
        "established, so no autonomous disposition is defensible.",
        {"manufactured": "2025-12-20", "received": "2026-01-08",
         "rev_c_effective": "2026-01-01", "rev_c_basis": None,
         "tensile_mpa": 462.0, "rev_b_min": 450.0, "rev_c_min": 480.0},
        "Certificate of Analysis — Lot NX-5233\nManufactured 20 Dec 2025. Received "
        "8 Jan 2026.\nTensile strength: 462 MPa.\n\n[Plant change notice ECN-2291 rev 2] "
        "Revision C of SPEC-A7 becomes effective 1 January 2026. Material is to be "
        "assessed against the applicable revision.",
        rule_solvable=False,
        tags=["ambiguous-applicability", "straddles-boundary"],
    ),
    Case(
        "GS-04", "governing_spec",
        "Certificate cites a spec revision that does not exist",
        "ABSTAIN",
        "The CoA claims conformance to 'Rev D', which is not a released revision. The "
        "basis of the conformance statement cannot be established.",
        {"cert_spec_rev": "D", "known_revs": ["A", "B", "C"], "master_spec_rev": "C",
         "tensile_mpa": 495.0, "rev_c_min": 480.0},
        "Certificate of Analysis — Lot NX-6001\nTensile strength: 495 MPa.\n"
        "Certified to SPEC-A7 Revision D. All requirements CONFORM.",
        rule_solvable=True,
        tags=["unknown-revision"],
    ),

    # ================= FAMILY 2: material identity ========================
    Case(
        "ID-01", "identity",
        "Supplier alias maps to the internal material ID",
        "RELEASE",
        "'NorthAlloy 7-HT' is a registered supplier alias for MAT-ALLOY-7. Identity "
        "resolves, and 512 MPa passes rev C.",
        {"supplier_name": "NorthAlloy 7-HT", "alias_map": {"NorthAlloy 7-HT": "MAT-ALLOY-7"},
         "po_material": "MAT-ALLOY-7", "tensile_mpa": 512.0, "rev_c_min": 480.0},
        "Certificate of Analysis\nProduct: NorthAlloy 7-HT\nSupplied against PO-9001 "
        "(MAT-ALLOY-7).\nTensile strength: 512 MPa. CONFORMS.",
        rule_solvable=True,
        tags=["alias"],
    ),
    Case(
        "ID-02", "identity",
        "Similar name is a genuinely different grade",
        "QUARANTINE",
        "'Alloy 7A' is a distinct grade from 'Alloy 7' with a different composition; it "
        "is not an alias. Material supplied does not match the PO material.",
        {"supplier_name": "Alloy 7A", "alias_map": {"NorthAlloy 7-HT": "MAT-ALLOY-7"},
         "po_material": "MAT-ALLOY-7", "distinct_grades": ["Alloy 7", "Alloy 7A"],
         "tensile_mpa": 505.0},
        "Certificate of Analysis\nProduct: Alloy 7A billet\nSupplied against PO-9002 "
        "(Alloy 7).\nTensile strength: 505 MPa. CONFORMS to Alloy 7A datasheet.\n"
        "Note: Alloy 7A is a niobium-stabilised variant of Alloy 7.",
        rule_solvable=True,
        tags=["near-miss-name"],
    ),
    Case(
        "ID-03", "identity",
        "Grade renamed by supplier mid-contract, no alias record yet",
        "ABSTAIN",
        "The supplier states a rename, but no controlled alias record exists. Accepting a "
        "supplier's unilateral identity claim would be inventing qualification.",
        {"supplier_name": "NorthAlloy 7X", "alias_map": {"NorthAlloy 7-HT": "MAT-ALLOY-7"},
         "po_material": "MAT-ALLOY-7", "supplier_claims_rename": True, "tensile_mpa": 498.0},
        "Certificate of Analysis\nProduct: NorthAlloy 7X\nTensile strength: 498 MPa.\n"
        "Supplier note: 'NorthAlloy 7X is the new designation for NorthAlloy 7-HT "
        "following our 2026 product naming update. Composition unchanged.'",
        rule_solvable=False,
        tags=["unverified-rename"],
    ),
    Case(
        "ID-04", "identity",
        "PO, CoA and receiving record disagree on material",
        "ABSTAIN",
        "Three controlled sources disagree and nothing adjudicates between them. "
        "Identity cannot be established.",
        {"po_material": "MAT-ALLOY-7", "coa_material": "MAT-ALLOY-9",
         "receiving_material": "MAT-ALLOY-7", "tensile_mpa": 486.0},
        "Purchase Order PO-9004: MAT-ALLOY-7.\nCertificate of Analysis: MAT-ALLOY-9, "
        "tensile 486 MPa, CONFORMS.\nReceiving record GRN-3391: MAT-ALLOY-7, 400 kg.",
        rule_solvable=True,
        tags=["three-way-conflict"],
    ),

    # ================= FAMILY 3: method equivalence =======================
    Case(
        "ME-01", "method_equivalence",
        "Supplier used a different method; approved equivalence covers it",
        "RELEASE",
        "Equivalence record EQ-114 approves ASTM-E8M as equivalent to ASTM-E8 for tensile "
        "on this material without condition limits. 511 MPa passes.",
        {"required_method": "ASTM-E8", "used_method": "ASTM-E8M",
         "equivalence": {"from": "ASTM-E8M", "to": "ASTM-E8", "material": "MAT-ALLOY-7",
                         "conditions": None, "status": "APPROVED"},
         "tensile_mpa": 511.0, "rev_c_min": 480.0},
        "Certificate of Analysis\nTensile strength: 511 MPa, determined per ASTM E8M.\n"
        "[Quality record EQ-114] ASTM E8M is approved as equivalent to ASTM E8 for "
        "tensile determination on Alloy 7 products. No condition restrictions.",
        rule_solvable=True,
        tags=["approved-equivalence"],
    ),
    Case(
        "ME-02", "method_equivalence",
        "Equivalence exists but only for a condition this test did not meet",
        "ABSTAIN",
        "EQ-115 approves the equivalence ONLY for room-temperature testing. This test ran "
        "at 150 C, outside the equivalence scope, so the requirement is not established.",
        {"required_method": "ASTM-E8", "used_method": "ASTM-E8M", "test_temp": "150C",
         "equivalence": {"from": "ASTM-E8M", "to": "ASTM-E8", "material": "MAT-ALLOY-7",
                         "conditions": "room_temperature_only", "status": "APPROVED"},
         "tensile_mpa": 494.0, "rev_c_min": 480.0},
        "Certificate of Analysis\nTensile strength: 494 MPa per ASTM E8M, elevated "
        "temperature 150 C.\n[Quality record EQ-115] ASTM E8M is approved as equivalent to "
        "ASTM E8 for tensile determination on Alloy 7, FOR ROOM TEMPERATURE TESTING ONLY. "
        "Elevated-temperature equivalence is not established by this record.",
        rule_solvable=False,
        tags=["scoped-equivalence", "out-of-scope"],
    ),
    Case(
        "ME-03", "method_equivalence",
        "Different method, no equivalence record at all",
        "ABSTAIN",
        "No controlled equivalence exists between the used and required methods. Absence "
        "of proof is not a defect, so abstain rather than quarantine.",
        {"required_method": "ASTM-D2196", "used_method": "ASTM-D445",
         "equivalence": None, "viscosity_cp": 268.0},
        "Certificate of Analysis\nViscosity: 268 cP by ASTM D445 at 40 C.\nResult: "
        "CONFORMS to supplier internal limits.",
        rule_solvable=True,
        tags=["no-equivalence"],
    ),
    Case(
        "ME-04", "method_equivalence",
        "Equivalence record exists but is withdrawn",
        "ABSTAIN",
        "EQ-090 is marked WITHDRAWN. A withdrawn equivalence cannot establish the "
        "requirement, though the material is not shown to be defective.",
        {"required_method": "ASTM-E8", "used_method": "ISO-6892",
         "equivalence": {"from": "ISO-6892", "to": "ASTM-E8", "status": "WITHDRAWN"},
         "tensile_mpa": 502.0, "rev_c_min": 480.0},
        "Certificate of Analysis\nTensile strength: 502 MPa per ISO 6892-1.\n"
        "[Quality record EQ-090 — STATUS: WITHDRAWN 2025-08-01] ISO 6892-1 was previously "
        "approved as equivalent to ASTM E8 for Alloy 7.",
        rule_solvable=True,
        tags=["withdrawn-equivalence"],
    ),

    # ================= FAMILY 4: test-condition mismatch ==================
    Case(
        "TC-01", "test_condition",
        "Different temperature, explicit correlation evidence establishes it",
        "RELEASE",
        "Approved correlation CR-22 establishes that the 40 C result maps to the 25 C "
        "requirement for this resin family; corrected value 305 cP is within 200-400.",
        {"required_condition": "25C", "used_condition": "40C",
         "correlation": {"record": "CR-22", "status": "APPROVED",
                         "material_family": "resin-3", "corrected_value_cp": 305.0},
         "limits_cp": [200.0, 400.0]},
        "Certificate of Analysis\nViscosity: 268 cP by ASTM D2196 at 40 C.\n"
        "[Quality record CR-22, APPROVED] For Resin-3 family, viscosity at 40 C "
        "correlates to 25 C by the validated factor in Table 2; the 25 C equivalent of "
        "268 cP at 40 C is 305 cP.",
        rule_solvable=False,
        tags=["approved-correlation"],
    ),
    Case(
        "TC-02", "test_condition",
        "Different sample preparation, no basis for comparison",
        "ABSTAIN",
        "Spec requires as-received hardness; the test was on a polished-and-etched "
        "specimen. No record establishes comparability of the two preparations.",
        {"required_condition": "as_received", "used_condition": "polished_etched",
         "correlation": None, "hardness_hrc": 31.0, "limits_hrc": [28.0, 36.0]},
        "Certificate of Analysis\nHardness: 31 HRC, specimen polished and etched prior "
        "to indentation.\nSpecification requires hardness in the as-received condition.",
        rule_solvable=False,
        tags=["prep-mismatch"],
    ),
    Case(
        "TC-03", "test_condition",
        "Condition difference that the spec explicitly permits",
        "RELEASE",
        "The governing spec itself allows testing at 23 C +/- 2 C. A 24 C test is inside "
        "the permitted window, so the condition matches.",
        {"required_condition": "23C+/-2", "used_condition": "24C",
         "viscosity_cp": 310.0, "limits_cp": [200.0, 400.0]},
        "Certificate of Analysis\nViscosity: 310 cP by ASTM D2196 at 24 C.\n"
        "SPEC-R3 rev A, clause 4.2: 'Viscosity shall be determined at 23 C +/- 2 C.'",
        rule_solvable=True,
        tags=["within-tolerance"],
    ),
    Case(
        "TC-04", "test_condition",
        "Condition difference outside an explicitly permitted window",
        "ABSTAIN",
        "The spec permits 23 C +/- 2 C; the test ran at 30 C, outside it, with no "
        "correlation record. The requirement is not established.",
        {"required_condition": "23C+/-2", "used_condition": "30C", "correlation": None,
         "viscosity_cp": 268.0, "limits_cp": [200.0, 400.0]},
        "Certificate of Analysis\nViscosity: 268 cP by ASTM D2196 at 30 C.\n"
        "SPEC-R3 rev A, clause 4.2: 'Viscosity shall be determined at 23 C +/- 2 C.'",
        rule_solvable=True,
        tags=["outside-tolerance"],
    ),

    # ================= FAMILY 5: supplier qualification ===================
    Case(
        "SQ-01", "supplier_qualification",
        "Qualified for material A, lot is closely-named material B",
        "QUARANTINE",
        "SUP-NORTH is qualified for MAT-ALLOY-7 only. The lot is MAT-ALLOY-9. Supplying "
        "an unqualified material against this PO is a disposition failure.",
        {"supplier": "SUP-NORTH", "qualified_for": ["MAT-ALLOY-7"],
         "lot_material": "MAT-ALLOY-9", "tensile_mpa": 500.0},
        "Certificate of Analysis\nSupplier: SUP-NORTH (approved vendor).\nProduct: "
        "MAT-ALLOY-9.\nTensile strength: 500 MPa. CONFORMS.\n[Vendor master] SUP-NORTH "
        "qualification covers MAT-ALLOY-7.",
        rule_solvable=True,
        tags=["wrong-material-qualification"],
    ),
    Case(
        "SQ-02", "supplier_qualification",
        "Qualification covers one manufacturing site; lot came from another",
        "QUARANTINE",
        "Qualification is site-specific to Hamburg. This lot was manufactured at the "
        "Rotterdam plant, which is not qualified for this material.",
        {"supplier": "SUP-EAST", "qualified_sites": ["Hamburg"],
         "lot_site": "Rotterdam", "tensile_mpa": 507.0},
        "Certificate of Analysis\nSupplier: SUP-EAST.\nPlace of manufacture: Rotterdam "
        "works.\nTensile strength: 507 MPa. CONFORMS.\n[Vendor master] SUP-EAST is a "
        "QUALIFIED supplier for Alloy 7; qualification scope: Hamburg works.",
        rule_solvable=True,
        tags=["site-scope"],
    ),
    Case(
        "SQ-03", "supplier_qualification",
        "Qualification expired before receipt",
        "QUARANTINE",
        "Qualification lapsed 2026-02-01; the lot was received 2026-03-02 with no "
        "renewal or deviation on record.",
        {"supplier": "SUP-WEST", "qual_expiry": "2026-02-01", "received": "2026-03-02",
         "deviation": None, "viscosity_cp": 305.0},
        "Certificate of Analysis\nSupplier: SUP-WEST.\nReceived 2 March 2026.\n"
        "Viscosity 305 cP. CONFORMS.\n[Vendor master] SUP-WEST qualification for Resin-3 "
        "valid until 1 February 2026.",
        rule_solvable=True,
        tags=["expired"],
    ),
    Case(
        "SQ-04", "supplier_qualification",
        "Qualification expired but a temporary deviation covers this order",
        "RELEASE",
        "Deviation DEV-77 explicitly authorises receipt against PO-9100 pending renewal, "
        "and this lot is on that PO. Material meets spec.",
        {"supplier": "SUP-WEST", "qual_expiry": "2026-02-01", "received": "2026-03-02",
         "deviation": {"id": "DEV-77", "scope_po": "PO-9100", "status": "APPROVED"},
         "lot_po": "PO-9100", "viscosity_cp": 305.0, "limits_cp": [200.0, 400.0]},
        "Certificate of Analysis\nSupplier: SUP-WEST. PO-9100. Received 2 March 2026.\n"
        "Viscosity 305 cP by ASTM D2196 at 25 C.\n[Vendor master] Qualification expired "
        "1 Feb 2026.\n[Deviation DEV-77, APPROVED] Receipt from SUP-WEST against PO-9100 "
        "is authorised pending requalification.",
        rule_solvable=True,
        tags=["deviation-covers"],
    ),
    Case(
        "SQ-05", "supplier_qualification",
        "Deviation exists but for a different PO",
        "QUARANTINE",
        "DEV-77 covers PO-9100 only; this lot is on PO-9200. The deviation does not "
        "extend, so an expired qualification governs.",
        {"supplier": "SUP-WEST", "qual_expiry": "2026-02-01", "received": "2026-03-02",
         "deviation": {"id": "DEV-77", "scope_po": "PO-9100", "status": "APPROVED"},
         "lot_po": "PO-9200", "viscosity_cp": 305.0},
        "Certificate of Analysis\nSupplier: SUP-WEST. PO-9200. Received 2 March 2026.\n"
        "Viscosity 305 cP. CONFORMS.\n[Deviation DEV-77, APPROVED] Receipt from SUP-WEST "
        "against PO-9100 is authorised pending requalification.",
        rule_solvable=True,
        tags=["deviation-wrong-scope"],
    ),

    # ================= FAMILY 6: hidden gap behind "CONFORMS" =============
    Case(
        "HG-01", "hidden_gap",
        "CoA says CONFORMS but omits a required characteristic entirely",
        "ABSTAIN",
        "Rev C requires tensile AND hardness. The certificate reports only tensile. The "
        "blanket CONFORMS does not establish the missing characteristic.",
        {"required": ["tensile_strength", "hardness"], "reported": ["tensile_strength"],
         "tensile_mpa": 500.0, "rev_c_min": 480.0},
        "Certificate of Analysis — Lot NX-7001\nTensile strength: 500 MPa.\n"
        "Overall result: CONFORMS to SPEC-A7 Rev C in all respects.",
        rule_solvable=True,
        tags=["missing-characteristic", "false-completeness"],
    ),
    Case(
        "HG-02", "hidden_gap",
        "Requirement lives in a referenced document, not the base spec",
        "ABSTAIN",
        "Rev C clause 6 incorporates SPEC-A7-SUP1, which adds a grain-size requirement "
        "not reported anywhere. Apparent completeness hides an unmet requirement.",
        {"base_spec_reqs": ["tensile_strength", "hardness"],
         "referenced_doc": {"id": "SPEC-A7-SUP1", "adds": ["grain_size"]},
         "reported": ["tensile_strength", "hardness"]},
        "Certificate of Analysis — Lot NX-7002\nTensile 498 MPa. Hardness 31 HRC.\n"
        "CONFORMS to SPEC-A7 Rev C.\n[SPEC-A7 Rev C, clause 6] 'Material shall "
        "additionally satisfy the requirements of SPEC-A7-SUP1.'\n[SPEC-A7-SUP1] "
        "Grain size shall be ASTM 5 or finer.",
        rule_solvable=False,
        tags=["incorporated-by-reference"],
    ),
    Case(
        "HG-03", "hidden_gap",
        "Certificate conforms, but to the wrong spec revision",
        "ABSTAIN",
        "The certificate certifies against rev A while rev C governs. Rev A's limits are "
        "not shown, so conformance to the governing revision is unestablished.",
        {"cert_rev": "A", "governing_rev": "C", "tensile_mpa": 470.0,
         "rev_c_min": 480.0, "rev_a_min": None},
        "Certificate of Analysis — Lot NX-7003\nTensile 470 MPa.\nCONFORMS to SPEC-A7 "
        "Revision A.\n[Material master] Governing revision: C.",
        rule_solvable=True,
        tags=["wrong-revision-certified"],
    ),

    # ================= FAMILY 7: conflicting evidence =====================
    Case(
        "CE-01", "conflicting_evidence",
        "CoA and independent lab report disagree on the same characteristic",
        "ABSTAIN",
        "Supplier CoA reports 495 MPa; the plant's own incoming lab reports 471 MPa. One "
        "passes rev C and one does not, with no adjudication rule on record.",
        {"coa_tensile": 495.0, "plant_lab_tensile": 471.0, "rev_c_min": 480.0,
         "adjudication_rule": None},
        "Certificate of Analysis (supplier): tensile 495 MPa. CONFORMS.\n"
        "Incoming inspection report IIR-556 (plant lab): tensile 471 MPa.\n"
        "No re-test or adjudication has been performed.",
        rule_solvable=False,
        tags=["source-conflict", "straddles-limit"],
    ),
    Case(
        "CE-02", "conflicting_evidence",
        "Conflict exists but a policy resolves it",
        "QUARANTINE",
        "Quality policy QP-3 states the plant lab result governs when it conflicts with a "
        "supplier certificate. The governing 471 MPa fails rev C.",
        {"coa_tensile": 495.0, "plant_lab_tensile": 471.0, "rev_c_min": 480.0,
         "adjudication_rule": {"id": "QP-3", "governs": "plant_lab"}},
        "Certificate of Analysis (supplier): tensile 495 MPa.\nIncoming inspection "
        "IIR-557 (plant lab): tensile 471 MPa.\n[Quality policy QP-3] 'Where plant "
        "laboratory results conflict with supplier certification, the plant laboratory "
        "result shall govern.'",
        rule_solvable=True,
        tags=["policy-resolves-conflict"],
    ),
    Case(
        "CE-03", "conflicting_evidence",
        "CoA site and qualification site disagree",
        "ABSTAIN",
        "The CoA header names Hamburg while the mill certificate attached names "
        "Rotterdam. Which site actually made the material cannot be established.",
        {"coa_site": "Hamburg", "mill_cert_site": "Rotterdam",
         "qualified_sites": ["Hamburg"], "tensile_mpa": 503.0},
        "Certificate of Analysis\nManufacturing location: Hamburg works.\n"
        "Tensile 503 MPa. CONFORMS.\n[Attached mill certificate MC-8812] Melt and roll "
        "performed at Rotterdam works.",
        rule_solvable=False,
        tags=["internal-contradiction"],
    ),

    # ================= FAMILY 8: harmless variation (robustness) ==========
    Case(
        "PV-01", "paraphrase",
        "GS-01 restated in a different layout and register",
        "QUARANTINE",
        "Same facts as GS-01: rev C governs by receipt date and 462 < 480 MPa.",
        {"po_spec_rev": "B", "master_spec_rev": "C", "received": "2026-03-02",
         "rev_c_effective": "2026-01-01", "tensile_mpa": 462.0,
         "rev_b_min": 450.0, "rev_c_min": 480.0},
        "MATERIAL TEST REPORT\n=====================\nLOT ................ NX-4471\n"
        "ORDER .............. PO-8812 (spec A7 rev B)\nUTS ................ 462 N/mm2\n"
        "DISPOSITION ........ ACCEPTABLE per order specification\n\n"
        "Engineering change ECN-2291 is in force: material booked into stores from "
        "01/01/2026 onward must meet SPEC-A7/C, which requires UTS >= 480 N/mm2.",
        rule_solvable=True, paraphrase_of="GS-01",
        tags=["layout-variation", "unit-variation"],
    ),
    Case(
        "PV-02", "paraphrase",
        "ME-03 restated with different wording",
        "ABSTAIN",
        "Same facts as ME-03: method differs and no equivalence record exists.",
        {"required_method": "ASTM-D2196", "used_method": "ASTM-D445",
         "equivalence": None, "viscosity_cp": 268.0},
        "QC RELEASE SHEET\nProperty measured: kinematic viscosity\nProcedure followed: "
        "ASTM D-445 (capillary), bath at 40 degrees C\nReading: 268 centipoise\n"
        "Supplier verdict: within house limits, released for shipment",
        rule_solvable=True, paraphrase_of="ME-03",
        tags=["layout-variation"],
    ),
    Case(
        "PV-03", "paraphrase",
        "SQ-04 restated as a terse internal memo",
        "RELEASE",
        "Same facts as SQ-04: expired qualification, but an approved deviation covers "
        "this exact PO, and the material meets spec.",
        {"supplier": "SUP-WEST", "qual_expiry": "2026-02-01", "received": "2026-03-02",
         "deviation": {"id": "DEV-77", "scope_po": "PO-9100", "status": "APPROVED"},
         "lot_po": "PO-9100", "viscosity_cp": 305.0, "limits_cp": [200.0, 400.0]},
        "memo: incoming resin-3, west supplier, po 9100, arrived 3/2.\nvisc 305 cP "
        "(D2196 @ 25C) - inside 200-400 band.\nvendor cert lapsed 2/1 BUT dev-77 signed "
        "off for po 9100 while requal is pending.",
        rule_solvable=True, paraphrase_of="SQ-04",
        tags=["informal-register"],
    ),
]


def by_id(case_id: str) -> Case:
    return next(c for c in CASES if c.case_id == case_id)


def summary() -> dict:
    from collections import Counter

    return {
        "total": len(CASES),
        "by_truth": dict(Counter(c.truth for c in CASES)),
        "by_family": dict(Counter(c.family for c in CASES)),
        "rule_solvable": sum(c.rule_solvable for c in CASES),
        "agent_valuable": sum(not c.rule_solvable for c in CASES),
    }
