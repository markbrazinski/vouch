"""The dev/film LOT reset.

What these tests actually protect: a reset must roll back OPERATING STATE for
one scenario and leave the audit ledger and every other scenario alone. Those
are two different stores and a reset that confuses them would either lose
history or corrupt the canonical demo.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from vouch.v2.demo_reset import NotResettable, RESETTABLE, reset_lot
from vouch.v2.fixtures import COA_DISPUTED, build_corpus
from vouch.v2.persistence import InMemoryRecordStore
from vouch.v2.workflow import VouchV2


@pytest.fixture
def corpus():
    return build_corpus()


@pytest.fixture
def vouch(corpus):
    return corpus, VouchV2(corpus, record_store=InMemoryRecordStore())


# ==========================================================================
# the whitelist IS the security boundary
# ==========================================================================


def test_only_whitelisted_lots_can_be_reset(corpus):
    for lot_id in ("LOT-1001", "LOT-1002", "LOT-1005", "LOT-1007", "C-417"):
        with pytest.raises(NotResettable):
            reset_lot(corpus, lot_id)


def test_an_arbitrary_identifier_is_refused(corpus):
    """This is the property that lets a dev route expose it at all: a caller
    cannot name an object and have it rewritten."""
    for hostile in ("", "*", "lot", "LOT-9999", "../../etc/passwd"):
        with pytest.raises(NotResettable):
            reset_lot(corpus, hostile)


def test_the_whitelist_names_only_rows_the_scenario_owns():
    # C-417 and C-418 belong to the alloy recovery story. A reset that touched
    # them would silently rewrite a different demo.
    owned = {key for rows in RESETTABLE.values() for _, key in rows}
    assert "C-417" not in owned
    assert "C-418" not in owned


# ==========================================================================
# what a reset restores
# ==========================================================================


def _advance(corpus, kind, key, **changes):
    """Mutate a row the way the workflow does: new value, version bumped."""
    current = corpus.get(kind, key)
    # Not every row is versioned (InventoryRecord is not), which is why
    # `reset_lot` guards on the attribute rather than assuming it.
    if hasattr(current, "state_version"):
        changes["state_version"] = current.state_version + 1
    corpus.put(kind, key, replace(current, **changes))


def test_reset_restores_lot_1006_to_pre_decision_state(corpus):
    _advance(corpus, "lot", "LOT-1003", status="RELEASED")
    _advance(corpus, "inventory", "LOT-1003", usable=True)
    _advance(corpus, "production_order", "C-419", status="READY")

    result = reset_lot(corpus, "LOT-1003")

    assert corpus.get("lot", "LOT-1003").status == "RECEIVED"
    assert corpus.get("inventory", "LOT-1003").usable is False
    assert corpus.get("production_order", "C-419").status == "AT_RISK"
    assert result["lot_status"] == "RECEIVED"
    assert result["inventory_usable"] is False
    assert result["readiness"]["C-419"] == "AT_RISK"


def test_reset_restores_the_planned_coverage_row(corpus):
    """PC-2 is what makes C-419 read AT_RISK rather than BLOCKED. Without it
    the reset would restore a DIFFERENT canonical state than the fixture."""
    canonical = corpus.get("planned_coverage", "PC-2")
    corpus.put("planned_coverage", "PC-2", None)

    reset_lot(corpus, "LOT-1003")

    restored = corpus.get("planned_coverage", "PC-2")
    assert restored is not None
    assert restored.lot_id == canonical.lot_id
    assert restored.quantity == canonical.quantity


def test_reset_is_idempotent(corpus):
    first = reset_lot(corpus, "LOT-1003")
    second = reset_lot(corpus, "LOT-1003")
    assert first["lot_status"] == second["lot_status"] == "RECEIVED"
    assert corpus.get("production_order", "C-419").status == "AT_RISK"


# ==========================================================================
# state_version must ADVANCE, never rewind
# ==========================================================================


def test_state_version_advances_rather_than_rewinding(corpus):
    """A capability binds to an observed state_version and refuses when it
    moves. Rewinding to 1 would re-validate a capability issued before the
    reset, which is exactly the replay the authority model exists to stop."""
    _advance(corpus, "lot", "LOT-1003", status="RELEASED")  # -> version 2
    before = corpus.get("lot", "LOT-1003").state_version

    reset_lot(corpus, "LOT-1003")

    after = corpus.get("lot", "LOT-1003").state_version
    assert after > before
    assert corpus.get("lot", "LOT-1003").status == "RECEIVED"


def test_repeated_resets_keep_advancing(corpus):
    versions = []
    for _ in range(3):
        reset_lot(corpus, "LOT-1003")
        versions.append(corpus.get("lot", "LOT-1003").state_version)
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)


# ==========================================================================
# nothing else moves
# ==========================================================================


def test_reset_leaves_every_other_canonical_lot_alone(corpus):
    others = ["LOT-1001", "LOT-1002", "LOT-1004", "LOT-1005", "LOT-1007", "LOT-8001"]
    before = {k: corpus.get("lot", k) for k in others}
    inv_before = {k: corpus.get("inventory", k) for k in others}

    reset_lot(corpus, "LOT-1003")

    for k in others:
        assert corpus.get("lot", k) == before[k], k
        assert corpus.get("inventory", k) == inv_before[k], k


def test_reset_leaves_c417_and_c418_alone(corpus):
    before = {
        k: corpus.get("production_order", k) for k in ("C-417", "C-418")
    }
    reset_lot(corpus, "LOT-1003")
    for k, was in before.items():
        assert corpus.get("production_order", k) == was, k


def test_reset_does_not_touch_unrelated_schedule_or_inventory(corpus):
    before = {p.order_id: p.planned_slot for p in corpus.all("production_order")}
    reset_lot(corpus, "LOT-1003")
    after = {p.order_id: p.planned_slot for p in corpus.all("production_order")}
    assert after == before


# ==========================================================================
# THE critical rule: a reset is not history deletion
# ==========================================================================


def test_previous_decision_records_survive_a_reset(vouch):
    """The acceptance criterion that matters most. A demo reset rolls back the
    plant, never the ledger."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_DISPUTED}])
    record_id = outcome.decision_record_id
    assert v.record_store.load(record_id) is not None

    reset_lot(corpus, "LOT-1003")

    stored = v.record_store.load(record_id)
    assert stored is not None, "a reset deleted a DecisionRecord"
    assert stored.get("record_id") == record_id


def test_the_old_record_is_not_rewritten_to_look_tidy(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_DISPUTED}])
    before = v.record_store.load(outcome.decision_record_id)

    reset_lot(corpus, "LOT-1003")

    after = v.record_store.load(outcome.decision_record_id)
    assert after == before, "a reset mutated an existing decision record"


def test_a_fresh_evaluation_after_reset_creates_a_new_record(vouch):
    corpus, v = vouch
    first = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_DISPUTED}])
    reset_lot(corpus, "LOT-1003")
    second = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_DISPUTED}])

    assert second.decision_record_id != first.decision_record_id
    # Both remain readable: the ledger grew, it did not get overwritten.
    assert v.record_store.load(first.decision_record_id) is not None
    assert v.record_store.load(second.decision_record_id) is not None


def test_the_lot_can_actually_be_evaluated_again(vouch):
    """A reset that left the lot un-evaluatable would be useless for filming."""
    corpus, v = vouch
    v.evaluate_lot("LOT-1003", documents=[{"raw": COA_DISPUTED}])
    reset_lot(corpus, "LOT-1003")

    again = v.evaluate_lot("LOT-1003", documents=[{"raw": COA_DISPUTED}])
    assert again.decision_record_id
    assert again.failure_category or again.disposition
