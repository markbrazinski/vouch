"""The five read actions the frontend needs from the runtime.

The entrypoint could run a decision and hand back its result, but nothing could
ask it what exists, re-read a record, or fetch the events a caller had not seen.
These five close that, and they are strictly additive: `evaluate_lot`,
`supply_evidence`, `readiness`, `recovery` and `ledger` are untouched.

The property worth the most scrutiny is that a read changes nothing. An action
that read the factory and altered it while doing so would make the authority
ledger an incomplete account of what happened — the ledger would be missing a
change that really occurred. So the side-effect test compares whole objects
rather than a status field, and re-enters each action several times, because a
side effect that only appears on the second call is exactly the kind that ships.

The entrypoint is loaded by path in LOCAL mode. It resolves `vouch` from
`app/Gatehouse/src` when that staged copy exists, so these tests only mean
something if the staged copy is current — which is why one of them asserts it.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "app" / "Gatehouse" / "main.py"


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    """The real entrypoint module, composed against local fixtures."""
    import os

    previous = os.environ.get("VOUCH_MODE")
    os.environ["VOUCH_MODE"] = "local"
    # The staged copy shadows src/ on sys.path; drop it so the module under test
    # is the canonical source rather than whatever was last packaged.
    staged = str(ROOT / "app" / "Gatehouse" / "src")
    removed = [p for p in sys.path if p == staged]
    for path in removed:
        sys.path.remove(path)

    spec = importlib.util.spec_from_file_location("vouch_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    yield module

    if previous is None:
        os.environ.pop("VOUCH_MODE", None)
    else:
        os.environ["VOUCH_MODE"] = previous


@pytest.fixture
def hero(runtime):
    """A settled QUARANTINE decision — Hero A's shape."""
    from vouch.v2.fixtures import COA_HERO

    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1002",
        "document": COA_HERO.decode(),
    })
    assert outcome["ok"], outcome
    return runtime, outcome["decision_record_id"]


# ======================================================================
# the invariant: a read changes nothing
# ======================================================================


def _world(runtime, record_id):
    """Everything a read could plausibly disturb, compared whole."""
    corpus, vouch = runtime._CORPUS, runtime._VOUCH
    return {
        "lots": {lot.lot_id: asdict(lot) for lot in corpus.all("lot")},
        "orders": {o.order_id: asdict(o) for o in corpus.all("production_order")},
        "inventory": {i.lot_id: asdict(i) for i in corpus.all("inventory")},
        "record": copy.deepcopy(vouch.record_store.load(record_id)),
        "events": copy.deepcopy(vouch.record_store.events_for(record_id)),
        "ledger": copy.deepcopy(vouch.capabilities.ledger),
        "record_ids": sorted(vouch.record_store.list_ids()),
    }


def test_no_read_action_changes_anything(hero):
    runtime, record_id = hero
    reads = [
        {"action": "list_decisions"},
        {"action": "get_decision", "decision_record_id": record_id},
        {"action": "get_events", "decision_record_id": record_id},
        {"action": "get_events", "decision_record_id": record_id, "after_sequence": 5, "limit": 3},
        {"action": "get_source", "decision_record_id": record_id},
        {"action": "get_today"},
    ]

    before = _world(runtime, record_id)
    for _ in range(3):  # a side effect that only appears on re-entry still counts
        for request in reads:
            assert runtime.invoke(request)["ok"]
    after = _world(runtime, record_id)

    for area in before:
        assert before[area] == after[area], f"a read action modified {area}"


def test_reads_emit_no_lifecycle_events(hero):
    """A read is not part of the decision's history and must not appear in it."""
    runtime, record_id = hero
    before = len(runtime._VOUCH.record_store.events_for(record_id))

    runtime.invoke({"action": "get_decision", "decision_record_id": record_id})
    runtime.invoke({"action": "get_events", "decision_record_id": record_id})
    runtime.invoke({"action": "get_source", "decision_record_id": record_id})

    assert len(runtime._VOUCH.record_store.events_for(record_id)) == before


def test_reads_issue_no_capability(hero):
    """Authority is minted only by the policy engine, never by looking."""
    runtime, record_id = hero
    before = len(runtime._VOUCH.capabilities.ledger)

    runtime.invoke({"action": "list_decisions"})
    runtime.invoke({"action": "get_today"})
    runtime.invoke({"action": "get_decision", "decision_record_id": record_id})

    assert len(runtime._VOUCH.capabilities.ledger) == before


# ======================================================================
# get_events
# ======================================================================


def test_get_events_returns_the_persisted_shape(hero):
    """Not the in-process shape, which flattens payload and has no sequence.

    A cursor cannot be built on a shape with no sequence, so serving the
    flattened form would make the whole polling contract unimplementable.
    """
    runtime, record_id = hero
    rows = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]

    assert rows
    for row in rows:
        assert set(row) == {
            "event_id", "sequence", "event", "decision_record_id", "at", "payload"
        }
        assert isinstance(row["payload"], dict)


def test_event_ids_are_stable_and_unique(hero):
    runtime, record_id = hero
    rows = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]

    ids = [row["event_id"] for row in rows]
    assert len(ids) == len(set(ids))
    for row in rows:
        assert row["event_id"] == f"{record_id}#{row['sequence']:06d}"

    again = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]
    assert [row["event_id"] for row in again] == ids, "ids must not shift between reads"


def test_sequences_are_strictly_ascending_and_gapless(hero):
    runtime, record_id = hero
    rows = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]
    sequences = [row["sequence"] for row in rows]

    assert sequences == sorted(sequences)
    assert all(b > a for a, b in zip(sequences, sequences[1:]))
    assert sequences == list(range(1, len(sequences) + 1))


def test_after_sequence_returns_only_the_unseen_tail(hero):
    runtime, record_id = hero
    everything = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]

    tail = runtime.invoke({
        "action": "get_events", "decision_record_id": record_id,
        "after_sequence": len(everything) - 2,
    })["events"]

    assert [row["sequence"] for row in tail] == [len(everything) - 1, len(everything)]


def test_polling_at_the_high_water_mark_returns_nothing(hero):
    runtime, record_id = hero
    everything = runtime.invoke({"action": "get_events", "decision_record_id": record_id})
    settled = runtime.invoke({
        "action": "get_events", "decision_record_id": record_id,
        "after_sequence": everything["last_event_sequence"],
    })

    assert settled["events"] == []
    # The cursor must not rewind when there is nothing new.
    assert settled["last_event_sequence"] == everything["last_event_sequence"]


def test_limit_pages_from_the_oldest_unseen_event(hero):
    runtime, record_id = hero
    page = runtime.invoke({
        "action": "get_events", "decision_record_id": record_id, "limit": 3
    })["events"]
    assert [row["sequence"] for row in page] == [1, 2, 3]


def test_events_stay_gapless_across_a_resumed_run(runtime):
    """Run 1 -> DECISION_RESUMED -> Run 2, read as one continuous history.

    This is where sequence allocation is easiest to get wrong: numbering that
    restarted per run collided with run 1's keys and silently dropped the
    continuation (audit-2 F8).
    """
    from vouch.v2.fixtures import COA_AMBIGUOUS, QA_RETEST

    first = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1007",
        "document": COA_AMBIGUOUS.decode(),
    })
    record_id = first["decision_record_id"]
    assert first["quality_decision_required"]
    run_one = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]

    resumed = runtime.invoke({
        "action": "supply_evidence", "decision_record_id": record_id,
        "lot_id": "LOT-1007", "document": QA_RETEST.decode(),
        "authority_source": "PLANT-QA-LAB",
    })
    assert resumed["decision_record_id"] == record_id

    both = runtime.invoke({"action": "get_events", "decision_record_id": record_id})["events"]
    sequences = [row["sequence"] for row in both]

    assert sequences == list(range(1, len(both) + 1)), "history is not gapless"
    assert both[: len(run_one)] == run_one, "run 1 history changed"
    assert len(both) > len(run_one)

    names = [row["event"] for row in both]
    assert "DECISION_RESUMED" in names
    # The boundary sits inside run 2, not at the seam of two separate histories.
    assert names.index("DECISION_RESUMED") >= len(run_one)

    # A cursor set at the end of run 1 picks up run 2 and nothing else.
    tail = runtime.invoke({
        "action": "get_events", "decision_record_id": record_id,
        "after_sequence": len(run_one),
    })["events"]
    assert [row["sequence"] for row in tail] == list(range(len(run_one) + 1, len(both) + 1))


# ======================================================================
# get_decision
# ======================================================================


def test_get_decision_returns_the_whole_record_not_a_summary(hero):
    """`_record_summary` drops most of what an audit surface renders."""
    runtime, record_id = hero
    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": record_id
    })["record"]

    for segment in (
        "identity", "evidence", "security", "extraction", "snapshot",
        "investigator", "verifier", "reconciliation", "corpus", "basis",
        "disposition", "policy", "capability", "mutation", "consequences",
        "human", "storage", "archived_runs", "run_count", "terminal",
    ):
        assert segment in record, f"{segment} missing from the record projection"

    # Things the lossy summary omits entirely.
    assert record["evidence"]["source_artifact_hashes"]
    assert record["reconciliation"]["outcome"]
    assert record["investigator"]["brief"]


def test_get_decision_reports_the_event_cursor(hero):
    runtime, record_id = hero
    response = runtime.invoke({"action": "get_decision", "decision_record_id": record_id})
    stored = runtime._VOUCH.record_store.events_for(record_id)

    assert response["last_event_sequence"] == len(stored)


def test_get_decision_carries_both_runs_after_a_resume(runtime):
    from vouch.v2.fixtures import COA_AMBIGUOUS, QA_RETEST

    first = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1007",
        "document": COA_AMBIGUOUS.decode(),
    })
    record_id = first["decision_record_id"]
    runtime.invoke({
        "action": "supply_evidence", "decision_record_id": record_id,
        "lot_id": "LOT-1007", "document": QA_RETEST.decode(),
        "authority_source": "PLANT-QA-LAB",
    })

    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": record_id
    })["record"]

    assert record["run_count"] == 2
    assert len(record["archived_runs"]) == 1

    archived = record["archived_runs"][0]
    assert archived["run_number"] == 1
    assert archived["disposition"]["disposition"] == "INSUFFICIENT_EVIDENCE"
    assert record["disposition"]["disposition"] == "RELEASE"
    # The reason a human was asked is still readable next to the release.
    assert archived["investigator"]["brief_hash"] != record["investigator"]["brief_hash"]


def test_an_unknown_record_is_a_typed_failure(runtime):
    """Not an empty record, which a caller would render as a real decision."""
    response = runtime.invoke({"action": "get_decision", "decision_record_id": "DR-nope"})

    assert response["ok"] is False
    assert response["failure_category"] == "PERSISTENCE_FAILURE"


def test_get_decision_requires_a_record_id(runtime):
    response = runtime.invoke({"action": "get_decision"})
    assert response["ok"] is False
    assert response["failure_category"] == "PERSISTENCE_FAILURE"


# ======================================================================
# list_decisions
# ======================================================================


def test_list_decisions_returns_rows_with_a_server_computed_state(hero):
    """`row_state` is computed here so two clients cannot disagree about it."""
    runtime, record_id = hero
    response = runtime.invoke({"action": "list_decisions"})

    assert response["ok"]
    row = next(r for r in response["rows"] if r["decision_record_id"] == record_id)
    assert row["lot_id"] == "LOT-1002"
    assert row["disposition"] == "QUARANTINE"
    assert row["row_state"] == "QUARANTINED"
    assert row["attention_required"] is False
    # Joined from the lot, not invented.
    assert row["material_id"] == "MAT-ALLOY-7"
    assert row["supplier_id"] == "SUP-EAST"


def test_an_identity_halt_needs_no_binding_specific_incoming_rule(runtime):
    """The version-based Incoming contract covers a NEW halt category for free.

    Pinned deliberately. The reset contract replaced a per-category allowlist
    precisely so each new evidence-level halt would not need `_incoming_row`
    extended; the human-resolvable identity case is the first new category
    since, so it is the first real test of that claim.
    """
    batch_only = (
        b"Certificate of Analysis\n"
        b"Northern Alloys - Supplier: SUP-NORTH\n"
        b"Site: SITE-N1\n"
        b"Material: MAT-ALLOY-7\n"
        b"Purchase Order: PO-82\n"
        b"Supplier Batch: WP-26-0317-B\n"
        b"Specification SPEC-A7 Revision C\n"
        b"tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
        b"hardness: 31 HRC (HRC, as_received)\n"
    )
    outcome = runtime._VOUCH.evaluate_lot(
        "LOT-1004", documents=[{"raw": batch_only, "document_identity": "COA"}]
    )
    assert outcome.failure_category == "EVIDENCE_IDENTITY_UNRESOLVED"

    row = next(
        r for r in runtime.invoke({"action": "list_decisions", "limit": 50})["rows"]
        if r["lot_id"] == "LOT-1004"
    )
    assert row["row_state"] == "QUALITY_DECISION_REQUIRED"
    assert row["attention_required"] is True
    # The lot never moved: an unattributable document says nothing about it.
    assert row["lot_status"] == "RECEIVED"


def _equivalence_option(runtime, record_id):
    """The offered path that relies on an equivalence — the one that RELEASES.

    Named explicitly because the two paths lead to different dispositions, so
    which is established decides the lot.
    """
    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": record_id,
    })["record"]
    options = record["quality_authority"]["question"]["options"]
    return next(o for o in options if o["equivalence_id"])["claim_id"]


def test_incoming_lists_arrivals_that_have_no_decision_yet(runtime):
    """A lot that has arrived and never been evaluated must still appear.

    Incoming is built from the decision ledger, so before this a lot with no
    DecisionRecord could not be listed at all — a freshly seeded plant showed
    an empty "material awaiting disposition" while its receiving dock was full,
    and there was no way to start the very first decision for a lot.
    """
    response = runtime.invoke({"action": "list_decisions"})
    assert response["ok"]

    by_lot = {row["lot_id"]: row for row in response["rows"]}
    for lot_id in ("LOT-1001", "LOT-1002", "LOT-1004", "LOT-1005", "LOT-1007", "LOT-1003"):
        assert lot_id in by_lot, f"{lot_id} has arrived and must be listed"

    arrival = by_lot["LOT-1003"]
    # No decision exists, so no record is claimed — but every fact about the
    # lot is real and comes from the authoritative corpus.
    assert arrival["decision_record_id"] == ""
    assert arrival["row_state"] == "EVIDENCE_RECEIVED"
    assert arrival["attention_required"] is False
    assert arrival["material_id"] == "MAT-RESIN-3"
    assert arrival["supplier_id"] == "SUP-WEST"
    assert arrival["quantity"] == 200.0
    assert arrival["units"] == "kg"


def test_incoming_survives_a_malformed_lot_and_hides_test_debris(runtime):
    """One bad row must not take down the whole surface.

    Two real defects, both found against the deployed table. The live AWS
    integration tests write `PYTEST-<hex>` lots into the shared dev state store
    and never remove them — 184 of them, most with an empty material_id. The
    decision ledger never surfaced these, so reading arrivals from the corpus
    exposed them: the empty material id was passed straight to the store as a
    key, which DynamoDB rejects outright, and `list_decisions` returned a
    PERSISTENCE_FAILURE instead of any arrivals at all.
    """
    from vouch.v2.corpus import Lot

    corpus = runtime._CORPUS
    corpus.put(
        "lot", "PYTEST-deadbeef01",
        Lot("PYTEST-deadbeef01", "", "", "", 0.0, status="RECEIVED"),
    )
    corpus.put(
        "lot", "LOT-MALFORMED",
        Lot("LOT-MALFORMED", "", "", "PO-X", 10.0, status="RECEIVED"),
    )

    response = runtime.invoke({"action": "list_decisions"})
    assert response["ok"], response

    listed = {row["lot_id"] for row in response["rows"]}
    assert "LOT-1003" in listed, "the real arrivals must still be listed"
    # Test litter is filtered by name; a genuinely malformed real lot is
    # skipped rather than crashing the surface.
    assert "PYTEST-deadbeef01" not in listed
    assert "LOT-MALFORMED" not in listed


def test_a_resolved_disagreement_stops_asking_for_a_decision(runtime):
    """Run 1's failure must not outlive the answer that settled it.

    `failure_category` is the LAST failure a record saw, and on a resumed case
    run 1's MATERIAL_DISAGREEMENT stays on the document after run 2 released
    the lot. Reading it alone made a reseeded LOT-1003 sit in Incoming asking
    for a quality decision that had already been given — work nobody owed.
    """
    import base64
    from pathlib import Path

    pdf = Path(__file__).resolve().parents[2] / "demo" / "evidence" / (
        "western-polymers-coa-lot-1006.pdf"
    )
    first = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1003",
        "document_b64": base64.b64encode(pdf.read_bytes()).decode(),
        "content_type": "application/pdf",
    })
    assert first["failure_category"] == "MATERIAL_DISAGREEMENT"

    rows = runtime.invoke({"action": "list_decisions"})["rows"]
    open_row = next(r for r in rows if r["lot_id"] == "LOT-1003")
    assert open_row["row_state"] == "QUALITY_DECISION_REQUIRED"
    assert open_row["attention_required"] is True

    resumed = runtime.invoke({
        "action": "submit_quality_authority",
        "decision_record_id": first["decision_record_id"],
        "decision": "ESTABLISH_EVIDENCE",
        "evidence_ref": _equivalence_option(runtime, first["decision_record_id"]),
        "accountable_actor": "QA-LEAD",
        "authority_source": "Plant Quality Authority",
    })
    assert resumed["disposition"] == "RELEASE"

    # Now roll the lot back the way a reseed does, leaving the record behind.
    # The runtime fixture is module-scoped, so the corpus is restored
    # afterwards — this test borrows LOT-1003's state and must give it back.
    from dataclasses import replace

    corpus = runtime._CORPUS
    released = corpus.lot("LOT-1003")
    corpus.put("lot", "LOT-1003", replace(released, status="RECEIVED"))
    try:
        rows = runtime.invoke({"action": "list_decisions"})["rows"]
        settled = next(r for r in rows if r["lot_id"] == "LOT-1003")

        assert settled["row_state"] == "EVIDENCE_RECEIVED"
        assert settled["attention_required"] is False
    finally:
        # Hand LOT-1003 back UNDECIDED, not released. This test drove it all
        # the way to RELEASE, and the module-scoped fixture would carry that
        # into every later test — one of which needs a fresh disagreement on
        # this same lot. Restoring the released row would leak this test's
        # effect into its neighbours.
        corpus.put("lot", "LOT-1003", replace(released, status="RECEIVED"))
        inventory = corpus.get("inventory", "LOT-1003")
        if inventory is not None:
            corpus.put(
                "inventory", "LOT-1003", replace(inventory, usable=False)
            )


def test_a_decided_lot_is_not_duplicated_by_its_arrival(runtime):
    """The record wins. An arrival row must never mask a real decision."""
    import base64
    from pathlib import Path

    pdf = Path(__file__).resolve().parents[2] / "demo" / "evidence" / (
        "western-polymers-coa-lot-1006.pdf"
    )
    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1003",
        "document_b64": base64.b64encode(pdf.read_bytes()).decode(),
        "content_type": "application/pdf",
    })
    assert outcome["failure_category"] == "MATERIAL_DISAGREEMENT"

    rows = runtime.invoke({"action": "list_decisions"})["rows"]
    mine = [r for r in rows if r["lot_id"] == "LOT-1003"]

    # Every row for this lot is a REAL DecisionRecord. The ledger legitimately
    # holds one per evaluation — Incoming collapses them to the newest — and
    # what must never appear beside them is a recordless arrival row claiming
    # the lot is still untouched.
    assert mine, "the decided lot must still be listed"
    assert all(r["decision_record_id"] for r in mine), (
        "an arrival row must not duplicate a lot that has a decision"
    )

    this_run = next(
        r for r in mine if r["decision_record_id"] == outcome["decision_record_id"]
    )
    assert this_run["row_state"] == "QUALITY_DECISION_REQUIRED"
    assert this_run["attention_required"] is True


def test_list_decisions_invents_no_unsupported_counts(hero):
    """`in_progress` and `completed_by_vouch` have no authoritative meaning.

    Invocation is synchronous, so nothing is ever persisted mid-flight, and the
    model attributes no decision to Vouch rather than to a human. A number for
    either would be fiction rendered as fact.
    """
    runtime, _ = hero
    counts = runtime.invoke({"action": "list_decisions"})["counts"]

    assert "in_progress" not in counts
    assert "completed_by_vouch" not in counts
    assert counts["returned"] >= 1


def test_a_security_quarantine_row_asks_for_attention(runtime):
    from vouch.v2.fixtures import COA_HOSTILE

    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1005",
        "document": COA_HOSTILE.decode(),
    })
    record_id = outcome["decision_record_id"]

    rows = runtime.invoke({"action": "list_decisions"})["rows"]
    row = next(r for r in rows if r["decision_record_id"] == record_id)

    assert row["row_state"] == "SECURITY_HOLD"
    assert row["attention_required"] is True


# ======================================================================
# get_source
# ======================================================================


def test_get_source_returns_metadata_without_a_retrieval_route(hero):
    """Change C has not landed. Absent `view_ref` is the honest answer.

    Faking one would make a frontend render a broken viewer instead of the
    "source unavailable" state the contract asks for.
    """
    runtime, record_id = hero
    response = runtime.invoke({"action": "get_source", "decision_record_id": record_id})

    assert response["ok"]
    assert response["retrieval_available"] is False

    source = response["sources"][0]
    assert source["view_ref"] is None
    # Everything the viewer renders without fetching content.
    assert source["artifact_id"].startswith("ART-")
    assert source["content_hash"]
    assert source["object_version"]
    assert source["storage_ref"].endswith(source["artifact_id"])
    assert source["trust_class"] == "UNTRUSTED_SUPPLIER"
    assert source["security_state"] == "CLEARED"
    assert source["excluded_from_decision_use"] is False


def test_a_quarantined_artifact_is_returned_and_marked_excluded(runtime):
    """Never silently omitted: dropping it hides the attack and loses evidence."""
    from vouch.v2.fixtures import COA_HOSTILE

    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1005",
        "document": COA_HOSTILE.decode(),
    })
    response = runtime.invoke({
        "action": "get_source", "decision_record_id": outcome["decision_record_id"],
    })

    source = response["sources"][0]
    assert source["security_state"] == "QUARANTINED"
    assert source["excluded_from_decision_use"] is True
    assert source["prompt_attack_detected"] is True
    # The original is still referenced, so it can be produced later.
    assert source["content_hash"]
    assert source["storage_ref"]


def test_get_source_can_address_one_artifact(hero):
    runtime, record_id = hero
    everything = runtime.invoke({"action": "get_source", "decision_record_id": record_id})
    artifact_id = everything["sources"][0]["artifact_id"]

    one = runtime.invoke({
        "action": "get_source", "decision_record_id": record_id, "artifact_id": artifact_id,
    })
    assert [s["artifact_id"] for s in one["sources"]] == [artifact_id]


def test_an_unknown_artifact_is_a_typed_failure(hero):
    runtime, record_id = hero
    response = runtime.invoke({
        "action": "get_source", "decision_record_id": record_id, "artifact_id": "ART-nope",
    })
    assert response["ok"] is False
    assert response["failure_category"] == "PERSISTENCE_FAILURE"


def test_human_authorized_evidence_is_labeled_as_such(runtime):
    """The trust class is what stops the UI calling this a supplier document."""
    from vouch.v2.fixtures import COA_AMBIGUOUS, QA_RETEST

    first = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1007",
        "document": COA_AMBIGUOUS.decode(),
    })
    record_id = first["decision_record_id"]
    runtime.invoke({
        "action": "supply_evidence", "decision_record_id": record_id,
        "lot_id": "LOT-1007", "document": QA_RETEST.decode(),
        "authority_source": "PLANT-QA-LAB",
    })

    sources = runtime.invoke({
        "action": "get_source", "decision_record_id": record_id
    })["sources"]

    trust = {s["trust_class"] for s in sources}
    assert "HUMAN_AUTHORIZED" in trust
    assert "UNTRUSTED_SUPPLIER" in trust, "the original supplier document is still listed"


# ======================================================================
# get_today
# ======================================================================


def test_get_today_reports_authoritative_readiness_per_line(runtime):
    response = runtime.invoke({"action": "get_today"})

    assert response["ok"]
    assert set(response["readiness_counts"]) >= {
        "READY", "AWAITING_QUALITY", "AT_RISK", "BLOCKED",
    }
    assert response["lines"]

    orders = [o for line in response["lines"] for o in line["orders"]]
    assert {"C-417", "C-418", "C-419"} <= {o["order_id"] for o in orders}
    for order in orders:
        assert order["readiness"] in (
            "READY", "AWAITING_QUALITY", "AT_RISK", "BLOCKED", "COMPLETE",
        )
        assert order["reason"], "a readiness verdict must say why"


def test_get_today_fabricates_no_before_and_after(runtime):
    """Which change to highlight is a frontend question, answered from causal
    links. A backend guess would be inventing operational history."""
    response = runtime.invoke({"action": "get_today"})

    blob = repr(response).lower()
    for invented in ("prior_slot", "before", "after", "change_banner"):
        assert invented not in blob


def test_today_readiness_matches_the_deterministic_calculation(runtime):
    """The read must not drift from what a decision would conclude."""
    from vouch.v2.consequences import compute_readiness

    response = runtime.invoke({"action": "get_today"})
    for line in response["lines"]:
        for order in line["orders"]:
            expected = compute_readiness(runtime._CORPUS, order["order_id"])
            assert order["readiness"] == expected.readiness.value


# ======================================================================
# the additive guarantee
# ======================================================================


def test_the_original_actions_still_work(runtime):
    """Strictly additive: the five that existed are untouched."""
    from vouch.v2.fixtures import COA_CLEAN

    outcome = runtime.invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1001", "document": COA_CLEAN.decode(),
    })
    assert outcome["ok"] and outcome["disposition"]

    assert runtime.invoke({"action": "readiness", "order_id": "C-417"})["ok"]
    assert runtime.invoke({"action": "recovery", "order_id": "C-417"})["ok"]
    assert runtime.invoke({
        "action": "ledger", "decision_record_id": outcome["decision_record_id"]
    })["ok"]


def test_an_unknown_action_is_still_rejected(runtime):
    assert runtime.invoke({"action": "delete_everything"})["ok"] is False


def test_the_staged_runtime_copy_is_current():
    """The deployed bundle resolves `vouch` from the staged copy, not src/.

    A stale staging directory means the runtime serves code that no longer
    matches the tests — which is exactly how these read actions first failed,
    against an `events_for` that predated its own cursor parameter.
    """
    staged = ROOT / "app" / "Gatehouse" / "src" / "vouch"
    if not staged.exists():
        pytest.skip("runtime not staged; scripts/stage_runtime.py has not run")

    canonical = ROOT / "src" / "vouch"
    for path in sorted(canonical.rglob("*.py")):
        mirror = staged / path.relative_to(canonical)
        assert mirror.exists(), f"{path.name} missing from the staged runtime"
        assert mirror.read_text() == path.read_text(), (
            f"{path.name} differs from src/; run scripts/stage_runtime.py"
        )
