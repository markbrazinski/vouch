"""Test A — material disagreement, human authority, and the same-record Run 2.

The case this file proves is the one Vouch could not previously make:

    two independent agents reach two individually VALID conclusions
      -> reconciliation fails closed as MATERIAL_DISAGREEMENT
      -> one answerable applicability question is raised
      -> an accountable human settles that question, and only that question
      -> the SAME DecisionRecord resumes
      -> both agents re-derive and converge
      -> deterministic disposition runs for the first time
      -> RELEASE

The disagreement is NOT manufactured. LOT-1006's snapshot carries two real
viscosity results — one by the method SPEC-R3:A names, one by a method an
authoritative equivalence genuinely covers — and the corpus states no
precedence between them. Both briefs survive every deterministic check. That
is the authority gap a human exists to close, and these tests assert it is
reached honestly rather than by a scripted verifier.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import FailureCategory, VouchFailure
from vouch.v2.fixtures import COA_CLEAN, COA_DISPUTED, build_corpus
from vouch.v2.lifecycle import EventType
from vouch.v2.persistence import InMemoryRecordStore, JsonRecordStore
from vouch.v2.workflow import VouchV2

ACTOR = "QA-LEAD"
SOURCE = "Plant Quality Authority"


@pytest.fixture
def corpus():
    return build_corpus()


@pytest.fixture
def vouch(corpus):
    return corpus, VouchV2(corpus, record_store=InMemoryRecordStore())


@pytest.fixture
def disagreed(vouch):
    """A case sitting at MATERIAL_DISAGREEMENT, awaiting a human."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
    assert outcome.failure_category == "MATERIAL_DISAGREEMENT", outcome.reason
    return corpus, v, outcome


def authorize(v, outcome, **overrides):
    kwargs = dict(
        decision_record_id=outcome.decision_record_id,
        decision="AUTHORIZE_APPLICABILITY",
        accountable_actor=ACTOR,
        authority_source=SOURCE,
    )
    kwargs.update(overrides)
    return v.submit_quality_authority(**kwargs)


# ==========================================================================
# Run 1 — a real disagreement, and nothing else
# ==========================================================================


def test_both_agents_run_and_produce_valid_briefs(disagreed):
    """Neither brief was rejected. A disagreement between two VALID briefs is
    the whole point — a contract violation would be a different failure."""
    _, _, outcome = disagreed
    record = outcome.record

    assert record.investigator.schema_valid
    assert record.verifier.schema_valid
    assert not record.investigator.brief_rejected
    assert not record.verifier.brief_rejected
    assert record.investigator.brief and record.verifier.brief


def test_the_briefs_differ_on_evidence_selection(disagreed):
    """The disagreement is about WHICH applicable evidence establishes the
    requirement — a judgment field, not a validation artifact."""
    _, _, outcome = disagreed
    reconciliation = outcome.record.reconciliation

    assert reconciliation.outcome == "MATERIAL_DISAGREEMENT"
    assert "coverage" in reconciliation.differing_fields

    def viscosity(values):
        rows = {row["test"]: row for row in values["coverage"]}
        return rows["viscosity"]

    mine = viscosity(reconciliation.investigator_values)
    theirs = viscosity(reconciliation.verifier_values)

    assert mine["evidence_ref"] != theirs["evidence_ref"]
    # The Investigator took the spec's own method; the Verifier took the
    # equivalence-covered path. Both are authorized routes to the requirement.
    assert mine["equivalence_record_id"] is None
    assert theirs["equivalence_record_id"] == "EQV-1"


def test_both_selected_claims_are_real_and_applicable(disagreed):
    """Neither agent invented evidence, and both cited claims that genuinely
    exist on this lot in this snapshot."""
    _, v, outcome = disagreed
    claims = {c.claim_id: c for c in v.claims[outcome.decision_record_id]}
    question = outcome.record.quality_authority.question

    for option in question.options:
        claim = claims.get(option["claim_id"])
        assert claim is not None, option
        assert claim.lot_id == "LOT-1006"
        assert claim.characteristic == "viscosity"


def test_run_one_does_not_disposition_or_mutate(disagreed):
    """Deterministic disposition must not have been reached, and nothing may
    have moved."""
    corpus, _, outcome = disagreed
    record = outcome.record

    assert record.disposition.disposition == ""
    assert record.mutation.action == ""
    assert record.capability.capability_id == ""
    assert corpus.lot("LOT-1006").status == "RECEIVED"
    assert corpus.get("inventory", "LOT-1006").usable is False
    assert corpus.lot("LOT-1006").state_version == 1


def test_run_one_raises_exactly_one_answerable_question(disagreed):
    _, _, outcome = disagreed
    question = outcome.record.quality_authority.question

    assert question.question_id
    assert question.question_type == "EVIDENCE_APPLICABILITY"
    assert question.characteristic == "viscosity"
    assert question.status == "OPEN"
    assert question.equivalence_id == "EQV-1"
    assert question.method_from == "ASTM-D445"
    assert question.method_to == "ASTM-D2196"
    assert question.condition == "25C"
    # Two options, one per agent, each carrying what an operator needs to see.
    assert len(question.options) == 2
    assert {o["selected_by"] for o in question.options} == {
        "INVESTIGATOR", "VERIFIER"
    }
    assert {o["value"] for o in question.options} == {285.0, 312.0}


def test_run_one_emits_the_escalation_events(disagreed):
    _, _, outcome = disagreed
    emitted = {event["event"] for event in outcome.events}

    assert EventType.QUALITY_QUESTION_RAISED.value in emitted
    assert EventType.QUALITY_DECISION_REQUIRED.value in emitted
    assert EventType.DISPOSITION_COMPUTED.value not in emitted
    assert EventType.MUTATION_COMPLETED.value not in emitted


# ==========================================================================
# Human authority -> Run 2 -> RELEASE
# ==========================================================================


def test_authorize_resumes_the_same_record_and_releases(disagreed):
    corpus, v, first = disagreed
    outcome = authorize(v, first)

    assert outcome.decision_record_id == first.decision_record_id
    assert outcome.record.run_count == 2
    assert outcome.record.reconciliation.outcome in (
        "MATCH", "NON_MATERIAL_DIFFERENCE"
    )
    assert outcome.disposition == "RELEASE"
    assert corpus.lot("LOT-1006").status == "RELEASED"
    assert corpus.get("inventory", "LOT-1006").usable is True
    assert outcome.record.mutation.action == "release_lot"
    assert outcome.record.mutation.inventory_delta == 200.0


def test_the_human_did_not_release_the_lot(disagreed):
    """The authority fact settles applicability only. The RELEASE is still the
    deterministic engine's, reached through policy and a consumed capability."""
    _, v, first = disagreed
    outcome = authorize(v, first)
    authority = outcome.record.quality_authority.decisions[0]

    assert authority.decision == "AUTHORIZE_APPLICABILITY"
    assert authority.question_type == "EVIDENCE_APPLICABILITY"
    # The authority names evidence, never a disposition or an action.
    assert authority.authorized_evidence_refs
    assert not hasattr(authority, "disposition")
    # And the release still went the full authority route.
    assert outcome.record.basis.checks_passed
    assert outcome.record.policy.gate_decision == "ALLOWED"
    assert outcome.record.capability.issued
    assert outcome.record.capability.consumed


def test_authority_is_bound_to_the_snapshot_it_answered(disagreed):
    _, v, first = disagreed
    snapshot_id = first.record.snapshot.snapshot_id
    claim_set_hash = first.record.snapshot.claim_set_hash

    outcome = authorize(v, first)
    authority = outcome.record.quality_authority.decisions[0]

    assert authority.evidence_snapshot_id == snapshot_id
    assert authority.claim_set_hash == claim_set_hash
    assert authority.source_run == 1
    assert authority.lot_id == "LOT-1006"
    assert authority.accountable_actor == ACTOR
    assert authority.authority_source == SOURCE
    assert authority.created_at


def test_both_agents_converge_on_the_authorized_path(disagreed):
    """Convergence must come from the shared authoritative fact, not from one
    agent being shown the other's answer."""
    _, v, first = disagreed
    authorized = set(
        first.record.quality_authority.question.options[1]["claim_id"].split()
    )
    outcome = authorize(v, first)

    def viscosity(brief):
        rows = {row["test"]: row for row in brief["coverage"]}
        return rows["viscosity"]

    mine = viscosity(outcome.record.investigator.brief)
    theirs = viscosity(outcome.record.verifier.brief)

    assert mine["evidence_ref"] == theirs["evidence_ref"]
    assert mine["evidence_ref"] in authorized
    assert mine["equivalence_record_id"] == "EQV-1"


def test_run_two_emits_resume_and_authority_events(disagreed):
    _, v, first = disagreed
    outcome = authorize(v, first)
    emitted = [event["event"] for event in outcome.events]

    assert EventType.QUALITY_AUTHORITY_RECORDED.value in emitted
    assert EventType.DECISION_RESUMED.value in emitted
    assert EventType.DISPOSITION_COMPUTED.value in emitted
    assert EventType.MUTATION_COMPLETED.value in emitted

    resumed = next(
        e for e in outcome.events if e["event"] == EventType.DECISION_RESUMED.value
    )
    assert resumed["trigger"] == "QUALITY_AUTHORITY"
    assert resumed["run_count"] == 2


def test_run_one_survives_the_continuation_intact(disagreed):
    """Nothing from run 1 may be overwritten — the disagreement is the reason
    a human was asked, and it must stay readable afterwards."""
    _, v, first = disagreed
    before = first.record.investigator.brief_hash
    outcome = authorize(v, first)

    archived = [r for r in outcome.record.archived_runs if r.run_number == 1]
    assert len(archived) == 1
    run_one = archived[0]

    assert run_one.failure_category == "MATERIAL_DISAGREEMENT"
    assert run_one.reconciliation.outcome == "MATERIAL_DISAGREEMENT"
    assert "coverage" in run_one.reconciliation.differing_fields
    assert run_one.investigator.brief_hash == before
    assert run_one.disposition.disposition == ""
    # And the question that was answered is still on the record.
    assert outcome.record.quality_authority.question.question_id


# ==========================================================================
# KEEP_HELD
# ==========================================================================


def test_keep_held_settles_without_a_second_run(disagreed):
    corpus, v, first = disagreed
    outcome = v.submit_quality_authority(
        decision_record_id=first.decision_record_id,
        decision="KEEP_HELD",
        accountable_actor=ACTOR,
        authority_source=SOURCE,
    )

    assert outcome.record.run_count == 1
    assert outcome.quality_decision_required is False
    assert outcome.record.quality_authority.question.status == "HELD"
    assert outcome.record.quality_authority.held
    assert outcome.disposition == ""
    assert outcome.record.mutation.action == ""
    assert corpus.lot("LOT-1006").status == "RECEIVED"
    assert corpus.get("inventory", "LOT-1006").usable is False


def test_keep_held_is_durably_recorded(disagreed):
    _, v, first = disagreed
    v.submit_quality_authority(
        decision_record_id=first.decision_record_id,
        decision="KEEP_HELD",
        accountable_actor=ACTOR,
        authority_source=SOURCE,
    )
    stored = v.record_store.load(first.decision_record_id)
    authority = stored["quality_authority"]

    assert authority["question"]["status"] == "HELD"
    assert authority["decisions"][0]["decision"] == "KEEP_HELD"
    assert authority["decisions"][0]["accountable_actor"] == ACTOR
    assert authority["decisions"][0]["authorized_evidence_refs"] == []


# ==========================================================================
# S13 — authority / security invariants
# ==========================================================================


def test_duplicate_authorize_is_idempotent(disagreed):
    corpus, v, first = disagreed
    authorize(v, first)
    version_after = corpus.lot("LOT-1006").state_version

    again = authorize(v, first)
    record = v.resume(first.decision_record_id)

    assert len(record.quality_authority.decisions) == 1
    assert record.run_count == 2, "a replay must not create a third run"
    assert corpus.lot("LOT-1006").state_version == version_after
    assert "already recorded" in again.reason


def test_a_second_conflicting_answer_is_refused(disagreed):
    _, v, first = disagreed
    authorize(v, first)

    with pytest.raises(VouchFailure) as raised:
        v.submit_quality_authority(
            decision_record_id=first.decision_record_id,
            decision="KEEP_HELD",
            accountable_actor=ACTOR,
            authority_source=SOURCE,
        )
    assert raised.value.category is FailureCategory.POLICY_REFUSAL


@pytest.mark.parametrize(
    "overrides, category",
    [
        ({"decision": "RELEASE"}, FailureCategory.POLICY_REFUSAL),
        ({"decision": "release_lot"}, FailureCategory.POLICY_REFUSAL),
        ({"decision": ""}, FailureCategory.POLICY_REFUSAL),
        ({"accountable_actor": ""}, FailureCategory.POLICY_REFUSAL),
        ({"authority_source": ""}, FailureCategory.POLICY_REFUSAL),
        ({"claim_set_hash": "not-the-snapshot"}, FailureCategory.STATE_CONFLICT),
        ({"question_id": "QQ-someone-elses"}, FailureCategory.POLICY_REFUSAL),
        (
            {"decision_record_id": "DR-does-not-exist"},
            FailureCategory.PERSISTENCE_FAILURE,
        ),
    ],
)
def test_invalid_authority_submissions_fail_closed(disagreed, overrides, category):
    corpus, v, first = disagreed

    with pytest.raises(VouchFailure) as raised:
        authorize(v, first, **overrides)

    assert raised.value.category is category
    assert corpus.lot("LOT-1006").status == "RECEIVED"
    assert v.resume(first.decision_record_id).quality_authority.decisions == []


def test_a_release_enum_cannot_be_smuggled_through_the_decision_field(disagreed):
    """There is no spelling of `decision` that releases a lot."""
    corpus, v, first = disagreed
    for attempt in ("RELEASE", "RELEASE_LOT", "AUTHORIZE_RELEASE", "ACT", "ALLOW"):
        with pytest.raises(VouchFailure):
            authorize(v, first, decision=attempt)
    assert corpus.lot("LOT-1006").status == "RECEIVED"


def test_authority_cannot_be_recorded_on_a_record_with_no_question(vouch):
    """A clean autonomous release has nothing to authorize."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert outcome.disposition == "RELEASE"

    with pytest.raises(VouchFailure) as raised:
        authorize(v, outcome)
    assert raised.value.category is FailureCategory.POLICY_REFUSAL


def test_authority_does_not_mutate_the_global_equivalence_catalog(disagreed):
    """The scoped fact must not widen EQV-2 for any other lot or decision."""
    corpus, v, first = disagreed
    before = corpus.get("equivalence", "EQV-1")
    authorize(v, first)
    after = corpus.get("equivalence", "EQV-1")

    assert after == before
    assert after.condition_scope == ("25C",)
    assert after.material_scope == ("MAT-RESIN-3",)
    assert after.status == "APPROVED"


def test_authority_does_not_leak_to_another_decision(corpus):
    """A second decision on the same lot starts with no authority at all."""
    v = VouchV2(corpus, record_store=InMemoryRecordStore())
    first = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
    authorize(v, first)

    second = VouchV2(build_corpus(), record_store=InMemoryRecordStore())
    fresh = second.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])

    assert fresh.failure_category == "MATERIAL_DISAGREEMENT"
    assert fresh.record.quality_authority.decisions == []


def test_authority_alone_moves_no_inventory(disagreed):
    """Recording the fact is not the mutation. Only the deterministic release
    that follows moves inventory, and only for this lot."""
    corpus, v, first = disagreed
    others = {
        lot_id: corpus.get("inventory", lot_id).usable
        for lot_id in ("LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004", "LOT-1005")
    }
    authorize(v, first)

    for lot_id, usable in others.items():
        assert corpus.get("inventory", lot_id).usable is usable


def test_authority_survives_a_restart_and_still_resumes(corpus, tmp_path):
    """The authority fact is durable, and a process that never saw run 1 can
    still continue the case."""
    store = JsonRecordStore(tmp_path / "records")
    first = VouchV2(corpus, record_store=store)
    outcome = first.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])

    second = VouchV2(corpus, record_store=JsonRecordStore(tmp_path / "records"))
    resumed = second.submit_quality_authority(
        decision_record_id=outcome.decision_record_id,
        decision="AUTHORIZE_APPLICABILITY",
        accountable_actor=ACTOR,
        authority_source=SOURCE,
    )

    assert resumed.disposition == "RELEASE"
    assert resumed.record.run_count == 2
    stored = store.load(outcome.decision_record_id)
    assert stored["quality_authority"]["decisions"][0]["accountable_actor"] == ACTOR


def test_the_authority_event_carries_no_private_reasoning(disagreed):
    _, v, first = disagreed
    outcome = authorize(v, first)
    recorded = [
        e for e in outcome.events
        if e["event"] == EventType.QUALITY_AUTHORITY_RECORDED.value
    ]
    assert recorded
    for event in recorded:
        for key in event:
            assert "rationale" not in key
            assert "reasoning" not in key


# ==========================================================================
# the production story stays where it was
# ==========================================================================


def test_lot_1006_recovers_c419_and_leaves_c417_c418_alone(vouch):
    """The consequence is real, and it lands where it belongs.

    C-419 needs 800 kg of MAT-RESIN-3 against 600 usable, with the missing 200
    queued against LOT-1006 — so it starts AT_RISK. LOT-1006 is exactly that
    200. Releasing it closes the gap and nothing else: the alloy orders belong
    to the LOT-1001/LOT-1002 story and must not move.
    """
    corpus, v = vouch
    assert corpus.get("production_order", "C-419").status == "AT_RISK"

    first = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
    # Run 1 changes nothing — the disagreement stopped before any mutation.
    assert corpus.get("production_order", "C-419").status == "AT_RISK"

    outcome = authorize(v, first)

    assert outcome.disposition == "RELEASE"
    assert corpus.get("production_order", "C-419").status == "READY"
    assert corpus.get("production_order", "C-417").status == "READY"
    assert corpus.get("production_order", "C-418").status == "READY"

    changes = outcome.record.consequences.readiness_changes
    assert [(c["order_id"], c["from"], c["to"]) for c in changes] == [
        ("C-419", "AT_RISK", "READY")
    ]
    assert changes[0]["persisted"] is True


def test_the_c417_recovery_story_is_unchanged_by_lot_1006(corpus):
    """The canonical LOT-1001 -> LOT-1002 sequence must reach exactly the same
    place whether or not LOT-1006 was decided first."""

    def sequence(with_1006: bool):
        from vouch.v2.fixtures import COA_HERO

        world = build_corpus()
        v = VouchV2(world, record_store=InMemoryRecordStore())
        if with_1006:
            first = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
            authorize(v, first)
        v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
        outcome = v.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
        recovery = outcome.record.consequences.recovery
        return {
            "c417": world.get("production_order", "C-417").status,
            "c418_slot": world.get("production_order", "C-418").planned_slot,
            "candidates": len(recovery.get("candidates") or []),
            "changes": [
                (c["order_id"], c["from"], c["to"])
                for c in outcome.record.consequences.readiness_changes
            ],
        }

    assert sequence(True) == sequence(False)


# ==========================================================================
# reasoner independence — a general property, not a LOT-1006 branch
# ==========================================================================


def _tools_for(corpus, lot_id, claims, agent):
    from vouch.v2.tools import CorpusTools

    lot = corpus.lot(lot_id)
    return CorpusTools(
        corpus, agent_name=agent, lot_id=lot_id,
        material_id=lot.material_id, snapshot_claims=claims,
    )


def _claim(
    claim_id, characteristic, value, method, condition,
    trust="UNTRUSTED_SUPPLIER", lot_id="LOT-1006", material_id="MAT-RESIN-3",
):
    """A real CanonicalEvidenceClaim, so the reasoners run against the same
    typed objects the pipeline gives them."""
    from vouch.v2.contracts import (
        CanonicalEvidenceClaim, ExtractionMethod, TrustLabel,
    )

    return CanonicalEvidenceClaim(
        claim_id=claim_id, evidence_artifact_id="ART-test", lot_id=lot_id,
        material_id=material_id, claim_type="measurement",
        characteristic=characteristic, value=value, units="cP",
        method=method, condition=condition, source_locator="line:1",
        extraction_method=ExtractionMethod.DETERMINISTIC_PARSER,
        extraction_version="test", trust_label=TrustLabel(trust),
        source_hash="h",
    )


def _briefs(corpus, lot_id, claims, context=None):
    from vouch.v2.local_reasoners import investigator_reasoner, verifier_reasoner

    lot = corpus.lot(lot_id)
    base = {
        "lot_id": lot_id, "material_id": lot.material_id,
        "manufactured_at": lot.manufactured_at, "received_at": lot.received_at,
        "supplier_site": lot.supplier_site, "po_reference": lot.po_reference,
    }
    base.update(context or {})
    return (
        investigator_reasoner(_tools_for(corpus, lot_id, claims, "investigator"), base),
        verifier_reasoner(_tools_for(corpus, lot_id, claims, "verifier"), base),
    )


def test_the_two_reasoners_agree_when_only_one_path_applies(corpus):
    """Independence is not disagreement. Given a single applicable evidence
    path, the two derivations must reach the SAME answer — otherwise they
    would manufacture disputes on ordinary lots."""
    claims = [_claim("CLM-a", "viscosity", 285.0, "ASTM-D2196", "25C")]
    investigator, verifier = _briefs(corpus, "LOT-1006", claims)

    assert investigator.material_fingerprint() == verifier.material_fingerprint()


def test_the_two_reasoners_agree_when_no_evidence_applies(corpus):
    """A method nothing covers is uncovered for both of them."""
    claims = [_claim("CLM-a", "viscosity", 285.0, "ASTM-XX", "25C")]
    investigator, verifier = _briefs(corpus, "LOT-1006", claims)

    assert investigator.material_fingerprint() == verifier.material_fingerprint()
    assert investigator.sufficiency.value == "INSUFFICIENT_EVIDENCE"


def test_the_reasoners_diverge_only_when_several_paths_are_authorized(corpus):
    """The divergence is a property of the EVIDENCE, not of the lot id: two
    equally authorized paths for one requirement is what separates them."""
    one_path = [_claim("CLM-a", "viscosity", 285.0, "ASTM-D2196", "25C")]
    two_paths = [
        _claim("CLM-a", "viscosity", 285.0, "ASTM-D2196", "25C"),
        _claim("CLM-b", "viscosity", 312.0, "ASTM-D445", "25C"),
    ]

    same = _briefs(corpus, "LOT-1006", one_path)
    assert same[0].material_fingerprint() == same[1].material_fingerprint()

    differ = _briefs(corpus, "LOT-1006", two_paths)
    assert differ[0].material_fingerprint() != differ[1].material_fingerprint()


def test_the_verifier_prefers_the_direct_method_when_it_is_the_latest(corpus):
    """The Verifier is not hard-coded to the equivalence path. Reverse the
    snapshot order and it selects the direct-method result instead."""
    claims = [
        _claim("CLM-a", "viscosity", 312.0, "ASTM-D445", "25C"),
        _claim("CLM-b", "viscosity", 285.0, "ASTM-D2196", "25C"),
    ]
    _, verifier = _briefs(corpus, "LOT-1006", claims)
    row = {c.test: c for c in verifier.coverage}["viscosity"]

    assert row.evidence_ref == "CLM-b"
    assert row.equivalence_record_id is None


def test_a_scoped_authority_converges_the_two_reasoners(corpus):
    """The authorized path is what makes them agree — on any evidence set."""
    claims = [
        _claim("CLM-a", "viscosity", 285.0, "ASTM-D2196", "25C"),
        _claim("CLM-b", "viscosity", 312.0, "ASTM-D445", "25C"),
    ]
    before = _briefs(corpus, "LOT-1006", claims)
    assert before[0].material_fingerprint() != before[1].material_fingerprint()

    after = _briefs(
        corpus, "LOT-1006", claims,
        context={"authorized_evidence_refs": ["CLM-b"]},
    )
    assert after[0].material_fingerprint() == after[1].material_fingerprint()
    row = {c.test: c for c in after[0].coverage}["viscosity"]
    assert row.evidence_ref == "CLM-b"


def test_higher_trust_evidence_still_wins_for_both(corpus):
    """A QA retest supersedes a supplier claim in both derivations, so the
    existing human-evidence continuation keeps working."""
    claims = [
        _claim("CLM-a", "viscosity", 285.0, "ASTM-D2196", "25C"),
        _claim(
            "CLM-qa", "viscosity", 305.0, "ASTM-D2196", "25C",
            trust="HUMAN_AUTHORIZED",
        ),
    ]
    investigator, verifier = _briefs(corpus, "LOT-1006", claims)

    for brief in (investigator, verifier):
        row = {c.test: c for c in brief.coverage}["viscosity"]
        assert row.evidence_ref == "CLM-qa"
