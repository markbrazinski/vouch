#!/usr/bin/env python3
"""Run the D21 load-bearing gate.

    AWS_PROFILE=gatehouse VOUCH_V2_MODE=bedrock \
        python scripts/run_v2_gate.py --repeats 1 --out evals/v2/gate_run.json

Configuration A is deterministic and runs once. B and C invoke the configured
model, so repeats measure run-to-run stability — which is itself a finding,
since V1's Nova flipped TC-03 across three identical runs.

P1-10: every case is checkpointed as it completes, and the artifact preserves
enough raw evidence for an independent auditor to re-derive the result — both
complete briefs, every tool call, per-requirement applicability, reconciliation
differences with actual values, typed failures, latency and retry counts, plus
the git SHA, corpus hash and prompt hashes the run was produced under.

Raw failures REMAIN in the artifact. There are no silent reruns: `--repeats`
records each pass separately rather than replacing a previous one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vouch.v2.agents import (  # noqa: E402
    INVESTIGATOR_PROMPT,
    INVESTIGATOR_PROMPT_VERSION,
    TEMPERATURE,
    TOP_P,
    VERIFIER_PROMPT,
    VERIFIER_PROMPT_VERSION,
    model_id_for,
)
from vouch.v2.contracts import content_hash  # noqa: E402
from vouch.v2.evalcases import CASES  # noqa: E402
from vouch.v2.evaluation import (  # noqa: E402
    CaseScore,
    build_case_world,
    derived_metrics,
    deterministic_basis_selector,
    gate_verdict,
    per_requirement_applicability,
    run_agent_config,
    score,
    summarize,
)
from vouch.v2.reconcile import POLICY_VERSION  # noqa: E402

#: Bumped when the deterministic baseline's LOGIC changes. An auditor comparing
#: two runs needs to know whether config A was the same program.
BASELINE_VERSION = "deterministic-basis-selector-1"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _git_dirty() -> bool:
    try:
        return bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], stderr=subprocess.DEVNULL, text=True
            ).strip()
        )
    except Exception:  # noqa: BLE001
        return True


def _corpus_hash() -> str:
    """Hash of the CASE CORPUS, so a changed corpus is visibly a changed run."""
    return content_hash([asdict(case) for case in CASES])


def provenance(repeats: int, mode: str) -> dict:
    return {
        "git_sha": _git_sha(),
        "git_dirty": _git_dirty(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "repeats": repeats,
        "corpus_version": _corpus_hash(),
        "corpus_case_count": len(CASES),
        "baseline_version": BASELINE_VERSION,
        "policy_version": POLICY_VERSION,
        "models": {
            "investigator": model_id_for("investigator"),
            "verifier": model_id_for("verifier"),
        },
        "inference": {"temperature": TEMPERATURE, "top_p": TOP_P},
        "prompts": {
            "investigator": {
                "version": INVESTIGATOR_PROMPT_VERSION,
                "hash": content_hash(INVESTIGATOR_PROMPT),
            },
            "verifier": {
                "version": VERIFIER_PROMPT_VERSION,
                "hash": content_hash(VERIFIER_PROMPT),
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--out", default="evals/v2/gate_run.json")
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument(
        "--label", default="", help="free-text label recorded in the artifact"
    )
    args = parser.parse_args()

    cases = CASES
    if args.only:
        wanted = {c.strip() for c in args.only.split(",")}
        cases = [c for c in CASES if c.case_id in wanted]

    mode = (os.environ.get("VOUCH_V2_MODE") or os.environ.get("VOUCH_MODE") or "local").lower()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = out.with_suffix(".partial.jsonl")
    if checkpoint.exists():
        checkpoint.unlink()

    meta = provenance(args.repeats, mode)
    meta["label"] = args.label
    all_scores: list[CaseScore] = []
    captures: list[dict] = []
    per_run = []

    def checkpoint_write(row: dict) -> None:
        """P1-10: write each case as it completes, so a crashed or interrupted
        run still leaves the evidence it already produced."""
        with checkpoint.open("a") as handle:
            handle.write(json.dumps(row, default=str) + "\n")

    # A is deterministic: one pass is the whole story.
    for case in cases:
        started = time.perf_counter()
        corpus, claims = build_case_world(case)
        result = deterministic_basis_selector(corpus, case, claims)
        case_score = score(case, result, "A")
        all_scores.append(case_score)
        capture = {
            "case_id": case.case_id,
            "segment": case.segment,
            "config": "A",
            "repeat": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "result": result,
            "score": asdict(case_score),
            "per_requirement": per_requirement_applicability(case, result),
            "baseline_version": BASELINE_VERSION,
        }
        captures.append(capture)
        checkpoint_write(capture)

    for repeat in range(args.repeats):
        run_scores: list[CaseScore] = []
        for case in cases:
            started = time.perf_counter()
            capture_b: dict = {}
            capture_c: dict = {}
            b = run_agent_config(case, with_verifier=False, capture=capture_b)
            c = run_agent_config(case, with_verifier=True, capture=capture_c)
            elapsed = time.perf_counter() - started

            score_b = score(case, b, "B")
            score_c = score(case, c, "C")
            run_scores.extend([score_b, score_c])

            for config, result, case_score, capture in (
                ("B", b, score_b, capture_b),
                ("C", c, score_c, capture_c),
            ):
                capture.update(
                    case_id=case.case_id,
                    segment=case.segment,
                    config=config,
                    repeat=repeat,
                    result=result,
                    score=asdict(case_score),
                    per_requirement=per_requirement_applicability(case, result),
                    gold={
                        "basis": list(case.gold_basis) if case.gold_basis else None,
                        "applicability": case.gold_applicability,
                        "disposition": case.gold_disposition,
                    },
                )
                captures.append(capture)
                checkpoint_write(capture)

            print(
                f"  run{repeat} {case.case_id:6} {case.segment:14} "
                f"B basis={'Y' if score_b.basis_correct else 'n'} "
                f"appl={'Y' if score_b.applicability_correct else 'n'} "
                f"({score_b.predicted_basis}) | "
                f"C recon={score_c.reconciliation:22} {elapsed:5.1f}s",
                flush=True,
            )
        all_scores.extend(run_scores)
        per_run.append(
            summarize(run_scores + [s for s in all_scores if s.config == "A"])
        )

    summary = summarize(all_scores)
    passed, detail = gate_verdict(summary)

    payload = {
        "provenance": meta,
        "repeats": args.repeats,
        "n_cases": len(cases),
        "summary": summary,
        "per_run": per_run,
        "gate_passed": passed,
        "gate_detail": detail,
        "metrics": derived_metrics(all_scores, captures),
        "scores": [asdict(s) for s in all_scores],
        # The raw evidence trail. Kept in full, failures included.
        "captures": captures,
    }
    out.write_text(json.dumps(payload, indent=2, default=str))

    print()
    print(json.dumps(summary, indent=2))
    print()
    print(json.dumps(payload["metrics"], indent=2))
    print()
    print("GATE:", "PASS" if passed else "FAIL")
    print(detail)
    print(f"\nwrote {out}  (checkpoints: {checkpoint})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
