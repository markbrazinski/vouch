#!/usr/bin/env python3
"""Capture film-quality GOLDEN RUNS against the DEPLOYED AgentCore runtime.

    AWS_PROFILE=gatehouse python scripts/capture_golden_runs.py [LOT-1001 ...]

One package per canonical film lot under `golden-runs/<LOT>/`:

    manifest.json        what this run was, and what it did
    events.json          the COMPLETE ordered lifecycle stream, unfiltered
    decision-record.json the durable record, archived runs included
    beats.json           per-beat film index (boundaries only, NO durations)

This script RECORDS. It never asserts an outcome into existence: the run is
whatever the deployed runtime, real Nova reasoners, real Guardrails, real
DynamoDB and real S3 produced. A non-golden outcome is written and reported as
non-golden rather than retried into the shape someone wanted.

Timing is deliberately NOT captured here. `beats.json` stores BOUNDARIES — which
event sequences open and close each beat — so playback cadence can be tuned per
lot and per beat later without re-executing anything.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vouch.config import assert_vouch_identity, load  # noqa: E402

OUT = ROOT / "golden-runs"
EVIDENCE = ROOT / "demo" / "evidence"
RUNTIME_NAME = os.environ.get("VOUCH_RUNTIME_NAME", "Gatehouse-IWAmEp93XP")

#: The canonical film ladder. Source PDF per lot, and what the scenario IS.
#:
#: `scenario` is descriptive, not an assertion: the capture reports what the
#: runtime actually did and flags a mismatch rather than suppressing it.
SCENARIOS: dict[str, dict] = {
    "LOT-1001": {
        "pdf": "northern-alloys-coa-lot-1001.pdf",
        "scenario": "agents agree + deterministic PASS -> RELEASE",
        "expect_disposition": "RELEASE",
        "human": None,
    },
    "LOT-1002": {
        "pdf": "eastern-metals-coa-lot-1002.pdf",
        "scenario": "agents agree + deterministic FAIL -> QUARANTINE, C-417 blocked, C-418 forward",
        "expect_disposition": "QUARANTINE",
        "human": None,
    },
    "LOT-1003": {
        "pdf": "western-polymers-coa-lot-1003.pdf",
        "scenario": "MATERIAL_DISAGREEMENT -> human establishes controlling evidence -> run 2 RELEASE",
        "expect_disposition": "RELEASE",
        "human": "QUALITY",
    },
    "LOT-1004": {
        "pdf": "northern-alloys-coa-batch-wp-26-0317-b.pdf",
        "scenario": "identity/binding ambiguity -> human confirms batch<->lot -> run 2 RELEASE",
        "expect_disposition": "RELEASE",
        "human": "IDENTITY",
    },
    "LOT-1005": {
        "pdf": "central-forgeworks-coa-lot-1005.pdf",
        "scenario": "prompt injection -> Bedrock Guardrails -> SECURITY QUARANTINE, agents never start",
        "expect_disposition": None,
        "human": None,
    },
}

#: Event -> semantic beat. The film index groups the raw stream into the units
#: a viewer actually perceives, which is coarser than the audit stream and must
#: never replace it: `events.json` stays complete.
BEAT_OF: dict[str, str] = {
    "EVIDENCE_RECEIVED": "evidence_received",
    "EVIDENCE_SECURITY_COMPLETED": "security",
    "EVIDENCE_BINDING_MISMATCH": "binding",
    "EVIDENCE_BINDING_COMPLETED": "binding",
    "EVIDENCE_IDENTITY_ESTABLISHED": "binding",
    "EVIDENCE_EXTRACTED": "extraction",
    "EVIDENCE_SNAPSHOT_CREATED": "extraction",
    "INVESTIGATOR_STARTED": "investigator",
    "TOOL_CALLED": "investigator",
    "TOOL_RESULT_BOUND": "investigator",
    "APPLICABILITY_BRIEF_COMPLETED": "investigator",
    "BRIEF_VALIDATION_FAILED": "investigator",
    "VERIFIER_STARTED": "verifier",
    "VERIFIER_BRIEF_COMPLETED": "verifier",
    "RECONCILIATION_COMPLETED": "reconciliation",
    "QUALITY_DECISION_REQUIRED": "human_gate",
    "QUALITY_QUESTION_RAISED": "human_gate",
    "QUALITY_AUTHORITY_RECORDED": "human_authority",
    "HUMAN_EVIDENCE_RECEIVED": "human_authority",
    "DECISION_RESUMED": "run_2_start",
    "DISPOSITION_COMPUTED": "disposition",
    "POLICY_EVALUATED": "disposition",
    "PRECEDENT_CONSULTED": "disposition",
    "CAPABILITY_ISSUED": "mutation",
    "MUTATION_COMPLETED": "mutation",
    "CONSEQUENCE_RECALCULATED": "consequence",
    "READINESS_TRANSITIONED": "consequence",
    "RECOVERY_EVALUATED": "consequence",
    "RECOVERY_EXECUTED": "consequence",
}

#: Beats a viewer must be given time to READ, and beats that may be compressed.
#: This is an editorial note recorded at capture time, not a duration.
READABILITY: dict[str, tuple[str, bool]] = {
    "startup": ("orientation only", True),
    "evidence_received": ("the document arriving; establishes the lot", True),
    "security": ("must be legible when it is the OUTCOME (LOT-1005)", False),
    "extraction": ("mechanical; safe to move through", True),
    "binding": ("identity question needs reading time (LOT-1004)", False),
    "investigator": ("first agent reasoning; sets the grammar", False),
    "verifier": ("independence is the point; must resolve visibly BEFORE disposition", False),
    "reconciliation": ("the comparison; slower when it DIFFERS", False),
    "human_gate": ("the operator must understand the question before the answer", False),
    "human_authority": ("the human act itself; the hinge of the story", False),
    "run_2_start": ("same record resuming; continuity must land", False),
    "disposition": ("the deterministic result and its arithmetic", False),
    "mutation": ("the state actually changing", True),
    "consequence": ("production effect; the 'so what'", False),
    "terminal": ("Outcome / Why / Next Action; the frame that must be read", False),
}


def runtime_arn() -> str:
    override = os.environ.get("VOUCH_RUNTIME_ARN")
    if override:
        return override
    config = load()
    if not config.account_id:
        raise SystemExit("no account id: set VOUCH_RUNTIME_ARN or provide provisioning.json")
    return (
        f"arn:aws:bedrock-agentcore:{config.region}:{config.account_id}"
        f":runtime/{RUNTIME_NAME}"
    )


def invoke(payload: dict) -> dict:
    """One real AgentCore invocation."""
    out = ROOT / "build" / "golden_invoke.json"
    out.parent.mkdir(exist_ok=True)
    proc = subprocess.run(
        [
            "aws", "bedrock-agentcore", "invoke-agent-runtime",
            "--agent-runtime-arn", runtime_arn(),
            "--payload", base64.b64encode(json.dumps(payload).encode()).decode(),
            "--region", load().region, str(out),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"invoke failed: {proc.stderr.strip()[:800]}")
    return json.loads(out.read_text())


def evaluate(lot_id: str, pdf: Path) -> dict:
    """Evaluate a lot from its REAL canonical PDF bytes."""
    return invoke({
        "action": "evaluate_lot",
        "lot_id": lot_id,
        "document_b64": base64.b64encode(pdf.read_bytes()).decode(),
        "content_type": "application/pdf",
    })


def full_events(record_id: str) -> list[dict]:
    """The COMPLETE ordered stream, nothing dropped."""
    return invoke({"action": "get_events", "decision_record_id": record_id})["events"]


def stored_record(record_id: str) -> dict:
    return invoke({"action": "get_decision", "decision_record_id": record_id})


def reset_lot(lot_id: str) -> None:
    """Isolated LOT reset — never a full reseed."""
    from vouch.v2.demo_reset import reset_lot as do_reset
    from vouch.v2.state import DynamoCorpus

    do_reset(DynamoCorpus(load().state_table), lot_id)


def beats_from(events: list[dict]) -> list[dict]:
    """Group the raw stream into contiguous semantic beats.

    A beat is a MAXIMAL RUN of adjacent events mapping to the same beat id
    within the same run number, so a stage the pipeline returns to (an agent
    re-running after human authority) yields a second beat rather than one beat
    spanning the human decision that separates them.

    Durations are deliberately absent. This records WHERE a beat starts and
    ends; how long it plays is a later, per-lot decision.
    """
    beats: list[dict] = [{
        "beat_id": "startup",
        "run": 1,
        "sequence_start": 0,
        "sequence_end": 0,
        "ui_stage": "startup",
        "interaction_required": False,
        "minimum_readability": READABILITY["startup"][0],
        "safe_to_compress": READABILITY["startup"][1],
        "event_types": [],
    }]

    for row in events:
        kind = row.get("event", "")
        beat_id = BEAT_OF.get(kind, "terminal")
        run = int((row.get("payload") or {}).get("run_number") or row.get("run_number") or 1)
        seq = int(row.get("sequence") or 0)
        last = beats[-1]
        if last["beat_id"] == beat_id and last["run"] == run:
            last["sequence_end"] = seq
            last["event_types"].append(kind)
            continue
        note, compress = READABILITY.get(beat_id, ("", False))
        beats.append({
            "beat_id": beat_id,
            "run": run,
            "sequence_start": seq,
            "sequence_end": seq,
            "ui_stage": beat_id,
            # The human gate is the only beat that BLOCKS on a person.
            "interaction_required": beat_id == "human_gate",
            "minimum_readability": note,
            "safe_to_compress": compress,
            "event_types": [kind],
        })

    # The terminal frame is a presentation beat, not an event: it is the frame
    # that remains after the last event, and it is the one a viewer must read.
    last_seq = int(events[-1]["sequence"]) if events else 0
    beats.append({
        "beat_id": "terminal",
        "run": beats[-1]["run"],
        "sequence_start": last_seq,
        "sequence_end": last_seq,
        "ui_stage": "terminal",
        "interaction_required": False,
        "minimum_readability": READABILITY["terminal"][0],
        "safe_to_compress": READABILITY["terminal"][1],
        "event_types": [],
    })
    return beats


def write_package(lot_id: str, result: dict, events: list[dict], record: dict,
                  extra: dict | None = None) -> Path:
    """Write one golden package. No credentials, no account ids, no presigned URLs."""
    pkg = OUT / lot_id
    pkg.mkdir(parents=True, exist_ok=True)
    spec = SCENARIOS[lot_id]
    pdf = EVIDENCE / spec["pdf"]

    beats = beats_from(events)
    runs = max((b["run"] for b in beats), default=1)
    consequences = result.get("consequences") or {}

    manifest = {
        "lot_id": lot_id,
        "scenario": spec["scenario"],
        "decision_record_id": result.get("decision_record_id", ""),
        "run_count": runs,
        # Stable identifiers only: the artifact is named by content hash and
        # filename, never by a bucket path or an expiring URL.
        "source_artifact_id": _sha256(pdf),
        "source_filename": spec["pdf"],
        "model_id": (result.get("backend") or {}).get("reasoners", ""),
        "runtime_version": os.environ.get("VOUCH_RUNTIME_VERSION", ""),
        "runtime_name": RUNTIME_NAME,
        "capture_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "terminal_outcome": result.get("disposition") or result.get("failure_category") or "",
        "mutation": result.get("mutation") or {},
        "production_consequence": consequences,
        "human_interaction": bool(spec["human"]),
        "human_kind": spec["human"] or "",
        "raw_event_count": len(events),
        "beat_count": len(beats),
        "backend": result.get("backend") or {},
    }
    if extra:
        manifest.update(extra)

    _write(pkg / "manifest.json", manifest)
    _write(pkg / "events.json", events)
    _write(pkg / "decision-record.json", record.get("record", record))
    _write(pkg / "beats.json", beats)
    return pkg


def _sha256(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, body) -> None:
    path.write_text(json.dumps(body, indent=1, default=str, sort_keys=False) + "\n")


def capture_simple(lot_id: str) -> dict:
    """A lot whose golden run is a single invocation."""
    spec = SCENARIOS[lot_id]
    result = evaluate(lot_id, EVIDENCE / spec["pdf"])
    record_id = result.get("decision_record_id", "")
    events = full_events(record_id) if record_id else []
    record = stored_record(record_id) if record_id else {}
    pkg = write_package(lot_id, result, events, record)
    return {"result": result, "events": events, "package": pkg}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lots", nargs="*", default=[])
    args = ap.parse_args()

    print(f"identity: {assert_vouch_identity()}")
    print(f"runtime:  {RUNTIME_NAME}")
    lots = args.lots or list(SCENARIOS)
    for lot_id in lots:
        print(f"\n=== {lot_id} — {SCENARIOS[lot_id]['scenario']}")
        got = capture_simple(lot_id)
        r = got["result"]
        print(f"  record={r.get('decision_record_id')} "
              f"disposition={r.get('disposition') or '(none)'} "
              f"qdr={r.get('quality_decision_required')} "
              f"events={len(got['events'])}")
        print(f"  package: {got['package']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
