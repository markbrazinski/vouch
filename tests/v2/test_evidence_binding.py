"""P0-4 — wrong-lot / wrong-material / wrong-supplier / wrong-site evidence.

The independent audit proved this attack worked at b8f54b0:

    document says:  LOT-9999
    API target:     LOT-1001
    result:         LOT-1001 RELEASED

because workflow metadata overwrote the document's own identity. Every test
here enters through REAL ingestion with a real document payload — never through
hand-constructed canonical claims — because the defect lived in the ingestion
path and a test that skips it proves nothing.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import ArtifactStatus, TrustLabel
from vouch.v2.evidence import (
    DocumentIdentity,
    extract_document_identity,
    validate_binding,
)
from vouch.v2.fixtures import build_corpus
from vouch.v2.lifecycle import EventLog, EventType
from vouch.v2.workflow import VouchV2

# LOT-1001 in the fixture corpus: MAT-ALLOY-7, SUP-NORTH, SITE-N1.
CORRECT = b"""Certificate of Analysis - Lot LOT-1001
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

WRONG_LOT = b"""Certificate of Analysis - Lot LOT-9999
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

WRONG_MATERIAL = b"""Certificate of Analysis - Lot LOT-1001
Material: MAT-RESIN-3
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

WRONG_SUPPLIER = b"""Certificate of Analysis - Lot LOT-1001
Supplier: SUP-WEST
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

WRONG_SITE = b"""Certificate of Analysis - Lot LOT-1001
Site: SITE-W1
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

NO_IDENTITY = b"""Certificate of Analysis
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""


@pytest.fixture
def vouch():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


# ==========================================================================
# the control: correct identity still works
# ==========================================================================


def test_correct_lot_is_accepted_and_releases(vouch):
    """The repair must not break the legitimate path."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": CORRECT}])

    assert outcome.disposition == "RELEASE"
    assert corpus.lot("LOT-1001").status == "RELEASED"
    assert not outcome.record.security.binding_mismatches


# ==========================================================================
# the audit's attack, and its siblings
# ==========================================================================


@pytest.mark.parametrize(
    "payload,expected_fragment",
    [
        (WRONG_LOT, "lot LOT-9999"),
        (WRONG_MATERIAL, "material MAT-RESIN-3"),
        (WRONG_SUPPLIER, "supplier SUP-WEST"),
        (WRONG_SITE, "supplier_site SITE-W1"),
    ],
    ids=["wrong-lot", "wrong-material", "wrong-supplier", "wrong-site"],
)
def test_mismatched_evidence_cannot_be_rebound(vouch, payload, expected_fragment):
    """The document's identity is never normalized onto the requested target."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": payload}])

    # No autonomous disposition, no mutation.
    assert outcome.failure_category == "EVIDENCE_BINDING_MISMATCH"
    assert outcome.disposition == ""
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"

    # The contradiction is recorded, naming both identities.
    mismatches = outcome.record.security.binding_mismatches
    assert mismatches
    assert any(expected_fragment in m for m in mismatches)
    assert any("LOT-1001" in m or "MAT-ALLOY-7" in m or "SUP-NORTH" in m
               or "SITE-N1" in m for m in mismatches)


def test_wrong_lot_evidence_is_preserved_not_dropped(vouch):
    """The artifact stays as evidence of the attempt."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": WRONG_LOT}])

    assert outcome.record.security.rejected_artifact_ids
    assert outcome.record.evidence.source_artifact_hashes  # original still bound
    assert outcome.record.evidence.storage_refs


def test_wrong_lot_emits_a_security_lifecycle_event(vouch):
    corpus, v = vouch
    events = EventLog()
    v.evaluate_lot("LOT-1001", documents=[{"raw": WRONG_LOT}], events=events)

    emitted = events.of_type(EventType.EVIDENCE_BINDING_MISMATCH)
    assert emitted
    payload = emitted[0].payload
    assert payload["requested_lot"] == "LOT-1001"
    assert payload["claimed_identity"]["claimed_lot"] == "LOT-9999"
    assert payload["mismatches"]


def test_mismatched_claims_never_enter_the_snapshot(vouch):
    """Nothing from a mismatched artifact becomes evidence."""
    corpus, v = vouch
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=WRONG_LOT, events=EventLog(),
    )
    assert claims == []
    assert summary["status"] is ArtifactStatus.EVIDENCE_BINDING_MISMATCH
    assert summary["claimed_identity"]["claimed_lot"] == "LOT-9999"


def test_a_lot_cannot_be_released_by_another_lots_coa(vouch):
    """End to end: the exact scenario the audit reported.

    LOT-1002 is the hero lot that must NOT release. Feeding LOT-1001's clean
    passing COA while targeting LOT-1002 must not release LOT-1002.
    """
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1002", documents=[{"raw": CORRECT}])

    assert outcome.disposition != "RELEASE"
    assert corpus.lot("LOT-1002").status != "RELEASED"
    assert outcome.failure_category == "EVIDENCE_BINDING_MISMATCH"


# ==========================================================================
# missing identity: abstain, do not reject and do not assume
# ==========================================================================


def test_missing_identity_routes_to_review_not_rejection(vouch):
    """A document that states no identity is not a contradiction.

    It cannot be affirmatively bound either, so it must not silently be treated
    as proof for the requested lot. It is accepted as claims but the absence is
    recorded, and the decision proceeds on evidence whose binding rests on the
    receiving record rather than on the document.
    """
    corpus, v = vouch
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=NO_IDENTITY, events=EventLog(),
    )
    assert summary["identity_stated"] is False
    assert summary["binding_mismatches"] == []
    assert summary["status"] is ArtifactStatus.RECEIVED


# ==========================================================================
# human-supplied evidence is checked too
# ==========================================================================


def test_human_evidence_for_the_wrong_lot_is_also_rejected(vouch):
    """HUMAN_AUTHORIZED trust does not exempt an artifact from binding.

    A QA retest for the wrong lot is still the wrong lot.
    """
    corpus, v = vouch
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1003",
        raw=b"Plant QA Laboratory Retest - Lot LOT-9999\nviscosity: 305 cP (ASTM-D2196, 25C)\n",
        events=EventLog(), trust_label=TrustLabel.HUMAN_AUTHORIZED,
    )
    assert claims == []
    assert summary["status"] is ArtifactStatus.EVIDENCE_BINDING_MISMATCH


# ==========================================================================
# the identity parser itself
# ==========================================================================


def test_identity_extraction_takes_no_workflow_context():
    """The parser cannot echo a requested target: it never receives one."""
    identity = extract_document_identity(
        "Certificate of Analysis - Lot LOT-9999\nSupplier: SUP-EVIL\nSite: SITE-X9\n"
        "Material: MAT-OTHER\n"
    )
    assert identity == DocumentIdentity(
        lot_id="LOT-9999", material_id="MAT-OTHER",
        supplier_id="SUP-EVIL", supplier_site="SITE-X9",
    )


def test_validate_binding_ignores_unstated_fields():
    identity = DocumentIdentity(lot_id="LOT-1001")
    assert validate_binding(
        identity, target_lot_id="LOT-1001", target_material_id="MAT-ALLOY-7",
        target_supplier_id="SUP-NORTH", target_supplier_site="SITE-N1",
    ) == []


def test_validate_binding_is_case_insensitive():
    identity = DocumentIdentity(lot_id="lot-1001")
    assert validate_binding(
        identity, target_lot_id="LOT-1001", target_material_id="",
        target_supplier_id="", target_supplier_site="",
    ) == []
