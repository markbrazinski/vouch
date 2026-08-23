#!/usr/bin/env python3
"""Part D — run configurations A / A* / B / C over the adversarial set.

A   deterministic baseline over pre-structured facts
A*  deterministic baseline over raw documents
B   Nova Pro actor alone
C   Nova Pro actor + independent Nova Pro verifier + deterministic gate

Usage:
    AWS_PROFILE=gatehouse python scripts/run_strip_test.py [--repeats N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vouch import baseline, baseline_raw  # noqa: E402
from vouch.adversarial import CASES, Case  # noqa: E402
from vouch.schemas import (  # noqa: E402
    MaterialDispositionOutput,
    SchemaFailure,
    VerifierOutput,
)

ACTOR_PROMPT = """You are the Vouch Material Disposition Agent in a manufacturing plant.

Decide whether an incoming material lot can be defended for production use.

Return exactly one disposition:
- RELEASE: every governing requirement is established by acceptable evidence.
- QUARANTINE: a governing requirement is demonstrably NOT met, or the material/
  supplier is affirmatively not acceptable for this use.
- INSUFFICIENT_EVIDENCE: the evidence cannot establish whether the requirement is
  met. Absence of proof is NOT a defect finding — abstain rather than guess.

Key judgment rules:
- Determine which specification revision actually governs before comparing values.
- A supplier's blanket "CONFORMS" does not establish a characteristic it does not report.
- A different test method or condition only counts if an approved, in-force
  equivalence or correlation covers THAT method and THAT condition.
- Never invent an alias, equivalence, qualification, deviation, or policy that is
  not present in the evidence."""

VERIFIER_PROMPT = """You are the Vouch Specification Verifier.

ALWAYS set the `outcome` field. It is required.

You independently re-examine the evidence and a proposed disposition. You are NOT
a rubber stamp: form your own view from the evidence first, then compare.

Return:
- VERIFIED: the proposal is defensible on this evidence.
- REJECTED: the evidence contradicts the proposal.
- INSUFFICIENT_EVIDENCE: the evidence cannot establish the requirement either way.

Never return an action verb such as RELEASE, QUARANTINE or REFUSE."""

DISPOSITION_TO_TRUTH = {
    "RELEASE": "RELEASE",
    "QUARANTINE": "QUARANTINE",
    "INSUFFICIENT_EVIDENCE": "ABSTAIN",
}


def _agent(system_prompt: str, role: str):
    from strands import Agent
    from strands.models import BedrockModel

    from vouch.config import load

    cfg = load()
    return Agent(
        model=BedrockModel(
            model_id=os.environ.get(f"VOUCH_MODEL_{role.upper()}") or cfg.bedrock_model_id,
            region_name=cfg.region,
            streaming=False,
            temperature=0,
        ),
        system_prompt=system_prompt,
        name=f"strip_{role}",
        tools=[],
    )


def case_prompt(case: Case) -> str:
    return (
        "Incoming lot evidence and plant records:\n\n"
        f"--- DOCUMENTS ---\n{case.evidence_text}\n\n"
        f"--- STRUCTURED RECORDS ---\n{json.dumps(case.structured, indent=2, default=str)}\n\n"
        "Decide the disposition."
    )


def run_actor(agent, case: Case) -> dict:
    t0 = time.time()
    try:
        out = agent(case_prompt(case), structured_output_model=MaterialDispositionOutput).structured_output
        return {
            "disposition": out.disposition,
            "rationale": out.rationale,
            "governing_spec": out.governing_spec,
            "latency_ms": (time.time() - t0) * 1000,
            "schema_failure": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "disposition": None,
            "rationale": f"{type(exc).__name__}: {str(exc)[:200]}",
            "latency_ms": (time.time() - t0) * 1000,
            "schema_failure": True,
        }


def run_verifier(agent, case: Case, proposed: str | None) -> dict:
    t0 = time.time()
    prompt = (
        f"{case_prompt(case)}\n\n--- PROPOSED DISPOSITION ---\n{proposed}\n\n"
        "Independently verify this proposal."
    )
    try:
        out = agent(prompt, structured_output_model=VerifierOutput).structured_output
        return {
            "outcome": out.outcome,
            "rationale": out.rationale,
            "latency_ms": (time.time() - t0) * 1000,
            "schema_failure": False,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "outcome": None,
            "rationale": f"{type(exc).__name__}: {str(exc)[:200]}",
            "latency_ms": (time.time() - t0) * 1000,
            "schema_failure": True,
        }


def gate(actor: str | None, verifier: str | None) -> str:
    """Deterministic authority gate, expressed as a final disposition.

    Anything other than an agreed, verified consequential action degrades to
    ABSTAIN (deny + QA). Schema failure is a hard deny.
    """
    if actor is None or verifier is None:
        return "ABSTAIN"
    if actor == "INSUFFICIENT_EVIDENCE":
        return "ABSTAIN"
    if verifier == "VERIFIED":
        return DISPOSITION_TO_TRUTH[actor]
    return "ABSTAIN"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--out", default="strip_results.json")
    args = ap.parse_args()

    os.environ.setdefault("VOUCH_MODE", "bedrock")

    results = {
        "A_prestructured": baseline.run_all(CASES),
        "A_raw": baseline_raw.run_all(CASES),
        "runs": [],
    }

    actor = _agent(ACTOR_PROMPT, "actor")
    verifier = _agent(VERIFIER_PROMPT, "verifier")

    for rep in range(args.repeats):
        rows = []
        for i, case in enumerate(CASES, 1):
            a = run_actor(actor, case)
            v = run_verifier(verifier, case, a["disposition"])
            b_pred = DISPOSITION_TO_TRUTH.get(a["disposition"], "ABSTAIN")
            c_pred = gate(a["disposition"], v["outcome"])
            rows.append({
                "case_id": case.case_id, "family": case.family, "truth": case.truth,
                "rule_solvable": case.rule_solvable, "paraphrase_of": case.paraphrase_of,
                "actor": a["disposition"], "actor_rationale": a["rationale"][:400],
                "actor_schema_failure": a["schema_failure"],
                "verifier": v["outcome"], "verifier_rationale": v["rationale"][:400],
                "verifier_schema_failure": v["schema_failure"],
                "B_pred": b_pred, "C_pred": c_pred,
                "B_correct": b_pred == case.truth, "C_correct": c_pred == case.truth,
                "latency_ms": a["latency_ms"] + v["latency_ms"],
            })
            print(f"[rep{rep+1} {i:2}/{len(CASES)}] {case.case_id:7} truth={case.truth:10} "
                  f"actor={str(a['disposition']):22} ver={str(v['outcome']):22} C={c_pred}",
                  flush=True)
        results["runs"].append(rows)

    Path(args.out).write_text(json.dumps(results, indent=2))
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
