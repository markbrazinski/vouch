"""The V2 DecisionRecord — the audit artifact (contract D13).

Reconstructability comes from re-derivability, not from stored reasoning: the
same claim set + prompt version + corpus version reproduces the brief. So this
record stores hashes, versions, structured outputs, tool events, evidence refs
and causal links — and never chain-of-thought.

It is one mutable object during a run and is written once at the end. Each
segment maps to a D13 row.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
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
    #: audit-2 F8: the canonical claims themselves, so a resumed case
    #: reconstructs the evidence it already had after a process restart.
    canonical_claims: list[dict] = field(default_factory=list)
    #: audit-2 F3: per-artifact binding status. An artifact that stated no
    #: identity is UNBOUND — neither a mismatch nor a successful binding.
    binding_statuses: list[str] = field(default_factory=list)
    #: The MIME type the artifact was ingested AS. Only one field is added here:
    #: `document_identities` above already carries the classification (COA,
    #: QA_RETEST, …), and duplicating it would give a viewer two document types
    #: that could disagree. Without the MIME type a frontend cannot tell a PDF
    #: from a text COA, and would have to guess a document type it must never
    #: invent.
    content_types: list[str] = field(default_factory=list)


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
    #: audit-2 F3/F4: artifacts that could not be affirmatively bound (stated
    #: no identity) or that contradicted themselves (conflicting identities).
    unbound_artifact_ids: list[str] = field(default_factory=list)
    identity_conflicts: list[str] = field(default_factory=list)


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
    #: P1-3: the ACTUAL category, not a blanket schema failure.
    failure_category: str = ""
    attempts: int = 1
    #: The brief was produced and then REFUSED for contradicting the corpus.
    brief_rejected: bool = False
    #: P1-1/P1-9: the complete brief, so a reviewer can see what was actually
    #: asserted rather than only its hash.
    brief: dict = field(default_factory=dict)


@dataclass
class ReconciliationSegment:
    outcome: str = ""
    differing_fields: list[str] = field(default_factory=list)
    #: P1-1: the ACTUAL differing values, not just which fields differed. An
    #: auditor needs to see what each agent said, or "they disagreed on basis"
    #: is unreviewable.
    investigator_values: dict = field(default_factory=dict)
    verifier_values: dict = field(default_factory=dict)


@dataclass
class CorpusSegment:
    """P1-1: every authoritative object consulted, with its version.

    Without this an auditor cannot tell whether a decision was made against the
    corpus as it stood then or as it stands now.
    """

    #: object_id -> {"version"/"revision", "status", "effective_*", ...}
    objects: dict[str, dict] = field(default_factory=dict)
    corpus_hash: str = ""


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
    #: The inventory row as it stood before and after the transition. A delta of
    #: 0.0 is a real, defensible outcome — quarantining a lot that was never
    #: usable moves nothing — but it is only defensible if the record shows the
    #: inventory was actually evaluated. These two fields are that proof, and
    #: they are what distinguishes "no change was required" from "the
    #: consequence step never ran".
    inventory_before: dict = field(default_factory=dict)
    inventory_after: dict = field(default_factory=dict)
    ledger_sequence: int = 0
    result: str = "NO_MUTATION"


@dataclass
class StorageSegment:
    """P0-5/P1-1: where this record and its evidence actually live."""

    evidence_store: str = ""
    record_store: str = ""
    record_ref: str = ""
    event_count: int = 0
    #: audit-2 F8: the highest durable event sequence, so a resumed run can be
    #: shown to have EXTENDED history rather than restarted it.
    last_event_sequence: int = 0


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
class ArchivedRun:
    """One completed run's structured evidence, kept when the next run begins.

    `investigator`, `verifier` and `reconciliation` are single segments, so a
    resumed case overwrote the run that made it necessary: Records could show
    that a decision abstained, but not what the two agents actually said when it
    did. The reason a human was asked for evidence was the first thing lost.

    Structured facts only — briefs, hashes, tool metadata, the reconciliation
    values. The same rule the live segments follow: no chain of thought, because
    there is no field here to put it in.
    """

    run_number: int = 0
    investigator: AgentSegment = field(default_factory=AgentSegment)
    verifier: AgentSegment = field(default_factory=AgentSegment)
    reconciliation: ReconciliationSegment = field(default_factory=ReconciliationSegment)
    basis: BasisSegment = field(default_factory=BasisSegment)
    disposition: DispositionSegment = field(default_factory=DispositionSegment)
    snapshot: SnapshotSegment = field(default_factory=SnapshotSegment)
    failure_category: str = ""
    archived_at: str = field(default_factory=utcnow)


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
    corpus: CorpusSegment = field(default_factory=CorpusSegment)
    basis: BasisSegment = field(default_factory=BasisSegment)
    disposition: DispositionSegment = field(default_factory=DispositionSegment)
    policy: PolicySegment = field(default_factory=PolicySegment)
    capability: CapabilitySegment = field(default_factory=CapabilitySegment)
    mutation: MutationSegment = field(default_factory=MutationSegment)
    consequences: ConsequenceSegment = field(default_factory=ConsequenceSegment)
    human: HumanContinuationSegment = field(default_factory=HumanContinuationSegment)
    storage: StorageSegment = field(default_factory=StorageSegment)
    #: Completed runs, oldest first. Run N is archived when run N+1 begins, so
    #: this holds every run but the current one.
    archived_runs: list[ArchivedRun] = field(default_factory=list)

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
        """A human supplied evidence; the SAME record continues (contract §18).

        The outgoing run is archived first. This is the only moment its evidence
        still exists: the next run writes straight over `investigator`,
        `verifier` and `reconciliation`.
        """
        self.archived_runs.append(
            ArchivedRun(
                run_number=self.run_count,
                investigator=replace(self.investigator),
                verifier=replace(self.verifier),
                reconciliation=replace(self.reconciliation),
                basis=replace(self.basis),
                disposition=replace(self.disposition),
                snapshot=replace(self.snapshot),
                failure_category=self.failure_category,
            )
        )
        self.run_count += 1
        self.human.resumed_run_ids.append(f"{self.record_id}#run{self.run_count}")

    def runs(self) -> list[ArchivedRun]:
        """Every run in order, the current one included.

        What an audit surface actually wants: `archived_runs` alone is missing
        the run in progress, and the live segments alone are missing history.
        """
        return [*self.archived_runs, ArchivedRun(
            run_number=self.run_count,
            investigator=self.investigator,
            verifier=self.verifier,
            reconciliation=self.reconciliation,
            basis=self.basis,
            disposition=self.disposition,
            snapshot=self.snapshot,
            failure_category=self.failure_category,
        )]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def audit_hash(self) -> str:
        """Hash over everything except the volatile event list."""
        payload = self.to_dict()
        payload.pop("events", None)
        return content_hash(payload)

    # ------------------------------------------------------------------
    # completeness (audit-2 F9)
    # ------------------------------------------------------------------
    @property
    def decision_type(self) -> str:
        """What kind of decision this record represents.

        Completeness is not one rule (audit-2 F9). An autonomous RELEASE must
        carry an authority chain and a mutation; an abstention must carry an
        escalation and must NOT claim a mutation; a technical failure cannot be
        required to carry a brief the model never produced. Asking one flat
        question of all three is how the old check stayed true after critical
        components were removed.
        """
        if self.mutation.action == "create_qa_review":
            # An abstention that DID mutate: the QA review is a real,
            # gate-authorized state change, but the lot's disposition was not
            # decided. It requires the full authority chain AND the escalation.
            return "AUTHORIZED_ESCALATION"
        if self.mutation.action:
            return "AUTONOMOUS_MUTATION"
        if self.failure_category:
            return "ESCALATED"
        return "INCOMPLETE"

    def _missing(self) -> list[str]:
        """Every required component this record does not have.

        Returned as a list rather than a bool so a failing assertion says WHICH
        link is missing. Each entry is checked against what that decision type
        actually requires, and aligned arrays are checked for alignment rather
        than merely for being non-empty — a record with three evidence hashes
        and one storage ref cannot re-fetch two of its own artifacts.
        """
        missing: list[str] = []

        def need(condition: bool, name: str) -> None:
            if not condition:
                missing.append(name)

        # -- identity, always -------------------------------------------
        need(bool(self.record_id), "record_id")
        need(bool(self.identity.record_id), "identity.record_id")
        need(bool(self.identity.lot_id), "identity.lot_id")
        need(bool(self.policy.policy_version), "policy.policy_version")
        need(bool(self.storage.record_ref), "storage.record_ref")

        kind = self.decision_type
        if kind == "INCOMPLETE":
            missing.append("neither a mutation nor a failure category")
            return missing

        # -- evidence provenance ----------------------------------------
        # A record with no artifacts at all is legitimate (an abstention for
        # missing paperwork), but a record whose decision RESTED on claims must
        # be able to re-fetch every artifact those claims came from.
        hashes = self.evidence.source_artifact_hashes
        if self.extraction.per_claim or self.evidence.canonical_claims:
            need(bool(hashes), "evidence.source_artifact_hashes")
            need(bool(self.evidence.storage_refs), "evidence.storage_refs")
            need(bool(self.evidence.object_versions), "evidence.object_versions")
            need(
                bool(self.evidence.document_identities),
                "evidence.document_identities",
            )
        if hashes:
            aligned = (
                len(self.evidence.storage_refs),
                len(self.evidence.object_versions),
                len(self.evidence.document_identities),
                len(self.evidence.receipt_timestamps),
                len(self.evidence.claimed_identities),
                len(self.evidence.content_types),
            )
            need(
                all(count == len(hashes) for count in aligned),
                "evidence arrays are not aligned with source_artifact_hashes",
            )
            need(all(bool(h) for h in hashes), "evidence.source_artifact_hashes values")
            need(all(bool(r) for r in self.evidence.storage_refs), "evidence.storage_refs values")
            need(
                all(bool(v) for v in self.evidence.object_versions),
                "evidence.object_versions values",
            )
            need(
                all(bool(d) for d in self.evidence.document_identities),
                "evidence.document_identities values",
            )
            need(
                len(self.evidence.binding_statuses) == len(hashes),
                "evidence.binding_statuses",
            )

        # -- per-claim extraction provenance ----------------------------
        for claim_id, meta in self.extraction.per_claim.items():
            for field_name in ("method", "version", "locator", "source_hash"):
                need(bool(meta.get(field_name)), f"extraction.per_claim[{claim_id}].{field_name}")

        # -- snapshot ----------------------------------------------------
        need(bool(self.snapshot.claim_set_hash), "snapshot.claim_set_hash")

        # -- agent segments ----------------------------------------------
        # A model that never ran cannot be required to have produced a brief —
        # but it MUST have recorded why, and the model identity is required
        # either way so an auditor knows which model was asked.
        for label, segment in (("investigator", self.investigator), ("verifier", self.verifier)):
            if segment.failure_category:
                need(bool(segment.failure), f"{label}.failure detail")
                continue
            if kind == "ESCALATED" and not segment.model_id:
                # The pipeline exited before this agent ran at all (e.g. an
                # evidence-binding refusal). Nothing to require.
                continue
            need(bool(segment.model_id), f"{label}.model_id")
            need(bool(segment.prompt_version), f"{label}.prompt_version")
            need(bool(segment.prompt_hash), f"{label}.prompt_hash")
            need(segment.temperature is not None, f"{label}.temperature")
            need(bool(segment.brief), f"{label}.brief")
            need(bool(segment.brief_hash), f"{label}.brief_hash")
            need(
                segment.input_claim_set_hash == self.snapshot.claim_set_hash,
                f"{label}.input_claim_set_hash does not match the snapshot",
            )
            for index, event in enumerate(segment.tool_events):
                need(bool(event.get("tool")), f"{label}.tool_events[{index}].tool")
                need(
                    "arguments" in event or bool(event.get("arguments_ref")),
                    f"{label}.tool_events[{index}].arguments",
                )
                need(
                    "result" in event or bool(event.get("result_ref")),
                    f"{label}.tool_events[{index}].result",
                )

        # -- reconciliation ----------------------------------------------
        if self.investigator.brief and self.verifier.brief:
            need(bool(self.reconciliation.outcome), "reconciliation.outcome")
            if self.reconciliation.differing_fields:
                # F9: a disagreement must record what each side actually said.
                need(
                    bool(self.reconciliation.investigator_values),
                    "reconciliation.investigator_values",
                )
                need(
                    bool(self.reconciliation.verifier_values),
                    "reconciliation.verifier_values",
                )
                need(
                    set(self.reconciliation.differing_fields)
                    <= set(self.reconciliation.investigator_values)
                    and set(self.reconciliation.differing_fields)
                    <= set(self.reconciliation.verifier_values),
                    "reconciliation values do not cover every differing field",
                )

        # -- corpus and basis --------------------------------------------
        if kind == "AUTONOMOUS_MUTATION" or self.basis.spec_id:
            need(bool(self.corpus.objects), "corpus.objects")
            need(bool(self.corpus.corpus_hash), "corpus.corpus_hash")
            need(
                self.corpus.corpus_hash == content_hash(self.corpus.objects),
                "corpus.corpus_hash does not match corpus.objects",
            )
            for object_id, meta in self.corpus.objects.items():
                need(bool(meta.get("kind")), f"corpus.objects[{object_id}].kind")
                if meta.get("kind") == "spec_revision":
                    need(
                        bool(meta.get("revision")),
                        f"corpus.objects[{object_id}].revision",
                    )

        # -- policy -------------------------------------------------------
        need(bool(self.policy.gate_decision), "policy.gate_decision")

        if kind in ("ESCALATED", "AUTHORIZED_ESCALATION"):
            # An escalation must actually escalate: a human has to be able to
            # find the open question.
            need(bool(self.human.review_id), "human.review_id")
            need(bool(self.human.review_status), "human.review_status")

        if kind == "ESCALATED":
            # No mutation happened, so the record must not claim one.
            need(bool(self.failure_category), "failure_category")
            need(not self.mutation.action, "escalated record claims a mutation")
            need(
                not self.capability.consumed,
                "escalated record claims a consumed capability",
            )
            return missing

        if kind == "AUTHORIZED_ESCALATION":
            # The QA review IS a gate-authorized mutation, so the authority
            # chain is required exactly as it is for a release — but the
            # DISPOSITION is an abstention, so no basis pass is claimed.
            need(bool(self.disposition.disposition), "disposition.disposition")
            need(bool(self.disposition.reason), "disposition.reason")
            need(self.policy.gate_decision == "ALLOWED", "policy gate did not allow")
            need(bool(self.capability.capability_id), "capability.capability_id")
            need(self.capability.issued, "capability.issued")
            need(self.capability.consumed, "capability.consumed")
            need(bool(self.mutation.target_type), "mutation.target_type")
            need(bool(self.mutation.target_id), "mutation.target_id")
            need(bool(self.mutation.result), "mutation.result")
            need(self.mutation.ledger_sequence != 0, "mutation.ledger_sequence")
            need(
                self.mutation.inventory_delta == 0.0,
                "an escalation must not move usable inventory",
            )
            return missing

        # -- AUTONOMOUS_MUTATION: the full authority chain ----------------
        need(bool(self.disposition.disposition), "disposition.disposition")
        need(bool(self.disposition.reason), "disposition.reason")
        need(self.basis.checks_passed, "basis.checks_passed")
        need(bool(self.basis.spec_id), "basis.spec_id")
        need(bool(self.basis.revision), "basis.revision")
        need(self.policy.gate_decision == "ALLOWED", "policy gate did not allow")
        need(bool(self.capability.capability_id), "capability.capability_id")
        need(self.capability.issued, "capability.issued")
        need(self.capability.consumed, "capability.consumed")
        need(bool(self.mutation.target_type), "mutation.target_type")
        need(bool(self.mutation.target_id), "mutation.target_id")
        need(
            self.mutation.target_id == self.identity.lot_id
            or self.mutation.target_type == "production_order",
            "mutation target does not match the record's subject",
        )
        need(bool(self.mutation.result), "mutation.result")
        need(self.mutation.ledger_sequence != 0, "mutation.ledger_sequence")
        need(
            self.mutation.after_version > self.mutation.before_version,
            "mutation before/after state versions",
        )
        need(
            self.mutation.before_version == self.snapshot.lot_state_version
            or self.mutation.target_type == "production_order",
            "mutation.before_version does not match the observed snapshot version",
        )
        # Inventory: a release or quarantine must show that usable inventory
        # was EVALUATED. Requiring a non-zero delta was wrong: quarantining a
        # lot that was not yet usable correctly moves nothing, and that lot is
        # exactly the Hero A case. What must never be missing is the evidence
        # that the inventory position was examined.
        if self.mutation.action in ("release_lot", "quarantine_lot"):
            need(
                bool(self.mutation.inventory_before)
                and bool(self.mutation.inventory_after),
                "mutation.inventory_before/after for a release/quarantine",
            )
        # Consequences: a mutation that changed usable inventory must record
        # what it did to coverage and readiness, and any recovery it triggered.
        if self.mutation.inventory_delta:
            # The causal chain must be recorded, but a readiness TRANSITION is
            # not the only honest outcome. Releasing a lot into an order that
            # was already covered changes coverage and flips nothing — that is
            # Hero B. Requiring `caused_by` there would have forced us either to
            # invent a transition or to call a correct record incomplete, so the
            # requirement is the consequence analysis, of which a readiness
            # change is one form and a coverage recalculation the other.
            need(
                bool(self.consequences.caused_by)
                or bool(self.consequences.coverage_changes),
                "consequences.caused_by or coverage_changes",
            )
        for change in self.consequences.readiness_changes:
            if change.get("to") == "BLOCKED":
                need(
                    bool(self.consequences.recovery),
                    "consequences.recovery for a blocked order",
                )

        return missing

    def missing_components(self) -> list[str]:
        """Public: exactly which required components are absent."""
        return self._missing()

    def is_reconstructable(self) -> bool:
        """The D13 completeness claim, checked rather than asserted.

        audit-2 F9: decision-type-aware. The old version was a flat list of
        nine truthiness checks and stayed True after storage refs, object
        versions, prompt hashes, tool arguments, capability bindings and
        mutation facts were removed one at a time. Every one of those is now
        required where the decision type requires it.
        """
        return not self._missing()

    def is_re_derivable(self) -> bool:
        """P1-1: could an auditor rebuild this decision from what is stored?

        Re-derivability is reconstructability plus verifiable hashes: the same
        evidence bytes and corpus versions must reproduce the same claim set
        and corpus hash, so a record whose stored hash does not match its own
        stored contents is not re-derivable no matter how complete it looks.
        """
        if self._missing():
            return False
        if self.corpus.objects and self.corpus.corpus_hash != content_hash(
            self.corpus.objects
        ):
            return False
        return True


__all__ = [
    "AgentSegment",
    "BasisSegment",
    "CapabilitySegment",
    "ConsequenceSegment",
    "CorpusSegment",
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
    "StorageSegment",
]
