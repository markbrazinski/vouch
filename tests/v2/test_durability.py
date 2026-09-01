"""P1-1 durable DecisionRecord, P1-2 durable lifecycle events, P1-8 tool provenance.

The audit found the DecisionRecord living in process memory and the lifecycle
events in a Python list: nothing an auditor could inspect survived a decision.
"""

from __future__ import annotations

import json

import pytest

from vouch.v2.decision_record import DecisionRecord
from vouch.v2.fixtures import COA_AMBIGUOUS, COA_CLEAN, COA_HERO, COA_HOSTILE, build_corpus
from vouch.v2.lifecycle import EventType
from vouch.v2.persistence import InMemoryRecordStore, JsonRecordStore
from vouch.v2.tools import CorpusTools, ToolAuthority
from vouch.v2.workflow import VouchV2

#: Every event the contract locks (D14 / P1-2) that a clean autonomous run
#: must actually emit.
REQUIRED_EVENTS = {
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


@pytest.fixture
def store(tmp_path):
    return JsonRecordStore(tmp_path / "records")


@pytest.fixture
def vouch(store):
    corpus = build_corpus()
    return corpus, VouchV2(corpus, record_store=store)


# ==========================================================================
# P1-1 — the record is durable and re-derivable
# ==========================================================================


def test_record_survives_the_process(vouch, store, tmp_path):
    """The point of durability: a NEW store object reads the same record."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    reopened = JsonRecordStore(tmp_path / "records")
    loaded = reopened.load(outcome.decision_record_id)

    assert loaded is not None
    assert loaded["identity"]["lot_id"] == "LOT-1001"
    assert loaded["disposition"]["disposition"] == "RELEASE"
    assert loaded["audit_hash"]


def test_record_is_re_derivable(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert outcome.record.is_re_derivable()
    assert outcome.record.is_reconstructable()


def test_record_stores_evidence_refs_versions_and_hashes(vouch):
    """P1-1 source segment: the exact bytes must be re-fetchable."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    evidence = outcome.record.evidence

    assert evidence.source_artifact_hashes and len(evidence.source_artifact_hashes[0]) == 64
    assert evidence.storage_refs
    assert evidence.object_versions
    assert evidence.receipt_timestamps


def test_record_stores_claims_with_locators_and_versions(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    per_claim = outcome.record.extraction.per_claim

    assert per_claim
    for entry in per_claim.values():
        assert entry["locator"]
        assert entry["version"]
        assert entry["source_hash"]
        assert entry["trust_label"] == "UNTRUSTED_SUPPLIER"


def test_record_stores_every_authoritative_object_with_its_version(vouch):
    """P1-1: object ID, revision and effective metadata for what was consulted."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    objects = outcome.record.corpus.objects

    assert "SPEC-A7:C" in objects
    spec = objects["SPEC-A7:C"]
    assert spec["revision"] == "C"
    assert spec["status"] == "ACTIVE"
    assert spec["effective_date"]
    assert spec["effective_basis"]
    assert any(o["kind"] == "requirement" for o in objects.values())
    assert outcome.record.corpus.corpus_hash


def test_record_stores_both_complete_briefs(vouch):
    """P1-1/P1-9: the complete brief, not merely its hash."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    for segment in (outcome.record.investigator, outcome.record.verifier):
        assert segment.brief
        assert segment.brief["governing_basis"]["spec_id"] == "SPEC-A7"
        assert segment.brief["coverage"]
        assert segment.brief_hash
        assert segment.model_id and segment.prompt_version and segment.prompt_hash


def test_record_stores_tool_calls_with_results(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    events = outcome.record.investigator.tool_events
    assert events
    for event in events:
        assert event["tool"]
        assert event["authority_class"]
        assert "result_count" in event
        assert "elapsed_ms" in event


def test_record_stores_policy_capability_and_mutation(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    record = outcome.record

    assert record.policy.policy_version
    assert record.policy.gate_decision == "ALLOWED"
    assert record.capability.capability_id and record.capability.issued
    assert record.capability.consumed
    assert record.mutation.before_version == 1
    assert record.mutation.after_version == 2
    assert record.mutation.ledger_sequence
    assert record.mutation.inventory_delta == 500.0


def test_record_stores_consequences_and_recovery(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    consequences = outcome.record.consequences

    assert consequences.coverage_changes
    assert consequences.readiness_changes
    assert consequences.caused_by
    assert consequences.recovery
    assert consequences.recovery["candidates"]


def test_escalated_decisions_are_persisted_too(vouch, store):
    """The abstention is exactly the record an auditor will want."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])

    loaded = store.load(outcome.decision_record_id)
    assert loaded is not None
    assert loaded["disposition"]["disposition"] == "INSUFFICIENT_EVIDENCE"


def test_security_quarantine_is_persisted(vouch, store):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1004", documents=[{"raw": COA_HOSTILE}])

    loaded = store.load(outcome.decision_record_id)
    assert loaded["failure_category"] == "SECURITY_QUARANTINE"
    assert loaded["security"]["quarantined_artifact_ids"]


def test_disagreement_records_the_actual_differing_values(vouch):
    """P1-1/P1-9: 'they disagreed on basis' is unreviewable without values."""
    from vouch.v2.agents import AgentRun, IndependentVerifier
    from vouch.v2.contracts import (
        EvidenceApplicabilityBrief,
        GoverningBasis,
        RequiredTest,
        Sufficiency,
    )

    corpus, _ = vouch

    from vouch.v2.contracts import CoverageItem

    class DivergentSufficiency(IndependentVerifier):
        """Contract-valid and divergent.

        The basis is the governing one and the coverage is complete, so nothing
        here contradicts the corpus — the two briefs simply reach different
        sufficiency judgments. That is the disagreement the record must render
        with real values; a brief citing a superseded revision is refused
        earlier now, as its own named contract failure.
        """

        def run(self, **kwargs):
            by_test = {c.characteristic: c.claim_id for c in kwargs["claims"]}
            brief = EvidenceApplicabilityBrief(
                governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="C"),
                required_tests=[
                    RequiredTest(name="tensile_strength"),
                    RequiredTest(name="hardness"),
                ],
                coverage=[
                    CoverageItem(
                        test=name, evidence_ref=by_test.get(name), method_match=True
                    )
                    for name in ("tensile_strength", "hardness")
                ],
                sufficiency=Sufficiency.INSUFFICIENT_EVIDENCE,
            )
            return AgentRun(brief, "m", "v", "h", [], True)

    v = VouchV2(
        corpus, verifier=DivergentSufficiency(corpus), record_store=InMemoryRecordStore()
    )
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "MATERIAL_DISAGREEMENT"
    reconciliation = outcome.record.reconciliation
    assert "sufficiency" in reconciliation.differing_fields
    assert reconciliation.investigator_values["sufficiency"] == "SUFFICIENT"
    assert (
        reconciliation.verifier_values["sufficiency"] == "INSUFFICIENT_EVIDENCE"
    )


def test_record_reports_where_it_is_stored(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    storage = outcome.record.storage

    assert storage.record_store == "LOCAL_JSON"
    assert storage.evidence_store == "LOCAL_SIMULATION"
    assert storage.record_ref
    assert storage.event_count > 0


def test_in_memory_store_is_labeled_not_durable():
    assert InMemoryRecordStore.kind == "IN_MEMORY_NOT_DURABLE"
    assert "NOT DURABLE" in InMemoryRecordStore.__doc__


def test_record_store_rejects_path_traversal(store):
    from vouch.v2.contracts import VouchFailure

    with pytest.raises(VouchFailure):
        store.load("../../etc/passwd")


# ==========================================================================
# P1-2 — lifecycle events are durable, ordered and queryable
# ==========================================================================


def test_events_are_persisted_and_queryable_by_record(vouch, store, tmp_path):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    reopened = JsonRecordStore(tmp_path / "records")
    rows = reopened.events_for(outcome.decision_record_id)

    assert rows
    emitted = {row["event"] for row in rows}
    for required in REQUIRED_EVENTS:
        assert required.value in emitted, f"missing {required.value}"


def test_events_have_durable_ids_and_ordering(vouch, store):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    rows = store.events_for(outcome.decision_record_id)

    sequences = [row["sequence"] for row in rows]
    assert sequences == sorted(sequences)
    assert len(set(row["event_id"] for row in rows)) == len(rows)
    assert all(row["event_id"].startswith(outcome.decision_record_id) for row in rows)


def test_new_event_types_are_persisted(vouch, store):
    """The events added this iteration are part of the durable contract."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    emitted = {row["event"] for row in store.events_for(outcome.decision_record_id)}

    assert "READINESS_TRANSITIONED" in emitted
    assert "RECOVERY_EVALUATED" in emitted


def test_persisted_events_carry_no_chain_of_thought(vouch, store):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    blob = json.dumps(store.events_for(outcome.decision_record_id)).lower()

    for forbidden in ("chain_of_thought", "rationale", "raw_prompt", "reasoning"):
        assert forbidden not in blob


def test_quality_decision_event_is_persisted(vouch, store):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    emitted = {row["event"] for row in store.events_for(outcome.decision_record_id)}
    assert "QUALITY_DECISION_REQUIRED" in emitted


# ==========================================================================
# P1-8 — tool provenance
# ==========================================================================


def _tools(corpus, snapshot_claims=None, **kwargs):
    return CorpusTools(
        corpus, agent_name="investigator", lot_id="LOT-1001",
        material_id="MAT-ALLOY-7", snapshot_claims=snapshot_claims or [], **kwargs,
    )


def test_qualification_tool_returns_no_precomputed_verdict(vouch):
    """P1-8: deterministic policy performs the hard scope check itself."""
    corpus, _ = vouch
    result = _tools(corpus).get_supplier_qualification()

    assert "covers_this_lot" not in result
    assert result["found"] is True
    assert result["status"] == "QUALIFIED"
    assert "site_scope" in result  # scope as DATA
    assert result["authority_class"] == ToolAuthority.AUTHORITATIVE


def test_policy_still_enforces_qualification_scope(vouch):
    """Removing the hint must not weaken enforcement.

    A lot from a site outside the qualification's scope is still refused
    deterministically, with no help from the model.
    """
    from dataclasses import replace

    from vouch.v2.authority import PolicyEngine
    from vouch.v2.contracts import Disposition
    from vouch.v2.corpus import SupplierQualification
    from vouch.v2.lifecycle import EventLog

    corpus, v = vouch
    qualification = corpus.qualification("SUP-NORTH", "MAT-ALLOY-7")
    corpus.put(
        "supplier_qualification", "SUP-NORTH:MAT-ALLOY-7",
        replace(qualification, site_scope=("SITE-OTHER",)),
    )

    decision = v.policy.evaluate_lot_disposition(
        decision_record_id="DR-1", lot_id="LOT-1001",
        disposition=Disposition.RELEASE, reconciliation_ok=True,
        basis_checks_ok=True, observed_state_version=1, events=EventLog(),
    )
    assert not decision.allowed
    assert "does not cover site" in decision.reason


def test_spec_tool_returns_versioned_object_refs(vouch):
    corpus, _ = vouch
    rows = _tools(corpus).list_candidate_specs()

    assert rows
    for row in rows:
        assert row["object_ref"] == f"{row['spec_id']}:{row['revision']}"
        assert row["authority_class"] == ToolAuthority.AUTHORITATIVE
        assert "effective_to" in row  # the P1-4 field must reach the model
        assert "material_scope" in row


def test_requirement_and_scope_tools_carry_refs(vouch):
    corpus, _ = vouch
    tools = _tools(corpus)

    for row in tools.get_spec_requirement("SPEC-A7", "C"):
        assert row["object_ref"].startswith("SPEC-A7:C/")
        assert row["authority_class"] == ToolAuthority.AUTHORITATIVE
    for row in tools.list_applicable_deviations():
        assert row["object_ref"] == row["deviation_id"]
    for row in tools.list_equivalence_records():
        assert row["object_ref"] == row["equivalence_id"]


def test_claims_carry_source_hashes(vouch):
    """A claim the model sees must be traceable to the bytes it came from."""
    corpus, v = vouch
    claims, _ = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=COA_CLEAN,
        events=__import__("vouch.v2.lifecycle", fromlist=["EventLog"]).EventLog(),
    )
    rows = _tools(corpus, claims).get_evidence_snapshot()

    assert rows
    for row in rows:
        assert row["source_hash"]
        assert row["object_ref"] == row["claim_id"]
        assert row["authority_class"] == ToolAuthority.FROZEN_CLAIMS
