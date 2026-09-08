"""Change A — lifecycle events are observable WHILE a decision runs.

Before this, every event of a run was written in one batch at terminal exit
(`_persist`), so a frontend polling the store saw nothing until the decision was
already over. The lifecycle was durable but not *observable*: a UI could only
ever replay a finished case, never watch one.

`EventLog` already accepted `sinks` and no production caller passed any. Change A
wires one, so each event lands as it fires.

What these tests protect is the boundary of that change. It alters WHEN an event
is written, never WHAT: no new event type, no payload change, no influence on any
decision. Two properties carry the whole guarantee —

  * the terminal batch must not duplicate what the sink already wrote, and
  * a sink failure must never fail a decision.

The second is the one worth being strict about. Observability that can take down
authority is worse than no observability at all.
"""

from __future__ import annotations

import pytest

from vouch.v2.fixtures import COA_AMBIGUOUS, COA_CLEAN, COA_HERO, QA_RETEST, build_corpus
from vouch.v2.lifecycle import EventLog
from vouch.v2.persistence import InMemoryRecordStore, JsonRecordStore
from vouch.v2.workflow import VouchV2


def _seqs(store, record_id):
    return [row["sequence"] for row in store.events_for(record_id)]


def _identities(store, record_id):
    return [(row["event"], row["at"]) for row in store.events_for(record_id)]


@pytest.fixture
def workflow():
    store = InMemoryRecordStore()
    return VouchV2(build_corpus(), record_store=store), store


# ======================================================================
# the point of the change: visibility during the run
# ======================================================================


def test_events_are_written_before_the_decision_finishes(workflow):
    """The sink writes as events fire, not once at the end.

    Asserted by counting store writes rather than by timing: a single terminal
    batch is one call, so many calls proves incremental delivery.
    """
    vouch, store = workflow
    calls = []
    original = store.append_all
    store.append_all = lambda events, start=None: (calls.append(1), original(events, start))[1]

    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    rows = store.events_for(outcome.decision_record_id)
    assert len(rows) > 10, "the hero path emits a substantial lifecycle"
    # One call per event plus the terminal batch. A pre-change run would be 1.
    assert len(calls) > 10, "events were batched, not streamed"


def test_the_terminal_batch_does_not_duplicate_what_the_sink_wrote(workflow):
    """`_persist` still appends the whole log; that must be a no-op here.

    This is the regression the sink most easily causes: `event_id` is derived
    from the sequence, so a naive re-append lands at the next free slot with a
    new id and silently doubles the history.
    """
    vouch, store = workflow
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
    record_id = outcome.decision_record_id

    identities = _identities(store, record_id)
    assert len(identities) == len(set(identities)), "an event was stored twice"

    sequences = _seqs(store, record_id)
    assert sequences == list(range(1, len(sequences) + 1)), "sequence gaps or repeats"


def test_last_event_sequence_is_the_real_high_water_mark(workflow):
    """The frontend's cursor start. It must match what is actually stored."""
    vouch, store = workflow
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    stored = store.events_for(outcome.decision_record_id)
    assert outcome.record.storage.last_event_sequence == len(stored)


# ======================================================================
# the invariant that matters more than the feature
# ======================================================================


def test_a_failing_sink_does_not_fail_the_decision():
    """Observability must never be able to break authority.

    Only the LIVE sink writes fail here, not the terminal `_persist`. That
    separation is the point: a store that cannot persist at all must still fail
    closed (the F5 rule, and `_persist` raises `PERSISTENCE_FAILURE` by design),
    but losing the live feed is not a reason to lose the decision.
    """
    corpus = build_corpus()
    store = InMemoryRecordStore()
    vouch = VouchV2(corpus, record_store=store)

    calls = {"n": 0}
    original = store.append_all

    def only_the_sink_fails(events, start=None):
        calls["n"] += 1
        # `_persist` hands over the whole log at the end; the sink hands over
        # one event at a time. Break exactly the latter.
        if len(list(events)) == 1:
            raise RuntimeError("event feed is down")
        return original(events, start)

    store.append_all = only_the_sink_fails

    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    assert calls["n"] > 1, "the sink never ran, so nothing was proven"
    assert outcome.disposition == "QUARANTINE"
    assert corpus.lot("LOT-1002").status == "QUARANTINED"
    # The terminal write still recorded the full history despite the dead feed.
    assert len(store.events_for(outcome.decision_record_id)) > 10


def test_a_caller_supplied_log_is_left_unwired(workflow):
    """Tests and callers that pass their own log get exactly that log.

    Several existing tests assert on a bare `EventLog`; silently attaching a
    sink to it would change what they observe.
    """
    vouch, store = workflow
    events = EventLog()
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}], events=events)

    assert events._sinks == [], "a supplied log must not be re-wired"
    assert events.events, "the supplied log still collects the run"


# ======================================================================
# the change must not alter what an event IS
# ======================================================================


def test_the_sink_adds_no_event_type_and_no_payload_key(workflow):
    """WHEN changed; WHAT did not.

    The stored vocabulary must be exactly what the in-process log emitted.
    """
    vouch, store = workflow
    events = EventLog()
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}], events=events)

    # The supplied log is unwired, so persist it the way `_persist` does and
    # compare vocabularies.
    emitted = [event.event_type.value for event in events.events]
    stored = [row["event"] for row in store.events_for(outcome.decision_record_id)]
    assert stored == emitted

    for row, event in zip(store.events_for(outcome.decision_record_id), events.events):
        assert row["payload"] == event.payload


def test_no_stored_event_carries_reasoning(workflow):
    """`_FORBIDDEN_KEYS` guards emission; assert it also holds in storage."""
    vouch, store = workflow
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    forbidden = ("chain_of_thought", "reasoning", "rationale", "raw_prompt", "prompt_text")
    for row in store.events_for(outcome.decision_record_id):
        for key in row["payload"]:
            assert not any(bad in key.lower() for bad in forbidden)


# ======================================================================
# continuation — the case the sequence allocator gets wrong most easily
# ======================================================================


def test_a_resumed_case_extends_history_rather_than_colliding(tmp_path):
    """Run 2's events must append after run 1's, with no gap and no overwrite.

    Durable store on disk, because this is exactly where restarting sequence
    numbering at 1 silently swallowed continuation events (audit-2 F8).
    """
    store = JsonRecordStore(tmp_path / "records")
    vouch = VouchV2(build_corpus(), record_store=store)

    first = vouch.evaluate_lot("LOT-1005", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = first.decision_record_id
    run_one = _identities(store, record_id)
    assert first.quality_decision_required

    vouch.supply_human_evidence(
        decision_record_id=record_id,
        lot_id="LOT-1005",
        raw=QA_RETEST,
        authority_source="PLANT-QA-LAB",
    )

    after = _identities(store, record_id)
    assert after[: len(run_one)] == run_one, "run 1 history was rewritten"
    assert len(after) > len(run_one), "run 2 wrote nothing"

    sequences = _seqs(store, record_id)
    assert sequences == list(range(1, len(sequences) + 1))
    assert len(after) == len(set(after)), "an event was stored twice across runs"

    assert any(row["event"] == "DECISION_RESUMED" for row in store.events_for(record_id))


def test_replayed_evidence_adds_no_events(tmp_path):
    """Re-submitting identical evidence is idempotent, including in the feed."""
    store = JsonRecordStore(tmp_path / "records")
    vouch = VouchV2(build_corpus(), record_store=store)

    first = vouch.evaluate_lot("LOT-1005", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = first.decision_record_id
    vouch.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1005",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )
    settled = _identities(store, record_id)

    replay = vouch.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1005",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    assert "already attached" in replay.reason
    assert _identities(store, record_id) == settled, "a replay grew the event feed"
