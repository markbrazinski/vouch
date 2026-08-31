"""The V2 DecisionRecord — the audit artifact (contract D13).

Reconstructability comes from re-derivability, not from stored reasoning: the
same claim set + prompt version + corpus version reproduces the brief. So this
record stores hashes, versions, structured outputs, tool events, evidence refs
and causal links — and never chain-of-thought.

It is one mutable object during a run and is written once at the end. Each
segment maps to a D13 row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .contracts import (
    Disposition,
    FailureCategory,
    ReconciliationOutcome,
    content_hash,
)
from .lifecycle import utcnow


@dataclass
class IdentitySegment:
    record_id: str = ""
    lot_id: str = ""
    material_id: str = ""
    supplier_id: str = ""
    supplier_site: str = ""


@dataclass
class EvidenceSegment:
    source_artifact_hashes: list[str] = field(default_factory=list)
    document_identities: list[str] = field(default_factory=list)
    receipt_timestamps: list[str] = field(default_factory=list)
    #: P0-5 / P1-1: durable storage refs and object versions, so the exact
    #: bytes behind a decision can be fetched again.
    storage_refs: list[str] = field(default_factory=list)
    object_versions: list[str] = field(default_factory=list)
    #: P0-4: what each artifact claimed about itself.
    claimed_identities: list[dict] = field(default_factory=list)


@dataclass
class SecuritySegment:
    inspection_performed: bool = False
    config_version: str = ""
    detector: str = ""
    #: P0-6: Guardrails provenance — which guardrail ran, at which version.
    guardrail_outcome: str = "NOT_RUN"
    guardrail_id: str = ""
    guardrail_version: str = ""
    inspected_at: str = ""
    #: P0-7: the truthful AV outcome, including NOT_RUN.
    malware_scan: str = "NOT_RUN"
    prompt_attack_detected: bool = False
    malware_found: bool = False
    blocked: bool = False
    quarantined_artifact_ids: list[str] = field(default_factory=list)
    #: P0-4: contradictions between document identity and requested target.
    binding_mismatches: list[str] = field(default_factory=list)
    rejected_artifact_ids: list[str] = field(default_factory=list)


@dataclass
class ExtractionSegment:
    #: claim_id -> {"method": ..., "version": ..., "confidence": ...}
    per_claim: dict[str, dict] = field(default_factory=dict)
    model_fallback_used: bool = False
    low_confidence_routed_to_human: bool = False


@dataclass
class SnapshotSegment:
    snapshot_id: str = ""
    claim_set_hash: str = ""
    lot_state_version: int = 0
    order_state_versions: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentSegment:
    """One model-backed agent's contribution. Note what is absent: rationale."""

    model_id: str = ""
    prompt_version: str = ""
    prompt_hash: str = ""
    temperature: float = 0.0
    input_claim_set_hash: str = ""
    brief_hash: str = ""
    tool_events: list[dict] = field(default_factory=list)
    schema_valid: bool = False
    precedent_consulted: list[str] = field(default_factory=list)
    failure: str = ""


@dataclass
class ReconciliationSegment:
    outcome: str = ""
    differing_fields: list[str] = field(default_factory=list)


@dataclass
class BasisSegment:
    spec_id: str = ""
    revision: str = ""
    checks_passed: bool = False
    check_failures: list[str] = field(default_factory=list)


@dataclass
class DispositionSegment:
    disposition: str = ""
    reason: str = ""


@dataclass
class PolicySegment:
    policy_version: str = ""
    gate_decision: str = ""
    refusal_reason: str = ""


@dataclass
class CapabilitySegment:
    capability_id: str = ""
    issued: bool = False
    consumed: bool = False
    refusal_reason: str = ""


@dataclass
class MutationSegment:
    target_type: str = ""
    target_id: str = ""
    action: str = ""
    before_version: int = 0
    after_version: int = 0
    inventory_delta: float = 0.0
    ledger_sequence: int = 0
    result: str = "NO_MUTATION"


@dataclass
class ConsequenceSegment:
    coverage_changes: list[dict] = field(default_factory=list)
    readiness_changes: list[dict] = field(default_factory=list)
    recovery: dict = field(default_factory=dict)
    #: Causal chain: lot disposition -> inventory delta -> coverage -> readiness.
    caused_by: list[dict] = field(default_factory=list)


@dataclass
class HumanContinuationSegment:
    evidence_supplied: list[str] = field(default_factory=list)
    authority_source: str = ""
    content_hashes: list[str] = field(default_factory=list)
    resumed_run_ids: list[str] = field(default_factory=list)
    review_id: str = ""
    review_status: str = ""
    final_outcome: str = ""


@dataclass
class DecisionRecord:
    """One consequential decision, start to finish."""

    record_id: str
    created_at: str = field(default_factory=utcnow)
    run_count: int = 1

    identity: IdentitySegment = field(default_factory=IdentitySegment)
    evidence: EvidenceSegment = field(default_factory=EvidenceSegment)
    security: SecuritySegment = field(default_factory=SecuritySegment)
    extraction: ExtractionSegment = field(default_factory=ExtractionSegment)
    snapshot: SnapshotSegment = field(default_factory=SnapshotSegment)
    investigator: AgentSegment = field(default_factory=AgentSegment)
    verifier: AgentSegment = field(default_factory=AgentSegment)
    reconciliation: ReconciliationSegment = field(default_factory=ReconciliationSegment)
    basis: BasisSegment = field(default_factory=BasisSegment)
    disposition: DispositionSegment = field(default_factory=DispositionSegment)
    policy: PolicySegment = field(default_factory=PolicySegment)
    capability: CapabilitySegment = field(default_factory=CapabilitySegment)
    mutation: MutationSegment = field(default_factory=MutationSegment)
    consequences: ConsequenceSegment = field(default_factory=ConsequenceSegment)
    human: HumanContinuationSegment = field(default_factory=HumanContinuationSegment)

    failure_category: str = ""
    terminal: bool = False
    events: list[dict] = field(default_factory=list)

    def fail(self, category: FailureCategory, detail: str = "") -> None:
        """Record a typed failure. Never rewrites the disposition — a technical
        failure leaves disposition empty rather than becoming an answer."""
        self.failure_category = category.value
        if detail:
            self.policy.refusal_reason = self.policy.refusal_reason or detail

    def rerun(self) -> None:
        """A human supplied evidence; the SAME record continues (contract §18)."""
        self.run_count += 1
        self.human.resumed_run_ids.append(f"{self.record_id}#run{self.run_count}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def audit_hash(self) -> str:
        """Hash over everything except the volatile event list."""
        payload = self.to_dict()
        payload.pop("events", None)
        return content_hash(payload)

    def is_reconstructable(self) -> bool:
        """The D13 completeness claim, checked rather than asserted.

        Every link in the chain must be present for an auditor to re-derive the
        decision. Absence of any one of these means the record cannot support
        the audit story, so we would rather fail a test than ship the claim.
        """
        required = [
            self.identity.record_id,
            self.identity.lot_id,
            self.snapshot.claim_set_hash,
            self.investigator.model_id,
            self.investigator.prompt_version,
            self.verifier.model_id,
            self.reconciliation.outcome,
            self.disposition.disposition or self.failure_category,
            self.policy.policy_version,
        ]
        return all(bool(x) for x in required)


__all__ = [
    "AgentSegment",
    "BasisSegment",
    "CapabilitySegment",
    "ConsequenceSegment",
    "DecisionRecord",
    "DispositionSegment",
    "EvidenceSegment",
    "ExtractionSegment",
    "HumanContinuationSegment",
    "IdentitySegment",
    "MutationSegment",
    "PolicySegment",
    "ReconciliationSegment",
    "SecuritySegment",
    "SnapshotSegment",
]
