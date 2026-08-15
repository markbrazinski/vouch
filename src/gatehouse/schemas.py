"""Typed agent outputs, enforced by Strands structured output.

A1: the model is constrained to this vocabulary at the SDK layer. If it cannot
produce a conforming object, that is a SchemaFailure — recorded explicitly and
failing safe to no consequential mutation. We never translate invalid vocabulary
into a valid disposition.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class _Base(BaseModel):
    """Tolerates null-for-empty-list, which Nova Pro emits for empty collections.

    This is a serialization nicety, NOT vocabulary leniency: the Literal fields
    below still reject any value outside the declared enum, and a missing
    required field is still a hard schema failure.
    """

    @field_validator("*", mode="before")
    @classmethod
    def _null_list_to_empty(cls, v: Any, info) -> Any:
        if v is None:
            ann = cls.model_fields[info.field_name].annotation
            if ann is not None and "list" in str(ann):
                return []
        return v


class MaterialDispositionOutput(_Base):
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


class VerifierOutput(_Base):
    """Specification Verifier. Read-only; never proposes an action.

    Deliberately minimal. A wider schema measurably degraded field compliance on
    Nova Pro (it filled evidence_refs/rationale and omitted the required
    `outcome`), so the verdict schema carries only what the gate consumes.
    """

    outcome: Literal["VERIFIED", "REJECTED", "INSUFFICIENT_EVIDENCE"] = Field(
        description=(
            "REQUIRED. Exactly one of VERIFIED, REJECTED, INSUFFICIENT_EVIDENCE. "
            "Never an action verb such as RELEASE, QUARANTINE or REFUSE."
        )
    )
    rationale: str = Field(default="", description="Independent basis for the outcome.")


class RecoveryJudgmentOutput(_Base):
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
