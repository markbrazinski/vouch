#!/usr/bin/env python3
"""Run the D21 load-bearing gate against real models.

    AWS_PROFILE=gatehouse VOUCH_V2_MODE=bedrock \
        python scripts/run_v2_gate.py --repeats 1 --out evals/v2/gate_run.json

Configuration A is deterministic and runs once. B and C invoke Nova Pro, so
repeats measure run-to-run stability — which is itself a finding, since V1's
Nova flipped TC-03 across three identical runs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vouch.v2.evalcases import CASES  # noqa: E402
from vouch.v2.evaluation import (  # noqa: E402
    build_case_world,
    deterministic_basis_selector,
    gate_verdict,
    run_agent_config,
    score,
    summarize,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", default="evals/v2/gate_run.json")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    args = parser.parse_args()

    cases = CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in CASES if c.case_id in wanted]

    all_scores = []
    per_run = []

    # A is deterministic: one pass is the whole story.
    for case in cases:
        corpus, claims = build_case_world(case)
        all_scores.append(score(case, deterministic_basis_selector(corpus, case, claims), "A"))

    for repeat in range(args.repeats):
        run_scores = []
        for case in cases:
            started = time.perf_counter()
            b = run_agent_config(case, with_verifier=False)
            c = run_agent_config(case, with_verifier=True)
            elapsed = time.perf_counter() - started

            score_b = score(case, b, "B")
            score_c = score(case, c, "C")
            run_scores.extend([score_b, score_c])
            print(
                f"  run{repeat} {case.case_id:6} {case.segment:14} "
                f"B basis={'Y' if score_b.basis_correct else 'n'} "
                f"appl={'Y' if score_b.applicability_correct else 'n'} "
                f"({score_b.predicted_basis}) | "
                f"C recon={score_c.reconciliation:22} {elapsed:5.1f}s",
                flush=True,
            )
        all_scores.extend(run_scores)
        per_run.append(summarize(run_scores + [s for s in all_scores if s.config == "A"]))

    summary = summarize(all_scores)
    passed, detail = gate_verdict(summary)

    payload = {
        "repeats": args.repeats,
        "n_cases": len(cases),
        "summary": summary,
        "per_run": per_run,
        "gate_passed": passed,
        "gate_detail": detail,
        "scores": [s.__dict__ for s in all_scores],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))

    print()
    print(json.dumps(summary, indent=2))
    print()
    print("GATE:", "PASS" if passed else "FAIL")
    print(detail)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
