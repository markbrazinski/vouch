"""Evaluation-harness integrity tests.

These guard the MEASUREMENT, not the result. A gate is only worth reporting if
the harness cannot flatter itself, so the tests below check the properties that
made V1's strip test unable to measure anything:

  * eval cases must not encode their own answer in the ERP fields;
  * the deterministic baseline must not be a strawman.
"""

from __future__ import annotations

import pytest

from vouch.v2.evalcases import CASES, by_segment
from vouch.v2.evaluation import (
    build_case_world,
    deterministic_basis_selector,
    gate_verdict,
    run_agent_config,
    run_all,
)


#: Fields that would hand a baseline the interpretive answer. V1's
#: adversarial.py had exactly these (`rev_c_basis`, `corrected_value_cp`,
#: `equivalence.conditions`), which is why its baseline scored 8/8 on the
#: supposedly-agentic slice and the gate could never mean anything.
FORBIDDEN_ERP_KEYS = {
    "governing_rev", "governing_spec", "rev_basis", "rev_c_basis", "correlation",
    "corrected_value_cp", "equivalence", "deviation", "applicable_revision",
    "answer", "truth", "expected", "adjudication_rule", "alias_map",
}


def test_no_eval_case_leaks_its_answer_into_erp_fields():
    """The corpus-integrity rule that makes the gate measurable at all."""
    for case in CASES:
        leaked = FORBIDDEN_ERP_KEYS & set(case.erp)
        assert not leaked, (
            f"{case.case_id}: ERP fields {sorted(leaked)} encode the interpretive "
            "answer; a baseline would read it rather than derive it"
        )


def test_erp_contains_only_plausible_system_of_record_fields():
    allowed = {
        "lot_id", "material_id", "supplier_id", "supplier_site", "received_at",
        "manufactured_at", "po_reference", "customer_id", "quantity",
    }
    for case in CASES:
        extra = set(case.erp) - allowed
        assert not extra, f"{case.case_id}: unexpected ERP fields {sorted(extra)}"


def test_every_segment_is_populated():
    assert len(by_segment("RULE_SOLVABLE")) >= 4
    assert len(by_segment("AGENT_VALUABLE")) >= 10
    assert len(by_segment("HUMAN_ONLY")) >= 3


def test_baseline_handles_incorporation_by_reference():
    """Anti-strawman guard.

    A baseline that ignores incorporation chains would hand the agents a free
    win on AV-01/AV-09. A competent engineer writes that loop, so the baseline
    must have it. This test exists because an earlier version did not, and the
    gate 'passed' purely on that omission.
    """
    case = next(c for c in CASES if c.case_id == "AV-09")
    corpus, claims = build_case_world(case)
    result = deterministic_basis_selector(corpus, case, claims)
    # AV-09's incorporated grain-size requirement IS reported and passes.
    assert result["applicability"].get("grain_size") == "APPLIES"


def test_baseline_handles_scope_containment():
    """The baseline must apply equivalence/deviation scope rules correctly."""
    case = next(c for c in CASES if c.case_id == "AV-02")
    corpus, claims = build_case_world(case)
    result = deterministic_basis_selector(corpus, case, claims)
    # EQV-11 is scoped to 25C; the test ran at 40C.
    assert result["applicability"].get("viscosity") == "NOT_APPLICABLE"


def test_baseline_is_strong_on_rule_solvable():
    """A is EXPECTED to be at or near ceiling here. That is not a failure."""
    scores = run_all(by_segment("RULE_SOLVABLE"))
    a = scores["summary"]["RULE_SOLVABLE"]["A"]
    assert a["basis"] == a["n"]
    assert a["disposition"] == a["n"]


def test_gate_is_measured_only_on_agent_valuable():
    summary = run_all()["summary"]
    _, detail = gate_verdict(summary)
    assert "AGENT_VALUABLE" in detail
    assert "RULE_SOLVABLE" not in detail


def test_gate_verdict_is_reproducible():
    first = gate_verdict(run_all()["summary"])
    second = gate_verdict(run_all()["summary"])
    assert first == second


def test_agent_configs_run_without_bedrock():
    """The harness must work offline so CI can exercise it."""
    case = CASES[0]
    result = run_agent_config(case, with_verifier=True)
    assert result["basis"] is not None
    assert "reconciliation" in result
