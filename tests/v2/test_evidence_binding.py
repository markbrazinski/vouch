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

from vouch.v2.contracts import ArtifactStatus, FailureCategory, TrustLabel
from vouch.v2.evidence import (
    BindingStatus,
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
    """A document that states no identity is not a contradiction — and not proof.

    audit-2 F3: this test previously asserted only that ingestion recorded
    `identity_stated=False` and reported no mismatch, then called that "routes
    to review". It did not, and the audit proved it: the artifact was
    ArtifactStatus.RECEIVED, its claims entered the snapshot, and the lot was
    RELEASED. The name promised an end-to-end outcome the assertions never
    checked.

    It now asserts the actual end-to-end outcome. "Routes to review" means the
    decision reaches a human without mutating anything — not merely that a flag
    was written.
    """
    corpus, v = vouch
    events = EventLog()
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=NO_IDENTITY, events=events,
    )
    # Not a contradiction...
    assert summary["identity_stated"] is False
    assert summary["binding_mismatches"] == []
    # ...but not a binding either, and therefore no usable claims.
    assert summary["status"] is ArtifactStatus.EVIDENCE_UNBOUND
    assert summary["binding_status"] == "UNBOUND_NO_IDENTITY"
    assert claims == []

    # And the end-to-end outcome the old name only implied.
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": NO_IDENTITY}])
    assert outcome.failure_category == FailureCategory.EVIDENCE_UNBOUND.value
    assert outcome.quality_decision_required
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"


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
    assert identity.lot_id == "LOT-9999"
    assert identity.material_id == "MAT-OTHER"
    assert identity.supplier_id == "SUP-EVIL"
    assert identity.supplier_site == "SITE-X9"
    assert identity.conflicts == []


def test_validate_binding_ignores_unstated_fields():
    """A lot number alone binds: it implies the rest through the receipt."""
    identity = DocumentIdentity(lot_ids=("LOT-1001",))
    status, reasons = validate_binding(
        identity, target_lot_id="LOT-1001", target_material_id="MAT-ALLOY-7",
        target_supplier_id="SUP-NORTH", target_supplier_site="SITE-N1",
    )
    assert status is BindingStatus.BOUND
    assert reasons == []


def test_validate_binding_is_case_insensitive():
    identity = DocumentIdentity(lot_ids=("lot-1001",))
    status, reasons = validate_binding(
        identity, target_lot_id="LOT-1001", target_material_id="",
        target_supplier_id="", target_supplier_site="",
    )
    assert status is BindingStatus.BOUND
    assert reasons == []


# ==========================================================================
# audit-2 F3 — missing document identity must NOT release a lot
# ==========================================================================

#: The exact exploit document from the Iteration 2 audit. It states no lot, no
#: material, no supplier and no site — and at the audited SHA it released
#: LOT-1001.
NO_IDENTITY_EXPLOIT = b"""Certificate of Analysis
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""


def test_missing_identity_cannot_release_a_lot(vouch):
    """F3, the exact audit exploit, end to end through evaluate_lot.

    Evidence that cannot be affirmatively bound to the receiving identity
    cannot produce claims usable for an autonomous disposition. The artifact is
    preserved and routed to a human, and the lot is NOT marked defective —
    absence of identity says nothing about the material's quality.
    """
    corpus, v = vouch
    before = corpus.lot("LOT-1001")

    outcome = v.evaluate_lot(
        "LOT-1001", documents=[{"raw": NO_IDENTITY_EXPLOIT}]
    )

    # no RELEASE
    assert outcome.disposition != "RELEASE"
    assert corpus.lot("LOT-1001").status != "RELEASED"
    # no QUARANTINE-as-defective
    assert outcome.disposition != "QUARANTINE"
    assert corpus.lot("LOT-1001").status != "QUARANTINED"
    # zero autonomous mutation
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").state_version == before.state_version
    assert corpus.get("inventory", "LOT-1001").usable is False
    assert v.capabilities.ledger == []
    # explicit binding/unbound failure category
    assert outcome.failure_category == FailureCategory.EVIDENCE_UNBOUND.value
    assert outcome.record.evidence.binding_statuses == ["UNBOUND_NO_IDENTITY"]
    # human review
    assert outcome.quality_decision_required
    assert outcome.record.human.review_status == "OPEN"
    # original artifact preserved
    assert outcome.record.security.unbound_artifact_ids
    assert outcome.record.evidence.storage_refs
    key = outcome.record.evidence.storage_refs[0].removeprefix("local://evidence/")
    assert v.evidence_store.get_original(key) == NO_IDENTITY_EXPLOIT


def test_unbound_is_not_a_mismatch_and_not_a_defect(vouch):
    """F3: three outcomes, three categories. They are not interchangeable."""
    corpus, v = vouch
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001",
        raw=NO_IDENTITY_EXPLOIT, events=EventLog(),
    )
    assert claims == []
    assert summary["status"] is ArtifactStatus.EVIDENCE_UNBOUND
    assert summary["binding_status"] == "UNBOUND_NO_IDENTITY"
    assert summary["binding_mismatches"] == [], "absence is not contradiction"
    assert summary["identity_stated"] is False


def test_material_and_supplier_together_bind_without_a_lot_number(vouch):
    """F3 is about UNBINDABLE evidence, not about demanding a lot number.

    A shipment-level document that names material and supplier can still be
    affirmatively tied to the receiving record.
    """
    corpus, v = vouch
    document = (
        b"Certificate of Analysis\nMaterial: MAT-ALLOY-7\nSupplier: SUP-NORTH\n"
        b"Specification SPEC-A7 Revision C\n"
        b"tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
        b"hardness: 31 HRC (HRC, as_received)\n"
    )
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=document, events=EventLog(),
    )
    assert summary["binding_status"] == "BOUND"
    assert claims


# ==========================================================================
# audit-2 F4 — conflicting identities inside ONE artifact
# ==========================================================================

#: The exact exploit document from the Iteration 2 audit. First-match-wins
#: parsing read this as LOT-1001 and released it.
CONFLICTING_LOT = b"""Certificate of Analysis - Lot LOT-1001
Corrected document identity: Lot LOT-9999
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

MATCHING_REPEATED = b"""Certificate of Analysis - Lot LOT-1001
Reference: Lot LOT-1001
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
"""

CONFLICTING_MATERIAL = b"""Certificate of Analysis - Lot LOT-1001
Material: MAT-ALLOY-7
Amended material: MAT-RESIN-3
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
"""

CONFLICTING_SUPPLIER = b"""Certificate of Analysis - Lot LOT-1001
Supplier: SUP-NORTH
Corrected supplier: SUP-WEST
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
"""

CONFLICTING_SITE = b"""Certificate of Analysis - Lot LOT-1001
Site: SITE-N1
Corrected site: SITE-W1
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
"""

#: A structured header field disagreeing with the free-text body.
HEADER_VERSUS_BODY = b"""lot_id: LOT-9999
Certificate of Analysis - Lot LOT-1001
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
"""


def test_matching_repeated_identities_still_bind(vouch):
    """F4: repeating the SAME identity is agreement, not conflict."""
    corpus, v = vouch
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001",
        raw=MATCHING_REPEATED, events=EventLog(),
    )
    assert summary["binding_status"] == "BOUND"
    assert summary["status"] is ArtifactStatus.RECEIVED
    assert claims


def test_conflicting_lot_identities_produce_a_conflict_not_a_release(vouch):
    """F4, the exact audit exploit. First-match-wins released LOT-1001."""
    corpus, v = vouch
    before = corpus.lot("LOT-1001")

    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": CONFLICTING_LOT}])

    assert outcome.disposition not in ("RELEASE", "QUARANTINE")
    assert corpus.lot("LOT-1001").status == "RECEIVED"
    assert corpus.lot("LOT-1001").state_version == before.state_version
    assert not outcome.mutated
    assert v.capabilities.ledger == []
    assert outcome.failure_category == FailureCategory.EVIDENCE_IDENTITY_CONFLICT.value
    assert outcome.quality_decision_required
    assert any("LOT-9999" in c for c in outcome.record.security.identity_conflicts)
    assert any("LOT-1001" in c for c in outcome.record.security.identity_conflicts)


@pytest.mark.parametrize(
    "document,label",
    [
        (CONFLICTING_LOT, "lot"),
        (CONFLICTING_MATERIAL, "material"),
        (CONFLICTING_SUPPLIER, "supplier"),
        (CONFLICTING_SITE, "supplier_site"),
        (HEADER_VERSUS_BODY, "lot"),
    ],
    ids=["lot", "material", "supplier", "site", "header-vs-body"],
)
def test_every_conflicting_identity_dimension_yields_zero_claims(vouch, document, label):
    """F4: lot, material, supplier, site, and structured-vs-body, all reconciled."""
    corpus, v = vouch
    claims, summary = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=document, events=EventLog(),
    )
    assert claims == [], "a self-contradictory artifact yields no usable claims"
    assert summary["status"] is ArtifactStatus.EVIDENCE_IDENTITY_CONFLICT
    assert summary["binding_status"] == "IDENTITY_CONFLICT"
    assert any(label in reason for reason in summary["binding_reasons"])
    assert corpus.lot("LOT-1001").status == "RECEIVED"


def test_identity_extraction_keeps_every_asserted_value():
    """F4: no first-match-wins. All assertions are preserved for reconciliation."""
    identity = extract_document_identity(
        "Certificate of Analysis - Lot LOT-1001\nCorrected document identity: Lot LOT-9999\n"
    )
    assert identity.lot_ids == ("LOT-1001", "LOT-9999")
    # The single-value accessor refuses to pick a winner.
    assert identity.lot_id == ""
    assert identity.conflicts


def test_conflict_is_checked_before_mismatch():
    """F4: a self-contradictory document is not 'about another lot'.

    Reporting it as a mismatch would blame the receiving record for the
    document's own inconsistency.
    """
    identity = DocumentIdentity(lot_ids=("LOT-1001", "LOT-9999"))
    status, reasons = validate_binding(
        identity, target_lot_id="LOT-1001", target_material_id="",
        target_supplier_id="", target_supplier_site="",
    )
    assert status is BindingStatus.IDENTITY_CONFLICT
    assert reasons and "conflicting lot" in reasons[0]
