"""The production day, pinned frame by frame.

Today is the surface where an incoming-material decision becomes a schedule
change, and every number on it is load-bearing: the shortage an operator reads,
the order that moves, the candidates that were refused and why. None of it is
asserted anywhere else, so a fixture edit could rewrite the demo's meaning
without failing a single test.

The causal shape this pins, and it is easy to get backwards:

  * LOT-1001 RELEASE covers C-418 outright (500 of 500) and brings C-417 to
    500 released + 400 queued against a 900 requirement — fully coverable ON
    PLAN, so AT_RISK rather than BLOCKED. The plan has not failed; it depends
    on a named lot that has not been decided yet.

  * LOT-1002 QUARANTINE is what makes it fail. The 400 kg queued against C-417
    came from that specific lot, and a quarantined lot can no longer honour an
    allocation, so the requirement becomes genuinely uncoverable and C-417
    transitions AT_RISK -> BLOCKED. Recovery runs on THAT transition.

    It still removes no usable inventory — a quarantined lot was never usable —
    so copy saying quarantine "took away 400 kg" remains false. What it removed
    was a PLAN, and this file exists partly to keep those two distinguishable.

  * LOT-1003 and LOT-1004 hold 650 kg of the same material and have no
    allocation row, so they correctly do not rescue C-417. Coverage is never
    inferred from a shared material_id.
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


def test_frame_b_c417_becomes_coverable_on_plan_not_blocked(world):
    """500 released + 400 queued against 900 required is AT_RISK, not BLOCKED.

    Calling this BLOCKED asserted something Vouch had not established: a named
    lot was still queued to close the gap and had not been decided. It also
    made the one clean decision of the day read as the thing that broke the
    schedule.
    """
    corpus, vouch = world
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    change = next(
        c for c in outcome.consequences["readiness_changes"] if c["order_id"] == "C-417"
    )
    assert (change["from"], change["to"]) == ("READY", "AT_RISK")
    assert change["persisted"] is True

    line = compute_readiness(corpus, "C-417").coverage[0]
    assert (line.required, line.available, line.planned) == (900.0, 500.0, 400.0)
    # Nothing is unaccounted for: 500 in stock plus 400 on the way.
    assert line.uncovered == 0.0
    # Still genuinely short of RELEASED material, which is a different fact.
    assert line.short_by == 400.0


def test_frame_b_no_recovery_runs_while_the_plan_still_holds(world):
    """An AT_RISK order is not a blocked one. Nothing is rescheduled yet."""
    _corpus, vouch = world
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert (outcome.consequences.get("recovery") or {}).get("executed") is not True


def test_frame_c_recovery_selects_c418_because_its_material_is_released(world):
    """Every candidate, with the reason it was refused or chosen."""
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
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


def test_frame_c_c418_actually_moves_into_the_vacated_slot(world):
    corpus, vouch = world
    assert corpus.order("C-418").planned_slot == "2026-08-15T14:00"

    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
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


def test_frame_c_the_quarantine_is_what_blocks_the_order(world):
    """The causal beat: a refused lot cannot honour its allocation.

    LOT-1002 was the named source for C-417's remaining 400 kg. Quarantining it
    does not remove usable inventory — there was none to remove — it removes the
    PLAN, and that is what makes the requirement uncoverable.
    """
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    change = next(
        c for c in outcome.consequences["readiness_changes"] if c["order_id"] == "C-417"
    )
    assert (change["from"], change["to"]) == ("AT_RISK", "BLOCKED")
    assert corpus.order("C-417").status == "BLOCKED"

    line = compute_readiness(corpus, "C-417").coverage[0]
    assert line.planned == 0.0, "a quarantined lot cannot honour an allocation"
    assert line.uncovered == 400.0


def test_frame_c_the_other_alloy_lots_do_not_rescue_c417(world):
    """LOT-1003 + LOT-1004 hold 650 kg of MAT-ALLOY-7 and no allocation row.

    Inferring coverage from a shared material_id would leave C-417 permanently
    AT_RISK behind material nobody planned to use for it, and the Hero A
    transition would never happen.
    """
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    undecided = sum(
        corpus.get("inventory", lot).quantity for lot in ("LOT-1003", "LOT-1004")
    )
    assert undecided == 650.0 > 400.0
    assert corpus.planned_coverage("C-417", "MAT-ALLOY-7") == 0.0
    assert compute_readiness(corpus, "C-417").readiness is Readiness.BLOCKED


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


def test_frame_d_the_schedule_moves_exactly_once(world):
    """One resequence, on the quarantine that caused the block."""
    corpus, vouch = world
    vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])

    assert corpus.order("C-418").planned_slot == "2026-08-15T08:00"
    assert corpus.order("C-418").state_version == 2


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


# ==========================================================================
# Incoming after a reset
# ==========================================================================


def _row_state(lot_status: str, disposition: str = "", failure: str = "") -> str:
    """`_incoming_row`'s state derivation, against a real runtime import."""
    import importlib.util
    import os
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    os.environ["VOUCH_MODE"] = "local"
    spec = importlib.util.spec_from_file_location(
        "vouch_incoming_row_entrypoint", root / "app" / "Gatehouse" / "main.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)

    lot = runtime._CORPUS.lot("LOT-1001")
    runtime._CORPUS.put(
        "lot", "LOT-1001", type(lot)(**{**lot.__dict__, "status": lot_status})
    )
    row = runtime._incoming_row(
        {
            "record_id": "DR-x",
            "lot_id": "LOT-1001",
            "disposition": disposition,
            "failure_category": failure,
            "saved_at": "2026-09-09T00:00:00+00:00",
        }
    )
    return row["row_state"]


def test_a_reset_lot_is_awaiting_disposition_again():
    """The demo reset has to LOOK like a reset.

    Every lot returns to RECEIVED, so Incoming must show all of them awaiting
    disposition whatever a previous run concluded about them.
    """
    assert _row_state("RECEIVED", disposition="RELEASE") == "EVIDENCE_RECEIVED"
    assert _row_state("RECEIVED", disposition="QUARANTINE") == "EVIDENCE_RECEIVED"


def test_a_stale_policy_refusal_does_not_survive_a_reset():
    """`POLICY_REFUSAL` describes a past ATTEMPT, not the evidence.

    The authority gate refusing to re-release an already-released lot is
    correct, and it is recorded. But once the lot is back at RECEIVED that
    refusal describes a world that no longer exists — it left a freshly
    reseeded LOT-1001 asking for a quality decision nobody owed it, which is
    exactly the row an operator would open first.
    """
    assert _row_state("RECEIVED", disposition="RELEASE", failure="POLICY_REFUSAL") == (
        "EVIDENCE_RECEIVED"
    )


def test_an_evidence_level_failure_still_asks_for_a_human():
    """The narrowing must not swallow failures that are still true.

    A security quarantine is a fact about the ARTIFACT and survives any reset of
    the lot, so it must keep its row state — otherwise this fix would hide the
    hostile document.
    """
    assert _row_state("RECEIVED", failure="SECURITY_QUARANTINE") == "SECURITY_HOLD"
    assert _row_state("RECEIVED", failure="EVIDENCE_UNBOUND") == (
        "QUALITY_DECISION_REQUIRED"
    )


# ==========================================================================
# planned coverage — the allocation itself
# ==========================================================================


def test_coverage_is_never_inferred_from_a_shared_material(world):
    """The whole reason PlannedCoverage exists.

    LOT-1003 (450 kg) and LOT-1004 (200 kg) are MAT-ALLOY-7 and undecided. If
    "undecided material of the same type exists" counted as coverage, C-417
    would stay AT_RISK behind 650 kg nobody planned to use for it, and the Hero
    A transition would never happen. Only an explicit row counts.
    """
    corpus, _ = world
    rows = corpus.planned_coverage_rows("C-417", "MAT-ALLOY-7")
    assert [r.lot_id for r in rows] == ["LOT-1002"]
    assert corpus.planned_coverage("C-418", "MAT-ALLOY-7") == 0.0
    assert corpus.planned_coverage("C-419", "MAT-RESIN-3") == 0.0


def test_a_queued_lot_counts_while_it_can_still_be_released(world):
    """RECEIVED and PENDING_QA are both "not usable yet, still possible"."""
    from dataclasses import replace

    corpus, _ = world
    for status in ("RECEIVED", "PENDING_QA"):
        corpus.put("lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status=status))
        assert corpus.planned_coverage("C-417", "MAT-ALLOY-7") == 400.0, status


def test_a_refused_lot_stops_counting(world):
    """A quarantined or rejected lot cannot honour an allocation."""
    from dataclasses import replace

    corpus, _ = world
    for status in ("QUARANTINED", "REJECTED"):
        corpus.put("lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status=status))
        assert corpus.planned_coverage("C-417", "MAT-ALLOY-7") == 0.0, status


def test_a_released_lot_is_not_counted_twice(world):
    """Once released it is usable inventory, and counting it here would double it."""
    from dataclasses import replace

    corpus, _ = world
    corpus.put("lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status="RELEASED"))
    assert corpus.planned_coverage("C-417", "MAT-ALLOY-7") == 0.0


def test_the_opening_frame_is_not_softened_by_the_allocation(world):
    """0 released + 400 queued against 900 required is still short 500.

    AT_RISK would be a lie here: the plan does not add up even if LOT-1002
    releases perfectly.
    """
    corpus, _ = world
    line = compute_readiness(corpus, "C-417").coverage[0]
    assert (line.available, line.planned, line.uncovered) == (0, 400.0, 500.0)
    assert compute_readiness(corpus, "C-417").readiness is Readiness.BLOCKED


def test_deferred_terminal_hold_policy_is_recorded_not_implemented():
    """A queued lot on a terminal HOLD still counts. Deliberately, for now.

    EVIDENCE_UNBOUND and SECURITY_QUARANTINE both leave the lot at RECEIVED, so
    an allocation against such a lot keeps counting as queued coverage even
    though its evidence cannot currently be relied upon.

    That is a real gap and it is documented on `Corpus.COVERABLE_LOT_STATES`
    rather than fixed, because nothing exercises it: neither LOT-1003 nor
    LOT-1004 has an allocation row. This test exists so the gap is visible and
    so closing it is a deliberate edit rather than a silent behaviour change.
    """
    corpus = build_corpus()
    # No canonical lot in a hold state carries an allocation, so the gap is
    # unreachable in this world.
    holdable = {"LOT-1003", "LOT-1004"}
    allocated = {row.lot_id for row in corpus.all("planned_coverage")}
    assert not (allocated & holdable)

    # And the current rule is exactly as documented: RECEIVED still counts.
    assert "RECEIVED" in corpus.COVERABLE_LOT_STATES
    assert "QUARANTINED" not in corpus.COVERABLE_LOT_STATES
