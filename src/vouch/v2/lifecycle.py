"""Observable lifecycle events (contract D14).

These are the machine-readable facts a UI can render. What they must NOT
contain is the reason this file has a rule rather than a convention: no chain
of thought, no raw prompts, no model reasoning tokens. An event carries
structured facts, hashes, versions and tool metadata — nothing that would leak
private reasoning into an audit surface that claims not to store it.

`emit` is deliberately a plain callable list rather than an event bus. There is
one process and one decision run at a time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventType(str, Enum):
    EVIDENCE_RECEIVED = "EVIDENCE_RECEIVED"
    EVIDENCE_SECURITY_COMPLETED = "EVIDENCE_SECURITY_COMPLETED"
    EVIDENCE_BINDING_MISMATCH = "EVIDENCE_BINDING_MISMATCH"
    #: The positive counterpart of BINDING_MISMATCH. Emitted for every
    #: artifact whose identity binding resolved, including the fail-closed
    #: UNBOUND/CONFLICT outcomes, so the frontend never has to infer a
    #: binding result from the absence of a mismatch event.
    EVIDENCE_BINDING_COMPLETED = "EVIDENCE_BINDING_COMPLETED"
    EVIDENCE_EXTRACTED = "EVIDENCE_EXTRACTED"
    EVIDENCE_SNAPSHOT_CREATED = "EVIDENCE_SNAPSHOT_CREATED"
    INVESTIGATOR_STARTED = "INVESTIGATOR_STARTED"
    TOOL_CALLED = "TOOL_CALLED"
    TOOL_RESULT_BOUND = "TOOL_RESULT_BOUND"
    APPLICABILITY_BRIEF_COMPLETED = "APPLICABILITY_BRIEF_COMPLETED"
    #: A brief contradicted the authoritative corpus and was sent back to the
    #: same agent with the specific errors. Observable because a silent retry
    #: would hide how often the models produce unsupported claims.
    BRIEF_VALIDATION_FAILED = "BRIEF_VALIDATION_FAILED"
    VERIFIER_STARTED = "VERIFIER_STARTED"
    VERIFIER_BRIEF_COMPLETED = "VERIFIER_BRIEF_COMPLETED"
    RECONCILIATION_COMPLETED = "RECONCILIATION_COMPLETED"
    DISPOSITION_COMPUTED = "DISPOSITION_COMPUTED"
    POLICY_EVALUATED = "POLICY_EVALUATED"
    CAPABILITY_ISSUED = "CAPABILITY_ISSUED"
    MUTATION_COMPLETED = "MUTATION_COMPLETED"
    CONSEQUENCE_RECALCULATED = "CONSEQUENCE_RECALCULATED"
    READINESS_TRANSITIONED = "READINESS_TRANSITIONED"
    RECOVERY_EVALUATED = "RECOVERY_EVALUATED"
    RECOVERY_EXECUTED = "RECOVERY_EXECUTED"
    QUALITY_DECISION_REQUIRED = "QUALITY_DECISION_REQUIRED"
    #: A disagreement produced exactly one answerable applicability question.
    #: Separate from QUALITY_DECISION_REQUIRED, which says only that a human is
    #: needed: this says WHAT is being asked, in structured form.
    QUALITY_QUESTION_RAISED = "QUALITY_QUESTION_RAISED"
    #: An accountable human settled that question. The authority is scoped to
    #: this record and this snapshot; it is never a disposition.
    QUALITY_AUTHORITY_RECORDED = "QUALITY_AUTHORITY_RECORDED"
    HUMAN_EVIDENCE_RECEIVED = "HUMAN_EVIDENCE_RECEIVED"
    DECISION_RESUMED = "DECISION_RESUMED"
    # Milestone 2 only. Declared so the vocabulary is complete, not emitted yet.
    PRECEDENT_CONSULTED = "PRECEDENT_CONSULTED"


#: Substrings that must never appear as event payload keys. Cheap structural
#: guard against someone later "just adding the rationale" to an event.
_FORBIDDEN_KEYS = ("chain_of_thought", "reasoning", "rationale", "raw_prompt", "prompt_text")


@dataclass(frozen=True)
class LifecycleEvent:
    event_type: EventType
    decision_record_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=utcnow)

    def __post_init__(self) -> None:
        for key in self.payload:
            if any(bad in key.lower() for bad in _FORBIDDEN_KEYS):
                raise ValueError(
                    f"lifecycle payload key {key!r} would leak private reasoning; "
                    "events carry structured facts only"
                )


class EventLog:
    """Append-only in-process event log for one workflow run."""

    def __init__(self, sinks: list[Callable[[LifecycleEvent], None]] | None = None) -> None:
        self.events: list[LifecycleEvent] = []
        self._sinks = sinks or []

    def emit(self, event_type: EventType, decision_record_id: str, **payload: Any) -> LifecycleEvent:
        event = LifecycleEvent(event_type, decision_record_id, payload)
        self.events.append(event)
        for sink in self._sinks:
            sink(event)
        return event

    def of_type(self, event_type: EventType) -> list[LifecycleEvent]:
        return [e for e in self.events if e.event_type is event_type]

    def types(self) -> list[EventType]:
        return [e.event_type for e in self.events]

    def as_dicts(self) -> list[dict]:
        return [
            {"event": e.event_type.value, "decision_record_id": e.decision_record_id,
             "at": e.at, **e.payload}
            for e in self.events
        ]


__all__ = ["EventLog", "EventType", "LifecycleEvent", "utcnow"]
