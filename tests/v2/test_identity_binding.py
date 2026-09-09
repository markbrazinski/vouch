"""The human-resolvable identity case.

A supplier certificate that is entirely legitimate: it parses, it clears
security, and its measurements extract cleanly. What it does NOT do is name a
Vouch lot. It names the supplier's own batch — `WP-26-0317-B` — and nothing
authoritative maps that identifier to `LOT-1003`.

The distinction this file exists to pin is:

    a perfectly valid test result for Lot A must never release Lot B

so the outcome is fail-closed on IDENTITY, not on parsing. Every test enters
through REAL ingestion; the point is that reading the document succeeds and
attributing it does not.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import ArtifactStatus, FailureCategory
from vouch.v2.evidence import BindingStatus, extract_document_identity, validate_binding
from vouch.v2.fixtures import build_corpus
from vouch.v2.lifecycle import EventLog, EventType
from vouch.v2.workflow import VouchV2, VouchFailure

# LOT-1003 in the fixture corpus: MAT-ALLOY-7, SUP-NORTH, SITE-N1, PO-82.
# The document agrees with every one of those. The only thing it does not say
# is which internal lot it is about — it says which SUPPLIER BATCH it is about.
BATCH_ONLY = b"""Certificate of Analysis
Northern Alloys - Supplier: SUP-NORTH
Site: SITE-N1
Material: MAT-ALLOY-7
Purchase Order: PO-82
Supplier Batch: WP-26-0317-B
Specification SPEC-A7 Revision C
tensile_strength: 512 MPa (ASTM-E8, room_temp)
hardness: 31 HRC (HRC, as_received)
Conformance statement: CONFORMS
"""

ACTOR = "R. Mehta, QA Lead"
SOURCE = "QMS-AUTH-QA-LEAD"


@pytest.fixture
def vouch():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


def _run1(vouch, payload=BATCH_ONLY, lot="LOT-1003"):
    corpus, v = vouch
    events = EventLog()
    outcome = v.evaluate_lot(
        lot,
        documents=[{"raw": payload, "document_identity": "COA"}],
        events=events,
    )
    return outcome, events


def _confirm(v, outcome, decision="CONFIRM_BINDING", **kwargs):
    return v.submit_quality_authority(
        decision_record_id=outcome.decision_record_id,
        decision=decision,
        accountable_actor=ACTOR,
        authority_source=SOURCE,
        **kwargs,
    )


# ==========================================================================
# identity parsing — a batch id is an identity, just not one Vouch owns
# ==========================================================================


def test_supplier_batch_is_parsed_and_is_not_read_as_a_lot():
    identity = extract_document_identity(BATCH_ONLY.decode())
    assert identity.supplier_batch == "WP-26-0317-B"
    # The decisive property: the supplier cannot name Vouch's objects. A batch
    # id must never land in `lot_ids`, or the supplier would be asserting which
    # internal lot its own paperwork releases.
    assert identity.lot_ids == ()


def test_supplier_batch_does_not_manufacture_a_phantom_supplier():
    """"Supplier Batch: X" must not be read as supplier id "BATCH"."""
    identity = extract_document_identity(BATCH_ONLY.decode())
    assert identity.supplier_id == "SUP-NORTH"


def test_batch_without_a_confirmed_binding_is_unresolved_not_unbound():
    identity = extract_document_identity(BATCH_ONLY.decode())
    status, reasons = validate_binding(
        identity,
        target_lot_id="LOT-1003", target_material_id="MAT-ALLOY-7",
        target_supplier_id="SUP-NORTH", target_supplier_site="SITE-N1",
    )
    assert status is BindingStatus.UNRESOLVED_SUPPLIER_BATCH
    assert "WP-26-0317-B" in reasons[0] and "LOT-1003" in reasons[0]


def test_a_truly_anonymous_document_is_still_unbound_not_unresolved():
    """The new state must not swallow the F3 case it sits next to."""
    identity = extract_document_identity(
        "Certificate of Analysis\ntensile_strength: 512 MPa\n"
    )
    status, _ = validate_binding(
        identity,
        target_lot_id="LOT-1003", target_material_id="MAT-ALLOY-7",
        target_supplier_id="SUP-NORTH", target_supplier_site="SITE-N1",
    )
    assert status is BindingStatus.UNBOUND_NO_IDENTITY


def test_binding_requires_an_exact_confirmed_reference():
    """No fuzzy match, no case games, no near-miss."""
    identity = extract_document_identity(BATCH_ONLY.decode())
    for wrong in ({"BATCH:WP-26-0317-A->LOT-1003"}, {"BATCH:WP-26-0317-B->LOT-1002"}):
        status, _ = validate_binding(
            identity,
            target_lot_id="LOT-1003", target_material_id="MAT-ALLOY-7",
            target_supplier_id="SUP-NORTH", target_supplier_site="SITE-N1",
            confirmed_batch_bindings=wrong,
        )
        assert status is BindingStatus.UNRESOLVED_SUPPLIER_BATCH


# ==========================================================================
# RUN 1 — read successfully, refuse to attribute
# ==========================================================================


def test_run1_halts_on_identity_not_on_parsing(vouch):
    outcome, _ = _run1(vouch)
    assert outcome.failure_category == FailureCategory.EVIDENCE_IDENTITY_UNRESOLVED.value
    assert outcome.quality_decision_required is True
    record = outcome.record
    # Positively true, so the surface can prove this is NOT an OCR failure.
    assert record.evidence.source_artifact_hashes, "artifact retained"
    assert not record.extraction.low_confidence_routed_to_human
    assert record.security.blocked is False
    assert record.security.prompt_attack_detected is False


def test_run1_extracted_the_measurements_and_held_them(vouch):
    outcome, _ = _run1(vouch)
    held = outcome.record.evidence.held_claims
    assert len(held) == 2, "both measurements extracted"
    assert {c["characteristic"] for c in held} == {"tensile_strength", "hardness"}
    # Held, not admitted. Nothing an agent reads may contain them.
    assert outcome.record.evidence.canonical_claims == []


def test_run1_starts_neither_agent(vouch):
    outcome, events = _run1(vouch)
    kinds = {e["event"] for e in events.as_dicts()}
    assert EventType.INVESTIGATOR_STARTED.value not in kinds
    assert outcome.record.investigator.brief_hash == ""
    assert outcome.record.verifier.brief_hash == ""
    assert outcome.record.disposition.disposition == ""


def test_run1_mutates_nothing(vouch):
    corpus, _ = vouch
    outcome, _ = _run1(vouch)
    assert outcome.mutated is False
    assert corpus.lot("LOT-1003").status == "RECEIVED"
    assert corpus.get("inventory", "LOT-1003").usable is False


def test_run1_is_not_a_defect_finding(vouch):
    """Absence of attribution says nothing about the material's quality."""
    corpus, _ = vouch
    _run1(vouch)
    assert corpus.lot("LOT-1003").status != "QUARANTINED"


def test_run1_asks_a_concrete_structured_question(vouch):
    outcome, _ = _run1(vouch)
    q = outcome.record.quality_authority.question
    assert q.question_type == "IDENTITY_BINDING"
    assert q.supplier_batch == "WP-26-0317-B"
    assert q.internal_lot_id == "LOT-1003"
    assert q.status == "OPEN"
    # Both answers are identity answers. Neither is a disposition.
    assert [o["decision"] for o in q.options] == ["CONFIRM_BINDING", "KEEP_UNBOUND"]
    assert not any(
        w in str(q.options).upper() for w in ("RELEASE", "QUARANTINE", "APPROVE")
    )


def test_run1_event_states_parse_and_security_positively(vouch):
    _, events = _run1(vouch)
    raised = next(
        e for e in events.as_dicts()
        if e["event"] == EventType.QUALITY_QUESTION_RAISED.value
    )
    assert raised["document_parsed"] is True
    assert raised["security_clean"] is True
    assert raised["extracted_claim_count"] == 2


# ==========================================================================
# CONFIRM_BINDING — same record resumes, agents run, RELEASE
# ==========================================================================


def test_confirm_binding_resumes_the_same_record_and_releases(vouch):
    corpus, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)

    assert resumed.decision_record_id == outcome.decision_record_id, "SAME record"
    assert resumed.record.run_count == 2
    assert resumed.disposition == "RELEASE"
    assert corpus.lot("LOT-1003").status == "RELEASED"
    assert corpus.get("inventory", "LOT-1003").usable is True


def test_run2_is_where_the_agents_run_for_the_first_time(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)
    assert resumed.record.investigator.brief_hash
    assert resumed.record.verifier.brief_hash
    # The same convergence label the clean LOT-1001 baseline produces: the
    # two agents agree on every material field, which is what this case is
    # supposed to be. The identity question was the whole difficulty.
    assert resumed.record.reconciliation.outcome == "NON_MATERIAL_DIFFERENCE"
    assert resumed.record.reconciliation.differing_fields == []


def test_run2_uses_the_same_bytes_and_the_same_claims(vouch):
    """Nothing is re-parsed and the supplier artifact is never rewritten."""
    _, v = vouch
    outcome, _ = _run1(vouch)
    held_before = [c["claim_id"] for c in outcome.record.evidence.held_claims]
    hashes_before = list(outcome.record.evidence.source_artifact_hashes)

    resumed = _confirm(v, outcome)
    assert resumed.record.evidence.source_artifact_hashes == hashes_before
    assert sorted(
        c["claim_id"] for c in resumed.record.evidence.canonical_claims
    ) == sorted(held_before)


def test_confirmation_preserves_the_supplier_identity_it_actually_stated(vouch):
    """Vouch must never pretend the supplier asserted the internal lot id."""
    _, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)
    claimed = resumed.record.evidence.claimed_identities[0]
    assert claimed["claimed_supplier_batch"] == "WP-26-0317-B"
    assert claimed["claimed_lot"] == "", "document still names no internal lot"


def test_run1_history_survives_the_continuation(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)
    runs = resumed.record.runs()
    assert [r.run_number for r in runs] == [1, 2]
    assert runs[0].failure_category == FailureCategory.EVIDENCE_IDENTITY_UNRESOLVED.value


def test_the_authority_records_what_was_established(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)
    auth = resumed.record.quality_authority.decisions[0]
    assert auth.decision == "CONFIRM_BINDING"
    assert (auth.supplier_batch, auth.bound_lot_id) == ("WP-26-0317-B", "LOT-1003")
    assert auth.accountable_actor == ACTOR and auth.authority_source == SOURCE
    assert auth.content_hash and auth.artifact_id
    assert auth.created_at


def test_identity_established_event_names_its_scope(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)
    established = next(
        e for e in resumed.events
        if e["event"] == EventType.EVIDENCE_IDENTITY_ESTABLISHED.value
    )
    assert established["scope"] == "THIS_DECISION_RECORD_AND_ARTIFACT_ONLY"


def test_continuation_is_automatic_not_a_second_start(vouch):
    """One human action produces the resumed run; no second Start."""
    _, v = vouch
    outcome, _ = _run1(vouch)
    resumed = _confirm(v, outcome)
    kinds = [e["event"] for e in resumed.events]
    assert EventType.DECISION_RESUMED.value in kinds
    assert kinds.index(EventType.DECISION_RESUMED.value) < kinds.index(
        EventType.INVESTIGATOR_STARTED.value
    )


# ==========================================================================
# KEEP_UNBOUND — settles the question, changes nothing else
# ==========================================================================


def test_keep_unbound_does_not_rerun_and_does_not_mutate(vouch):
    corpus, v = vouch
    outcome, _ = _run1(vouch)
    held = _confirm(v, outcome, decision="KEEP_UNBOUND")

    assert held.record.run_count == 1, "no second run"
    assert held.record.investigator.brief_hash == ""
    assert held.mutated is False
    assert corpus.lot("LOT-1003").status == "RECEIVED"
    assert held.record.quality_authority.question.status == "HELD"
    assert held.record.quality_authority.unbound is True


def test_keep_unbound_retains_the_evidence(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    held = _confirm(v, outcome, decision="KEEP_UNBOUND")
    assert held.record.evidence.source_artifact_hashes
    assert held.record.evidence.held_claims, "extracted claims are kept, not erased"


# ==========================================================================
# security / authority invariants
# ==========================================================================


def test_a_human_cannot_bind_a_different_lot(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    with pytest.raises(VouchFailure) as err:
        _confirm(v, outcome, bound_lot_id="LOT-1002")
    assert "LOT-1002" in str(err.value)


def test_a_human_cannot_bind_a_different_batch(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    with pytest.raises(VouchFailure):
        _confirm(v, outcome, supplier_batch="WP-26-0317-C")


def test_a_human_cannot_bind_a_different_artifact(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    with pytest.raises(VouchFailure):
        _confirm(v, outcome, artifact_id="ART-000000000000")


def test_a_stale_content_hash_is_rejected(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    with pytest.raises(VouchFailure):
        _confirm(v, outcome, content_hash="0" * 64)


def test_binding_is_scoped_to_this_record_only(vouch):
    """A confirmation for one record must not bind the same batch elsewhere."""
    corpus, v = vouch
    outcome, _ = _run1(vouch)
    _confirm(v, outcome)

    # A SECOND lot receiving the very same supplier document is unresolved
    # again. The authority did not create a global alias.
    corpus.put(
        "lot", "LOT-7777",
        type(corpus.lot("LOT-1003"))(
            "LOT-7777", "SUP-NORTH", "MAT-ALLOY-7", "PO-82", 100.0,
            supplier_site="SITE-N1",
        ),
    )
    other = v.evaluate_lot(
        "LOT-7777", documents=[{"raw": BATCH_ONLY, "document_identity": "COA"}]
    )
    assert other.failure_category == FailureCategory.EVIDENCE_IDENTITY_UNRESOLVED.value


def test_duplicate_confirmation_is_idempotent(vouch):
    corpus, v = vouch
    outcome, _ = _run1(vouch)
    first = _confirm(v, outcome)
    version = corpus.version_of("lot", "LOT-1003")

    second = _confirm(v, outcome)
    assert second.decision_record_id == first.decision_record_id
    assert second.record.run_count == 2, "no third run"
    assert len(second.record.quality_authority.decisions) == 1
    assert corpus.version_of("lot", "LOT-1003") == version, "no second mutation"


def test_confirmation_cannot_answer_with_a_disposition(vouch):
    """There is no code path from an identity answer to a disposition word."""
    _, v = vouch
    outcome, _ = _run1(vouch)
    for bogus in ("RELEASE", "QUARANTINE", "APPROVE", "ESTABLISH_EVIDENCE"):
        with pytest.raises(VouchFailure):
            _confirm(v, outcome, decision=bogus)


def test_confirmation_requires_an_accountable_actor(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    with pytest.raises(VouchFailure):
        v.submit_quality_authority(
            decision_record_id=outcome.decision_record_id,
            decision="CONFIRM_BINDING",
            accountable_actor="", authority_source=SOURCE,
        )


def test_a_wrong_lot_document_is_still_a_mismatch_not_a_binding_question(vouch):
    """A batch id must not become a way to launder contradicted identity."""
    _, v = vouch
    payload = BATCH_ONLY.replace(b"Material: MAT-ALLOY-7", b"Material: MAT-RESIN-3")
    outcome, _ = _run1(vouch, payload=payload)
    assert outcome.failure_category == FailureCategory.EVIDENCE_BINDING_MISMATCH.value
    assert outcome.record.quality_authority.question.question_id == ""


def test_an_answered_question_cannot_be_answered_again_differently(vouch):
    _, v = vouch
    outcome, _ = _run1(vouch)
    _confirm(v, outcome)
    with pytest.raises(VouchFailure):
        _confirm(v, outcome, decision="KEEP_UNBOUND")
