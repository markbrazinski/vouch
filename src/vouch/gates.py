"""Deterministic authority gates. No LLM runs here.

The gate is the only place an AuthorityToken is minted, so it is the only path
to a state mutation. Truth tables are explicit and deny by default.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import Disposition, RecoveryAction, VerifierOutcome
from .tools import AuthorityToken, make_idempotency_key

MATERIAL_GATE = "deterministic_material_authority_gate"
RECOVERY_GATE = "deterministic_recovery_authority_gate"


@dataclass(frozen=True)
class GateDecision:
    allowed: bool
    tool: str | None
    reason: str
    token: AuthorityToken | None = None
    authority_source: str = ""


def material_authority_gate(
    case_id: str,
    lot_id: str,
    actor: Disposition,
    verifier: VerifierOutcome,
) -> GateDecision:
    """Consequential lot mutation requires actor+verifier agreement.

    Deny by default. Disagreement fails safe: no mutation, and never
    quarantine-as-defective merely because evidence is missing.
    """

    def allow(tool: str, reason: str) -> GateDecision:
        key = make_idempotency_key(case_id, tool, lot_id)
        return GateDecision(
            allowed=True,
            tool=tool,
            reason=reason,
            authority_source=MATERIAL_GATE,
            token=AuthorityToken(case_id, tool, lot_id, key, MATERIAL_GATE),
        )

    def deny(tool: str | None, reason: str) -> GateDecision:
        # A QA review is an escalation, not a consequential defect finding, so
        # the gate still mints a token for it while refusing release/quarantine.
        if tool == "create_qa_review":
            key = make_idempotency_key(case_id, tool, lot_id)
            return GateDecision(
                allowed=False,
                tool=tool,
                reason=reason,
                authority_source=MATERIAL_GATE,
                token=AuthorityToken(case_id, tool, lot_id, key, MATERIAL_GATE),
            )
        return GateDecision(False, tool, reason, None, MATERIAL_GATE)

    if verifier is VerifierOutcome.REJECTED:
        return deny("create_qa_review", "verifier REJECTED the proposal; failing safe")

    if verifier is VerifierOutcome.INSUFFICIENT_EVIDENCE:
        return deny("create_qa_review", "verifier found evidence insufficient; escalating to QA")

    if actor is Disposition.INSUFFICIENT_EVIDENCE:
        return deny("create_qa_review", "actor abstained on insufficient evidence; escalating to QA")

    if verifier is VerifierOutcome.VERIFIED:
        if actor is Disposition.RELEASE:
            return allow("release_lot", "actor RELEASE verified independently")
        if actor is Disposition.QUARANTINE:
            return allow("quarantine_lot", "actor QUARANTINE verified independently")

    return deny(None, f"no authority path for actor={actor.value}, verifier={verifier.value}")


def recovery_authority_gate(
    case_id: str,
    order_id: str,
    action: RecoveryAction,
    verifier: VerifierOutcome,
    deterministic_facts_ok: bool,
    target_slot: str | None = None,
) -> GateDecision:
    """Schedule/substitution mutation.

    `deterministic_facts_ok` is computed by EvalTools, never by an agent — a
    verified proposal built on false arithmetic still gets refused.
    """

    def deny(reason: str) -> GateDecision:
        return GateDecision(False, None, reason, None, RECOVERY_GATE)

    if action in (RecoveryAction.REFUSE, RecoveryAction.ESCALATE):
        return deny(f"recovery agent returned {action.value}; no mutation by design")

    if verifier is not VerifierOutcome.VERIFIED:
        return deny(f"recovery verifier returned {verifier.value}; failing safe")

    if not deterministic_facts_ok:
        return deny("deterministic checks refuted the proposal (slot or approval)")

    if action is RecoveryAction.RESEQUENCE:
        if not target_slot:
            return deny("resequence proposed without a target slot")
        tool = "resequence_production_order"
        key = make_idempotency_key(case_id, tool, order_id)
        return GateDecision(
            allowed=True,
            tool=tool,
            reason="verified resequence with deterministic slot confirmation",
            authority_source=RECOVERY_GATE,
            token=AuthorityToken(case_id, tool, order_id, key, RECOVERY_GATE),
        )

    return deny(f"no authority path for action={action.value}")
