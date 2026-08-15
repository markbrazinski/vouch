"""Typed agent outputs, enforced by Strands structured output.

A1: the model is constrained to this vocabulary at the SDK layer. If it cannot
produce a conforming object, that is a SchemaFailure — recorded explicitly and
failing safe to no consequential mutation. We never translate invalid vocabulary
into a valid disposition.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class MaterialDispositionOutput(BaseModel):
    """Material Disposition Agent (actor)."""

    disposition: Literal["RELEASE", "QUARANTINE", "INSUFFICIENT_EVIDENCE"] = Field(
        description=(
            "RELEASE only if every required characteristic is established by the "
            "required method/condition and within governing limits. QUARANTINE if a "
            "requirement is demonstrably not met. INSUFFICIENT_EVIDENCE if the "
            "evidence cannot establish the requirement — absence of proof is not a defect."
        )
    )
    governing_spec: str = Field(description="The specification and revision judged to govern.")
    rationale: str = Field(description="Concise basis. Cite what the evidence does/does not establish.")
    evidence_refs: list[str] = Field(default_factory=list, description="evidence_ids relied upon.")
    requirements_evaluated: list[str] = Field(
        default_factory=list, description="Characteristic names evaluated."
    )
    unresolved_requirements: list[str] = Field(
        default_factory=list, description="Requirements that could not be established."
    )


class VerifierOutput(BaseModel):
    """Specification Verifier. Read-only; never proposes an action."""

    outcome: Literal["VERIFIED", "REJECTED", "INSUFFICIENT_EVIDENCE"] = Field(
        description=(
            "VERIFIED if the proposal is defensible on the evidence. REJECTED if the "
            "evidence contradicts it. INSUFFICIENT_EVIDENCE if the evidence cannot "
            "establish the requirement. These are the only valid values — never an "
            "action verb such as RELEASE or REFUSE."
        )
    )
    rationale: str = Field(description="Independent basis for the outcome.")
    evidence_refs: list[str] = Field(default_factory=list)


class RecoveryJudgmentOutput(BaseModel):
    """Recovery judgment — only where deterministic checks cannot decide.

    A3: feasibility, approval, quantity, and slot constraints are computed in
    Python. The agent only weighs candidates already proven admissible.
    """

    action: Literal["RESEQUENCE", "REFUSE", "ESCALATE"] = Field(
        description="Choose only among deterministically admissible candidates."
    )
    target_order_id: str | None = None
    target_slot: str | None = None
    rationale: str = ""


class SchemaFailure(Exception):
    """The model could not produce a conforming typed output.

    Never coerced into a valid disposition. The gate treats this as a hard deny.
    """

    def __init__(self, agent_name: str, detail: str) -> None:
        self.agent_name = agent_name
        self.detail = detail
        super().__init__(f"{agent_name}: schema failure: {detail}")
