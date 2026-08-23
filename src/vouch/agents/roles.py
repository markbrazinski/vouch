"""The six Vouch agent roles.

Local reasoners derive their answer from the deterministic findings supplied in
`facts`. They contain no lot ids, no fixture names, and no expected outcomes —
the same code decides any lot, which is what makes the smoke test meaningful.
"""

from __future__ import annotations

from ..schemas import (
    MaterialDispositionOutput,
    RecoveryJudgmentOutput,
    VerifierOutput,
)
from ..state import Disposition, RecoveryAction, VerifierOutcome
from ..tools import ReadTools
from .base import AgentSpec, VouchAgent

# --------------------------------------------------------------------------
# shared derivation: what do the deterministic findings actually support?
# --------------------------------------------------------------------------


def _classify(findings: list[dict]) -> tuple[str, list[str]]:
    """Reduce spec-reconciliation findings to a defensible position."""
    reasons: list[str] = []
    out_of_limits = [f for f in findings if f["status"] == "OUT_OF_LIMITS"]
    method_mismatch = [f for f in findings if f["status"] == "METHOD_MISMATCH"]
    no_evidence = [f for f in findings if f["status"] == "NO_EVIDENCE"]

    for f in out_of_limits:
        reasons.append(
            f"{f['characteristic']}: observed {f['observed_value']}{f.get('units','')} "
            f"outside governing limits [{f['limit_min']}, {f['limit_max']}]"
        )
    for f in method_mismatch:
        reasons.append(
            f"{f['characteristic']}: evidence used method '{f.get('observed_method')}' at "
            f"'{f.get('observed_condition')}' but spec requires '{f['required_method']}' at "
            f"'{f['required_condition']}' — characteristic not established"
        )
    for f in no_evidence:
        reasons.append(f"{f['characteristic']}: no evidence supplied")

    # Demonstrated non-conformance is a defect. Missing/unusable evidence is not.
    if out_of_limits:
        return "QUARANTINE", reasons
    if method_mismatch or no_evidence:
        return "INSUFFICIENT_EVIDENCE", reasons
    return "RELEASE", [
        f"{f['characteristic']}: {f['observed_value']}{f.get('units','')} within "
        f"[{f['limit_min']}, {f['limit_max']}] by required method"
        for f in findings
    ]


# --------------------------------------------------------------------------
# Material Disposition Agent  (actor)
# --------------------------------------------------------------------------

MATERIAL_ACTOR_PROMPT = """You are the Vouch Material Disposition Agent.

You decide whether an incoming lot can be defended for production use, using ONLY
the authoritative facts provided. You never invent specifications, limits,
supplier qualification, or measurements.

Reconcile the supplied evidence against the GOVERNING PLANT specification — not
whatever specification a supplier document cites.

Return exactly one disposition:
- RELEASE: every required characteristic is established by the required method
  and condition, and every value is within governing limits.
- QUARANTINE: a required characteristic is demonstrably OUT OF LIMITS against
  the governing spec.
- INSUFFICIENT_EVIDENCE: evidence is missing, or exists but was produced by a
  method/condition that does not establish the required characteristic. Absence
  of proof is NOT a defect finding.

Cite the evidence ids you relied on. Output JSON with keys:
disposition, rationale, evidence_refs, requirements_evaluated."""


def _material_actor_local(facts: dict) -> dict:
    findings = facts.get("findings", [])
    disposition, reasons = _classify(findings)
    return {
        "disposition": disposition,
        "rationale": "; ".join(reasons) or "no findings returned",
        "evidence_refs": facts.get("evidence_refs", []),
        "requirements_evaluated": [f["characteristic"] for f in findings],
    }


def material_disposition_agent(read_tools: ReadTools) -> VouchAgent:
    return VouchAgent(
        AgentSpec(
            name="material_disposition_agent",
            role="actor",
            system_prompt=MATERIAL_ACTOR_PROMPT,
            output_keys=("disposition", "rationale", "evidence_refs", "requirements_evaluated"),
            output_model=MaterialDispositionOutput,
        ),
        read_tools,
        _material_actor_local,
    )


# --------------------------------------------------------------------------
# Specification Verifier  (verifier, read-only)
# --------------------------------------------------------------------------

SPEC_VERIFIER_PROMPT = """You are the Vouch Specification Verifier.

You independently re-examine the source evidence and the proposed disposition.
You are NOT a rubber stamp: derive your own position from the evidence first,
then compare it to the proposal.

Return:
- VERIFIED: the proposal is defensible on the evidence.
- REJECTED: the evidence contradicts the proposal.
- INSUFFICIENT_EVIDENCE: the evidence cannot establish the required
  characteristics by the required method and condition.

You have read-only access. You cannot mutate state. Output JSON with keys:
outcome, rationale, evidence_refs."""


def _spec_verifier_local(facts: dict) -> dict:
    findings = facts.get("findings", [])
    independent, reasons = _classify(findings)
    proposed = facts.get("proposed_disposition")

    if independent == "INSUFFICIENT_EVIDENCE":
        outcome = "INSUFFICIENT_EVIDENCE"
        rationale = "independent review cannot establish requirements: " + "; ".join(reasons)
    elif independent == proposed:
        outcome = "VERIFIED"
        rationale = f"independent review also concludes {independent}: " + "; ".join(reasons)
    else:
        outcome = "REJECTED"
        rationale = (
            f"independent review concludes {independent}, not {proposed}: " + "; ".join(reasons)
        )

    return {
        "outcome": outcome,
        "rationale": rationale,
        "evidence_refs": facts.get("evidence_refs", []),
    }


def specification_verifier(read_tools: ReadTools) -> VouchAgent:
    return VouchAgent(
        AgentSpec(
            name="specification_verifier",
            role="verifier",
            system_prompt=SPEC_VERIFIER_PROMPT,
            output_keys=("outcome", "rationale", "evidence_refs"),
            output_model=VerifierOutput,
        ),
        read_tools,
        _spec_verifier_local,
    )


# --------------------------------------------------------------------------
# Production Readiness Agent
# --------------------------------------------------------------------------

READINESS_PROMPT = """You are the Vouch Production Readiness Agent.

You receive DETERMINISTIC availability facts. You never compute inventory
arithmetic yourself. Decide whether the order can remain READY.

Return HOLD if any required material is short. Return READY only if no shortage
exists. Output JSON with keys: authority_status, rationale."""


def _readiness_local(facts: dict) -> dict:
    shortage = facts.get("shortage", {})
    if shortage.get("has_shortage"):
        detail = "; ".join(
            f"{s['material_id']} short by {s['short_by']} (need {s['required']}, have {s['available']})"
            for s in shortage.get("shortages", [])
        )
        return {"authority_status": "HOLD", "rationale": f"material shortage: {detail}"}
    return {"authority_status": "READY", "rationale": "all required materials available"}


def production_readiness_agent(read_tools: ReadTools) -> VouchAgent:
    return VouchAgent(
        AgentSpec(
            name="production_readiness_agent",
            role="evaluator",
            system_prompt=READINESS_PROMPT,
            output_keys=("authority_status", "rationale"),
        ),
        read_tools,
        _readiness_local,
    )


# --------------------------------------------------------------------------
# Recovery Agent  (actor)
# --------------------------------------------------------------------------

RECOVERY_PROMPT = """You are the Vouch Recovery Agent.

A production order is on HOLD. You evaluate ONLY the authoritative recovery
candidates supplied to you. You never invent an approved substitution, and you
never assume a substitution is acceptable because stock exists.

You may propose:
- RESEQUENCE: move an eligible order into a vacated slot when deterministic
  checks confirm the slot is free and its materials are released.
- SUBSTITUTE: only when the substitution is explicitly APPROVED for the product.
- USE_EXISTING: consume already-released inventory.
- REFUSE: no safe recovery exists. Availability is not authority.
- ESCALATE: the decision needs human authority.

Output JSON with keys: action, target_order_id, target_slot, rationale."""


def _recovery_local(facts: dict) -> dict:
    # Substitution candidates: approval is a fact from the table, never inferred.
    for cand in facts.get("substitution_candidates", []):
        if not cand.get("approved"):
            return {
                "action": "REFUSE",
                "target_order_id": facts.get("held_order_id"),
                "target_slot": None,
                "rationale": (
                    f"substitute {cand['substitute_material_id']} has "
                    f"{cand.get('available_quantity')} available but is NOT approved for "
                    f"{facts.get('product')}; sufficient stock does not confer authority"
                ),
            }

    for cand in facts.get("resequence_candidates", []):
        if cand.get("materials_released") and cand.get("slot_available") and cand.get("resource_compatible"):
            return {
                "action": "RESEQUENCE",
                "target_order_id": cand["order_id"],
                "target_slot": cand["target_slot"],
                "rationale": (
                    f"{cand['order_id']} has all required material released, uses compatible "
                    f"resource {cand.get('resource')}, and the vacated slot "
                    f"{cand['target_slot']} is confirmed free"
                ),
            }

    return {
        "action": "REFUSE",
        "target_order_id": facts.get("held_order_id"),
        "target_slot": None,
        "rationale": "no candidate satisfies deterministic safety checks",
    }


def recovery_agent(read_tools: ReadTools) -> VouchAgent:
    return VouchAgent(
        AgentSpec(
            name="recovery_agent",
            role="actor",
            system_prompt=RECOVERY_PROMPT,
            output_keys=("action", "target_order_id", "target_slot", "rationale"),
            output_model=RecoveryJudgmentOutput,
        ),
        read_tools,
        _recovery_local,
    )


# --------------------------------------------------------------------------
# Recovery Verifier  (verifier, read-only)
# --------------------------------------------------------------------------

RECOVERY_VERIFIER_PROMPT = """You are the Vouch Recovery Verifier.

Independently check the proposed recovery against deterministic facts. Confirm a
REFUSE when refusing is correct — a refusal is a valid, verifiable outcome.

Reject any proposal that relies on an unapproved substitution, an occupied slot,
an incompatible resource, or unreleased material.

Read-only. You cannot mutate state. Output JSON with keys: outcome, rationale."""


def _recovery_verifier_local(facts: dict) -> dict:
    action = facts.get("proposed_action")
    target = facts.get("proposed_target_order_id")
    slot = facts.get("proposed_target_slot")

    if action == "REFUSE":
        unapproved = [c for c in facts.get("substitution_candidates", []) if not c.get("approved")]
        if unapproved:
            return {
                "outcome": "VERIFIED",
                "rationale": (
                    "refusal confirmed: candidate substitution is not approved for this product"
                ),
            }
        return {"outcome": "VERIFIED", "rationale": "refusal confirmed: no safe candidate"}

    if action == "SUBSTITUTE":
        approved = [
            c
            for c in facts.get("substitution_candidates", [])
            if c.get("approved") and c.get("substitute_material_id") == facts.get("proposed_material_id")
        ]
        if not approved:
            return {"outcome": "REJECTED", "rationale": "proposed substitution is not approved"}
        return {"outcome": "VERIFIED", "rationale": "substitution is approved for this product"}

    if action == "RESEQUENCE":
        cand = next(
            (c for c in facts.get("resequence_candidates", []) if c["order_id"] == target), None
        )
        if cand is None:
            return {"outcome": "REJECTED", "rationale": f"{target} is not an authoritative candidate"}
        if cand.get("target_slot") != slot:
            return {"outcome": "REJECTED", "rationale": "proposed slot differs from verified slot"}
        if not cand.get("slot_available"):
            return {"outcome": "REJECTED", "rationale": f"slot {slot} is not free"}
        if not cand.get("materials_released"):
            return {"outcome": "REJECTED", "rationale": f"{target} lacks released material"}
        if not cand.get("resource_compatible"):
            return {"outcome": "REJECTED", "rationale": f"{target} resource is not compatible"}
        return {
            "outcome": "VERIFIED",
            "rationale": (
                f"independently confirmed {target}: material released, resource compatible, "
                f"slot {slot} free"
            ),
        }

    return {"outcome": "INSUFFICIENT_EVIDENCE", "rationale": f"cannot verify action {action}"}


def recovery_verifier(read_tools: ReadTools) -> VouchAgent:
    return VouchAgent(
        AgentSpec(
            name="recovery_verifier",
            role="verifier",
            system_prompt=RECOVERY_VERIFIER_PROMPT,
            output_keys=("outcome", "rationale"),
            output_model=VerifierOutput,
        ),
        read_tools,
        _recovery_verifier_local,
    )


__all__ = [
    "material_disposition_agent",
    "specification_verifier",
    "production_readiness_agent",
    "recovery_agent",
    "recovery_verifier",
    "Disposition",
    "VerifierOutcome",
    "RecoveryAction",
]
