"""End-to-end pipeline, agent independence, reconciliation, consequences, recovery."""

from __future__ import annotations

import pytest

from vouch.v2.agents import ApplicabilityInvestigator, IndependentVerifier
from vouch.v2.consequences import (
    Readiness,
    ReasonCode,
    Verdict,
    compute_readiness,
    enumerate_recovery,
)
from vouch.v2.contracts import (
    EvidenceApplicabilityBrief,
    GoverningBasis,
    ReconciliationOutcome,
    Sufficiency,
    TrustLabel,
)
from vouch.v2.fixtures import (
    COA_AMBIGUOUS,
    COA_CLEAN,
    COA_HERO,
    QA_RETEST,
    build_corpus,
)
from vouch.v2.lifecycle import EventLog, EventType
from vouch.v2.reconcile import reconcile
from vouch.v2.tools import CorpusTools
from vouch.v2.workflow import VouchV2


@pytest.fixture
def vouch():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


# -- the canonical chain ---------------------------------------------------
def test_clean_lot_releases(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.disposition == "RELEASE"
    assert corpus.lot("LOT-1001").status == "RELEASED"
    assert corpus.usable_inventory("MAT-ALLOY-7") == 500.0
    assert outcome.record.capability.consumed
    assert outcome.mutation["sequence"] == 1


def test_hero_lot_quarantines_on_governing_basis(vouch):
    """The COA cites rev B and says CONFORMS; rev C governs by receipt date."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    assert outcome.disposition == "QUARANTINE"
    assert outcome.record.basis.spec_id == "SPEC-A7"
    assert outcome.record.basis.revision == "C"
    assert corpus.lot("LOT-1002").status == "QUARANTINED"


def test_ambiguous_evidence_abstains_without_marking_defective(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])

    assert outcome.disposition == "INSUFFICIENT_EVIDENCE"
    assert outcome.quality_decision_required
    # Absence of evidence is NOT a defect finding.
    assert corpus.lot("LOT-1003").status == "PENDING_QA"
    assert corpus.lot("LOT-1003").status != "QUARANTINED"


def test_human_evidence_resumes_the_same_record(vouch):
    corpus, v = vouch
    first = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = first.decision_record_id

    second = v.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1003",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    assert second.decision_record_id == record_id
    assert second.record.run_count == 2
    assert second.disposition == "RELEASE"
    assert second.record.human.review_status == "RESOLVED"
    assert corpus.lot("LOT-1003").status == "RELEASED"


def test_human_evidence_attach_is_idempotent(vouch):
    corpus, v = vouch
    first = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = first.decision_record_id

    v.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1003",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )
    again = v.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1003",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )
    assert again.record.run_count == 2  # no third run
    assert len(again.record.human.content_hashes) == 1


def test_human_evidence_is_labeled_human_authorized(vouch):
    corpus, v = vouch
    claims, _ = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1003", raw=QA_RETEST,
        events=EventLog(), trust_label=TrustLabel.HUMAN_AUTHORIZED,
    )
    assert all(c.trust_label is TrustLabel.HUMAN_AUTHORIZED for c in claims)


# -- agent independence ----------------------------------------------------
def test_verifier_never_receives_the_investigator_brief(vouch):
    """Structural: run() takes context+claims, and no brief parameter exists."""
    import inspect

    signature = inspect.signature(IndependentVerifier.run)
    assert "brief" not in signature.parameters
    assert "investigator" not in signature.parameters
    assert set(signature.parameters) - {"self"} == {
        "context", "claims", "events", "decision_record_id",
        # The Verifier's OWN contract errors from its OWN previous attempt.
        # Nothing here carries the Investigator's brief, rationale or basis —
        # independence is about what the peer said, not about being told that
        # your own citation is unsupported by the corpus.
        "validation_errors",
    }


def test_investigator_and_verifier_use_different_derivations():
    """No shared classifier. V1's actor and verifier both called _classify."""
    from vouch.v2 import local_reasoners

    assert local_reasoners.investigator_reasoner is not local_reasoners.verifier_reasoner
    source_i = local_reasoners.investigator_reasoner.__code__
    source_v = local_reasoners.verifier_reasoner.__code__
    assert source_i.co_code != source_v.co_code


def test_both_agents_actually_call_tools(vouch):
    corpus, v = vouch
    events = EventLog()
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}], events=events)

    tool_calls = events.of_type(EventType.TOOL_CALLED)
    agents = {e.payload["agent"] for e in tool_calls}
    assert agents == {"investigator", "verifier"}
    assert outcome.record.investigator.tool_events
    assert outcome.record.verifier.tool_events


def test_agents_cannot_emit_a_disposition():
    """The vocabulary itself forbids it."""
    assert "disposition" not in EvidenceApplicabilityBrief.model_fields
    assert "release" not in str(EvidenceApplicabilityBrief.model_fields).lower()


# -- reconciliation --------------------------------------------------------
def _brief(spec_id="SPEC-A7", revision="C", sufficiency=Sufficiency.SUFFICIENT, notes=""):
    return EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id=spec_id, revision=revision),
        sufficiency=sufficiency,
        investigation_notes=notes,
    )


def test_material_disagreement_abstains():
    events = EventLog()
    result = reconcile(_brief(revision="C"), _brief(revision="B"), events, "DR-1")
    assert result.outcome is ReconciliationOutcome.MATERIAL_DISAGREEMENT
    assert "revision" in result.differing_fields


def test_non_material_difference_proceeds():
    events = EventLog()
    result = reconcile(
        _brief(notes="checked the ECN"), _brief(notes="different phrasing entirely"),
        events, "DR-1",
    )
    assert result.outcome is ReconciliationOutcome.NON_MATERIAL_DIFFERENCE


def test_missing_brief_is_technical_not_disagreement():
    events = EventLog()
    result = reconcile(_brief(), None, events, "DR-1")
    assert result.outcome is ReconciliationOutcome.TECHNICAL_FAILURE


def test_a_brief_citing_a_superseded_revision_blocks_mutation(vouch):
    """Contract-invalid, not merely divergent.

    Revision B ceased to govern before this lot's basis date, so this brief
    contradicts the corpus rather than making a different defensible judgment.
    Per-brief validation now names that specifically instead of reporting an
    unattributed disagreement — a strictly better audit answer. What must not
    change is the safety property: no mutation, lot untouched.
    """
    corpus, _ = vouch

    class Divergent(IndependentVerifier):
        def run(self, **kwargs):
            from vouch.v2.agents import AgentRun

            return AgentRun(_brief(revision="B"), "m", "v", "h", [], True)

    v = VouchV2(corpus, verifier=Divergent(corpus))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "BRIEF_CONTRACT_VIOLATION"
    assert "SPEC-A7:B" in outcome.reason
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"


def test_genuine_disagreement_between_valid_briefs_still_fails_closed(vouch):
    """Category C must survive the repair.

    Both briefs here are contract-valid — the governing revision exists,
    governs, and covers the material; the coverage rows are complete and
    consistent with the claims. They differ only in sufficiency, which is a
    judgment neither the validator nor the reconciler may resolve. The
    pipeline must still refuse to mutate.
    """
    corpus, _ = vouch

    class Divergent(IndependentVerifier):
        def run(self, **kwargs):
            from vouch.v2.agents import AgentRun
            from vouch.v2.contracts import CoverageItem, RequiredTest

            claims = kwargs["claims"]
            by_test = {c.characteristic: c.claim_id for c in claims}
            brief = EvidenceApplicabilityBrief(
                governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="C"),
                required_tests=(
                    RequiredTest(name="tensile_strength"),
                    RequiredTest(name="hardness"),
                ),
                coverage=(
                    CoverageItem(
                        test="tensile_strength",
                        evidence_ref=by_test.get("tensile_strength"),
                        method_match=True,
                    ),
                    CoverageItem(
                        test="hardness",
                        evidence_ref=by_test.get("hardness"),
                        method_match=True,
                    ),
                ),
                sufficiency=Sufficiency.INSUFFICIENT_EVIDENCE,
            )
            return AgentRun(brief, "m", "v", "h", [], True)

    v = VouchV2(corpus, verifier=Divergent(corpus))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "MATERIAL_DISAGREEMENT"
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"


# -- consequences ----------------------------------------------------------
def test_quarantine_removes_usable_inventory_and_blocks_the_order(vouch):
    """Readiness is PERSISTED, not merely computed (P1-6).

    Releasing LOT-1001 is already not enough to cover C-417, so the order
    transitions READY -> BLOCKED on that decision and the transition is written.
    Quarantining LOT-1002 then adds no usable inventory, so C-417 stays BLOCKED
    — the same state, already persisted, and therefore no second transition.
    """
    corpus, v = vouch
    first = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    # The transition happened AND was written through the capability path.
    change = next(
        c for c in first.consequences["readiness_changes"] if c["order_id"] == "C-417"
    )
    assert change == {
        **change, "from": "READY", "to": "BLOCKED", "persisted": True,
    }
    assert corpus.order("C-417").status == "BLOCKED"
    assert corpus.order("C-417").state_version == 2
    assert first.consequences["caused_by"]

    outcome = v.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
    assert corpus.usable_inventory("MAT-ALLOY-7") == 500.0
    assert compute_readiness(corpus, "C-417").readiness is Readiness.BLOCKED
    # Already BLOCKED and persisted: no spurious re-transition, no version churn.
    assert outcome.consequences["readiness_changes"] == []
    assert corpus.order("C-417").state_version == 2


def test_causal_chain_is_reconstructable(vouch):
    """The causal link belongs to the decision that CAUSED the transition."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    links = outcome.record.consequences.caused_by
    assert links
    link = next(link for link in links if link["order_id"] == "C-417")
    assert link["cause"] == "lot_disposition"
    assert link["lot_id"] == "LOT-1001"
    assert link["effect"] == "order_readiness"
    assert link["from"] == "READY"
    assert link["to"] == "BLOCKED"
    # P1-6: the link points at the ledger entry that actually wrote the change.
    assert link["ledger_sequence"]


def test_release_restores_availability(vouch):
    corpus, v = vouch
    before = corpus.usable_inventory("MAT-ALLOY-7")
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert corpus.usable_inventory("MAT-ALLOY-7") == before + 500.0


# -- recovery --------------------------------------------------------------
def test_recovery_returns_all_candidates_with_verdicts(vouch):
    corpus, v = vouch
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    v.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    options, selected = enumerate_recovery(corpus, "C-417")
    by_kind = {(o.kind, o.candidate_id): o for o in options}

    assert by_kind[("EXISTING_INVENTORY", "MAT-ALLOY-7")].verdict is Verdict.NOT_FEASIBLE
    assert by_kind[("SUBSTITUTE", "MAT-SUB-9")].verdict is Verdict.REFUSED
    assert by_kind[("SUBSTITUTE", "MAT-SUB-9")].reason_code is ReasonCode.NOT_APPROVED
    assert by_kind[("RESEQUENCE", "C-418")].verdict is Verdict.ELIGIBLE
    assert by_kind[("RESEQUENCE", "C-419")].reason_code is ReasonCode.RESOURCE_INCOMPATIBLE
    assert selected.candidate_id == "C-418"


def test_refusal_is_distinct_from_infeasibility(vouch):
    """Stock exists for MAT-SUB-9; authority does not. Availability != authority."""
    corpus, v = vouch
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    v.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    options, _ = enumerate_recovery(corpus, "C-417")
    substitute = next(o for o in options if o.kind == "SUBSTITUTE")
    assert substitute.verdict is Verdict.REFUSED
    assert substitute.facts["available"] == 900.0  # plenty in stock


def test_recovery_priority_is_explicit_not_alphabetical(vouch):
    """V1 used min(key=order_id). Business priority must decide instead."""
    from dataclasses import replace

    corpus, v = vouch

    # Add a candidate that sorts LATER alphabetically but is customer-committed
    # and needed sooner — the correct answer under business policy. It is added
    # BEFORE the pipeline runs, because recovery now actually executes (P1-7)
    # and enumerating afterwards would be scoring an already-recovered plan.
    c418 = corpus.order("C-418")
    corpus.put(
        "production_order", "C-999",
        replace(c418, order_id="C-999", customer_committed=True, need_by="2026-08-16",
                planned_slot="2026-08-15T16:00"),
    )
    corpus.bump("production_order", "C-417", status="BLOCKED")

    options, selected = enumerate_recovery(corpus, "C-417")
    assert selected.candidate_id == "C-999"  # not the alphabetically-first C-418


# -- lifecycle + decision record ------------------------------------------
def test_full_lifecycle_event_sequence(vouch):
    corpus, v = vouch
    events = EventLog()
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}], events=events)

    emitted = set(events.types())
    required = {
        EventType.EVIDENCE_SECURITY_COMPLETED,
        EventType.EVIDENCE_EXTRACTED,
        EventType.EVIDENCE_SNAPSHOT_CREATED,
        EventType.INVESTIGATOR_STARTED,
        EventType.TOOL_CALLED,
        EventType.TOOL_RESULT_BOUND,
        EventType.APPLICABILITY_BRIEF_COMPLETED,
        EventType.VERIFIER_STARTED,
        EventType.VERIFIER_BRIEF_COMPLETED,
        EventType.RECONCILIATION_COMPLETED,
        EventType.DISPOSITION_COMPUTED,
        EventType.POLICY_EVALUATED,
        EventType.CAPABILITY_ISSUED,
        EventType.MUTATION_COMPLETED,
        EventType.CONSEQUENCE_RECALCULATED,
    }
    assert required <= emitted


def test_precedent_consulted_is_not_emitted_in_milestone_1(vouch):
    corpus, v = vouch
    events = EventLog()
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}], events=events)
    assert EventType.PRECEDENT_CONSULTED not in set(events.types())


def test_decision_record_carries_every_required_segment(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    record = outcome.record

    assert record.is_reconstructable()
    assert record.identity.lot_id == "LOT-1001"
    assert record.evidence.source_artifact_hashes
    assert record.security.inspection_performed
    assert record.extraction.per_claim
    assert record.snapshot.claim_set_hash
    assert record.investigator.model_id and record.investigator.prompt_version
    assert record.verifier.model_id and record.verifier.prompt_version
    assert record.reconciliation.outcome
    assert record.basis.spec_id and record.basis.revision
    assert record.disposition.disposition
    assert record.policy.policy_version
    assert record.capability.capability_id and record.capability.consumed
    assert record.mutation.ledger_sequence == 1
    assert record.mutation.inventory_delta == 500.0


def test_decision_record_stores_no_chain_of_thought(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    payload = str(outcome.record.to_dict()).lower()
    assert "chain_of_thought" not in payload
    assert "reasoning_tokens" not in payload


def test_model_id_and_prompt_version_are_recorded(vouch):
    """An auditor must be able to tell which model made the decision."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert outcome.record.investigator.model_id == "us.amazon.nova-pro-v1:0"
    assert outcome.record.investigator.prompt_version == "investigator-v2.1"
    assert outcome.record.investigator.temperature == 0.0


def test_no_silent_model_substitution():
    """config.load() defaulted to Sonnet when the manifest lacked a key."""
    from vouch.v2.agents import model_id_for

    assert model_id_for("investigator") == "us.amazon.nova-pro-v1:0"
    assert model_id_for("verifier") == "us.amazon.nova-pro-v1:0"


# -- Strands tool registration --------------------------------------------
def test_strands_tool_registration_produces_real_tools(vouch):
    """Regression guard for a silent, dangerous failure.

    Passing bound methods to strands.Agent(tools=...) is rejected as an
    "unrecognized tool specification" — and the agent then runs with NO tools
    while reporting success. Observed live: Nova invented a specification
    ("SPEC-ALLOY-7 REV-A") that does not exist in the corpus. That is V1's
    tools=[] failure returning through the back door, so it gets a test.
    """
    from strands.tools.decorator import DecoratedFunctionTool

    corpus, _ = vouch
    tools = CorpusTools(
        corpus, agent_name="investigator", lot_id="LOT-1001",
        material_id="MAT-ALLOY-7", snapshot_claims=[],
    )
    registered = tools.strands_tools(CorpusTools.INVESTIGATOR_TOOLS)

    assert len(registered) == len(CorpusTools.INVESTIGATOR_TOOLS)
    for entry in registered:
        assert isinstance(entry, DecoratedFunctionTool), (
            f"{entry} is not a Strands tool; the agent would silently run tool-less"
        )


def test_registered_tools_are_bound_to_the_decision_context(vouch):
    """A tool cannot be pointed at another lot by the model."""
    corpus, _ = vouch
    tools = CorpusTools(
        corpus, agent_name="investigator", lot_id="LOT-1001",
        material_id="MAT-ALLOY-7", snapshot_claims=[],
    )
    registered = {t.tool_name: t for t in tools.strands_tools(CorpusTools.INVESTIGATOR_TOOLS)}
    # get_supplier_qualification takes no lot argument at all.
    assert "get_supplier_qualification" in registered
    result = tools.get_supplier_qualification()
    assert result["qualification_id"] == "QUAL-1"


def test_recovery_is_returned_to_the_caller_not_only_stored_on_the_record():
    """Recovery is the half of the consequence that moved the schedule.

    It was written to the DecisionRecord but left out of the returned
    consequences, so every API consumer — the AgentCore runtime included — saw
    a blocked order with no candidates, no refusals and no executed resequence.
    """
    corpus = build_corpus()
    outcome = VouchV2(corpus).evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    recovery = outcome.consequences.get("recovery")
    assert recovery, "recovery must reach the caller"
    assert recovery == outcome.record.consequences.recovery
    assert recovery["executed"] is True
    verdicts = {c["candidate_id"]: c["verdict"] for c in recovery["candidates"]}
    assert verdicts["MAT-SUB-9"] == "REFUSED"
    assert verdicts["C-418"] == "ELIGIBLE"
