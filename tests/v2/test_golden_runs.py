"""Integrity of the captured GOLDEN RUN packages.

These are the film's source of truth: one real execution per canonical lot,
saved so playback timing can be tuned later WITHOUT re-executing the backend.
The value of that only holds if the saved truth is actually intact, so this
asserts on the packages themselves rather than on the pipeline that made them.

Skipped when `golden-runs/` is absent, so a clean checkout is not failed by the
absence of capture artifacts — but every package that IS present is checked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
GOLDEN = ROOT / "golden-runs"

#: What each canonical lot's golden run must have DONE. Stated here rather than
#: read from the package, so a package that recorded the wrong outcome fails
#: instead of describing itself as correct.
EXPECTED: dict[str, dict] = {
    "LOT-1001": {"outcome": "RELEASE", "human": False, "mutation": "release_lot"},
    "LOT-1002": {"outcome": "QUARANTINE", "human": False, "mutation": "quarantine_lot"},
    "LOT-1003": {"outcome": "RELEASE", "human": True, "mutation": "release_lot"},
    "LOT-1004": {"outcome": "RELEASE", "human": True, "mutation": "release_lot"},
    "LOT-1005": {"outcome": "SECURITY_QUARANTINE", "human": False, "mutation": ""},
}

PACKAGES = sorted(p.name for p in GOLDEN.iterdir()) if GOLDEN.is_dir() else []

pytestmark = pytest.mark.skipif(not PACKAGES, reason="no golden runs captured")


def load(lot_id: str, name: str):
    return json.loads((GOLDEN / lot_id / name).read_text())


@pytest.fixture(params=PACKAGES)
def lot_id(request):
    return request.param


# ==========================================================================
# structure
# ==========================================================================


def test_package_has_every_required_file(lot_id):
    for name in ("manifest.json", "events.json", "decision-record.json", "beats.json"):
        assert (GOLDEN / lot_id / name).exists(), f"{lot_id}/{name} missing"


def test_manifest_states_what_the_run_was(lot_id):
    manifest = load(lot_id, "manifest.json")
    for field in (
        "lot_id", "scenario", "decision_record_id", "run_count",
        "source_artifact_id", "source_filename", "model_id",
        "capture_timestamp", "terminal_outcome", "raw_event_count", "beat_count",
    ):
        assert manifest.get(field) not in (None, ""), f"{lot_id}: {field} is empty"
    assert manifest["lot_id"] == lot_id


# ==========================================================================
# the run is REAL
# ==========================================================================


def test_the_run_was_model_backed_and_fully_durable(lot_id):
    """A hand-composed or memory-backed run is not a golden run."""
    backend = load(lot_id, "manifest.json")["backend"]
    assert backend["reasoners"] == "BEDROCK_NOVA", (
        f"{lot_id} was not decided by the deployed Bedrock reasoners"
    )
    assert backend["durable"] is True
    for role in ("corpus", "capability_store", "record_store", "event_store"):
        assert backend[role] == "AWS_DYNAMODB", f"{lot_id}: {role} was not durable"
    assert backend["evidence_store"] == "AWS_S3"


def test_the_outcome_is_the_canonical_one(lot_id):
    manifest = load(lot_id, "manifest.json")
    expected = EXPECTED[lot_id]
    assert manifest["terminal_outcome"] == expected["outcome"]
    assert manifest["human_interaction"] is expected["human"]
    action = (manifest.get("mutation") or {}).get("action", "")
    assert action == expected["mutation"], (
        f"{lot_id} mutated {action!r}, expected {expected['mutation']!r}"
    )


# ==========================================================================
# the event stream is intact
# ==========================================================================


def test_sequences_are_contiguous_and_ordered(lot_id):
    """A gap means events were dropped; a repeat means the stream replayed."""
    events = load(lot_id, "events.json")
    sequences = [row["sequence"] for row in events]
    assert sequences == sorted(sequences), f"{lot_id}: events out of order"
    assert sequences == list(range(1, len(events) + 1)), (
        f"{lot_id}: sequence gaps or duplicates in {sequences[:12]}..."
    )


def test_no_event_is_stored_twice(lot_id):
    """The regression the LOT-1001 capture caught, asserted on the artifact.

    The terminal batch used to re-append every live-written event at a fresh
    sequence, so the stored stream replayed the whole run with the original
    timestamps. Identity is (type, at, payload) — genuinely repeated emissions
    carry distinct timestamps and stay distinct.
    """
    events = load(lot_id, "events.json")
    seen = [
        (row["event"], row["at"], json.dumps(row.get("payload") or {}, sort_keys=True))
        for row in events
    ]
    duplicates = {item for item in seen if seen.count(item) > 1}
    assert not duplicates, (
        f"{lot_id}: {len(duplicates)} event(s) stored more than once — "
        f"first: {sorted(duplicates)[0][0]}"
    )


def test_the_record_and_the_stream_agree(lot_id):
    manifest = load(lot_id, "manifest.json")
    record = load(lot_id, "decision-record.json")
    assert record.get("record_id") == manifest["decision_record_id"]
    assert manifest["raw_event_count"] == len(load(lot_id, "events.json"))


def test_the_stream_belongs_to_one_decision(lot_id):
    record_id = load(lot_id, "manifest.json")["decision_record_id"]
    for row in load(lot_id, "events.json"):
        assert row.get("decision_record_id", record_id) == record_id


# ==========================================================================
# causal coherence — no result before its cause
# ==========================================================================


def test_no_downstream_event_precedes_its_cause(lot_id):
    """The ordering invariant the film depends on.

    Each stage may only appear after the stage that produces its input. A frame
    showing a disposition while verification is still open is the specific
    defect the causal-sequence audit closed; this asserts the SAVED stream can
    never replay one.
    """
    order = [
        "EVIDENCE_RECEIVED",
        "INVESTIGATOR_STARTED",
        "APPLICABILITY_BRIEF_COMPLETED",
        "VERIFIER_STARTED",
        "VERIFIER_BRIEF_COMPLETED",
        "RECONCILIATION_COMPLETED",
        "DISPOSITION_COMPUTED",
        "MUTATION_COMPLETED",
        "CONSEQUENCE_RECALCULATED",
    ]
    first: dict[str, int] = {}
    for row in load(lot_id, "events.json"):
        first.setdefault(row["event"], row["sequence"])

    present = [(kind, first[kind]) for kind in order if kind in first]
    for (earlier, at_earlier), (later, at_later) in zip(present, present[1:]):
        assert at_earlier < at_later, (
            f"{lot_id}: {later} (seq {at_later}) appears before "
            f"{earlier} (seq {at_earlier})"
        )


def test_a_halted_run_never_reaches_an_agent(lot_id):
    """LOT-1005: Guardrails halts BEFORE any agent starts, and nothing mutates."""
    if lot_id != "LOT-1005":
        pytest.skip("security-halt invariant")
    kinds = {row["event"] for row in load(lot_id, "events.json")}
    assert "INVESTIGATOR_STARTED" not in kinds
    assert "VERIFIER_STARTED" not in kinds
    assert "MUTATION_COMPLETED" not in kinds
    assert "DISPOSITION_COMPUTED" not in kinds
    assert not load(lot_id, "manifest.json")["mutation"]


def test_a_human_gated_run_carries_both_runs(lot_id):
    """LOT-1003 / LOT-1004: the human act is IN the stream, and run 2 follows it."""
    if not EXPECTED[lot_id]["human"]:
        pytest.skip("no human authority in this scenario")
    events = load(lot_id, "events.json")
    kinds = [row["event"] for row in events]
    assert "QUALITY_AUTHORITY_RECORDED" in kinds, f"{lot_id}: no human authority event"

    authority_at = kinds.index("QUALITY_AUTHORITY_RECORDED")
    assert any(
        kind in ("INVESTIGATOR_STARTED", "VERIFIER_STARTED")
        for kind in kinds[authority_at:]
    ), f"{lot_id}: agents did not re-run after the human decided"
    assert load(lot_id, "manifest.json")["run_count"] >= 2

    runs = {beat["run"] for beat in load(lot_id, "beats.json")}
    assert runs >= {1, 2}, f"{lot_id}: beats do not span both runs, got {runs}"


# ==========================================================================
# the beat index
# ==========================================================================


def test_beats_cover_the_stream_without_gaps_or_overlap(lot_id):
    """Beats partition the stream: every event belongs to exactly one beat."""
    events = load(lot_id, "events.json")
    beats = [b for b in load(lot_id, "beats.json") if b["beat_id"] != "startup"]
    spans = [(b["sequence_start"], b["sequence_end"]) for b in beats if b["beat_id"] != "terminal"]

    covered: list[int] = []
    for start, end in spans:
        covered.extend(range(start, end + 1))
    assert covered == sorted(covered), f"{lot_id}: beat spans are not ordered"
    assert sorted(covered) == list(range(1, len(events) + 1)), (
        f"{lot_id}: beats do not cover every event exactly once"
    )


def test_every_beat_is_playable(lot_id):
    """A beat must carry what a timing pass needs, and keep truth separable."""
    known = {
        "startup", "evidence_received", "security", "extraction", "binding",
        "investigator", "verifier", "reconciliation", "human_gate",
        "human_authority", "run_2_start", "disposition", "mutation",
        "consequence", "terminal",
    }
    for beat in load(lot_id, "beats.json"):
        assert beat["beat_id"] in known, f"{lot_id}: unknown beat {beat['beat_id']}"
        assert beat["run"] >= 1
        assert beat["sequence_start"] <= beat["sequence_end"]
        assert isinstance(beat["interaction_required"], bool)
        assert isinstance(beat["safe_to_compress"], bool)
        # Timing may now be present (`scripts/time_golden_runs.py --write`),
        # but the two numbers must stay DISTINGUISHABLE: `measured_s` is what
        # the machine did and is re-derivable from events.json, `film_s` is a
        # presentation choice. A single ambiguous "duration" would collapse them
        # and make the capture unfalsifiable.
        assert "duration" not in beat and "seconds" not in beat, (
            f"{lot_id}: beat {beat['beat_id']} carries an ambiguous duration; "
            f"use measured_s (truth) and film_s (presentation)"
        )
        if "film_s" in beat:
            assert "measured_s" in beat, (
                f"{lot_id}: beat {beat['beat_id']} has a film time with no "
                f"measurement to justify it"
            )


def test_only_the_human_gate_blocks_on_a_person(lot_id):
    for beat in load(lot_id, "beats.json"):
        if beat["interaction_required"]:
            assert beat["beat_id"] == "human_gate", (
                f"{lot_id}: {beat['beat_id']} claims to require interaction"
            )


def test_a_beat_blocks_only_where_a_question_was_actually_raised(lot_id):
    """An escalation is not a question.

    LOT-1005's security halt emits QUALITY_DECISION_REQUIRED with no question,
    no options and no disposition — nobody is being asked anything. Marking that
    beat interactive would tell a timing pass to hold for an answer that never
    comes, so only a beat containing QUALITY_QUESTION_RAISED may block.
    """
    for beat in load(lot_id, "beats.json"):
        raised = "QUALITY_QUESTION_RAISED" in beat["event_types"]
        assert beat["interaction_required"] == raised, (
            f"{lot_id}: beat {beat['beat_id']} "
            f"interaction_required={beat['interaction_required']} but "
            f"question_raised={raised}"
        )


# ==========================================================================
# nothing secret ships
# ==========================================================================


def test_no_credentials_or_account_targeting_in_any_package(lot_id):
    """§8: no credentials, no account ids, no expiring URLs."""
    import re

    for name in ("manifest.json", "events.json", "decision-record.json", "beats.json"):
        text = (GOLDEN / lot_id / name).read_text()
        assert not re.search(r"\b\d{12}\b", text), f"{lot_id}/{name}: AWS account id"
        assert "X-Amz-Signature" not in text, f"{lot_id}/{name}: presigned URL"
        assert "X-Amz-Credential" not in text, f"{lot_id}/{name}: presigned URL"
        assert "aws_secret_access_key" not in text.lower(), f"{lot_id}/{name}: secret"
        assert "ASIA" not in text and "AKIA" not in text, f"{lot_id}/{name}: access key"


def test_the_source_artifact_is_named_by_a_stable_identifier(lot_id):
    """A content hash survives re-upload; a bucket path and a URL do not."""
    manifest = load(lot_id, "manifest.json")
    assert manifest["source_artifact_id"].startswith("sha256:")
    source = ROOT / "demo" / "evidence" / manifest["source_filename"]
    assert source.exists(), f"{lot_id}: source PDF {source.name} is missing"

    import hashlib

    actual = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    assert actual == manifest["source_artifact_id"], (
        f"{lot_id}: the captured source no longer matches {source.name}"
    )


# ==========================================================================
# film timing — derived from the measured runs
# ==========================================================================


def timings(lot_id: str):
    """Beats with `measured_s` / `film_s`, computed fresh from the capture."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "time_golden_runs", ROOT / "scripts" / "time_golden_runs.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    beats = module.measure(lot_id)
    for beat in beats:
        beat["film_s"] = module.film_time(beat, 1.5, lot_id)
    return beats


def test_measured_time_never_exceeds_the_runs_wall_clock(lot_id):
    """Beat measurements must add up to the run, not invent time.

    Spans are contiguous (previous beat's last event to this beat's last), so
    their sum cannot exceed first-to-last across the whole stream.
    """
    from datetime import datetime

    events = load(lot_id, "events.json")
    if len(events) < 2:
        pytest.skip("too short to bound")
    span = (
        datetime.fromisoformat(events[-1]["at"]) - datetime.fromisoformat(events[0]["at"])
    ).total_seconds()
    total = sum(b["measured_s"] for b in timings(lot_id))
    assert total <= span + 0.05, f"{lot_id}: beats claim {total}s of a {span}s run"


def test_operator_latency_is_excluded_from_machine_time(lot_id):
    """A person's response time is not something the factory did.

    LOT-1003's capture shows 61s between the question and the answer — the
    interval a human (here, the harness) took to reply. Counting that as machine
    time would overstate the pipeline by a factor of four.
    """
    for beat in timings(lot_id):
        if beat["beat_id"] in ("human_gate", "human_authority"):
            assert beat["measured_is_operator_latency"] is True
        else:
            assert beat["measured_is_operator_latency"] is False


def test_every_beat_is_on_screen_long_enough_to_read(lot_id):
    """No real beat flashes past. Binding genuinely took 16ms; 16ms is not a frame."""
    for beat in timings(lot_id):
        assert beat["film_s"] >= 0.6, (
            f"{lot_id}: beat {beat['beat_id']} holds for only {beat['film_s']}s"
        )


def test_only_a_real_question_gets_the_decision_hold(lot_id):
    """LOT-1005 escalates without asking anything, and must not stage a pause.

    Holding a security halt's escalation for the full decision beat would show a
    deliberation that never happened.
    """
    for beat in timings(lot_id):
        if beat["beat_id"] == "human_gate" and not beat["interaction_required"]:
            assert beat["film_s"] < 1.5, (
                f"{lot_id}: an unanswered escalation is held as if it were a decision"
            )


def test_the_verifier_never_reads_as_instant(lot_id):
    """Independent verification is the product; it must be visible as work."""
    verifiers = [b for b in timings(lot_id) if b["beat_id"] == "verifier"]
    if not verifiers:
        pytest.skip("no verifier ran in this scenario")
    for beat in verifiers:
        assert beat["measured_s"] > 1.0, (
            f"{lot_id}: verifier measured {beat['measured_s']}s — suspiciously fast"
        )
        assert beat["film_s"] >= 1.0
