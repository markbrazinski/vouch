"""P1-9 verifier observability and P1-10 evaluation-artifact quality.

These tests assert the harness PRESERVES enough evidence for an independent
auditor. They deliberately assert nothing about whether the gate passes: the
verdict is not this iteration's to change, and the historical corpus and
results are preserved as evidence.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from vouch.v2.agents import AgentRun, IndependentVerifier
from vouch.v2.contracts import (
    EvidenceApplicabilityBrief,
    GoverningBasis,
    RequiredTest,
    Sufficiency,
)
from vouch.v2.evalcases import CASES
from vouch.v2.evaluation import (
    CaseScore,
    derived_metrics,
    gate_verdict,
    per_requirement_applicability,
    run_agent_config,
    run_all,
    summarize,
)
from vouch.v2.fixtures import COA_CLEAN, build_corpus
from vouch.v2.lifecycle import EventLog
from vouch.v2.persistence import InMemoryRecordStore
from vouch.v2.workflow import VouchV2

REPO = Path(__file__).resolve().parents[2]


# ==========================================================================
# P1-9 — verifier observability, through the ORDINARY contract
# ==========================================================================


class DeterministicWrongBasis(IndependentVerifier):
    """A test double standing in for the ACTOR's error.

    P1-9 permits inducing the actor error with a double, but requires the
    VERIFIER to travel through its ordinary contract. So this double replaces
    the investigator; the real IndependentVerifier runs untouched.
    """


def _wrong_basis_investigator(corpus):
    from vouch.v2.agents import ApplicabilityInvestigator

    class PlausibleButWrong(ApplicabilityInvestigator):
        def run(self, **kwargs):
            # Rev B is plausible: the supplier COA cites it. It is not the
            # governing basis for a lot received after C took effect.
            brief = EvidenceApplicabilityBrief(
                governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="B"),
                required_tests=[
                    RequiredTest(name="tensile_strength"), RequiredTest(name="hardness")
                ],
                sufficiency=Sufficiency.SUFFICIENT,
            )
            return AgentRun(brief, "test-double", "wrong-basis-v1", "h", [], True)

    return PlausibleButWrong(corpus)


def test_verifier_catches_a_wrong_basis_through_the_normal_pipeline():
    """The required P1-9 scenario.

    Investigator resolves a plausible but wrong basis; the REAL verifier
    independently resolves the correct one; the normal pipeline produces
    MATERIAL_DISAGREEMENT and mutates nothing.
    """
    corpus = build_corpus()
    v = VouchV2(
        corpus,
        investigator=_wrong_basis_investigator(corpus),
        record_store=InMemoryRecordStore(),
    )
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "MATERIAL_DISAGREEMENT"
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"
    assert v.capabilities.ledger == []


def test_the_disagreement_is_fully_observable():
    """P1-9: complete brief, selected basis, tool trail, differing values."""
    corpus = build_corpus()
    v = VouchV2(
        corpus,
        investigator=_wrong_basis_investigator(corpus),
        record_store=InMemoryRecordStore(),
    )
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    record = outcome.record

    # The verifier travelled its ordinary contract: real tools, real brief.
    assert record.verifier.brief
    assert record.verifier.brief["governing_basis"]["revision"] == "C"
    assert record.verifier.tool_events, "verifier must have called real tools"
    assert record.verifier.model_id and record.verifier.prompt_version

    # The disagreement names both sides with actual values.
    assert "revision" in record.reconciliation.differing_fields
    assert record.reconciliation.investigator_values["revision"] == "B"
    assert record.reconciliation.verifier_values["revision"] == "C"


def test_verifier_does_not_falsely_disagree_on_a_clean_case():
    """The other half of the measurement: catch rate means nothing without it."""
    corpus = build_corpus()
    v = VouchV2(corpus, record_store=InMemoryRecordStore())
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.disposition == "RELEASE"
    assert outcome.record.reconciliation.outcome in (
        "MATCH", "NON_MATERIAL_DIFFERENCE"
    )


def test_verifier_runs_are_captured_in_the_eval_harness():
    """P1-9: for every live verifier run, persist the full picture."""
    case = CASES[0]
    capture: dict = {}
    run_agent_config(case, with_verifier=True, capture=capture)

    verifier = capture["verifier"]
    assert verifier["brief"] is not None
    assert verifier["basis"]
    assert verifier["model_id"] and verifier["prompt_version"] and verifier["prompt_hash"]
    assert "tool_calls" in verifier
    assert capture["reconciliation"]["outcome"]
    assert "investigator_values" in capture["reconciliation"]


# ==========================================================================
# P1-10 — artifact quality
# ==========================================================================


def test_capture_records_everything_an_auditor_needs():
    case = CASES[0]
    capture: dict = {}
    run_agent_config(case, with_verifier=True, capture=capture)

    for key in ("investigator", "verifier", "reconciliation", "claims", "events"):
        assert key in capture

    investigator = capture["investigator"]
    for key in (
        "model_id", "prompt_version", "prompt_hash", "temperature", "brief",
        "brief_hash", "tool_calls", "latency_ms", "attempts", "failure_category",
        "schema_valid",
    ):
        assert key in investigator, f"missing {key}"


def test_per_requirement_applicability_is_reported():
    """P1-10: per-test applicability, not only a whole-case boolean."""
    case = next(c for c in CASES if len(c.gold_applicability) > 1)
    capture: dict = {}
    result = run_agent_config(case, with_verifier=False, capture=capture)

    rows = per_requirement_applicability(case, result)
    assert len(rows) == len(case.gold_applicability)
    for row in rows:
        assert set(row) == {"requirement", "expected", "predicted", "correct"}


def test_derived_metrics_cover_the_required_measures():
    results = run_all()
    scores = [CaseScore(**s) for s in results["scores"]]
    metrics = derived_metrics(scores)

    assert "governing_basis_accuracy" in metrics
    assert "correct_abstention" in metrics
    assert "verifier" in metrics
    assert "catch_rate" in metrics["verifier"]
    assert "false_disagreement_rate" in metrics["verifier"]
    assert "unsafe_release_count" in metrics
    for segment in ("RULE_SOLVABLE", "AGENT_VALUABLE", "HUMAN_ONLY"):
        assert segment in metrics["governing_basis_accuracy"]["A"]


def test_metrics_do_not_change_the_verdict():
    """derived_metrics DESCRIBES the result; gate_verdict DECIDES it."""
    results = run_all()
    before, before_detail = gate_verdict(results["summary"])
    derived_metrics([CaseScore(**s) for s in results["scores"]])
    after, after_detail = gate_verdict(results["summary"])

    assert (before, before_detail) == (after, after_detail)


def test_capture_does_not_change_scores():
    """Instrumentation must be inert with respect to what is measured."""
    case = CASES[0]
    without = run_agent_config(case, with_verifier=True)
    with_capture = run_agent_config(case, with_verifier=True, capture={})

    assert without["basis"] == with_capture["basis"]
    assert without["applicability"] == with_capture["applicability"]
    assert without["disposition"] == with_capture["disposition"]
    assert without.get("reconciliation") == with_capture.get("reconciliation")


def test_gate_runner_emits_provenance_and_checkpoints(tmp_path):
    """End-to-end: the runner writes provenance, captures and checkpoints.

    This is an ENGINEERING test that the harness works — not an official
    benchmark run, and it asserts nothing about the verdict.
    """
    out = tmp_path / "engineering_run.json"
    result = subprocess.run(
        [sys.executable, "scripts/run_v2_gate.py", "--out", str(out), "--only", "RS-01,AV-01"],
        cwd=REPO, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stderr

    payload = json.loads(out.read_text())
    provenance = payload["provenance"]
    for key in (
        "git_sha", "corpus_version", "baseline_version", "models", "inference",
        "prompts", "policy_version", "mode",
    ):
        assert key in provenance, f"missing provenance {key}"

    assert payload["captures"]
    assert payload["metrics"]
    assert "gate_passed" in payload

    # P1-10: each case checkpointed as it completed.
    checkpoint = out.with_suffix(".partial.jsonl")
    assert checkpoint.exists()
    rows = [json.loads(line) for line in checkpoint.read_text().splitlines() if line]
    assert {row["config"] for row in rows} == {"A", "B", "C"}


def test_historical_eval_artifacts_are_preserved():
    """The commission requires the prior corpus and results kept as evidence."""
    for name in ("gate_run_1.json", "gate_run_2.json"):
        path = REPO / "evals" / "v2" / name
        assert path.exists(), f"{name} must be preserved as historical evidence"
        payload = json.loads(path.read_text())
        assert payload["gate_passed"] is False
        assert payload["scores"]


def test_corpus_is_unchanged_in_size_and_segments():
    """A guard against quietly adding easier cases or deleting failing ones."""
    assert len(CASES) == 18
    counts: dict[str, int] = {}
    for case in CASES:
        counts[case.segment] = counts.get(case.segment, 0) + 1
    assert counts == {"RULE_SOLVABLE": 4, "AGENT_VALUABLE": 11, "HUMAN_ONLY": 3}
