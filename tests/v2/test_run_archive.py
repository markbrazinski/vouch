"""Change B — a resumed case keeps the run that made it necessary.

`investigator`, `verifier` and `reconciliation` are single segments on the
DecisionRecord, so run 2 wrote straight over run 1. The record could show that a
decision had abstained and then released, but not what the two agents said when
it abstained — the reason a human was asked for evidence at all was the first
thing destroyed.

`rerun()` now archives the outgoing run first. That is the only moment its
evidence still exists.

The archive is structured facts only: briefs, hashes, tool metadata,
reconciliation values. There is deliberately no field for reasoning text, which
is the same rule the live segments follow.
"""

from __future__ import annotations

import gc

import pytest

from vouch.v2.decision_record import ArchivedRun, DecisionRecord
from vouch.v2.fixtures import COA_AMBIGUOUS, QA_RETEST, build_corpus
from vouch.v2.persistence import InMemoryRecordStore, JsonRecordStore, hydrate_record
from vouch.v2.workflow import VouchV2

FORBIDDEN = ("chain_of_thought", "reasoning", "rationale", "raw_prompt", "prompt_text")


def _resolve(vouch, record_id):
    """The Hero B shape: abstain on ambiguous evidence, then resolve it."""
    first = vouch.evaluate_lot("LOT-1007", documents=[{"raw": COA_AMBIGUOUS}])
    vouch.supply_human_evidence(
        decision_record_id=first.decision_record_id,
        lot_id="LOT-1007",
        raw=QA_RETEST,
        authority_source="PLANT-QA-LAB",
    )
    return first.decision_record_id


# ======================================================================
# the loss this exists to prevent
# ======================================================================


def test_run_one_survives_the_run_that_replaces_it():
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())

    first = vouch.evaluate_lot("LOT-1007", documents=[{"raw": COA_AMBIGUOUS}])
    record_id = first.decision_record_id
    live = vouch._record_for(record_id)
    run_one_hash = live.investigator.brief_hash
    run_one_sufficiency = (live.investigator.brief or {}).get("sufficiency")
    assert first.quality_decision_required

    vouch.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1007",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    record = vouch._record_for(record_id)
    assert len(record.archived_runs) == 1

    archived = record.archived_runs[0]
    assert archived.run_number == 1
    assert archived.investigator.brief_hash == run_one_hash
    assert (archived.investigator.brief or {}).get("sufficiency") == run_one_sufficiency

    # And the live segments are genuinely the NEW run, not a copy of the old.
    assert record.investigator.brief_hash != run_one_hash
    assert record.run_count == 2


def test_the_two_runs_tell_different_stories():
    """The whole point of Records showing both: they must not be identical."""
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())
    record_id = _resolve(vouch, None)
    record = vouch._record_for(record_id)

    archived = record.archived_runs[0]
    assert archived.disposition.disposition == "INSUFFICIENT_EVIDENCE"
    assert record.disposition.disposition == "RELEASE"


def test_archived_evidence_is_not_aliased_to_the_live_run():
    """A shallow copy that shared `tool_events` would corrupt history in place."""
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())
    record_id = _resolve(vouch, None)
    record = vouch._record_for(record_id)

    archived = record.archived_runs[0]
    assert archived.investigator.tool_events is not record.investigator.tool_events
    assert archived.verifier.tool_events is not record.verifier.tool_events
    assert archived.reconciliation is not record.reconciliation


def test_runs_returns_history_plus_the_current_run():
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())
    record_id = _resolve(vouch, None)
    record = vouch._record_for(record_id)

    runs = record.runs()
    assert [run.run_number for run in runs] == [1, 2]
    assert runs[-1].investigator.brief_hash == record.investigator.brief_hash


def test_a_single_run_case_has_no_archive_but_still_reports_one_run():
    """Hero A never resumes; `runs()` must still answer sensibly."""
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())
    outcome = vouch.evaluate_lot("LOT-1007", documents=[{"raw": COA_AMBIGUOUS}])

    record = vouch._record_for(outcome.decision_record_id)
    assert record.archived_runs == []
    assert [run.run_number for run in record.runs()] == [1]


# ======================================================================
# it has to survive storage, or it did not survive at all
# ======================================================================


def test_the_archive_is_readable_after_a_restart(tmp_path):
    """Typed access, not dicts.

    Storing the archive is not enough: if hydration leaves the nested segments
    as raw dicts, `run.investigator.brief_hash` raises and the archive is
    unreadable in exactly the audit surface it was built for.
    """
    store = JsonRecordStore(tmp_path / "records")
    corpus = build_corpus()

    vouch = VouchV2(corpus, record_store=store)
    record_id = _resolve(vouch, None)
    del vouch
    gc.collect()

    resumed = VouchV2(corpus, record_store=store).resume(record_id)

    assert len(resumed.archived_runs) == 1
    archived = resumed.archived_runs[0]
    assert isinstance(archived, ArchivedRun)
    assert archived.investigator.brief_hash, "brief hash lost in storage"
    assert archived.reconciliation.outcome, "reconciliation lost in storage"
    assert archived.disposition.disposition == "INSUFFICIENT_EVIDENCE"


def test_hydrating_a_record_written_before_the_archive_existed():
    """Forward compatibility, the same rule the rest of hydration follows."""
    record = hydrate_record({"record_id": "DR-old", "run_count": 2})
    assert record.archived_runs == []
    assert [run.run_number for run in record.runs()] == [2]


# ======================================================================
# the boundary: structured facts only
# ======================================================================


def test_the_archive_has_no_field_for_reasoning():
    """Asserted on the schema, so a later field addition trips it."""
    from dataclasses import fields

    def field_names(cls):
        return [f.name for f in fields(cls)]

    names = field_names(ArchivedRun)
    for nested in ("investigator", "verifier", "reconciliation", "basis",
                   "disposition", "snapshot"):
        default = getattr(ArchivedRun(), nested)
        names.extend(field_names(type(default)))

    for name in names:
        assert not any(bad in name.lower() for bad in FORBIDDEN), name


def test_no_archived_value_carries_reasoning_text():
    """The schema check above, asserted again on real stored content."""
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())
    record_id = _resolve(vouch, None)
    record = vouch._record_for(record_id)

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, item in value.items():
                assert not any(bad in str(key).lower() for bad in FORBIDDEN), f"{path}.{key}"
                walk(item, f"{path}.{key}")
        elif isinstance(value, list):
            for item in value:
                walk(item, path)

    from dataclasses import asdict

    for archived in record.archived_runs:
        walk(asdict(archived), "archived_run")


def test_archiving_does_not_change_the_decision():
    """Change B is an audit change. The outcome must be untouched."""
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())

    first = vouch.evaluate_lot("LOT-1007", documents=[{"raw": COA_AMBIGUOUS}])
    outcome = vouch.supply_human_evidence(
        decision_record_id=first.decision_record_id, lot_id="LOT-1007",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    assert outcome.disposition == "RELEASE"
    assert corpus.lot("LOT-1007").status == "RELEASED"
    assert outcome.record.human.review_status == "RESOLVED"


def test_a_replay_archives_nothing():
    """No rerun, so no new archived run."""
    corpus = build_corpus()
    vouch = VouchV2(corpus, record_store=InMemoryRecordStore())
    record_id = _resolve(vouch, None)

    vouch.supply_human_evidence(
        decision_record_id=record_id, lot_id="LOT-1007",
        raw=QA_RETEST, authority_source="PLANT-QA-LAB",
    )

    record = vouch._record_for(record_id)
    assert len(record.archived_runs) == 1
    assert record.run_count == 2
