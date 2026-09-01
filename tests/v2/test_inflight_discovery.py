"""A browser must be able to watch a decision it is still waiting on.

Invocation is synchronous. The record id used to be generated inside
`evaluate_lot` and returned only when the call finished, so a caller could not
poll the decision it was waiting for: by the time it learned the id, there was
nothing left to watch. Live progress would have had to be faked.

`evaluate_lot` had always accepted a `decision_record_id` — the resumed-case
path uses it — so the fix was plumbing, not semantics: let the caller name the
decision before starting it. The entrypoint was also passing its own `EventLog`,
which silently opted out of the sink that makes events visible during a run.

These tests slow the Investigator down to open a real polling window. That
touches call timing only; no prompt, judgment, or outcome changes.

The division of labour they pin down:

  get_events      LIVE   — readable while the decision runs
  get_decision    TERMINAL — the record document is written at exit
  list_decisions  TERMINAL — it lists persisted records

That split is correct rather than a limitation: a record is not authoritative
until the decision that produced it has settled. It is also exactly why the
caller-supplied id matters — it is the only thing that tells the browser what to
poll before a record exists.
"""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "app" / "Gatehouse" / "main.py"

SLOW_SECONDS = 2.0
MID_RUN = 0.6


@pytest.fixture(scope="module")
def runtime():
    import os

    previous = os.environ.get("VOUCH_MODE")
    os.environ["VOUCH_MODE"] = "local"
    staged = str(ROOT / "app" / "Gatehouse" / "src")
    for path in [p for p in sys.path if p == staged]:
        sys.path.remove(path)

    spec = importlib.util.spec_from_file_location("vouch_inflight_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module

    if previous is None:
        os.environ.pop("VOUCH_MODE", None)
    else:
        os.environ["VOUCH_MODE"] = previous


@pytest.fixture
def slow_investigator(runtime):
    """Open a polling window without altering what the Investigator decides."""
    original = runtime._VOUCH.investigator.run

    def delayed(*args, **kwargs):
        time.sleep(SLOW_SECONDS)
        return original(*args, **kwargs)

    runtime._VOUCH.investigator.run = delayed
    yield
    runtime._VOUCH.investigator.run = original


def _start(runtime, record_id, lot_id="LOT-1002"):
    from vouch.v2.fixtures import COA_HERO

    result = {}

    def run():
        result["outcome"] = runtime.invoke({
            "action": "evaluate_lot",
            "lot_id": lot_id,
            "document": COA_HERO.decode(),
            "decision_record_id": record_id,
        })

    thread = threading.Thread(target=run)
    thread.start()
    return thread, result


# ======================================================================
# the discovery path
# ======================================================================


def test_the_caller_can_name_the_decision_before_it_starts(runtime):
    """The id is known to the browser before any work begins."""
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1002",
        "document": _hero(), "decision_record_id": record_id,
    })

    assert outcome["ok"]
    assert outcome["decision_record_id"] == record_id


def _hero():
    from vouch.v2.fixtures import COA_HERO

    return COA_HERO.decode()


def test_a_generated_id_is_still_returned_when_none_is_supplied(runtime):
    """The existing contract is unchanged for callers that do not care."""
    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1001", "document": _clean(),
    })
    assert outcome["decision_record_id"].startswith("DR-")


def _clean():
    from vouch.v2.fixtures import COA_CLEAN

    return COA_CLEAN.decode()


def test_events_are_readable_while_the_evaluation_is_still_running(
    runtime, slow_investigator
):
    """The proof the whole live-polling contract rests on."""
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    thread, _ = _start(runtime, record_id)
    try:
        time.sleep(MID_RUN)

        # Assert liveness AT the moment of the read, not before or after it.
        alive = thread.is_alive()
        response = runtime.invoke({
            "action": "get_events", "decision_record_id": record_id, "after_sequence": 0,
        })

        assert alive, "the decision finished too fast to prove anything"
        assert response["events"], "no events were visible mid-run"
        assert response["last_event_sequence"] >= 1

        names = [row["event"] for row in response["events"]]
        assert "EVIDENCE_RECEIVED" in names
    finally:
        thread.join()


def test_a_cursor_advances_during_the_run(runtime, slow_investigator):
    """Polling must not re-deliver what the client already has."""
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    thread, _ = _start(runtime, record_id)
    try:
        time.sleep(MID_RUN)
        first = runtime.invoke({
            "action": "get_events", "decision_record_id": record_id, "after_sequence": 0,
        })
        assert first["events"]

        repeat = runtime.invoke({
            "action": "get_events", "decision_record_id": record_id,
            "after_sequence": first["last_event_sequence"],
        })
        # Whatever arrives next must be strictly newer than the cursor.
        for row in repeat["events"]:
            assert row["sequence"] > first["last_event_sequence"]
    finally:
        thread.join()


def test_mid_run_events_are_a_true_prefix_of_the_final_history(
    runtime, slow_investigator
):
    """Nothing observed live may be renumbered or rewritten by the terminal write."""
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    thread, _ = _start(runtime, record_id)
    try:
        time.sleep(MID_RUN)
        assert thread.is_alive()
        observed = runtime.invoke({
            "action": "get_events", "decision_record_id": record_id,
        })["events"]
        assert observed
    finally:
        thread.join()

    final = runtime.invoke({
        "action": "get_events", "decision_record_id": record_id,
    })["events"]

    assert [row["event_id"] for row in observed] == [
        row["event_id"] for row in final[: len(observed)]
    ]
    sequences = [row["sequence"] for row in final]
    assert sequences == list(range(1, len(final) + 1)), "final history is not gapless"
    assert len({row["event_id"] for row in final}) == len(final), "duplicate events"


def test_the_supplied_id_survives_to_completion(runtime, slow_investigator):
    """The id the caller chose is the id the durable record ends up under.

    Deliberately asserts identity rather than disposition. These tests share one
    corpus, and LOT-1002 is already QUARANTINED by the time this runs — so a
    second quarantine is refused as an illegal QUARANTINED -> QUARANTINED
    transition. That refusal is the authority model working, not a failure, and
    an earlier version of this test asserted the disposition and failed because
    of it.
    """
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    thread, result = _start(runtime, record_id)
    thread.join()

    outcome = result["outcome"]
    assert outcome["decision_record_id"] == record_id

    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": record_id
    })["record"]
    assert record["record_id"] == record_id
    assert record["identity"]["lot_id"] == "LOT-1002"


# ======================================================================
# what is deliberately NOT live
# ======================================================================


def test_the_record_projection_is_terminal_not_in_flight(runtime, slow_investigator):
    """`get_decision` answers only once the decision has settled.

    A half-written record is not an authoritative projection, and returning one
    would let a UI render a disposition that no gate had authorized yet. The
    typed failure is the honest answer; the live feed is `get_events`.
    """
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    thread, _ = _start(runtime, record_id)
    try:
        time.sleep(MID_RUN)
        alive = thread.is_alive()
        response = runtime.invoke({
            "action": "get_decision", "decision_record_id": record_id,
        })
        assert alive
        assert response["ok"] is False
        assert response["failure_category"] == "PERSISTENCE_FAILURE"
    finally:
        thread.join()

    settled = runtime.invoke({"action": "get_decision", "decision_record_id": record_id})
    assert settled["ok"] is True


def test_listing_shows_the_decision_only_once_it_has_settled(
    runtime, slow_investigator
):
    """`list_decisions` lists persisted records, so an in-flight run is absent.

    This is why the caller-supplied id matters: discovery cannot come from the
    list, so it has to come from the caller.
    """
    record_id = f"DR-{uuid.uuid4().hex[:12]}"
    thread, _ = _start(runtime, record_id)
    try:
        time.sleep(MID_RUN)
        alive = thread.is_alive()
        rows = runtime.invoke({"action": "list_decisions"})["rows"]
        assert alive
        assert not any(row["decision_record_id"] == record_id for row in rows)
    finally:
        thread.join()

    rows = runtime.invoke({"action": "list_decisions"})["rows"]
    assert any(row["decision_record_id"] == record_id for row in rows)


# ======================================================================
# the authoritative join
# ======================================================================


def test_incoming_rows_carry_display_names_not_just_ids(runtime):
    """Resolved server-side so no client reimplements the lookup.

    A browser joining ids to names would need the corpus, and a client that got
    it wrong would render a name the plant does not use.
    """
    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1002", "document": _hero(),
    })
    rows = runtime.invoke({"action": "list_decisions"})["rows"]
    row = next(r for r in rows if r["decision_record_id"] == outcome["decision_record_id"])

    assert row["material_id"] == "MAT-ALLOY-7"
    assert row["material_name"] == "Alloy 7 billet"
    assert row["supplier_id"] == "SUP-EAST"
    assert row["supplier_name"] == "Eastern Metals"
    assert row["supplier_site"] == "SITE-E1"


def test_a_missing_name_is_empty_rather_than_an_id_in_disguise(runtime):
    """An unresolvable name must not silently render as its identifier."""
    row = runtime._incoming_row({"record_id": "DR-x", "lot_id": "LOT-does-not-exist"})

    assert row["material_name"] == ""
    assert row["supplier_name"] == ""
    assert row["material_id"] == ""
