#!/usr/bin/env python3
"""Hero A and Hero B acceptance, through the DEPLOYED AgentCore runtime.

    AWS_PROFILE=gatehouse python scripts/hero_acceptance.py [--runs 3] [--hero A|B|both]

Every run starts from a re-seeded canonical state and drives the deployed
runtime over `invoke-agent-runtime`, so what is measured is the thing that is
deployed — real Nova reasoners, real S3, real DynamoDB — not a local
composition that resembles it.

A run is CLEAN when the business outcome is reached. Internal non-material
wording may vary between runs; the state transitions may not.
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

from vouch.config import load  # noqa: E402
from vouch.v2.fixtures import COA_AMBIGUOUS, COA_HERO, QA_RETEST  # noqa: E402

#: The account id is account-specific targeting information: it lives in the
#: gitignored provisioning manifest (contract §13), never in a tracked file.
#: Set VOUCH_RUNTIME_ARN to point at a different deployed runtime.
RUNTIME_NAME = os.environ.get("VOUCH_RUNTIME_NAME", "Gatehouse-IWAmEp93XP")


def runtime_arn() -> str:
    """The deployed runtime, composed from configuration rather than literal."""
    override = os.environ.get("VOUCH_RUNTIME_ARN")
    if override:
        return override
    config = load()
    if not config.account_id:
        raise SystemExit(
            "no account id: set VOUCH_RUNTIME_ARN, or AWS_ACCOUNT_ID, or "
            "provide provisioning.json"
        )
    return (
        f"arn:aws:bedrock-agentcore:{config.region}:{config.account_id}"
        f":runtime/{RUNTIME_NAME}"
    )


def invoke(payload: dict) -> dict:
    """One real AgentCore invocation."""
    out = ROOT / "build" / "invoke.json"
    out.parent.mkdir(exist_ok=True)
    subprocess.run(
        [
            "aws", "bedrock-agentcore", "invoke-agent-runtime",
            "--agent-runtime-arn", runtime_arn(),
            "--payload", base64.b64encode(json.dumps(payload).encode()).decode(),
            "--region", load().region, str(out),
        ],
        check=True, capture_output=True,
    )
    return json.loads(out.read_text())


def seed() -> None:
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo_corpus.py")],
        check=True, capture_output=True,
    )


def hero_a() -> dict:
    """quarantine -> consequence -> recovery."""
    seed()
    result = invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1002",
        "document": COA_HERO.decode(),
    })
    recovery = (result.get("consequences") or {}).get("recovery") or {}
    verdicts = {c["candidate_id"]: c["verdict"] for c in recovery.get("candidates", [])}
    readiness = {
        c["order_id"]: (c["from"], c["to"])
        for c in (result.get("consequences") or {}).get("readiness_changes", [])
    }
    checks = {
        "disposition QUARANTINE": result.get("disposition") == "QUARANTINE",
        "lot mutated": bool(result.get("mutation")),
        "C-417 READY->BLOCKED": readiness.get("C-417") == ("READY", "BLOCKED"),
        "a NOT_FEASIBLE": "NOT_FEASIBLE" in verdicts.values(),
        "a REFUSED": "REFUSED" in verdicts.values(),
        "an ELIGIBLE": "ELIGIBLE" in verdicts.values(),
        "C-418 resequenced": recovery.get("executed") is True,
        "nova reasoners": result.get("backend", {}).get("reasoners") == "BEDROCK_NOVA",
        "durable": result.get("backend", {}).get("durable") is True,
    }
    return {
        "record": result.get("decision_record_id", ""),
        "disposition": result.get("disposition", ""),
        "verdicts": verdicts,
        "checks": checks,
        "clean": all(checks.values()),
        "reason": result.get("reason", ""),
    }


def hero_b() -> dict:
    """abstain / disagree -> human evidence -> same-record resume -> RELEASE."""
    seed()
    first = invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1003",
        "document": COA_AMBIGUOUS.decode(),
    })
    record_id = first.get("decision_record_id", "")

    # The product requirement: Vouch could not establish the evidence and asked
    # Quality. INSUFFICIENT_EVIDENCE and a genuine MATERIAL_DISAGREEMENT are
    # both truthful ways to reach that, so both are accepted — what may not
    # happen is a release, or an unsafe capability.
    #: Opening the QA case IS a mutation, and the right one — `create_qa_review`
    #: goes through the same policy/capability path as any other. What must not
    #: happen on the first run is a LOT state change, so that is what is
    #: checked rather than "no mutation at all", which would have failed the
    #: system for doing exactly what it should.
    first_mutation = first.get("mutation") or {}
    first_ok = {
        "asked quality": first.get("quality_decision_required") is True,
        "no release": first.get("disposition") != "RELEASE",
        "no lot state change": first_mutation.get("action")
        in (None, "", "create_qa_review"),
        "reason persisted": bool(first.get("reason")),
    }

    second = invoke({
        "action": "supply_evidence", "decision_record_id": record_id,
        "lot_id": "LOT-1003", "document": QA_RETEST.decode(),
        "authority_source": "QA-LEAD",
    })
    record = second.get("decision_record") or {}
    readiness = invoke({"action": "readiness", "order_id": "C-419"})

    checks = {
        **first_ok,
        "same record": second.get("decision_record_id") == record_id,
        "run_count 2": record.get("run_count") == 2,
        "RELEASE": second.get("disposition") == "RELEASE",
        "capability consumed": (second.get("mutation") or {}).get("action")
        == "release_lot",
        "C-419 READY": readiness.get("readiness") == "READY",
        "nova reasoners": second.get("backend", {}).get("reasoners") == "BEDROCK_NOVA",
    }
    return {
        "record": record_id,
        "first_disposition": first.get("disposition") or "(none)",
        "first_category": first.get("failure_category", ""),
        "second_disposition": second.get("disposition", ""),
        "run_count": record.get("run_count"),
        "checks": checks,
        "clean": all(checks.values()),
        "reason": first.get("reason", ""),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--hero", choices=["A", "B", "both"], default="both")
    args = parser.parse_args()

    heroes = {"A": hero_a, "B": hero_b}
    selected = ["A", "B"] if args.hero == "both" else [args.hero]
    results: dict[str, list[dict]] = {}
    ok = True

    for name in selected:
        results[name] = []
        for run in range(1, args.runs + 1):
            started = time.time()
            try:
                outcome = heroes[name]()
            except Exception as exc:  # noqa: BLE001
                outcome = {"clean": False, "error": f"{type(exc).__name__}: {exc}"}
            outcome["elapsed_s"] = round(time.time() - started, 1)
            results[name].append(outcome)
            state = "CLEAN" if outcome["clean"] else "DIRTY"
            print(
                f"HERO {name} run {run}: {state} "
                f"record={outcome.get('record', '')} "
                f"({outcome['elapsed_s']}s)",
                flush=True,
            )
            if not outcome["clean"]:
                ok = False
                failed = [
                    k for k, v in (outcome.get("checks") or {}).items() if not v
                ]
                print(f"    failed: {failed or outcome.get('error')}", flush=True)

    (ROOT / "build" / "hero_acceptance.json").write_text(
        json.dumps(results, indent=1, default=str)
    )
    print("\nALL CLEAN" if ok else "\nNOT CLEAN")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
