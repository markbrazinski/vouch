"""The read surface a frontend needs, and the two defects it exposed.

The backend was an invocation API: it could run a decision and hand back the
result, but nothing could ask it what decisions exist, re-read one, or fetch the
events it had not seen yet. Those reads existed as library calls and were wired
to nothing.

Two of them were also wrong in ways that only a reader would notice.

`events_for` returned everything or nothing, so a polling client re-read the
whole history on every tick — and it ignored `LastEvaluatedKey`, so a case with
more than 1MB of events returned a truncated history that looked complete. For
an audit read that is the worst possible shape: not an error, just quietly less
than the truth.

`list_ids` raised on purpose, because the single-table layout keys records by
`RECORD#<id>` and offers no way to enumerate them. That is what the
decisions-by-recency index is for.

The Dynamo tests here drive a fake client rather than AWS: what needs proving is
the QUERY SHAPE — that the cursor becomes a key range and that pagination is
followed — and a fake shows that more precisely than a live table would.
"""

from __future__ import annotations

import json

import pytest

from vouch.v2.contracts import VouchFailure
from vouch.v2.fixtures import COA_HERO, build_corpus
from vouch.v2.persistence import DynamoRecordStore, InMemoryRecordStore, JsonRecordStore
from vouch.v2.workflow import VouchV2


# ======================================================================
# cursor semantics — the same contract in every store
# ======================================================================


@pytest.fixture(params=["memory", "json"])
def store(request, tmp_path):
    if request.param == "memory":
        return InMemoryRecordStore()
    return JsonRecordStore(tmp_path / "records")


@pytest.fixture
def decided(store):
    vouch = VouchV2(build_corpus(), record_store=store)
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
    return store, outcome.decision_record_id


def test_a_cursor_returns_only_what_has_not_been_seen(decided):
    store, record_id = decided
    everything = store.events_for(record_id)
    assert len(everything) > 5

    tail = store.events_for(record_id, after_sequence=len(everything) - 3)
    assert [row["sequence"] for row in tail] == [
        len(everything) - 2, len(everything) - 1, len(everything),
    ]


def test_polling_at_the_high_water_mark_returns_nothing(decided):
    """What stops a poll loop from re-reading history forever."""
    store, record_id = decided
    everything = store.events_for(record_id)
    assert store.events_for(record_id, after_sequence=len(everything)) == []


def test_a_zero_cursor_is_the_whole_history(decided):
    store, record_id = decided
    assert store.events_for(record_id, after_sequence=0) == store.events_for(record_id)


def test_limit_takes_the_oldest_unseen_events_first(decided):
    """Ascending order matters: a rail replays chronology, then reverses it."""
    store, record_id = decided
    page = store.events_for(record_id, after_sequence=0, limit=5)
    assert [row["sequence"] for row in page] == [1, 2, 3, 4, 5]


def test_events_are_ascending_and_gapless(decided):
    store, record_id = decided
    sequences = [row["sequence"] for row in store.events_for(record_id)]
    assert sequences == list(range(1, len(sequences) + 1))


# ======================================================================
# the Dynamo query shape
# ======================================================================


class FakeDynamo:
    """Records the requests made, and replays scripted pages back."""

    def __init__(self, pages):
        self.pages = list(pages)
        self.requests = []

    def query(self, **request):
        self.requests.append(request)
        return self.pages.pop(0) if self.pages else {"Items": []}


def _event_item(sequence, record_id="DR-x"):
    return {
        "sk": {"S": f"EVENT#{sequence:06d}"},
        "event_id": {"S": f"{record_id}#{sequence:06d}"},
        "event": {"S": "TOOL_CALLED"},
        "at": {"S": "2026-01-01T00:00:00+00:00"},
        "payload": {"S": json.dumps({"tool": "get_spec_requirement"})},
    }


def _dynamo(pages):
    store = DynamoRecordStore.__new__(DynamoRecordStore)
    store.table = "test-table"
    store._region = None
    store._ddb = FakeDynamo(pages)
    return store


def test_the_cursor_becomes_a_sort_key_range():
    """`after_sequence` must be pushed into the query, not filtered after it.

    Filtering in Python would still be correct and would still read the whole
    history on every poll, which is the cost the cursor exists to avoid.
    """
    store = _dynamo([{"Items": [_event_item(7)]}])
    store.events_for("DR-x", after_sequence=6)

    request = store._ddb.requests[0]
    assert request["KeyConditionExpression"] == "pk = :pk AND sk > :after"
    assert request["ExpressionAttributeValues"][":after"] == {"S": "EVENT#000006"}


def test_pagination_is_followed_to_the_end():
    """A truncated history that looks complete is the defect being fixed."""
    store = _dynamo([
        {"Items": [_event_item(1), _event_item(2)], "LastEvaluatedKey": {"sk": {"S": "EVENT#000002"}}},
        {"Items": [_event_item(3)]},
    ])

    rows = store.events_for("DR-x")

    assert [row["sequence"] for row in rows] == [1, 2, 3]
    assert len(store._ddb.requests) == 2
    assert store._ddb.requests[1]["ExclusiveStartKey"] == {"sk": {"S": "EVENT#000002"}}


def test_non_event_rows_are_never_returned_as_events():
    """`sk > EVENT#...` also admits keys that sort after the EVENT# range."""
    store = _dynamo([{"Items": [_event_item(1), {"sk": {"S": "META"}}]}])
    assert [row["sequence"] for row in store.events_for("DR-x")] == [1]


# ======================================================================
# decision enumeration
# ======================================================================


def test_listing_decisions_queries_the_index_newest_first():
    store = _dynamo([{
        "Items": [{
            "record_id": {"S": "DR-2"},
            "lot_id": {"S": "LOT-1002"},
            "disposition": {"S": "QUARANTINE"},
            "saved_at": {"S": "2026-01-02T00:00:00+00:00"},
        }],
    }])

    rows, cursor = store.list_decisions(limit=10)

    request = store._ddb.requests[0]
    assert request["IndexName"] == DynamoRecordStore.DECISION_INDEX
    assert request["ScanIndexForward"] is False, "Incoming reads newest first"
    assert request["ExpressionAttributeValues"][":entity"] == {
        "S": DynamoRecordStore.DECISION_ENTITY
    }
    assert rows[0]["record_id"] == "DR-2"
    assert rows[0]["disposition"] == "QUARANTINE"
    assert cursor is None


def test_listing_returns_a_cursor_when_more_remain():
    store = _dynamo([{
        "Items": [{"record_id": {"S": "DR-1"}}],
        "LastEvaluatedKey": {"pk": {"S": "RECORD#DR-1"}},
    }])
    _, cursor = store.list_decisions(limit=1)
    assert cursor == {"pk": {"S": "RECORD#DR-1"}}


def test_a_failed_listing_is_a_typed_failure():
    """An unreachable index must not look like an empty factory."""

    class Broken(FakeDynamo):
        def query(self, **request):
            raise RuntimeError("index not found")

    store = DynamoRecordStore.__new__(DynamoRecordStore)
    store.table = "test-table"
    store._region = None
    store._ddb = Broken([])

    with pytest.raises(VouchFailure):
        store.list_decisions()


def test_saving_stamps_the_index_partition_key():
    """Without it a record is invisible to the index that enumerates it."""

    class Recorder:
        def __init__(self):
            self.item = None

        def put_item(self, **request):
            self.item = request["Item"]

    from vouch.v2.decision_record import DecisionRecord

    store = DynamoRecordStore.__new__(DynamoRecordStore)
    store.table = "test-table"
    store._region = None
    store._ddb = Recorder()

    store.save(DecisionRecord(record_id="DR-x"))

    assert store._ddb.item["entity"] == {"S": DynamoRecordStore.DECISION_ENTITY}
    assert store._ddb.item["saved_at"]["S"], "the index sorts on saved_at"
