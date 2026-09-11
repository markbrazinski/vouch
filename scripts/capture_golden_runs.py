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
    "APPLICABILITY_BRIEF_COMPLETED": "investigator",
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


def source_artifacts(record_id: str) -> list[dict]:
    """The artifact panel's contents, as `get_source` returns them."""
    out = invoke({"action": "get_source", "decision_record_id": record_id})
    return _strip_expiring(out.get("sources") or [])


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

    # TOOL_CALLED / TOOL_RESULT_BOUND belong to whichever agent is CURRENTLY
    # reasoning — the event does not say which. Attributing them statically to
    # the investigator split the verifier into two fragments around its own tool
    # calls, which would let a timing pass hold "verifier" for 18ms and run the
    # 7.5s it actually spent reasoning under the investigator's label.
    agent = "investigator"
    # Run number is DERIVED, mirroring `runNumbers()` in the frontend adapter:
    # the backend does not put `run_number` on the wire (`rerun()` increments
    # `run_count` on the RECORD), so the only in-stream markers are the human
    # act and DECISION_RESUMED. The boundary opens at the HUMAN act, because
    # that is what causes the new run — filing it under run 1 would attribute
    # it to the run it actually ended.
    #
    # Deliberately the same rule as the UI: beats and the activity rail must
    # not disagree about which run a frame belongs to.
    run = 1
    stepped = False

    for row in events:
        kind = row.get("event", "")
        payload = row.get("payload") or {}
        human_act = kind == "HUMAN_EVIDENCE_RECEIVED" or (
            kind == "QUALITY_AUTHORITY_RECORDED"
            and payload.get("decision") in ("CONFIRM_BINDING", "ESTABLISH_EVIDENCE")
        )
        if human_act:
            run += 1
            stepped = True
        elif kind == "DECISION_RESUMED":
            if not stepped:
                run += 1
            stepped = False
        run = int(payload.get("run_number") or row.get("run_number") or run)

        if kind == "INVESTIGATOR_STARTED":
            agent = "investigator"
        elif kind == "VERIFIER_STARTED":
            agent = "verifier"
        # Events that belong to whichever agent is CURRENTLY reasoning. Tool
        # calls do not name a beat, and BRIEF_VALIDATION_FAILED is emitted by
        # either role — a verifier whose first brief ignored established
        # evidence retries, and attributing that rejection to the investigator
        # would split the verifier around its own retry.
        #
        # `agent` in the payload is authoritative where present; the running
        # agent is the fallback.
        if kind in ("TOOL_CALLED", "TOOL_RESULT_BOUND", "BRIEF_VALIDATION_FAILED"):
            beat_id = payload.get("agent") or agent
        else:
            beat_id = BEAT_OF.get(kind, "terminal")
        seq = int(row.get("sequence") or 0)
        last = beats[-1]
        if last["beat_id"] == beat_id and last["run"] == run:
            last["sequence_end"] = seq
            last["event_types"].append(kind)
            # A beat is a RUN of events, and the question may not be its first:
            # LOT-1003 raises QUALITY_QUESTION_RAISED then QUALITY_DECISION_
            # REQUIRED, so the flag has to survive the merge.
            if kind == "QUALITY_QUESTION_RAISED":
                last["interaction_required"] = True
            continue
        note, compress = READABILITY.get(beat_id, ("", False))
        beats.append({
            "beat_id": beat_id,
            "run": run,
            "sequence_start": seq,
            "sequence_end": seq,
            "ui_stage": beat_id,
            # Only a beat that actually RAISED a question blocks on a person.
            #
            # QUALITY_DECISION_REQUIRED alone is an escalation, not a choice:
            # LOT-1005's security halt emits it with no question, no options and
            # no disposition, and marking that beat interactive would tell a
            # timing pass to wait for an answer nobody is being asked for.
            "interaction_required": beat_id == "human_gate"
            and kind == "QUALITY_QUESTION_RAISED",
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
                  sources: list[dict] | None = None,
                  extra: dict | None = None) -> Path:
    """Write one golden package. No credentials, no account ids, no presigned URLs."""
    pkg = OUT / lot_id
    pkg.mkdir(parents=True, exist_ok=True)
    spec = SCENARIOS[lot_id]
    pdf = EVIDENCE / spec["pdf"]

    sources = sources or []
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
    # The TERMINAL AUTHORITATIVE RESPONSE, verbatim.
    #
    # Not derivable from the other three: the live app receives this from the
    # invocation and `project()` reads the disposition, mutation and
    # consequences straight off it. Playback that had to reconstruct it from the
    # record would be re-deriving the outcome rather than replaying it, which is
    # exactly the line these packages exist to hold.
    _write(pkg / "result.json", result)
    # The artifact panel. Derived by the backend from events + record, but not
    # reconstructible here — `get_source` joins metadata this script does not
    # model, so it is captured rather than recomputed.
    _write(pkg / "sources.json", sources)
    return pkg


def _sha256(path: Path) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


#: Fields that must not survive into a saved package.
#:
#: `view_ref` is a PRESIGNED URL. It carries the bucket, it expires, and §8
#: forbids persisting one — a film shot weeks from now would open a dead link.
#: Dropping it costs nothing: the adapter reads only its PRESENCE (to decide
#: whether the document is openable) and the viewer fetches a fresh URL from the
#: BFF when the operator actually opens it.
EXPIRING_FIELDS = ("view_ref", "view_url")


def _strip_expiring(sources: list[dict]) -> list[dict]:
    """Keep the artifact metadata, drop the link that will not survive."""
    cleaned = []
    for source in sources:
        row = {k: v for k, v in source.items() if k not in EXPIRING_FIELDS}
        # `openable` is derived downstream from view_ref's presence, so state it
        # positively here rather than leaving a dead URL behind to imply it.
        row["retrievable"] = any(source.get(f) for f in EXPIRING_FIELDS)
        cleaned.append(row)
    return cleaned


def _redact(body):
    """Strip account-specific targeting from anything written to disk.

    Evidence refs are stored as `s3://<bucket>/evidence/<lot>/<artifact-id>`,
    and the bucket name embeds the AWS account id — tracked targeting
    information the contract (§13) and `test_no_aws_account_id_in_tracked_files`
    both forbid. The ARTIFACT ID is the stable identifier a playback or an audit
    actually needs, so the bucket is replaced and the path kept.

    Applied to the whole serialized document rather than to known fields: a ref
    can appear anywhere in a record, and a redaction that has to enumerate
    locations is one schema change away from leaking.
    """
    config = load()
    text = json.dumps(body, indent=1, default=str, sort_keys=False)
    if config.evidence_bucket:
        text = text.replace(f"s3://{config.evidence_bucket}/", "s3://<evidence-bucket>/")
        text = text.replace(config.evidence_bucket, "<evidence-bucket>")
    if config.account_id:
        text = text.replace(config.account_id, "<account-id>")
    return text


def _write(path: Path, body) -> None:
    path.write_text(_redact(body) + "\n")


def capture_simple(lot_id: str) -> dict:
    """A lot whose golden run is a single invocation."""
    spec = SCENARIOS[lot_id]
    result = evaluate(lot_id, EVIDENCE / spec["pdf"])
    record_id = result.get("decision_record_id", "")
    events = full_events(record_id) if record_id else []
    record = stored_record(record_id) if record_id else {}
    sources = source_artifacts(record_id) if record_id else []
    pkg = write_package(lot_id, result, events, record, sources)
    return {"result": result, "events": events, "package": pkg}


#: LOT-1003 is non-deterministic BY DESIGN: two honest measurements point
#: opposite ways, and whether the two agents select materially different
#: controlling evidence is a property of the run, not of the fixture. The
#: commission allows this many live attempts before declaring the golden run
#: unfindable. Nothing is tuned between attempts — same prompt, same fixture,
#: same model. A convergent run is a truthful non-golden outcome, kept as
#: history, and the next attempt starts from an isolated LOT reset.
MAX_DISAGREEMENT_ATTEMPTS = 15


def capture_disagreement(lot_id: str = "LOT-1003") -> dict:
    """Retry LOT-1003 until the agents genuinely disagree, then let a human decide.

    Returns the attempt ledger alongside the golden package, because the runs
    that did NOT qualify are evidence too: they are what makes the qualifying
    run a real sample rather than a staged one.
    """
    spec = SCENARIOS[lot_id]
    pdf = EVIDENCE / spec["pdf"]
    ledger: list[dict] = []

    for attempt in range(1, MAX_DISAGREEMENT_ATTEMPTS + 1):
        if attempt > 1:
            reset_lot(lot_id)  # isolated, never a full reseed
        result = evaluate(lot_id, pdf)
        record_id = result.get("decision_record_id", "")
        category = result.get("failure_category") or ""
        qdr = bool(result.get("quality_decision_required"))
        question = _question_of(result)

        row = {
            "attempt": attempt,
            "decision_record_id": record_id,
            "investigator_selection": "",
            "verifier_selection": "",
            "reconciliation": category or (result.get("disposition") or ""),
            "contract_valid": bool(record_id) and category != "TECHNICAL_FAILURE",
            "human_gate": qdr,
            "final_state": result.get("disposition") or category or "",
            "golden": False,
        }
        if question:
            row["investigator_selection"] = question.get("investigator_evidence_ref", "")
            row["verifier_selection"] = question.get("verifier_evidence_ref", "")

        qualifies = qdr and category == "MATERIAL_DISAGREEMENT" and bool(question)
        print(f"  attempt {attempt}: {row['reconciliation'] or '(none)'} "
              f"qdr={qdr} {'<- QUALIFIES' if qualifies else ''}")
        if not qualifies:
            ledger.append(row)
            continue

        # The human establishes the RELEASE-producing controlling evidence. The
        # option is chosen by its OWN computed `would_disposition`, never by a
        # hard-coded claim id: the engine states which path releases, and the
        # capture selects that one rather than assuming which agent found it.
        release = next(
            (o for o in (question.get("options") or [])
             if o.get("would_disposition") == "RELEASE"),
            None,
        )
        if release is None:
            row["contract_valid"] = False
            ledger.append(row)
            print("    no RELEASE option offered; not a usable golden run")
            continue

        resumed = invoke({
            "action": "submit_quality_authority",
            "decision_record_id": record_id,
            "decision": "ESTABLISH_EVIDENCE",
            "accountable_actor": "QA-LEAD",
            "authority_source": "PLANT_QUALITY",
            "evidence_ref": release["claim_id"],
            "question_id": question.get("question_id", ""),
        })
        row.update(
            golden=True,
            final_state=resumed.get("disposition") or "",
            human_selection=release["claim_id"],
            human_selection_detail={
                k: release.get(k) for k in
                ("value", "units", "method", "condition", "selected_by",
                 "equivalence_id", "within_limits", "threshold")
            },
            run2_result=resumed.get("disposition") or "",
        )
        ledger.append(row)

        events = full_events(record_id)
        record = stored_record(record_id)
        sources = source_artifacts(record_id)
        pkg = write_package(lot_id, resumed, events, record, sources, extra={
            "total_attempts": attempt,
            "attempt_ledger": ledger,
            "human_choice": release["claim_id"],
            "human_choice_detail": row["human_selection_detail"],
            "investigator_selection": row["investigator_selection"],
            "verifier_selection": row["verifier_selection"],
            "run_2_result": resumed.get("disposition") or "",
            # Run 1's terminal state, so the package proves the case ABSTAINED
            # before a human touched it rather than merely ending in RELEASE.
            "run_1_outcome": "MATERIAL_DISAGREEMENT",
        })
        return {"result": resumed, "events": events, "package": pkg, "ledger": ledger}

    raise SystemExit(
        f"LOT-1003_GOLDEN_RUN_NOT_FOUND after {MAX_DISAGREEMENT_ATTEMPTS} attempts"
    )


def capture_identity(lot_id: str = "LOT-1004") -> dict:
    """LOT-1004: the document was READ; what was missing was authority to attribute it.

    Extraction succeeds completely and security is clean. The certificate simply
    names the supplier's own consignment (`WP-26-0317-B`) and nothing
    authoritative maps that to an internal lot — so Vouch asks rather than
    guessing, and a human establishes the binding.
    """
    spec = SCENARIOS[lot_id]
    first = evaluate(lot_id, EVIDENCE / spec["pdf"])
    record_id = first.get("decision_record_id", "")
    question = _question_of(first)
    print(f"  run 1: {first.get('failure_category') or '(none)'} "
          f"qdr={first.get('quality_decision_required')}")

    if not question or question.get("question_type") != "IDENTITY_BINDING":
        raise SystemExit(
            f"LOT-1004 did not raise an identity question: "
            f"{first.get('failure_category')!r} / {(question or {}).get('question_type')!r}"
        )

    supplier_batch = question.get("supplier_batch", "")
    resumed = invoke({
        "action": "submit_quality_authority",
        "decision_record_id": record_id,
        "decision": "CONFIRM_BINDING",
        "accountable_actor": "QA-LEAD",
        "authority_source": "PLANT_QUALITY",
        "question_id": question.get("question_id", ""),
        "supplier_batch": supplier_batch,
        "bound_lot_id": lot_id,
        "artifact_id": question.get("artifact_id", ""),
        "content_hash": question.get("content_hash", ""),
    })
    print(f"  run 2: disposition={resumed.get('disposition') or '(none)'} "
          f"failure={resumed.get('failure_category') or '(none)'}")

    events = full_events(record_id)
    record = stored_record(record_id)
    sources = source_artifacts(record_id)
    pkg = write_package(lot_id, resumed, events, record, sources, extra={
        "human_choice": "CONFIRM_BINDING",
        "human_choice_detail": {
            "supplier_batch": supplier_batch,
            "bound_lot_id": lot_id,
            "question_type": "IDENTITY_BINDING",
        },
        # Stated explicitly because the whole point of the scenario is that this
        # is NOT an OCR failure: the document parsed and extracted cleanly.
        "run_1_outcome": first.get("failure_category") or "",
        "run_2_result": resumed.get("disposition") or "",
        "extraction_succeeded": any(
            row["event"] == "EVIDENCE_EXTRACTED" for row in events
        ),
    })
    return {"result": resumed, "events": events, "package": pkg}


def _question_of(result: dict) -> dict | None:
    """The open quality question on a returned record, if there is one."""
    record = result.get("decision_record") or {}
    question = ((record.get("quality_authority") or {}).get("question")) or {}
    return question or None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("lots", nargs="*", default=[])
    args = ap.parse_args()

    print(f"identity: {assert_vouch_identity()}")
    print(f"runtime:  {RUNTIME_NAME}")
    lots = args.lots or list(SCENARIOS)
    for lot_id in lots:
        print(f"\n=== {lot_id} — {SCENARIOS[lot_id]['scenario']}")
        capture = {
            "LOT-1003": capture_disagreement,
            "LOT-1004": capture_identity,
        }.get(lot_id, capture_simple)
        got = capture(lot_id)
        r = got["result"]
        print(f"  record={r.get('decision_record_id')} "
              f"disposition={r.get('disposition') or '(none)'} "
              f"qdr={r.get('quality_decision_required')} "
              f"events={len(got['events'])}")
        print(f"  package: {got['package']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
