"""The film-reset acceptance sequence, end to end.

One test walking the nine acceptance criteria in order, because the ordering IS
the claim: execute -> record exists -> reset -> only LOT-1006 moved -> the old
record survives -> execute again -> a NEW record, with everything else still
where it was.
"""

from __future__ import annotations

from vouch.v2.demo_reset import reset_lot
from vouch.v2.fixtures import COA_DISPUTED, build_corpus
from vouch.v2.persistence import InMemoryRecordStore
from vouch.v2.workflow import VouchV2

#: Everything a reset must NOT touch.
UNRELATED_LOTS = ("LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004", "LOT-1005", "LOT-8001")
UNRELATED_ORDERS = ("C-417", "C-418")


def _snapshot(corpus) -> dict:
    return {
        "lots": {k: corpus.get("lot", k) for k in UNRELATED_LOTS},
        "inventory": {k: corpus.get("inventory", k) for k in UNRELATED_LOTS},
        "orders": {k: corpus.get("production_order", k) for k in UNRELATED_ORDERS},
        "slots": {
            p.order_id: p.planned_slot for p in corpus.all("production_order")
        },
    }


def test_the_full_film_reset_acceptance_sequence():
    corpus = build_corpus()
    v = VouchV2(corpus, record_store=InMemoryRecordStore())

    # Canonical pre-decision state, and what must survive untouched.
    assert corpus.get("lot", "LOT-1006").status == "RECEIVED"
    assert corpus.get("production_order", "C-419").status == "AT_RISK"
    untouched = _snapshot(corpus)

    # (1) execute LOT-1006 to a terminal state
    first = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
    assert first.failure_category or first.disposition

    # (2) a prior DecisionRecord exists
    first_id = first.decision_record_id
    assert v.record_store.load(first_id) is not None
    before_reset = v.record_store.load(first_id)

    # (3) press Shift+R -> the bounded server-side reset
    result = reset_lot(corpus, "LOT-1006")

    # (4) only LOT-1006 returns to canonical pre-decision state
    assert corpus.get("lot", "LOT-1006").status == "RECEIVED"
    assert corpus.get("inventory", "LOT-1006").usable is False
    assert result["lot_status"] == "RECEIVED"

    # (5) C-419 returns to canonical pre-decision readiness
    assert corpus.get("production_order", "C-419").status == "AT_RISK"
    assert corpus.get("planned_coverage", "PC-2") is not None

    # (6) the prior DecisionRecord still exists, unmodified
    after_reset = v.record_store.load(first_id)
    assert after_reset is not None, "the reset deleted history"
    assert after_reset == before_reset, "the reset rewrote history"

    # (7)+(8) execute again -> a fresh evaluation, a NEW record
    second = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
    assert second.decision_record_id != first_id
    assert second.failure_category or second.disposition
    # Both readable: the ledger grew rather than being overwritten.
    assert v.record_store.load(first_id) is not None
    assert v.record_store.load(second.decision_record_id) is not None

    # (9) no other canonical lot or state changed across the whole sequence
    now = _snapshot(corpus)
    assert now["lots"] == untouched["lots"]
    assert now["inventory"] == untouched["inventory"]
    assert now["orders"] == untouched["orders"]
    assert now["slots"] == untouched["slots"]


def test_a_reset_between_takes_leaves_a_growing_ledger():
    """Filming means several takes. Each one is its own historical decision."""
    corpus = build_corpus()
    v = VouchV2(corpus, record_store=InMemoryRecordStore())

    ids = []
    for _ in range(3):
        outcome = v.evaluate_lot("LOT-1006", documents=[{"raw": COA_DISPUTED}])
        ids.append(outcome.decision_record_id)
        reset_lot(corpus, "LOT-1006")

    assert len(set(ids)) == 3, "takes reused a record id"
    for record_id in ids:
        assert v.record_store.load(record_id) is not None, record_id
