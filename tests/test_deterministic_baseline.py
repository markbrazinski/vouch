"""Deterministic-baseline comparison.

AGENTS.md ESCALATE: "simple deterministic rules reproduce essentially all
supposedly agentic judgment." That is a claim to test, not assume. This encodes
the baseline so the answer is measured, and so the next-stage eval inherits it.

The honest finding on the current fixtures is recorded in the final assertion.
"""

from __future__ import annotations

import pytest

from vouch.fixtures import add_qa_evidence, build_store
from vouch.tools import EvalTools
from vouch.workflow import Vouch

LOTS = ["LOT-1001", "LOT-1002", "LOT-1003"]


def deterministic_baseline(findings: list[dict]) -> str:
    """The whole rules engine. If this matches the agents everywhere, say so."""
    if any(f["status"] == "OUT_OF_LIMITS" for f in findings):
        return "QUARANTINE"
    if any(f["status"] in ("METHOD_MISMATCH", "NO_EVIDENCE") for f in findings):
        return "INSUFFICIENT_EVIDENCE"
    return "RELEASE"


@pytest.mark.parametrize("lot_id", LOTS)
def test_baseline_matches_agent_on_current_fixtures(lot_id: str):
    """Documents the overlap honestly: on these fixtures, they agree."""
    gh = Vouch(build_store())
    findings = EvalTools(gh.store).evaluate_evidence_against_spec(lot_id)["findings"]
    result = gh.evaluate_lot(f"BASE-{lot_id}", lot_id)

    assert result["actor"]["disposition"] == deterministic_baseline(findings), (
        "agent and rules diverged; update the recorded baseline finding"
    )


def test_baseline_equivalence_is_total_on_current_fixtures():
    """The escalation-worthy result, asserted rather than hand-waved.

    On the current fixture set the deterministic baseline reproduces the actor's
    disposition for every lot, including after QA evidence arrives. The agentic
    layer is therefore NOT yet justified by these cases alone — see
    SMOKE_TEST_REPORT.md 'deterministic baseline' and the eval plan.
    """
    agreements = 0
    total = 0

    for lot_id in LOTS:
        gh = Vouch(build_store())
        findings = EvalTools(gh.store).evaluate_evidence_against_spec(lot_id)["findings"]
        actor = gh.evaluate_lot(f"B-{lot_id}", lot_id)["actor"]["disposition"]
        total += 1
        agreements += actor == deterministic_baseline(findings)

    # resumed case after QA evidence
    gh = Vouch(build_store())
    gh.evaluate_lot("B-RESUME", "LOT-1003")
    add_qa_evidence(gh.store, "LOT-1003")
    findings = EvalTools(gh.store).evaluate_evidence_against_spec("LOT-1003")["findings"]
    actor = gh.evaluate_lot("B-RESUME", "LOT-1003")["actor"]["disposition"]
    total += 1
    agreements += actor == deterministic_baseline(findings)

    assert agreements == total == 4, (
        f"baseline reproduced {agreements}/{total} agent dispositions"
    )
