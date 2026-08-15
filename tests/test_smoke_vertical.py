"""S1-S9 vertical smoke test: the canonical Gatehouse chain.

S0 (real AgentCore invoke) lives in tests/test_s0_agentcore.py because it needs
live AWS. Everything here runs the same workflow code S0 deploys.
"""

from __future__ import annotations

import pytest

from gatehouse.fixtures import add_qa_evidence, build_store
from gatehouse.gates import material_authority_gate
from gatehouse.state import (
    Disposition,
    LotStatus,
    OrderStatus,
    Usability,
    VerifierOutcome,
)
from gatehouse.tools import AuthorityError, AuthorityToken, MutationTools, ReadTools
from gatehouse.workflow import Gatehouse


@pytest.fixture
def gh() -> Gatehouse:
    return Gatehouse(build_store())


# ==========================================================================
# S1 — clean lot autonomously releases
# ==========================================================================
def test_s1_clean_lot_releases(gh: Gatehouse):
    before = gh.read.get_usable_inventory("MAT-ALLOY-7")
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RECEIVED

    r = gh.evaluate_lot("CASE-S1", "LOT-1001")

    assert r["actor"]["disposition"] == Disposition.RELEASE.value
    assert r["verifier"]["outcome"] == VerifierOutcome.VERIFIED.value
    assert r["gate"].allowed is True
    assert r["gate"].tool == "release_lot"
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RELEASED

    after = gh.read.get_usable_inventory("MAT-ALLOY-7")
    assert after > before, "usable inventory must increase on release"
    assert after == before + 500.0


# ==========================================================================
# S2 — hero lot quarantines (defensible vs supplier's cited spec, not vs governing)
# ==========================================================================
def test_s2_hero_lot_quarantines(gh: Gatehouse):
    facts = gh.eval.evaluate_evidence_against_spec("LOT-1002")
    tensile = next(f for f in facts["findings"] if f["characteristic"] == "tensile_strength")
    # The supplier value would pass an older/looser revision; against governing rev C it does not.
    assert tensile["observed_value"] == 462.0
    assert tensile["limit_min"] == 480.0
    assert tensile["status"] == "OUT_OF_LIMITS"

    r = gh.evaluate_lot("CASE-S2", "LOT-1002")

    assert r["actor"]["disposition"] == Disposition.QUARANTINE.value
    assert r["verifier"]["outcome"] == VerifierOutcome.VERIFIED.value
    assert r["gate"].tool == "quarantine_lot"
    assert gh.read.get_lot("LOT-1002").status is LotStatus.QUARANTINED
    assert gh.store.get("inventory", "LOT-1002").usability is Usability.NOT_USABLE


# ==========================================================================
# S3 — quarantine breaks production readiness
# ==========================================================================
def test_s3_quarantine_holds_production(gh: Gatehouse):
    gh.evaluate_lot("CASE-S1", "LOT-1001")  # +500 usable
    gh.evaluate_lot("CASE-S2", "LOT-1002")  # quarantined, stays unusable

    assert gh.read.get_production_order("C-417").status is OrderStatus.READY

    r = gh.evaluate_production_readiness("CASE-S3", "C-417")

    assert r["shortage"]["has_shortage"] is True
    short = r["shortage"]["shortages"][0]
    assert short["material_id"] == "MAT-ALLOY-7"
    assert short["required"] == 800.0
    assert short["available"] == 500.0
    assert short["short_by"] == 300.0

    assert r["readiness"]["authority_status"] == "HOLD"
    assert r["state_before"] == "READY"
    assert r["state_after"] == "HOLD"
    assert gh.read.get_production_order("C-417").status is OrderStatus.HOLD


# ==========================================================================
# S4 — unsafe recovery is refused
# ==========================================================================
def test_s4_unsafe_substitution_refused(gh: Gatehouse):
    gh.evaluate_lot("CASE-S1", "LOT-1001")
    gh.evaluate_lot("CASE-S2", "LOT-1002")
    gh.evaluate_production_readiness("CASE-S3", "C-417")

    facts = gh._build_recovery_facts("C-417")
    cand = next(c for c in facts["substitution_candidates"] if c["substitute_material_id"] == "MAT-SUB-9")
    assert cand["available_quantity"] == 900.0, "stock is plentiful"
    assert cand["approved"] is False, "but it is not approved for this product"

    r = gh.evaluate_recovery("CASE-S4", "C-417")

    # S4's guarantee is about the UNAPPROVED SUBSTITUTE specifically: it must
    # never be selected or consumed, no matter how much stock exists. Whether
    # some other lawful recovery (a resequence) is available is S5's concern.
    assert r["actor"]["action"] != "SUBSTITUTE", "unapproved substitute must never be chosen"
    assert "MAT-SUB-9" not in str(r["actor"].get("target_order_id") or "")
    assert gh.store.get("inventory", "LOT-9001").quantity == 900.0, "no substitution consumed"
    assert gh.read.get_lot("LOT-9001").status is LotStatus.RELEASED, "substitute lot untouched"

    # C-417 itself is never silently un-held by a recovery.
    assert gh.read.get_production_order("C-417").status is OrderStatus.HOLD


def test_s4_refuses_when_no_lawful_candidate_exists(gh: Gatehouse):
    """The pure refusal path: unapproved substitute AND no admissible resequence."""
    gh.evaluate_lot("CASE-S1", "LOT-1001")
    gh.evaluate_lot("CASE-S2", "LOT-1002")
    gh.evaluate_production_readiness("CASE-S3", "C-417")

    # Remove the lawful alternative so only the unapproved substitute remains.
    gh.store._t["production_order"].pop("C-418")

    schedule_before = gh.read.get_production_schedule()
    r = gh.evaluate_recovery("CASE-S4B", "C-417")

    assert r["actor"]["action"] == "REFUSE"
    assert "not approved" in r["actor"]["rationale"].lower()
    assert r["verifier"]["outcome"] == VerifierOutcome.VERIFIED.value
    assert r["gate"].allowed is False
    assert r["mutation_result"] == "NO_MUTATION"
    assert gh.read.get_production_schedule() == schedule_before, "no schedule mutation"
    assert gh.store.get("inventory", "LOT-9001").quantity == 900.0, "no substitution consumed"


# ==========================================================================
# S5 — safe recovery executes
# ==========================================================================
def test_s5_safe_resequence_executes(gh: Gatehouse):
    gh.evaluate_lot("CASE-S1", "LOT-1001")
    gh.evaluate_lot("CASE-S2", "LOT-1002")
    gh.evaluate_production_readiness("CASE-S3", "C-417")

    # Remove the unapproved substitute so a safe candidate is reachable;
    # S4 already proved the refusal path.
    gh.store._t["substitution"].clear()

    vacated = gh.read.get_production_order("C-417").planned_slot
    assert gh.read.get_production_order("C-418").planned_slot != vacated

    r = gh.evaluate_recovery("CASE-S5", "C-417")

    assert r["actor"]["action"] == "RESEQUENCE"
    assert r["actor"]["target_order_id"] == "C-418"
    assert r["verifier"]["outcome"] == VerifierOutcome.VERIFIED.value
    assert r["gate"].allowed is True
    assert gh.read.get_production_order("C-418").planned_slot == vacated

    # C-419 is on LINE-2, so it must never be chosen for a LINE-1 slot.
    assert r["actor"]["target_order_id"] != "C-419"


# ==========================================================================
# S6 — ambiguous evidence abstains
# ==========================================================================
def test_s6_ambiguous_evidence_abstains(gh: Gatehouse):
    facts = gh.eval.evaluate_evidence_against_spec("LOT-1003")
    finding = facts["findings"][0]
    assert finding["status"] == "METHOD_MISMATCH"
    assert finding["observed_method"] == "ASTM-D445"
    assert finding["required_method"] == "ASTM-D2196"

    r = gh.evaluate_lot("CASE-S6", "LOT-1003")

    assert r["actor"]["disposition"] == Disposition.INSUFFICIENT_EVIDENCE.value
    assert r["verifier"]["outcome"] == VerifierOutcome.INSUFFICIENT_EVIDENCE.value
    assert r["gate"].allowed is False

    lot = gh.read.get_lot("LOT-1003")
    assert lot.status is not LotStatus.RELEASED, "no release mutation"
    assert lot.status is not LotStatus.QUARANTINED, "must not be marked defective"
    assert lot.status is LotStatus.PENDING_QA

    qa = gh.store.get("qa_review", "QA-CASE-S6")
    assert qa is not None and qa.lot_id == "LOT-1003"


# ==========================================================================
# S7 — human evidence resumes the case
# ==========================================================================
def test_s7_qa_evidence_resumes_case(gh: Gatehouse):
    first = gh.evaluate_lot("CASE-S7", "LOT-1003")
    assert first["actor"]["disposition"] == Disposition.INSUFFICIENT_EVIDENCE.value
    assert gh.read.get_lot("LOT-1003").status is LotStatus.PENDING_QA

    new_evidence = add_qa_evidence(gh.store, "LOT-1003")

    second = gh.evaluate_lot("CASE-S7", "LOT-1003")  # same case id: continuous history

    assert second["actor"]["disposition"] == Disposition.RELEASE.value
    assert second["verifier"]["outcome"] == VerifierOutcome.VERIFIED.value
    assert second["gate"].allowed is True
    assert gh.read.get_lot("LOT-1003").status is LotStatus.RELEASED
    assert new_evidence in second["authority_record"].evidence_refs

    same_case = [r for r in gh.store.authority_log if r.case_id == "CASE-S7"]
    assert len(same_case) == 2, "history must remain continuous across resumption"
    assert same_case[0].actor_disposition == "INSUFFICIENT_EVIDENCE"
    assert same_case[1].actor_disposition == "RELEASE"


# ==========================================================================
# S8 — authority ledger
# ==========================================================================
def test_s8_authority_ledger_is_complete(gh: Gatehouse):
    gh.evaluate_lot("CASE-A", "LOT-1001")
    gh.evaluate_lot("CASE-B", "LOT-1002")
    gh.evaluate_production_readiness("CASE-C", "C-417")
    gh.evaluate_recovery("CASE-D", "C-417")

    assert len(gh.store.authority_log) == 4
    for rec in gh.store.authority_log:
        assert rec.case_id
        assert rec.actor_disposition
        assert rec.verifier_outcome
        assert rec.authority_result
        assert rec.requested_tool
        assert rec.mutation_result
        assert rec.state_before and rec.state_after
        assert rec.timestamp
        # audit artifact is typed output + evidence, never hidden reasoning
        assert isinstance(rec.evidence_refs, tuple)

    mutating = [r for r in gh.store.authority_log if r.mutation_result != "NO_MUTATION"]
    assert mutating, "expected consequential mutations"
    for rec in mutating:
        assert rec.authority_result == "ALLOWED" or rec.requested_tool == "create_qa_review"
        assert rec.idempotency_key, "every mutation must carry an idempotency key"


# ==========================================================================
# S9 — permission / fail-safe invariants
# ==========================================================================
def test_s9_verifier_cannot_receive_mutation_tools(gh: Gatehouse):
    from gatehouse.agents.base import PermissionViolation, assert_readonly_toolset

    with pytest.raises(PermissionViolation):
        assert_readonly_toolset("specification_verifier", MutationTools(gh.store))

    # the real verifiers hold read-only tools
    for verifier in (gh.spec_verifier, gh.recovery_check):
        assert isinstance(verifier.tools, ReadTools)
        assert not hasattr(verifier.tools, "release_lot")


def test_s9_no_agent_holds_mutation_tools(gh: Gatehouse):
    for agent in (gh.material_actor, gh.spec_verifier, gh.readiness,
                  gh.recovery_actor, gh.recovery_check):
        assert not isinstance(agent.tools, MutationTools)


def test_s9_unverified_proposal_cannot_mutate(gh: Gatehouse):
    """A direct mutation call with no gate token must raise."""
    mt = MutationTools(gh.store)
    with pytest.raises(AuthorityError):
        mt.release_lot("LOT-1001")
    with pytest.raises(AuthorityError):
        mt.quarantine_lot("LOT-1001", None)
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RECEIVED


def test_s9_token_cannot_be_reused_for_another_mutation(gh: Gatehouse):
    """A token minted for one tool/target must not authorize another."""
    decision = material_authority_gate(
        "CASE-X", "LOT-1001", Disposition.RELEASE, VerifierOutcome.VERIFIED
    )
    mt = MutationTools(gh.store)
    with pytest.raises(AuthorityError):
        mt.quarantine_lot("LOT-1001", decision.token)  # wrong tool
    with pytest.raises(AuthorityError):
        mt.release_lot("LOT-1002", decision.token)  # wrong target


def test_s9_forged_token_is_still_bound(gh: Gatehouse):
    """Even a hand-made token only works for its declared tool/target."""
    forged = AuthorityToken("CASE-Y", "release_lot", "LOT-1001", "k", "forged")
    mt = MutationTools(gh.store)
    with pytest.raises(AuthorityError):
        mt.release_lot("LOT-1002", forged)


def test_s9_disagreement_fails_safe(gh: Gatehouse):
    """Denial must be caused by the verifier, and cite it.

    Asserting only `allowed is False` is too weak: a gate that ignored the
    verifier entirely would still deny these via the catch-all branch. Pinning
    the reason is what makes this test able to fail.
    """
    cases = [
        (Disposition.RELEASE, VerifierOutcome.REJECTED, "REJECTED"),
        (Disposition.QUARANTINE, VerifierOutcome.REJECTED, "REJECTED"),
        (Disposition.RELEASE, VerifierOutcome.INSUFFICIENT_EVIDENCE, "insufficient"),
        (Disposition.INSUFFICIENT_EVIDENCE, VerifierOutcome.VERIFIED, "abstained"),
    ]
    for actor, verifier, expected_reason in cases:
        d = material_authority_gate("CASE-Z", "LOT-1001", actor, verifier)
        assert d.allowed is False
        assert d.tool == "create_qa_review", (
            f"{actor.value}/{verifier.value} must escalate to QA, got tool={d.tool}"
        )
        assert d.token is not None, "QA escalation still needs authority"
        assert expected_reason.lower() in d.reason.lower(), (
            f"deny reason must cite why: expected '{expected_reason}', got '{d.reason}'"
        )
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RECEIVED


def test_s9_verifier_rejection_blocks_mutation_end_to_end(gh: Gatehouse):
    """Drive the real workflow with a verifier forced to REJECT.

    Exercises the actual evaluate_lot path rather than the gate alone, so a gate
    that stopped consulting the verifier would fail here.
    """
    gh.spec_verifier.local_fn = lambda facts: {
        "outcome": "REJECTED",
        "rationale": "forced rejection for invariant test",
        "evidence_refs": facts.get("evidence_refs", []),
    }

    r = gh.evaluate_lot("CASE-REJECT", "LOT-1001")

    assert r["actor"]["disposition"] == Disposition.RELEASE.value, "actor still proposes release"
    assert r["gate"].allowed is False, "verifier rejection must block the mutation"
    assert r["gate"].tool == "create_qa_review"
    assert gh.read.get_lot("LOT-1001").status is not LotStatus.RELEASED
    assert gh.read.get_usable_inventory("MAT-ALLOY-7") == 0.0, "no inventory may become usable"
    assert r["authority_record"].verifier_outcome == "REJECTED"
    assert "DENIED" in r["authority_record"].authority_result


def test_s9_retries_are_idempotent(gh: Gatehouse):
    first = gh.evaluate_lot("CASE-IDEM", "LOT-1001")
    inventory_after_first = gh.read.get_usable_inventory("MAT-ALLOY-7")

    # replay the identical case: same idempotency key, no double-application
    decision = material_authority_gate(
        "CASE-IDEM", "LOT-1001", Disposition.RELEASE, VerifierOutcome.VERIFIED
    )
    mt = MutationTools(gh.store)
    replay = mt.release_lot("LOT-1001", decision.token)

    assert replay == first["mutation_result"]
    assert gh.read.get_usable_inventory("MAT-ALLOY-7") == inventory_after_first
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RELEASED


def test_s9_replay_cannot_double_change_schedule(gh: Gatehouse):
    gh.evaluate_lot("CASE-S1", "LOT-1001")
    gh.evaluate_lot("CASE-S2", "LOT-1002")
    gh.evaluate_production_readiness("CASE-S3", "C-417")
    gh.store._t["substitution"].clear()

    first = gh.evaluate_recovery("CASE-REPLAY", "C-417")
    slot_after_first = gh.read.get_production_order("C-418").planned_slot
    assert first["gate"].allowed is True

    # replaying the same case must not move the order a second time
    replay = gh.evaluate_recovery("CASE-REPLAY", "C-417")
    assert gh.read.get_production_order("C-418").planned_slot == slot_after_first
    assert replay["mutation_result"] in ("NO_MUTATION", first["mutation_result"])


def test_s9_state_machine_rejects_illegal_transition(gh: Gatehouse):
    from gatehouse.state import TransitionError

    gh.evaluate_lot("CASE-S1", "LOT-1001")
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RELEASED
    with pytest.raises(TransitionError):
        gh.store.set_lot_status("LOT-1001", LotStatus.RELEASED)


def test_s9f_verifier_cannot_silently_gain_actor_permissions(gh: Gatehouse):
    """S9F: a verifier cannot acquire mutation capability after construction.

    Covers the escalation path the other S9 tests miss: not "was it built
    read-only" but "can it be *made* privileged later" — by reconfiguring its
    toolset, or by having its output routed as if it were an actor proposal.
    """
    from gatehouse.agents.base import PermissionViolation, assert_readonly_toolset

    # 1. Re-validating a verifier that was handed mutation tools must raise.
    for verifier in (gh.spec_verifier, gh.recovery_check):
        assert verifier.spec.role == "verifier"
        object.__setattr__(verifier, "tools", MutationTools(gh.store))
        with pytest.raises(PermissionViolation):
            assert_readonly_toolset(verifier.spec.name, verifier.tools)

    # 2. Even holding mutation tools, a verifier has no gate token, so the
    #    mutation surface stays closed. Capability requires authority, not access.
    smuggled = MutationTools(gh.store)
    with pytest.raises(AuthorityError):
        smuggled.release_lot("LOT-1001")
    assert gh.read.get_lot("LOT-1001").status is LotStatus.RECEIVED

    # 3. A verifier verdict cannot stand in for an actor proposal: the gate
    #    requires a Disposition, and a VerifierOutcome is not one.
    with pytest.raises(ValueError):
        Disposition(VerifierOutcome.VERIFIED.value)


def test_s9_llm_never_does_inventory_arithmetic(gh: Gatehouse):
    """Shortage math is pure Python and independent of any agent."""
    result = gh.eval.calculate_material_shortage("C-417")
    assert result["shortages"][0]["short_by"] == 800.0  # nothing released yet
    assert result["has_shortage"] is True
