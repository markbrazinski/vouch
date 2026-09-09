"""The production day, pinned frame by frame.

Today is the surface where an incoming-material decision becomes a schedule
change, and every number on it is load-bearing: the shortage an operator reads,
the order that moves, the candidates that were refused and why. None of it is
asserted anywhere else, so a fixture edit could rewrite the demo's meaning
without failing a single test.

The causal shape this pins, and it is easy to get backwards:

  * LOT-1001 RELEASE is the event with TWO consequences. It covers C-418
    outright (500 of 500) AND exposes that C-417 needs 900 against 500 usable.
    So C-417 blocks and a materially-ready alternative appears in one instant,
    which is what makes the recovery safe rather than convenient.

  * LOT-1002 QUARANTINE changes NO arithmetic. A quarantined lot was never
    usable inventory, so quarantine subtracts nothing. Its consequence is that
    the remaining incoming material cannot close C-417's gap — a quality fact,
    not an inventory one. Copy that says quarantine "removed 400 kg" is false
    and this file exists partly to keep it false-able.
"""

from __future__ import annotations

import pytest

from vouch.v2.consequences import Readiness, compute_readiness, enumerate_recovery
from vouch.v2.fixtures import COA_CLEAN, COA_HERO, build_corpus
from vouch.v2.workflow import VouchV2


@pytest.fixture
def world():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


def _verdicts(recovery: dict) -> dict[str, tuple[str, str]]:
    return {
        c["candidate_id"]: (c["verdict"], c["reason_code"])
        for c in recovery["candidates"]
    }


# ==========================================================================
# FRAME A — the opening plan
# ==========================================================================


def test_frame_a_plan_says_ready_while_vouch_says_blocked(world):
    """The distinction the UI must show, and must not collapse.

    C-417 is the planned order — the plan genuinely says READY. Vouch says
    BLOCKED because no ALLOY-7 has been released yet. Both are true, and
    showing only one of them is what makes the opening frame a lie.
    """
    corpus, _ = world
    assert corpus.order("C-417").status == "READY"
    assert compute_readiness(corpus, "C-417").readiness is Readiness.BLOCKED


def test_frame_a_no_incoming_material_counts_as_usable(world):
    """Pending lots are not inventory. 1550 kg exists; 0 kg is usable."""
    corpus, _ = world
    on_hand = sum(
        corpus.get("inventory", lot).quantity
        for lot in ("LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004")
    )
    assert on_hand == 1550.0
    assert corpus.usable_inventory("MAT-ALLOY-7") == 0


def test_frame_a_both_alloy_orders_are_short(world):
    corpus, _ = world
    for order_id, required in (("C-417", 900.0), ("C-418", 500.0)):
        line = compute_readiness(corpus, order_id).coverage[0]
        assert (line.material_id, line.required, line.available) == (
            "MAT-ALLOY-7", required, 0
        )
        assert line.short_by == required


# ==========================================================================
# FRAME B — LOT-1001 releases: one event, two consequences
# ==========================================================================


def test_frame_b_release_makes_exactly_five_hundred_usable(world):
    corpus, vouch = world
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert outcome.disposition == "RELEASE"
    assert corpus.lot("LOT-1001").status == "RELEASED"
    assert corpus.usable_inventory("MAT-ALLOY-7") == 500.0


def test_frame_b_c418_is_covered_outright_by_the_released_lot(world):
    """500 of 500. This is why moving C-418 risks nothing."""
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    line = compute_readiness(corpus, "C-418").coverage[0]
    assert (line.required, line.available, line.short_by) == (500.0, 500.0, 0.0)
    assert compute_readiness(corpus, "C-418").readiness is Readiness.READY


def test_frame_b_the_same_release_exposes_c417s_real_shortfall(world):
    """C-417 needs 900. Releasing 500 does not cover it and never could.

    The transition is the plan catching up to a readiness Vouch already
    reported at Frame A — not the clean lot damaging anything.
    """
    corpus, vouch = world
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    change = next(
        c for c in outcome.consequences["readiness_changes"] if c["order_id"] == "C-417"
    )
    assert (change["from"], change["to"]) == ("READY", "BLOCKED")
    assert change["persisted"] is True
    line = compute_readiness(corpus, "C-417").coverage[0]
    assert (line.required, line.available, line.short_by) == (900.0, 500.0, 400.0)


def test_frame_b_recovery_selects_c418_because_its_material_is_released(world):
    """Every candidate, with the reason it was refused or chosen."""
    corpus, vouch = world
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    recovery = outcome.consequences["recovery"]

    assert recovery["blocked_order_id"] == "C-417"
    assert _verdicts(recovery) == {
        # 500 usable against 900 required.
        "MAT-ALLOY-7": ("NOT_FEASIBLE", "INSUFFICIENT_QUANTITY"),
        # Stock exists (900 kg). Authority does not. Availability is not
        # permission, and collapsing these two would hide the safety story.
        "MAT-SUB-9": ("REFUSED", "NOT_APPROVED"),
        # The one lawful move: materials fully released, same line, slot free.
        "C-418": ("ELIGIBLE", "FEASIBLE"),
        # Materially ready, but LINE-2 cannot run a LINE-1 slot.
        "C-419": ("NOT_FEASIBLE", "RESOURCE_INCOMPATIBLE"),
    }
    selected = recovery["selected"]
    assert selected["candidate_id"] == "C-418"
    assert selected["facts"]["materials_ready"] is True
    assert selected["facts"]["slot_free"] is True


def test_frame_b_c418_actually_moves_into_the_vacated_slot(world):
    corpus, vouch = world
    assert corpus.order("C-418").planned_slot == "2026-08-15T14:00"

    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    recovery = outcome.consequences["recovery"]

    assert recovery["executed"] is True
    assert recovery["mutation"]["action"] == "resequence_production_order"
    assert corpus.order("C-418").planned_slot == "2026-08-15T08:00"


# ==========================================================================
# FRAME C — LOT-1002 quarantines: a quality fact, not an inventory one
# ==========================================================================


def test_frame_c_quarantine_removes_no_usable_inventory(world):
    """The assertion behind the copy rule.

    If this ever fails, "LOT-1002 removed 400 kg" became true and the Today
    wording has to change with it. Until then that sentence is false.
    """
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    before = corpus.usable_inventory("MAT-ALLOY-7")

    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    assert outcome.disposition == "QUARANTINE"
    assert corpus.lot("LOT-1002").status == "QUARANTINED"
    assert corpus.usable_inventory("MAT-ALLOY-7") == before == 500.0
    assert corpus.get("inventory", "LOT-1002").usable is False


def test_frame_c_quarantine_causes_no_readiness_transition(world):
    """Already BLOCKED and persisted, so there is nothing to re-transition."""
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
    assert outcome.consequences["readiness_changes"] == []
    assert corpus.order("C-417").status == "BLOCKED"


def test_frame_c_c417_remains_short_by_exactly_four_hundred(world):
    """The number the Today banner is allowed to say."""
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    assert compute_readiness(corpus, "C-417").coverage[0].short_by == 400.0


# ==========================================================================
# FRAME D — the day, after
# ==========================================================================


def test_frame_d_the_final_plan_is_the_whole_story(world):
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    # The blocked order stayed blocked, and did not move.
    assert corpus.order("C-417").status == "BLOCKED"
    assert corpus.order("C-417").planned_slot == "2026-08-15T08:00"
    # The safe alternative ran in its place.
    assert corpus.order("C-418").planned_slot == "2026-08-15T08:00"
    assert compute_readiness(corpus, "C-418").readiness is Readiness.READY
    # The untouched line is untouched.
    assert corpus.order("C-419").planned_slot == "2026-08-15T09:00"
    # Two lots decided, two lots still awaiting evidence.
    assert corpus.lot("LOT-1001").status == "RELEASED"
    assert corpus.lot("LOT-1002").status == "QUARANTINED"
    assert corpus.lot("LOT-1003").status == "RECEIVED"
    assert corpus.lot("LOT-1004").status == "RECEIVED"


def test_frame_d_the_quarantine_triggers_no_second_resequence(world):
    """The schedule moves once, on the release. Nothing moves on the quarantine.

    Re-enumerating afterwards still reports C-418 ELIGIBLE, because it is
    already sitting in the target slot and "move it there" is trivially
    satisfiable. That is a harmless artefact of scoring an already-recovered
    plan, and it is pinned here so nobody reads it as a second recovery: what
    matters is that LOT-1002's decision executed no mutation at all.
    """
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    assert (outcome.consequences.get("recovery") or {}).get("executed") is not True
    assert corpus.order("C-418").planned_slot == "2026-08-15T08:00"
    assert corpus.order("C-418").state_version == 2  # moved once, by the release


# ==========================================================================
# durable-store shapes
# ==========================================================================


def test_causal_history_sorts_when_the_store_returns_mixed_number_types():
    """DynamoDB round-trips numbers as Decimal or str; memory keeps ints.

    Sorting that mixed list raised `TypeError: '<' not supported between
    instances of 'int' and 'str'`, and because the sort happens while BUILDING
    the payload it took the entire Today read down — a 400 on the surface the
    demo opens on. Every local test passed, because the in-memory store only
    ever produces ints, so this pins the coercion directly.
    """
    import importlib.util
    import os
    from decimal import Decimal
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    os.environ["VOUCH_MODE"] = "local"
    spec = importlib.util.spec_from_file_location(
        "vouch_today_sort_entrypoint", root / "app" / "Gatehouse" / "main.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    key = runtime.ledger_sequence_of

    rows = [
        {"kind": "quarantine", "ledger_sequence": None},
        {"kind": "resequence", "ledger_sequence": "3"},
        {"kind": "readiness", "ledger_sequence": 2},
        {"kind": "extra", "ledger_sequence": Decimal("4")},
        {"kind": "unparseable", "ledger_sequence": "not-a-number"},
    ]
    rows.sort(key=key)

    # Every shape the stores actually produce is orderable together.
    assert [row["kind"] for row in rows[-3:]] == ["readiness", "resequence", "extra"]
    # Neither a missing nor an unparseable sequence raises.
    assert key({}) == 0.0
    assert key({"ledger_sequence": "not-a-number"}) == 0.0
