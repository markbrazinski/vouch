"""audit-2 F8 — a case survives the process that created it.

The Iteration 2 audit found `supply_human_evidence` reading only
`self.records`, so a persisted DecisionRecord could never be continued:
destroying the process destroyed the case. Claims, capabilities, corpus state
and the ledger were all process-local, and event numbering restarted at 1 so
continuation events collided with run 1's sort keys and were silently swallowed
as duplicates.

These tests destroy every workflow object and construct a NEW instance over the
SAME durable stores, then continue the case. Durability is modeled by:

  * `JsonRecordStore` on a tmp_path — genuinely on disk, genuinely survives
    the objects that wrote it;
  * a corpus and capability store handed to both instances, which is what the
    single DynamoDB table is in production.

The point is that nothing carries over inside the workflow instance. The
`del` calls are load-bearing: they are the restart.
"""

from __future__ import annotations

import gc

import pytest

from vouch.v2.authority import CapabilityStore
from vouch.v2.evidence import LocalEvidenceStore
from vouch.v2.fixtures import COA_AMBIGUOUS, COA_CLEAN, QA_RETEST, build_corpus
from vouch.v2.persistence import JsonRecordStore
from vouch.v2.workflow import VouchV2


@pytest.fixture
def durable(tmp_path):
    """Stores that outlive any workflow instance built over them."""
    return {
        "corpus": build_corpus(),
        "capabilities": CapabilityStore(),
        "evidence_store": LocalEvidenceStore(),
        "record_store": JsonRecordStore(tmp_path / "records"),
    }


def _workflow(durable) -> VouchV2:
    return VouchV2(
        durable["corpus"],
        evidence_store=durable["evidence_store"],
        capabilities=durable["capabilities"],
        record_store=durable["record_store"],
    )


def test_a_case_resumes_after_the_process_is_destroyed(durable):
    """F8, the full regression the commission specifies.

    Run an insufficient-evidence case, destroy all workflow objects, construct
    a new instance over the same durable stores, add human evidence.
    """
    first = _workflow(durable)
    initial = first.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = initial.decision_record_id
    assert initial.quality_decision_required
    assert initial.record.run_count == 1

    events_before = durable["record_store"].events_for(record_id)
    assert events_before, "the first run must have persisted events"
    prior_evidence = list(initial.record.evidence.source_artifact_hashes)
    prior_sequences = [row["sequence"] for row in events_before]
    lot_version_before = durable["corpus"].version_of("lot", "LOT-1003")

    # -- the restart ---------------------------------------------------
    del initial
    del first
    gc.collect()

    resumed = _workflow(durable)
    assert resumed.records == {}, "a new instance must start with no cached case"

    outcome = resumed.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1003",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    # same DecisionRecord id
    assert outcome.decision_record_id == record_id
    # incremented run count
    assert outcome.record.run_count == 2
    # prior evidence remains
    for digest in prior_evidence:
        assert digest in outcome.record.evidence.source_artifact_hashes
    # new evidence is appended
    assert len(outcome.record.evidence.source_artifact_hashes) > len(prior_evidence)
    assert outcome.record.human.content_hashes
    # continuous prior and new events: the new run EXTENDS the sequence
    events_after = durable["record_store"].events_for(record_id)
    sequences = [row["sequence"] for row in events_after]
    assert sequences == list(range(1, len(sequences) + 1)), "event numbering must be gapless"
    assert len(sequences) > len(prior_sequences), "continuation events were dropped"
    assert sequences[: len(prior_sequences)] == prior_sequences, "history was overwritten"
    # correct CURRENT lot version was used, and the mutation happened once
    assert outcome.disposition == "RELEASE"
    assert durable["corpus"].lot("LOT-1003").status == "RELEASED"
    assert durable["corpus"].version_of("lot", "LOT-1003") == lot_version_before + 1
    releases = [
        entry for entry in durable["capabilities"].ledger
        if entry["action"] == "release_lot" and entry["target_id"] == "LOT-1003"
    ]
    assert len(releases) == 1, "the final mutation must occur exactly once"


def test_a_restart_after_the_mutation_cannot_replay_it(durable):
    """F8: restart after mutation cannot replay the capability or the delta."""
    first = _workflow(durable)
    initial = first.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = initial.decision_record_id
    resolved = first.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1003",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )
    assert resolved.disposition == "RELEASE"

    capability_id = resolved.record.capability.capability_id
    version_after = durable["corpus"].version_of("lot", "LOT-1003")
    inventory_after = durable["corpus"].get("inventory", "LOT-1003").usable
    ledger_after = len(durable["capabilities"].ledger)

    del resolved
    del initial
    del first
    gc.collect()

    # A new process re-presents the SAME evidence for the SAME case.
    resumed = _workflow(durable)
    replay = resumed.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1003",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    assert "already attached" in replay.reason
    assert replay.record.run_count == 2, "a replay must not open a third run"
    assert durable["corpus"].version_of("lot", "LOT-1003") == version_after
    assert durable["corpus"].get("inventory", "LOT-1003").usable is inventory_after
    assert len(durable["capabilities"].ledger) == ledger_after

    # The spent capability is still spent, from any process.
    stored = durable["capabilities"].get(capability_id)
    assert stored is not None and stored.used


def test_a_resumed_record_carries_its_claims(durable):
    """F8: claims are part of the durable record, not process state."""
    first = _workflow(durable)
    initial = first.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = initial.decision_record_id
    claim_ids = [c.claim_id for c in first.claims[record_id]]
    assert claim_ids

    del initial, first
    gc.collect()

    resumed = _workflow(durable)
    record = resumed.resume(record_id)
    assert record is not None
    assert [c.claim_id for c in resumed.claims[record_id]] == claim_ids


def test_resuming_an_unknown_record_is_a_typed_failure(durable):
    """F8: a case that does not exist is a typed refusal, not a fresh case."""
    from vouch.v2.contracts import FailureCategory, VouchFailure

    workflow = _workflow(durable)
    assert workflow.resume("DR-does-not-exist") is None
    with pytest.raises(VouchFailure) as caught:
        workflow.supply_human_evidence(
            decision_record_id="DR-does-not-exist", lot_id="LOT-1003",
            raw=QA_RETEST, authority_source="PLANT-QA-LAB",
        )
    assert caught.value.category is FailureCategory.PERSISTENCE_FAILURE


def test_evaluate_lot_on_an_existing_record_id_continues_it(durable):
    """F8: re-entering a case must not erase its prior runs."""
    first = _workflow(durable)
    initial = first.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = initial.decision_record_id
    first.records[record_id].rerun()
    first._persist(first.records[record_id], __import__(
        "vouch.v2.lifecycle", fromlist=["EventLog"]
    ).EventLog())
    assert first.records[record_id].run_count == 2

    del initial, first
    gc.collect()

    resumed = _workflow(durable)
    again = resumed.evaluate_lot("LOT-1003", decision_record_id=record_id)
    assert again.record.run_count == 2, "prior runs were erased by a fresh record"


def test_event_sequence_continues_rather_than_restarting(durable):
    """F8: the exact defect — restarting at 1 silently dropped continuations."""
    store = durable["record_store"]
    first = _workflow(durable)
    outcome = first.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    record_id = outcome.decision_record_id
    first_run = store.events_for(record_id)
    assert first_run

    assert store.next_sequence(record_id) == first_run[-1]["sequence"] + 1

    del outcome, first
    gc.collect()

    # A second batch of events for the same record must extend, not collide.
    from vouch.v2.lifecycle import EventLog, EventType

    log = EventLog()
    log.emit(EventType.QUALITY_DECISION_REQUIRED, record_id, reason="ABSTAIN")
    appended = store.append_all(log.events)
    assert appended == 1

    after = store.events_for(record_id)
    assert len(after) == len(first_run) + 1
    assert [row["sequence"] for row in after] == list(range(1, len(after) + 1))
