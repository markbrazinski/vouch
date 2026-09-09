"""The production day, pinned frame by frame.

Today is the surface where an incoming-material decision becomes a schedule
change, and every number on it is load-bearing: the shortage an operator reads,
the order that moves, the candidates that were refused and why. None of it is
asserted anywhere else, so a fixture edit could rewrite the demo's meaning
without failing a single test.

The causal shape this pins, and it is easy to get backwards:

  * At seed NOTHING has been decided, so all three orders read
    AWAITING_QUALITY. Their material is allocated and sitting in receiving.
    This is a PRE-DECISION state and deliberately not AT_RISK or BLOCKED:
    before Vouch evaluates anything there is no negative finding to report,
    and rendering one made an untouched plant look like a failing one.

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

import inspect

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


def test_frame_a_plan_says_ready_while_vouch_awaits_quality(world):
    """The distinction the UI must show, and must not collapse.

    C-417's plan genuinely says READY. Vouch says AWAITING_QUALITY: the alloy
    it needs is sitting in receiving, allocated, and undecided.

    This test previously asserted BLOCKED, and that was the semantic bug. No
    evidence had been evaluated at seed time, so BLOCKED reported a negative
    judgement nobody had made and rendered an untouched factory as a failing
    one. "Not yet decided" is its own state.
    """
    corpus, _ = world
    assert corpus.order("C-417").status == "READY"
    assert compute_readiness(corpus, "C-417").readiness is Readiness.AWAITING_QUALITY


def test_frame_a_awaiting_quality_is_not_a_negative_verdict(world):
    """Every canonical order is pre-decision at seed, and none reads as failed."""
    corpus, _ = world
    for order_id in ("C-417", "C-418", "C-419"):
        readiness = compute_readiness(corpus, order_id).readiness
        assert readiness is Readiness.AWAITING_QUALITY, order_id
        assert readiness not in (Readiness.AT_RISK, Readiness.BLOCKED), order_id


def test_frame_a_a_decided_lot_ends_the_pre_decision_state(world):
    """AWAITING_QUALITY is strictly pre-decision.

    Quarantine LOT-1002 and C-417 must stop reading as merely pending: part of
    its shortfall is now an evaluated fact. Without this the new state could
    mask a real negative, which is the one thing it must never do.
    """
    from dataclasses import replace

    corpus, _ = world
    corpus.put(
        "lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status="QUARANTINED")
    )
    assert compute_readiness(corpus, "C-417").readiness is not Readiness.AWAITING_QUALITY


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


def test_frame_c_c418_is_not_feasible_until_lot_1001_releases(world):
    """The negative half of the recovery story, and the one that bit us.

    Evaluating LOT-1002 against a freshly seeded corpus — LOT-1001 still
    RECEIVED — makes C-418 truthfully NOT_FEASIBLE: its 500 kg requirement is
    covered by exactly that lot, and nothing has released it yet. The UI
    rendering "C-418 MATERIALS NOT RELEASED" was therefore reporting the
    backend correctly; the demo path was skipping the release.

    Pinned so nobody "fixes" the symptom by seeding LOT-1001 as RELEASED and
    quietly deleting the S1 beat that earns the recovery.
    """
    _corpus, vouch = world
    outcome = vouch.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
    recovery = outcome.consequences["recovery"]

    assert _verdicts(recovery)["C-418"] == ("NOT_FEASIBLE", "MATERIALS_NOT_RELEASED")
    assert recovery["selected"] is None
    assert recovery["executed"] is not True


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


def _row_state(
    lot_status: str,
    disposition: str = "",
    failure: str = "",
    *,
    lot_version: int = 1,
    observed_version: int | None = None,
) -> str:
    """`_incoming_row`'s state derivation, against a real runtime import.

    `observed_version` is the lot version the RECORD froze against. Leaving it
    equal to `lot_version` (the default) models a current record; making them
    differ models a record a reset has since superseded, which is the only
    thing that distinguishes a live finding from a rolled-back one.
    """
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
        "lot", "LOT-1001",
        type(lot)(**{
            **lot.__dict__, "status": lot_status, "state_version": lot_version,
        }),
    )
    row = runtime._incoming_row(
        {
            "record_id": "DR-x",
            "lot_id": "LOT-1001",
            "disposition": disposition,
            "failure_category": failure,
            "lot_state_version": (
                lot_version if observed_version is None else observed_version
            ),
            "saved_at": "2026-09-09T00:00:00+00:00",
        }
    )
    return row["row_state"]


def test_a_reset_lot_is_awaiting_disposition_again():
    """The demo reset has to LOOK like a reset.

    Every lot returns to RECEIVED, so Incoming must show all of them awaiting
    disposition whatever a previous run concluded about them.

    The reset is modelled the way both real reset paths mark it: the live lot
    no longer carries the version the record froze against. A full reseed
    returns the version to 1, and Shift+R advances it past whatever the store
    held — opposite directions, same signal.
    """
    # Both reset paths ADVANCE the version past what the store held, so the
    # live lot is ahead of whatever the record observed.
    reseeded = dict(lot_version=5, observed_version=4)
    assert _row_state("RECEIVED", disposition="RELEASE", **reseeded) == (
        "EVIDENCE_RECEIVED"
    )
    assert _row_state("RECEIVED", disposition="QUARANTINE", **reseeded) == (
        "EVIDENCE_RECEIVED"
    )
    # Shift+R marks it the same way, one lot at a time.
    advanced = dict(lot_version=7, observed_version=4)
    assert _row_state("RECEIVED", failure="MATERIAL_DISAGREEMENT", **advanced) == (
        "EVIDENCE_RECEIVED"
    )


def test_a_stale_policy_refusal_does_not_survive_a_reset():
    """`POLICY_REFUSAL` describes a past ATTEMPT, not the evidence.

    The authority gate refusing to re-release an already-released lot is
    correct, and it is recorded. But once the lot is back at RECEIVED that
    refusal describes a world that no longer exists — it left a freshly
    reseeded LOT-1001 asking for a quality decision nobody owed it, which is
    exactly the row an operator would open first.
    """
    assert _row_state(
        "RECEIVED", disposition="RELEASE", failure="POLICY_REFUSAL",
        lot_version=4, observed_version=3,
    ) == "EVIDENCE_RECEIVED"


def test_an_evidence_level_failure_still_asks_for_a_human():
    """The narrowing must not swallow failures that are still true.

    A security quarantine is a fact about the ARTIFACT and survives any reset of
    the lot, so it must keep its row state — otherwise this fix would hide the
    hostile document.
    """
    # CURRENT records — the versions agree, so nothing has been rolled back.
    assert _row_state("RECEIVED", failure="SECURITY_QUARANTINE") == "SECURITY_HOLD"
    assert _row_state("RECEIVED", failure="EVIDENCE_UNBOUND") == (
        "QUALITY_DECISION_REQUIRED"
    )
    # And the same findings AFTER a reset describe a world that no longer
    # exists. This is the pre-renumber gate's defect: every evidence-level halt
    # leaves the lot at RECEIVED, so lot status alone could never clear them.
    assert _row_state(
        "RECEIVED", failure="SECURITY_QUARANTINE", lot_version=3, observed_version=2
    ) == "EVIDENCE_RECEIVED"
    assert _row_state(
        "RECEIVED", failure="EVIDENCE_UNBOUND", lot_version=3, observed_version=2
    ) == "EVIDENCE_RECEIVED"


def test_a_halt_before_the_snapshot_still_clears_on_reset():
    """A security quarantine never observes a lot version.

    The artifact is refused before extraction, so the decision halts ahead of
    the snapshot freeze and records `lot_state_version` 0 permanently. Treating
    0 as "unknown, keep the finding" pinned LOT-1004 to SECURITY_HOLD through
    every reseed — the defect the pre-renumber gate found.

    Version 0 means "this run stopped before it looked at the lot". Every
    fixture lot starts at version 1, so a live lot ABOVE 1 has been written
    since, which for a RECEIVED lot only a reset does.
    """
    # Pristine, never reset: the hostile document must still ask for attention.
    assert _row_state(
        "RECEIVED", failure="SECURITY_QUARANTINE", lot_version=1, observed_version=0
    ) == "SECURITY_HOLD"
    # After any reset the lot has been rewritten, so the finding is superseded.
    assert _row_state(
        "RECEIVED", failure="SECURITY_QUARANTINE", lot_version=2, observed_version=0
    ) == "EVIDENCE_RECEIVED"


def test_a_record_ahead_of_the_lot_is_not_treated_as_a_reset():
    """Strictly BEHIND, not merely different.

    A record observing a version AHEAD of the live lot is not a reset; it is a
    store that has lost writes. Clearing a real finding there would hide a
    genuine problem behind a routine-looking row.
    """
    assert _row_state(
        "RECEIVED", failure="SECURITY_QUARANTINE", lot_version=2, observed_version=5
    ) == "SECURITY_HOLD"


# ==========================================================================
# planned coverage — the allocation itself
# ==========================================================================


def _contribution(corpus, lot_id: str, order_id: str = "C-417",
                  material_id: str = "MAT-ALLOY-7") -> float:
    """How much ONE lot currently contributes to an order's planned coverage.

    Isolates a single allocation from the order total so these tests assert the
    lot-status rule they are named for, rather than the fixture's allocation
    count.
    """
    with_lot = corpus.planned_coverage(order_id, material_id)
    without = sum(
        row.quantity
        for row in corpus.planned_coverage_rows(order_id, material_id)
        if row.lot_id != lot_id
        and getattr(corpus.lot(row.lot_id), "status", None)
        in corpus.COVERABLE_LOT_STATES
    )
    return round(with_lot - without, 6)


def test_coverage_is_never_inferred_from_a_shared_material(world):
    """The whole reason PlannedCoverage exists.

    LOT-1003 (450 kg) and LOT-1004 (200 kg) are MAT-ALLOY-7 and undecided. If
    "undecided material of the same type exists" counted as coverage, C-417
    would stay AT_RISK behind 650 kg nobody planned to use for it, and the Hero
    A transition would never happen. Only an explicit row counts.
    """
    corpus, _ = world
    rows = corpus.planned_coverage_rows("C-417", "MAT-ALLOY-7")
    # The invariant is the ABSENCE of the unallocated lots, asserted directly.
    # This used to pin the exact row list, which coupled it to how many
    # allocations the fixture happened to hold and broke the moment LOT-1001's
    # genuine allocation was recorded — without any inference having crept in.
    assert {r.lot_id for r in rows} == {"LOT-1002", "LOT-1001"}
    assert not {"LOT-1003", "LOT-1004"} & {r.lot_id for r in rows}
    # C-418 is allocated LOT-1001 and nothing else; the 650 kg of unallocated
    # MAT-ALLOY-7 still contributes nothing to it.
    assert [r.lot_id for r in corpus.planned_coverage_rows("C-418", "MAT-ALLOY-7")] == [
        "LOT-1001"
    ]

    # C-419 has an EXPLICIT row (PC-2, LOT-1006), which is the point rather
    # than a counterexample: its 200 kg counts because someone allocated that
    # named lot to that order. LOT-1005 is also MAT-RESIN-3 and also undecided,
    # and contributes nothing — sharing a material is still not coverage.
    resin_rows = corpus.planned_coverage_rows("C-419", "MAT-RESIN-3")
    assert [r.lot_id for r in resin_rows] == ["LOT-1006"]
    assert corpus.planned_coverage("C-419", "MAT-RESIN-3") == 200.0
    assert "LOT-1005" not in [r.lot_id for r in resin_rows]


def test_a_queued_lot_counts_while_it_can_still_be_released(world):
    """RECEIVED and PENDING_QA are both "not usable yet, still possible"."""
    from dataclasses import replace

    corpus, _ = world
    # Measured as LOT-1002's own contribution — the total also carries
    # LOT-1001's separately-allocated 500 kg, which this test is not about.
    for status in ("RECEIVED", "PENDING_QA"):
        corpus.put("lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status=status))
        assert _contribution(corpus, "LOT-1002") == 400.0, status


def test_a_refused_lot_stops_counting(world):
    """A quarantined or rejected lot cannot honour an allocation."""
    from dataclasses import replace

    corpus, _ = world
    for status in ("QUARANTINED", "REJECTED"):
        corpus.put("lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status=status))
        assert _contribution(corpus, "LOT-1002") == 0.0, status


def test_a_released_lot_is_not_counted_twice(world):
    """Once released it is usable inventory, and counting it here would double it."""
    from dataclasses import replace

    corpus, _ = world
    corpus.put("lot", "LOT-1002", replace(corpus.lot("LOT-1002"), status="RELEASED"))
    assert _contribution(corpus, "LOT-1002") == 0.0


def test_the_opening_frame_states_the_real_shortfall(world):
    """Pre-decision does not mean the numbers are softened.

    C-417 still shows 0 kg available against a 900 kg requirement. What changed
    is only the LABEL on that fact: 900 kg is queued across LOT-1001 and
    LOT-1002, neither decided, so nothing is uncovered by a *plan* — the
    question is entirely open. The arithmetic is reported unflatteringly and in
    full; it is simply not called a failure before anyone has looked.
    """
    corpus, _ = world
    line = compute_readiness(corpus, "C-417").coverage[0]
    assert (line.required, line.available, line.short_by) == (900.0, 0, 900.0)
    assert (line.planned, line.uncovered) == (900.0, 0.0)
    assert compute_readiness(corpus, "C-417").readiness is Readiness.AWAITING_QUALITY


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


def test_a_durable_release_records_the_quantity_it_made_usable():
    """The durable ledger's inventory delta comes from the INVENTORY ROW.

    A release is authorized with `parameters={}` — the lot's quantity is not
    the caller's to choose, so there is nothing to sign — and the durable path
    read the delta from those bound parameters, yielding 0.0 on every real
    release. The record showed inventory moving False -> True with a delta of
    zero, and the causal copy had to describe a release that moved nothing.
    Local runs compute the delta from the row and were correct, so no test saw
    it; this one pins the durable branch specifically.

    A source assertion, deliberately, and its limits are real: it proves the
    delta is no longer taken from `bound`, not that the transaction behaves.
    Exercising the true path needs a live table (see the VOUCH_LIVE_AWS suite),
    and a mock rebuilt around this branch would only assert the mock.
    """
    import inspect as _inspect

    from vouch.v2.aws import DynamoCapabilityStore

    source = _inspect.getsource(DynamoCapabilityStore)
    assert "inventory_delta = quantity if usable else -quantity" in source
    assert 'inventory_delta = float(bound.get("quantity"' not in source
