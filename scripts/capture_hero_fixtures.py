#!/usr/bin/env python3
"""Capture Hero B and Hostile responses from the DEPLOYED runtime, verbatim.

    AWS_PROFILE=gatehouse python scripts/capture_hero_fixtures.py

Counterpart to `hero_acceptance.py`, which asserts. This one only records: the
frontend needs the same kind of artifact `hero-a-capture.json` already is — a
real AgentCore response, not a hand-written approximation of one — so that a
rendering test proves the UI handles what the backend actually emits.

Hero B is two invocations against ONE record: the abstain/ask-Quality run, then
the human-evidence resume. Both are written, because the continuation is the
thing being proven and a single terminal frame would hide it.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vouch.config import load  # noqa: E402
from vouch.v2.fixtures import COA_AMBIGUOUS, COA_HOSTILE, QA_RETEST  # noqa: E402

#: Account-specific targeting stays in the gitignored provisioning manifest
#: (contract §13), never in a tracked file. Set VOUCH_RUNTIME_ARN to override.
RUNTIME_ARN = os.environ.get("VOUCH_RUNTIME_ARN", "")
OUT = ROOT / "frontend" / "src" / "decision" / "__tests__"


def invoke(payload: dict) -> dict:
    out = ROOT / "build" / "capture.json"
    out.parent.mkdir(exist_ok=True)
    subprocess.run(
        [
            "aws", "bedrock-agentcore", "invoke-agent-runtime",
            "--agent-runtime-arn", RUNTIME_ARN,
            "--payload", base64.b64encode(json.dumps(payload).encode()).decode(),
            "--region", load().region, str(out),
        ],
        check=True, capture_output=True,
    )
    return json.loads(out.read_text())


def write(name: str, body: dict) -> None:
    (OUT / name).write_text(json.dumps(body, indent=1, default=str) + "\n")
    print(f"  wrote {name}")


def main() -> int:
    if not RUNTIME_ARN:
        print("set VOUCH_RUNTIME_ARN to the deployed AgentCore runtime ARN")
        return 2
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "seed_demo_corpus.py")],
        check=True, capture_output=True,
    )
    print("seeded canonical corpus")

    print("HERO B run 1: ambiguous evidence")
    first = invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1005",
        "document": COA_AMBIGUOUS.decode(),
    })
    record_id = first.get("decision_record_id", "")
    print(f"  record={record_id} disposition={first.get('disposition') or '(none)'} "
          f"qdr={first.get('quality_decision_required')}")
    write("hero-b-run1-capture.json", first)

    print("HERO B run 2: human evidence resumes the same record")
    second = invoke({
        "action": "supply_evidence", "decision_record_id": record_id,
        "lot_id": "LOT-1005", "document": QA_RETEST.decode(),
        "authority_source": "QA-LEAD",
    })
    print(f"  record={second.get('decision_record_id')} "
          f"disposition={second.get('disposition')} "
          f"run_count={(second.get('decision_record') or {}).get('run_count')}")
    write("hero-b-run2-capture.json", second)

    print("HOSTILE: injection payload in an authentic-looking COA")
    hostile = invoke({
        "action": "evaluate_lot", "lot_id": "LOT-1004",
        "document": COA_HOSTILE.decode(),
    })
    print(f"  disposition={hostile.get('disposition') or '(none)'} "
          f"category={hostile.get('failure_category')} "
          f"mutation={hostile.get('mutation') or '{}'}")
    write("hostile-capture.json", hostile)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
