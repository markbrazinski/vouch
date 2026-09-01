"""The V2 decision pipeline.

This is a deterministic state machine, not a coordinator. The order of steps is
fixed and known; there is no decomposition for a model to discover, so no model
routes anything (contract D3).

    ingest -> inspect -> extract -> canonicalize -> freeze snapshot
        -> Investigator brief        (model)
        -> Verifier brief            (model, independent)
        -> reconcile                 (deterministic)
        -> basis checks              (deterministic, always)
        -> disposition               (deterministic)
        -> policy                    (deterministic, only issuer of authority)
        -> capability consume + mutate (atomic)
        -> consequences              (deterministic)

Every exit is typed. A technical failure never becomes a domain answer — the
V1 defect at workflow.py:70-77 collapsed SchemaFailure into
INSUFFICIENT_EVIDENCE, which made a broken model look like missing paperwork.
"""

from __future__ import annotations

import time

import uuid
from dataclasses import dataclass, field

from .agents import ApplicabilityInvestigator, IndependentVerifier
from .authority import Action, CapabilityStore, PolicyEngine, execute
from .consequences import Verdict, enumerate_recovery, recalculate_consequences
from .contracts import (
    ArtifactStatus,
    content_hash,
    CanonicalEvidenceClaim,
    Disposition,
    EvidenceSnapshot,
    FailureCategory,
    ReconciliationOutcome,
    TrustLabel,
    VouchFailure,
)
from .corpus import Corpus
from .decision_record import DecisionRecord
from .disposition import compute_disposition
from .evidence import (
    LOW_CONFIDENCE,
    LocalEvidenceStore,
    canonicalize,
    extract,
    freeze_snapshot,
    ingest,
)
from .lifecycle import EventLog, EventType, utcnow
from .persistence import InMemoryRecordStore, hydrate_claims, hydrate_record
from .local_reasoners import investigator_reasoner, verifier_reasoner
from .reconcile import POLICY_VERSION, reconcile, run_basis_checks

MAX_MODEL_ATTEMPTS = 2

#: Base backoff before retrying a throttled or timed-out model call, multiplied
#: by the attempt number. Bedrock throttles under burst; retrying instantly just
#: collides again. Read through `vouch.config.env_var` so a test suite or a
#: local run can set it to 0 without patching the clock.
def _throttle_backoff_seconds() -> float:
    from ..config import env_var

    try:
        return float(env_var("THROTTLE_BACKOFF_SECONDS") or 3.0)
    except ValueError:
        return 3.0


def _binding_reasons(artifact, inspection) -> list[str]:
    """Why this artifact is not affirmatively bound, if it is not (F3/F4)."""
    if artifact.binding_status == "MISMATCH":
        return list(inspection.binding_mismatches)
    if artifact.binding_status == "IDENTITY_CONFLICT":
        identity = inspection.claimed_identity
        conflicts = []
        for label, key in (
            ("lot", "claimed_lots"), ("material", "claimed_materials"),
            ("supplier", "claimed_suppliers"), ("supplier_site", "claimed_supplier_sites"),
        ):
            values = identity.get(key, [])
            if len(values) > 1:
                conflicts.append(
                    f"document asserts conflicting {label} identities: "
                    + ", ".join(values)
                )
        return conflicts
    if artifact.binding_status == "UNBOUND_NO_IDENTITY":
        return [
            "document states no lot, material or supplier identity, so it "
            "cannot be affirmatively bound to the receiving record"
        ]
    return []


@dataclass
class DecisionOutcome:
    """What the pipeline concluded, and what it did about it."""

    decision_record_id: str
    lot_id: str
    disposition: str = ""
    failure_category: str = ""
    quality_decision_required: bool = False
    reason: str = ""
    mutation: dict = field(default_factory=dict)
    consequences: dict = field(default_factory=dict)
    record: DecisionRecord | None = None
    events: list[dict] = field(default_factory=list)

    @property
    def mutated(self) -> bool:
        return bool(self.mutation)


class VouchV2:
    """One decision pipeline over one authoritative corpus."""

    def __init__(
        self,
        corpus: Corpus,
        *,
        evidence_store: LocalEvidenceStore | None = None,
        capabilities: CapabilityStore | None = None,
        investigator=None,
        verifier=None,
        detector=None,
        model_fallback=None,
        scanner=None,
        record_store=None,
    ) -> None:
        self.corpus = corpus
        self.evidence_store = evidence_store or LocalEvidenceStore()
        self.capabilities = capabilities or CapabilityStore()
        self.policy = PolicyEngine(corpus, self.capabilities)
        self.detector = detector
        self.model_fallback = model_fallback
        self.scanner = scanner
        # P1-1/P1-2: durable by default. InMemoryRecordStore is explicitly
        # labeled non-durable and is only chosen by a caller that wants it.
        self.record_store = record_store or InMemoryRecordStore()

        # Local reasoners are the default so the architecture is testable
        # without model access; bedrock mode swaps them at the agent layer.
        self.investigator = investigator or ApplicabilityInvestigator(
            corpus, local_fn=investigator_reasoner
        )
        self.verifier = verifier or IndependentVerifier(
            corpus, local_fn=verifier_reasoner
        )

        # Process-local CACHE of the durable record, never the record itself
        # (audit-2 F8). `_record_for` reads through to the store on a miss, so
        # a fresh process resumes a case rather than failing to find it.
        self.records: dict[str, DecisionRecord] = {}
        self.claims: dict[str, list[CanonicalEvidenceClaim]] = {}

    # ------------------------------------------------------------------
    # durable hydration (audit-2 F8)
    # ------------------------------------------------------------------
    def _record_for(self, record_id: str) -> DecisionRecord | None:
        """The DecisionRecord for this case, from memory or from the store.

        The audit found `supply_human_evidence` reading only `self.records`, so
        destroying the process destroyed the case: a persisted record could
        never be continued. Reading through to the durable store is what makes
        "the same case resumes" true across a restart rather than only within
        one process.
        """
        cached = self.records.get(record_id)
        if cached is not None:
            return cached
        stored = self.record_store.load(record_id)
        if stored is None:
            return None
        record = hydrate_record(stored)
        self.records[record_id] = record
        self.claims.setdefault(record_id, hydrate_claims(stored))
        return record

    def resume(self, record_id: str) -> DecisionRecord | None:
        """Public hydration entry point. Also refreshes corpus state.

        A resumed case must judge against the CURRENT lot version, not the one
        the previous run saw, so any cached corpus objects are dropped first.
        """
        refresh = getattr(self.corpus, "refresh", None)
        if callable(refresh):
            refresh()
        return self._record_for(record_id)

    # ------------------------------------------------------------------
    # ingestion
    # ------------------------------------------------------------------
    def ingest_evidence(
        self,
        *,
        decision_record_id: str,
        lot_id: str,
        raw: bytes,
        content_type: str = "text/plain",
        document_identity: str = "COA",
        source: str = "supplier-portal",
        events: EventLog,
        trust_label: TrustLabel = TrustLabel.UNTRUSTED_SUPPLIER,
    ) -> tuple[list[CanonicalEvidenceClaim], dict]:
        """S1-S6 for one artifact. Returns (claims, security_summary).

        `lot_id` is the REQUESTED TARGET. The document's own claimed identity is
        parsed from its bytes and validated against the authoritative receiving
        record (P0-4); a contradiction yields no claims and no autonomous
        disposition. A security-quarantined artifact likewise yields nothing:
        hostile content never reaches a decision model, and the artifact is
        preserved for human review rather than dropped.
        """
        lot = self.corpus.lot(lot_id)
        artifact = ingest(
            raw=raw,
            content_type=content_type,
            source=source,
            supplier_id=lot.supplier_id if lot else "",
            supplier_site=lot.supplier_site if lot else "",
            lot_id=lot_id,
            material_id=lot.material_id if lot else "",
            document_identity=document_identity,
            store=self.evidence_store,
            events=events,
            decision_record_id=decision_record_id,
            detector=self.detector,
            scanner=self.scanner,
            trust_label=trust_label,
        )

        inspection = artifact.security_inspection
        summary = {
            "artifact_id": artifact.artifact_id,
            "content_hash": artifact.content_hash,
            "object_version": artifact.object_version,
            "storage_ref": artifact.storage_ref,
            "document_identity": artifact.document_identity,
            "received_at": artifact.received_at,
            "inspection": inspection,
            "status": artifact.status,
            "claimed_identity": inspection.claimed_identity,
            "binding_mismatches": list(inspection.binding_mismatches),
            # audit-2 F3/F4: the explicit binding outcome and every reason.
            "binding_status": artifact.binding_status,
            "binding_reasons": _binding_reasons(artifact, inspection),
            "identity_stated": artifact.identity_stated,
        }

        if artifact.parse_error:
            # P0-8. The artifact could not be read at all. That is an extraction
            # failure requiring a human, not evidence that anything is missing.
            summary["extraction_method"] = "NONE"
            summary["extraction_confidence"] = 0.0
            summary["low_confidence"] = True
            summary["parse_error"] = artifact.parse_error
            return [], summary

        if artifact.status is ArtifactStatus.QUARANTINED_SECURITY:
            # Hostile content never reaches extraction, let alone a model. The
            # artifact is preserved for human review rather than dropped.
            summary["extraction_method"] = "NONE"
            summary["extraction_confidence"] = 0.0
            summary["low_confidence"] = False
            summary["parse_error"] = artifact.parse_error
            return [], summary

        # P0-8: the text comes from the content-type-aware parser used during
        # ingestion (a real PDF parser for PDFs), not a blind utf-8 decode.
        #
        # Extraction runs even for an artifact that is not affirmatively bound
        # (audit-2 F3/F4), because "how much of this could we read" is a fact
        # about the bytes and stays truthful either way. What the binding status
        # controls is whether the resulting claims may be USED — an unbound or
        # conflicted artifact returns none.
        candidates, method, confidence = extract(
            artifact, artifact.extraction_text, events, decision_record_id,
            self.model_fallback, parse_confidence=artifact.parse_confidence,
        )
        summary["extraction_method"] = method.value
        summary["extraction_confidence"] = confidence
        summary["low_confidence"] = confidence < LOW_CONFIDENCE
        summary["parse_error"] = artifact.parse_error

        if artifact.status is not ArtifactStatus.RECEIVED:
            # F3/F4: mismatch, self-conflict or no identity at all. No claims
            # enter the autonomous snapshot, and nothing is rebound to the
            # requested lot.
            return [], summary

        claims = canonicalize(candidates, artifact, method, trust_label)
        return claims, summary

    # ------------------------------------------------------------------
    # the decision
    # ------------------------------------------------------------------
    def evaluate_lot(
        self,
        lot_id: str,
        *,
        documents: list[dict] | None = None,
        decision_record_id: str | None = None,
        events: EventLog | None = None,
    ) -> DecisionOutcome:
        """Run the full pipeline for one lot."""
        record_id = decision_record_id or f"DR-{uuid.uuid4().hex[:12]}"
        events = events or EventLog()
        # F8: a record id that already exists durably is CONTINUED, never
        # replaced with a fresh object that would erase its prior runs.
        record = self._record_for(record_id) or DecisionRecord(record_id=record_id)
        self.records[record_id] = record

        lot = self.corpus.lot(lot_id)
        if lot is None:
            record.fail(FailureCategory.PERSISTENCE_FAILURE, f"unknown lot {lot_id}")
            self._persist(record, events)
            return DecisionOutcome(
                record_id, lot_id, failure_category=record.failure_category,
                reason=f"unknown lot {lot_id}", record=record, events=events.as_dicts(),
            )

        record.identity.record_id = record_id
        record.identity.lot_id = lot_id
        record.identity.material_id = lot.material_id
        record.identity.supplier_id = lot.supplier_id
        record.identity.supplier_site = lot.supplier_site
        record.policy.policy_version = POLICY_VERSION

        # -- 1. evidence -------------------------------------------------
        # F8: prior claims come from the hydrated record when this process did
        # not itself extract them.
        claims = list(self.claims.get(record_id, []))
        for document in documents or []:
            new_claims, summary = self.ingest_evidence(
                decision_record_id=record_id,
                lot_id=lot_id,
                events=events,
                **document,
            )
            inspection = summary["inspection"]
            record.evidence.source_artifact_hashes.append(summary["content_hash"])
            record.evidence.document_identities.append(summary["document_identity"])
            record.evidence.receipt_timestamps.append(summary["received_at"])
            record.evidence.storage_refs.append(summary["storage_ref"])
            record.evidence.object_versions.append(summary["object_version"])
            record.evidence.claimed_identities.append(summary["claimed_identity"])
            record.security.inspection_performed = True
            record.security.config_version = inspection.config_version
            record.security.detector = inspection.detector
            record.security.guardrail_outcome = inspection.guardrail_outcome.value
            record.security.guardrail_id = inspection.guardrail_id
            record.security.guardrail_version = inspection.guardrail_version
            record.security.malware_scan = inspection.malware_scan.value
            record.security.inspected_at = inspection.inspected_at
            record.security.prompt_attack_detected |= inspection.prompt_attack_detected
            record.security.malware_found |= inspection.malware_found

            record.evidence.binding_statuses.append(summary["binding_status"])

            if summary.get("parse_error") or summary.get("low_confidence"):
                # P0-8: the artifact could not be READ, or not read well enough
                # to stand alone. That is an EXTRACTION failure, not an identity
                # one. Checked before the binding branches because a document
                # nobody could parse obviously states no identity too, and
                # reporting it as "unbound" would point triage at the wrong
                # problem (audit-2 F3 must not swallow P0-8).
                record.extraction.low_confidence_routed_to_human = True
                if not summary.get("parse_error"):
                    # A readable-but-uncertain artifact may still have produced
                    # claims; keep them out of an autonomous disposition but do
                    # not discard the binding facts already recorded.
                    pass
                continue

            if summary["status"] is ArtifactStatus.EVIDENCE_BINDING_MISMATCH:
                # P0-4. The artifact is preserved and reported; it is NOT
                # rebound to the requested lot and produces no claims.
                record.security.binding_mismatches.extend(summary["binding_mismatches"])
                record.security.rejected_artifact_ids.append(summary["artifact_id"])
                continue

            if summary["status"] is ArtifactStatus.EVIDENCE_IDENTITY_CONFLICT:
                # audit-2 F4. The artifact contradicts ITSELF. Preserved, no
                # claims, explicit conflict recorded for human review.
                record.security.identity_conflicts.extend(summary["binding_reasons"])
                record.security.rejected_artifact_ids.append(summary["artifact_id"])
                continue

            if summary["status"] is ArtifactStatus.EVIDENCE_UNBOUND:
                # audit-2 F3. The artifact states no identity, so it cannot be
                # affirmatively bound. Preserved, no claims, human review — and
                # explicitly NOT a defect finding about the lot.
                record.security.unbound_artifact_ids.append(summary["artifact_id"])
                continue

            if summary["status"] is ArtifactStatus.QUARANTINED_SECURITY:
                record.security.blocked = True
                record.security.quarantined_artifact_ids.append(summary["artifact_id"])
                continue

            for claim in new_claims:
                record.extraction.per_claim[claim.claim_id] = {
                    "method": claim.extraction_method.value,
                    "version": claim.extraction_version,
                    "confidence": claim.extraction_confidence,
                    "locator": claim.source_locator,
                    "source_hash": claim.source_hash,
                    "trust_label": claim.trust_label.value,
                }
            if summary.get("extraction_method") == "MODEL_FALLBACK":
                record.extraction.model_fallback_used = True
            if summary.get("low_confidence"):
                # P0-8: truthful, and it actually routes.
                record.extraction.low_confidence_routed_to_human = True
            claims.extend(new_claims)

        self.claims[record_id] = claims

        # P0-4. Evidence that belongs to another lot/material/supplier/site is
        # a distinct outcome from insufficiency AND from a security quarantine:
        # nothing is wrong with the document, it is simply not about this lot.
        if record.security.binding_mismatches and not claims:
            return self._quality_decision(
                record, events, lot_id,
                FailureCategory.EVIDENCE_BINDING_MISMATCH,
                "; ".join(record.security.binding_mismatches),
            )

        # Extraction confidence too low to stand alone routes to a human rather
        # than to an autonomous disposition (P0-8).
        if record.extraction.low_confidence_routed_to_human and not claims:
            return self._quality_decision(
                record, events, lot_id,
                FailureCategory.EXTRACTION_LOW_CONFIDENCE,
                "extraction confidence below threshold; human review required",
            )

        # audit-2 F4. A self-contradictory artifact is its own category: the
        # document is not about another lot, it cannot say which lot it is
        # about at all.
        if record.security.identity_conflicts and not claims:
            return self._quality_decision(
                record, events, lot_id,
                FailureCategory.EVIDENCE_IDENTITY_CONFLICT,
                "; ".join(record.security.identity_conflicts),
            )

        # audit-2 F3. Evidence that cannot be affirmatively bound to the
        # receiving identity produces no autonomous disposition. The artifact
        # is preserved and a human decides; the lot is NOT marked defective,
        # because an unbindable document says nothing about its quality.
        if record.security.unbound_artifact_ids and not claims:
            return self._quality_decision(
                record, events, lot_id,
                FailureCategory.EVIDENCE_UNBOUND,
                "evidence states no lot, material or supplier identity and "
                "cannot be bound to this receipt; human review required",
            )

        # A security block with no usable evidence is a SECURITY_QUARANTINE,
        # not insufficiency: the difference matters to whoever triages it.
        if record.security.blocked and not claims:
            return self._quality_decision(
                record, events, lot_id,
                FailureCategory.SECURITY_QUARANTINE,
                "evidence quarantined by security inspection; human review required",
            )

        # -- 2. freeze ---------------------------------------------------
        lot_version = self.corpus.version_of("lot", lot_id)
        order_versions = {
            order.order_id: order.state_version
            for order in self.corpus.all("production_order")
            if any(line.material_id == lot.material_id for line in order.requirements)
        }
        snapshot = freeze_snapshot(
            claims=claims,
            decision_record_id=record_id,
            lot_id=lot_id,
            lot_state_version=lot_version,
            order_state_versions=order_versions,
            events=events,
        )
        record.snapshot.snapshot_id = snapshot.snapshot_id
        record.snapshot.claim_set_hash = snapshot.claim_set_hash
        record.snapshot.lot_state_version = lot_version
        record.snapshot.order_state_versions = dict(order_versions)

        context = {
            "lot_id": lot_id,
            "material_id": lot.material_id,
            "manufactured_at": lot.manufactured_at,
            "received_at": lot.received_at,
            "supplier_site": lot.supplier_site,
            "customer_id": lot.customer_id,
            "po_reference": lot.po_reference,
        }

        # -- 3. two independent briefs -----------------------------------
        # Each brief is validated against the authoritative corpus BEFORE the
        # two are compared (audit blocker 2). Validation was already written —
        # `run_basis_checks` catches an out-of-scope equivalence, a
        # non-existent object, evidence from another lot — but it only ran
        # after reconciliation, so a contract-INVALID brief and a valid one
        # reconciled to MATERIAL_DISAGREEMENT and the pipeline stopped before
        # the check that would have named the invalid one.
        #
        # Live Nova runs showed exactly that: both agents reasoned identically
        # and correctly, then one recorded an equivalence it had itself
        # rejected. Validating first turns that into a retryable, machine-
        # readable contract error instead of a false disagreement.
        claims_by_id = {c.claim_id: c for c in claims}
        investigation = self._run_with_retry(
            self.investigator, context, claims, events, record_id,
            validate=lambda brief: self._brief_contract_errors(
                brief, lot_id, claims_by_id
            ),
        )
        record.investigator = self._agent_segment(investigation, snapshot)

        if investigation.brief is None:
            # P1-3: report what ACTUALLY failed. A Bedrock outage is not a
            # schema failure, and an auditor must be able to tell them apart.
            return self._quality_decision(
                record, events, lot_id,
                investigation.failure_category
                or FailureCategory.INVESTIGATOR_SCHEMA_FAILURE,
                f"investigator failed: {investigation.failure}",
            )

        verification = self._run_with_retry(
            self.verifier, context, claims, events, record_id,
            validate=lambda brief: self._brief_contract_errors(
                brief, lot_id, claims_by_id
            ),
        )
        record.verifier = self._agent_segment(verification, snapshot)

        if verification.brief is None:
            # Verification unavailable fails CLOSED to abstain (contract D5),
            # under its actual category (P1-3).
            return self._quality_decision(
                record, events, lot_id,
                verification.failure_category
                or FailureCategory.VERIFIER_SCHEMA_FAILURE,
                f"verification unavailable: {verification.failure}",
            )

        # -- 4. reconcile -------------------------------------------------
        reconciliation = reconcile(
            investigation.brief, verification.brief, events, record_id
        )
        record.reconciliation.outcome = reconciliation.outcome.value
        record.reconciliation.differing_fields = reconciliation.differing_fields
        # P1-1/P1-9: the actual differing VALUES, so a disagreement is
        # reviewable rather than merely announced.
        if reconciliation.differing_fields:
            left = investigation.brief.material_fingerprint()
            right = verification.brief.material_fingerprint()
            record.reconciliation.investigator_values = {
                k: left[k] for k in reconciliation.differing_fields
            }
            record.reconciliation.verifier_values = {
                k: right[k] for k in reconciliation.differing_fields
            }

        if reconciliation.outcome is ReconciliationOutcome.MATERIAL_DISAGREEMENT:
            return self._quality_decision(
                record, events, lot_id,
                FailureCategory.MATERIAL_DISAGREEMENT,
                reconciliation.detail,
            )
        if reconciliation.outcome is ReconciliationOutcome.TECHNICAL_FAILURE:
            return self._quality_decision(
                record, events, lot_id, FailureCategory.MODEL_UNAVAILABLE,
                reconciliation.detail,
            )

        # -- 5. basis checks (always) -------------------------------------
        brief = investigation.brief
        checks = run_basis_checks(
            brief, self.corpus, lot_id=lot_id, claims_by_id=claims_by_id
        )
        record.corpus.objects = self._enrich_corpus_objects(
            self._corpus_objects(brief, lot, checks)
        )
        record.corpus.corpus_hash = content_hash(record.corpus.objects)
        record.basis.spec_id = brief.governing_basis.spec_id
        record.basis.revision = brief.governing_basis.revision
        record.basis.checks_passed = checks.passed
        record.basis.check_failures = checks.failures

        if not checks.passed:
            return self._quality_decision(
                record, events, lot_id, FailureCategory.POLICY_REFUSAL,
                "; ".join(checks.failures),
            )

        # -- 6. deterministic disposition ---------------------------------
        result = compute_disposition(
            brief, checks.resolved_requirements, claims_by_id, self.corpus,
            lot_id=lot_id, events=events, decision_record_id=record_id,
        )
        record.disposition.disposition = result.disposition.value
        record.disposition.reason = result.reason

        # -- 7. policy + capability ---------------------------------------
        decision = self.policy.evaluate_lot_disposition(
            decision_record_id=record_id,
            lot_id=lot_id,
            disposition=result.disposition,
            reconciliation_ok=True,
            basis_checks_ok=True,
            observed_state_version=lot_version,
            events=events,
        )
        record.policy.gate_decision = "ALLOWED" if decision.allowed else "REFUSED"

        if not decision.allowed or decision.capability is None:
            record.policy.refusal_reason = decision.reason
            return self._quality_decision(
                record, events, lot_id, FailureCategory.POLICY_REFUSAL, decision.reason,
            )

        record.capability.capability_id = decision.capability.capability_id
        record.capability.issued = True

        # -- 8. atomic mutation --------------------------------------------
        try:
            entry = execute(decision.capability, self.corpus, self.capabilities, events)
        except VouchFailure as failure:
            record.capability.refusal_reason = failure.detail
            return self._quality_decision(
                record, events, lot_id, failure.category, failure.detail
            )

        record.capability.consumed = True
        record.mutation.target_type = entry["target_type"]
        record.mutation.target_id = entry["target_id"]
        record.mutation.action = entry["action"]
        record.mutation.before_version = entry["before_version"]
        record.mutation.after_version = entry["after_version"]
        record.mutation.inventory_delta = entry["inventory_delta"]
        record.mutation.inventory_before = entry.get("inventory_before", {})
        record.mutation.inventory_after = entry.get("inventory_after", {})
        record.mutation.ledger_sequence = entry["sequence"]
        record.mutation.result = entry["result"]

        # -- 9. consequences -----------------------------------------------
        # P1-6: readiness changes are PERSISTED through policy + capability,
        # not merely computed and returned.
        consequences = recalculate_consequences(
            self.corpus,
            decision_record_id=record_id,
            lot_id=lot_id,
            inventory_delta=entry["inventory_delta"],
            events=events,
            policy=self.policy,
            capabilities=self.capabilities,
        )
        record.consequences.coverage_changes = consequences["coverage_changes"]
        record.consequences.readiness_changes = consequences["readiness_changes"]
        record.consequences.caused_by = consequences["caused_by"]

        # P1-7: where an order was blocked, evaluate and EXECUTE safe recovery.
        for change in consequences["readiness_changes"]:
            if change["to"] == "BLOCKED":
                record.consequences.recovery = self.recover_order(
                    change["order_id"], decision_record_id=record_id, events=events,
                )
                # The caller gets what the record got. Recovery is the half of
                # the consequence that actually moved the schedule, so omitting
                # it from the returned dict left every API consumer — the
                # AgentCore runtime included — unable to see the candidates,
                # the refusals, or the executed resequence.
                consequences["recovery"] = record.consequences.recovery
                break

        if result.disposition is Disposition.INSUFFICIENT_EVIDENCE:
            record.human.review_id = f"QA-{record_id}"
            record.human.review_status = "OPEN"
            events.emit(
                EventType.QUALITY_DECISION_REQUIRED, record_id,
                reason="INSUFFICIENT", lot_id=lot_id,
            )

        record.terminal = result.disposition in (Disposition.RELEASE, Disposition.QUARANTINE)
        self._persist(record, events)

        return DecisionOutcome(
            decision_record_id=record_id,
            lot_id=lot_id,
            disposition=result.disposition.value,
            quality_decision_required=result.disposition
            is Disposition.INSUFFICIENT_EVIDENCE,
            reason=result.reason,
            mutation=entry,
            consequences=consequences,
            record=record,
            events=events.as_dicts(),
        )

    # ------------------------------------------------------------------
    # recovery (contract D15, P1-7)
    # ------------------------------------------------------------------
    def recover_order(
        self,
        order_id: str,
        *,
        decision_record_id: str,
        events: EventLog | None = None,
    ) -> dict:
        """Enumerate lawful recovery options and EXECUTE the selected one.

        The audit found recovery being selected but never executed: the plan
        never changed. Execution now runs through the same authority path as
        every other mutation — deterministic selection, policy authorization,
        capability bound to {order, current version, from slot, target slot,
        action, decision record, expiry}, atomic consume that re-verifies the
        slot, ledger entry.

        Every candidate is returned with its verdict, so REFUSED (could, but not
        permitted) stays visibly distinct from NOT_FEASIBLE.
        """
        events = events or EventLog()
        blocked = self.corpus.order(order_id)
        options, selected = enumerate_recovery(self.corpus, order_id)

        result: dict = {
            "blocked_order_id": order_id,
            "candidates": [o.as_dict() for o in options],
            "selected": selected.as_dict() if selected else None,
            "executed": False,
            "mutation": {},
            "reason": "",
        }

        events.emit(
            EventType.RECOVERY_EVALUATED, decision_record_id,
            blocked_order_id=order_id,
            candidate_count=len(options),
            eligible_count=sum(1 for o in options if o.verdict is Verdict.ELIGIBLE),
            refused_count=sum(1 for o in options if o.verdict is Verdict.REFUSED),
            selected=selected.candidate_id if selected else "",
        )

        if selected is None or selected.kind != "RESEQUENCE" or blocked is None:
            # The system never invents an option. No lawful resequence means
            # escalation, not improvisation.
            result["reason"] = (
                "no lawful recovery option" if selected is None
                else f"selected option {selected.kind} is not autonomously executable"
            )
            return result

        candidate = self.corpus.order(selected.candidate_id)
        if candidate is None:
            result["reason"] = "selected order disappeared"
            return result

        # F7: the target slot is part of the AUTHORIZATION, signed into the
        # capability. There is no execution-time slot parameter to substitute.
        decision = self.policy.authorize_order_action(
            decision_record_id=decision_record_id,
            order_id=candidate.order_id,
            action=Action.RESEQUENCE_PRODUCTION_ORDER,
            observed_state_version=candidate.state_version,
            events=events,
            parameters={"target_slot": blocked.planned_slot},
        )
        if not decision.allowed or decision.capability is None:
            result["reason"] = decision.reason
            return result

        try:
            entry = execute(decision.capability, self.corpus, self.capabilities, events)
        except VouchFailure as failure:
            # The slot was taken between enumeration and execution, or the
            # order moved. Refuse rather than overwrite.
            result["reason"] = failure.detail
            result["failure_category"] = failure.category.value
            return result

        result["executed"] = True
        result["mutation"] = entry
        # Distinct from RECOVERY_EVALUATED: evaluation considers, execution
        # changes the schedule. Only the latter moved the factory.
        events.emit(
            EventType.RECOVERY_EXECUTED, decision_record_id,
            blocked_order_id=order_id,
            order_id=candidate.order_id,
            candidate_id=selected.candidate_id,
            kind=selected.kind,
            capability_id=decision.capability.capability_id,
            from_slot=entry.get("from_slot")
            or entry.get("before_state", {}).get("planned_slot", ""),
            to_slot=entry.get("target_slot")
            or entry.get("after_state", {}).get("planned_slot", ""),
            ledger_sequence=entry["sequence"],
        )
        result["caused_by"] = {
            "cause": "order_blocked",
            "blocked_order_id": order_id,
            "effect": "resequence",
            "order_id": candidate.order_id,
            "from_slot": entry.get("from_slot")
            or entry.get("before_state", {}).get("planned_slot", ""),
            "to_slot": entry.get("target_slot")
            or entry.get("after_state", {}).get("planned_slot", ""),
            "decision_record_id": decision_record_id,
            "ledger_sequence": entry["sequence"],
        }
        return result

    # ------------------------------------------------------------------
    # human continuation (contract §18)
    # ------------------------------------------------------------------
    def supply_human_evidence(
        self,
        *,
        decision_record_id: str,
        lot_id: str,
        raw: bytes,
        authority_source: str,
        document_identity: str = "QA_RETEST",
        events: EventLog | None = None,
    ) -> DecisionOutcome:
        """A human supplies authorized evidence; the SAME record resumes.

        The evidence is labeled HUMAN_AUTHORIZED — higher trust than supplier,
        tracked as human-sourced. Attachment is idempotent by content hash, so
        submitting twice does not duplicate claims or re-open a closed review.
        """
        events = events or EventLog()
        # F8: hydrate from the durable store. A case survives the process that
        # created it, so a new instance over the same stores can continue it.
        record = self.resume(decision_record_id)
        if record is None:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                f"no decision record {decision_record_id}",
            )

        claims, summary = self.ingest_evidence(
            decision_record_id=decision_record_id,
            lot_id=lot_id,
            raw=raw,
            document_identity=document_identity,
            source=authority_source,
            events=events,
            trust_label=TrustLabel.HUMAN_AUTHORIZED,
        )

        if summary["content_hash"] in record.human.content_hashes:
            # Idempotent attach: already have this exact evidence.
            return DecisionOutcome(
                decision_record_id, lot_id,
                reason="evidence already attached to this record",
                record=record, events=events.as_dicts(),
            )

        record.human.content_hashes.append(summary["content_hash"])
        record.human.authority_source = authority_source
        record.human.evidence_supplied.extend(c.claim_id for c in claims)

        # The human contribution is a first-class, provenanced event: who
        # supplied it, under what authority, and which durable object it is.
        events.emit(
            EventType.HUMAN_EVIDENCE_RECEIVED,
            decision_record_id,
            lot_id=lot_id,
            authority_source=authority_source,
            document_identity=summary["document_identity"],
            content_hash=summary["content_hash"],
            storage_ref=summary["storage_ref"],
            object_version=summary["object_version"],
            trust_label=TrustLabel.HUMAN_AUTHORIZED.value,
            claim_ids=[c.claim_id for c in claims],
            binding_status=summary["binding_status"],
        )

        # F8: the human artifact's provenance belongs in the record's evidence
        # segment like any other artifact. Recording it only under `human`
        # meant a resumed decision could not re-fetch the very evidence that
        # resolved it.
        record.evidence.source_artifact_hashes.append(summary["content_hash"])
        record.evidence.document_identities.append(summary["document_identity"])
        record.evidence.receipt_timestamps.append(summary["received_at"])
        record.evidence.storage_refs.append(summary["storage_ref"])
        record.evidence.object_versions.append(summary["object_version"])
        record.evidence.claimed_identities.append(summary["claimed_identity"])
        record.evidence.binding_statuses.append(summary["binding_status"])
        for claim in claims:
            record.extraction.per_claim[claim.claim_id] = {
                "method": claim.extraction_method.value,
                "version": claim.extraction_version,
                "confidence": claim.extraction_confidence,
                "locator": claim.source_locator,
                "source_hash": claim.source_hash,
                "trust_label": claim.trust_label.value,
            }

        record.rerun()

        existing = self.claims.get(decision_record_id, [])
        self.claims[decision_record_id] = existing + claims

        # Continuation, not a new case. run_count is the proof: the frontend
        # renders one continuous history rather than two unrelated decisions.
        events.emit(
            EventType.DECISION_RESUMED,
            decision_record_id,
            lot_id=lot_id,
            run_count=record.run_count,
            resumed_run_ids=list(record.human.resumed_run_ids),
            trigger="HUMAN_EVIDENCE",
            total_claims=len(self.claims[decision_record_id]),
        )

        # Same record, new snapshot version, both agents rerun.
        outcome = self.evaluate_lot(
            lot_id, decision_record_id=decision_record_id, events=events
        )

        if outcome.disposition in ("RELEASE", "QUARANTINE"):
            record.human.review_status = "RESOLVED"
            record.human.final_outcome = outcome.disposition
            review = self.corpus.get("qa_review", f"QA-{decision_record_id}")
            if isinstance(review, dict):
                review["status"] = "RESOLVED"
        return outcome

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _brief_contract_errors(self, brief, lot_id, claims_by_id) -> list[str]:
        """Objective contract violations in one brief, as machine-readable text.

        This is `run_basis_checks` — the SAME deterministic validator the
        pipeline already applied after reconciliation — asked one brief at a
        time, so an invalid brief is caught before it can masquerade as a
        disagreement.

        It answers only questions with a structured answer: does the cited
        object exist, is the evidence in this snapshot and on this lot, is the
        requirement set complete, is a cited equivalence or deviation within
        its own recorded scope, are two method identifiers the same string.

        It does NOT decide which candidate spec governs, whether ambiguous
        evidence applies, or whether an equivalence is appropriate. Those stay
        with the model: a brief that answers them differently from its
        counterpart is a genuine disagreement and must still fail closed.
        """
        checks = run_basis_checks(
            brief, self.corpus, lot_id=lot_id, claims_by_id=claims_by_id
        )
        return list(checks.failures)

    def _run_with_retry(
        self, agent, context, claims, events, record_id, validate=None
    ):
        """Retry within budget, and ONLY for categories a retry could clear.

        P1-3: not every failure is retried identically. A schema failure may
        clear on a re-ask; a throttle deserves the attempt; an AccessDenied or a
        validation error will produce the identical result every time, so
        retrying it just burns budget and delays the escalation.

        `validate` adds one more retryable condition: a brief that came back
        structurally fine but contradicts the authoritative corpus. The errors
        are handed back to the SAME agent through the existing budget — the
        validator never edits a brief or supplies the answer, it only says
        which claim is not supported. If the budget runs out the run fails
        closed, exactly as an unusable brief already did.
        """
        run = None
        # Held ACROSS iterations: `run` is rebound by each attempt, so the
        # previous attempt's errors have to live outside it or the feedback
        # silently never reaches the model.
        pending_errors: tuple = ()
        for attempt in range(1, MAX_MODEL_ATTEMPTS + 1):
            run = agent.run(
                context=context, claims=claims, events=events,
                decision_record_id=record_id,
                validation_errors=pending_errors,
            )
            run.attempts = attempt
            if run.brief is None:
                if not run.retryable:
                    break
                # A throttle retried immediately is a throttle made worse, and
                # it spends the budget on a condition that only time clears.
                # Backing off separates "the service was busy" from "the model
                # cannot produce a valid brief", which are different failures
                # that were otherwise indistinguishable in the record.
                if run.failure_category is FailureCategory.MODEL_TIMEOUT:
                    time.sleep(_throttle_backoff_seconds() * attempt)
                continue
            errors = validate(run.brief) if validate else []
            if not errors:
                return run
            # CUMULATIVE, not replaced. Live runs showed a model correct the
            # error it was shown and reintroduce one it had already fixed on
            # the previous attempt, because each retry only ever saw the
            # latest complaint. Carrying the earlier ones forward stops the
            # budget being spent oscillating between two violations.
            #
            # Everything listed is still a real contradiction of the corpus,
            # and none of them says what the answer should be.
            pending_errors = tuple(dict.fromkeys(pending_errors + tuple(errors)))
            run.validation_errors = pending_errors
            events.emit(
                EventType.BRIEF_VALIDATION_FAILED, record_id,
                agent=agent.role, attempt=attempt,
                # What THIS attempt got wrong, and everything the next attempt
                # is told. Logging only the former made cumulative feedback
                # look like it was not being delivered.
                errors=list(errors),
                carried_forward=list(pending_errors),
            )
            if attempt >= MAX_MODEL_ATTEMPTS:
                # Budget spent on a brief that still contradicts the corpus.
                # The brief is retained on the run so the record can show WHAT
                # was rejected; only the usable-brief slot is cleared, which is
                # what stops it reaching reconciliation or a mutation.
                run.rejected_brief = run.brief
                run.brief = None
                run.failure = (
                    f"{agent.role} brief contradicts the authoritative corpus "
                    f"after {attempt} attempts: {'; '.join(errors)}"
                )
                run.failure_category = FailureCategory.BRIEF_CONTRACT_VIOLATION
                break
        return run

    @staticmethod
    def _corpus_objects(brief, lot, checks) -> dict:
        """Every authoritative object this decision rested on, with versions.

        P1-1: an auditor must be able to tell whether the decision was made
        against the corpus as it stood THEN. Recording the ids without their
        revisions/effective metadata would not answer that.
        """
        objects: dict[str, dict] = {}
        basis = brief.governing_basis
        objects[f"{basis.spec_id}:{basis.revision}"] = {
            "kind": "spec_revision",
            "spec_id": basis.spec_id,
            "revision": basis.revision,
        }
        for requirement in checks.resolved_requirements:
            objects[requirement.requirement_id] = {
                "kind": "requirement",
                "characteristic": requirement.characteristic,
                "method": requirement.method,
                "condition": requirement.condition,
                "min_value": requirement.min_value,
                "max_value": requirement.max_value,
            }
        for reference in brief.deviations_applied:
            objects[reference.deviation_id] = {"kind": "deviation"}
        for item in brief.coverage:
            if item.equivalence_record_id:
                objects[item.equivalence_record_id] = {"kind": "equivalence"}
        return objects

    def _enrich_corpus_objects(self, objects: dict) -> dict:
        """Attach the authoritative version/status metadata for each object."""
        for key, meta in objects.items():
            if meta["kind"] == "spec_revision":
                revision = self.corpus.spec_revision(meta["spec_id"], meta["revision"])
                if revision is not None:
                    meta.update(
                        status=revision.status,
                        effective_date=revision.effective_date,
                        effective_to=revision.ended_at,
                        effective_basis=revision.effective_basis,
                    )
            elif meta["kind"] == "deviation":
                found = next(
                    (d for d in self.corpus.all("deviation") if d.deviation_id == key),
                    None,
                )
                if found is not None:
                    meta.update(
                        status=found.status, effective_date=found.effective_date,
                        expiry_date=found.expiry_date,
                    )
            elif meta["kind"] == "equivalence":
                found = next(
                    (e for e in self.corpus.all("equivalence") if e.equivalence_id == key),
                    None,
                )
                if found is not None:
                    meta.update(
                        status=found.status, effective_date=found.effective_date,
                        expiry_date=found.expiry_date,
                    )
        return objects

    def _persist(self, record: DecisionRecord, events: EventLog) -> None:
        """P1-1/P1-2. Write the record and its events durably.

        Called on EVERY exit — autonomous, refused, abstained or failed. A
        decision that escalated is exactly the one an auditor will want to read.
        """
        record.events = events.as_dicts()
        record.storage.evidence_store = getattr(
            self.evidence_store, "kind", type(self.evidence_store).__name__
        )
        record.storage.record_store = getattr(
            self.record_store, "kind", type(self.record_store).__name__
        )
        # F8: the canonical claims are part of the durable record, so a
        # resumed case reconstructs the evidence it already had rather than
        # starting from an empty claim set.
        record.evidence.canonical_claims = [
            claim.model_dump(mode="json") for claim in self.claims.get(record.record_id, [])
        ]
        try:
            record.storage.record_ref = self.record_store.save(record)
            # F8: append-only sequence allocation that CONTINUES after the
            # existing maximum. Restarting at 1 collided with run 1's keys and
            # silently dropped every continuation event.
            appended = self.record_store.append_all(events.events)
            record.storage.event_count += appended
            record.storage.last_event_sequence = (
                self.record_store.next_sequence(record.record_id) - 1
            )
            # Re-save so the storage segment itself is part of the stored
            # document rather than only in memory.
            self.record_store.save(record)
        except VouchFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE, f"could not persist record: {exc}"
            ) from exc

    @staticmethod
    def _agent_segment(run, snapshot: EvidenceSnapshot):
        from .decision_record import AgentSegment

        return AgentSegment(
            model_id=run.model_id,
            prompt_version=run.prompt_version,
            prompt_hash=run.prompt_hash,
            temperature=0.0,
            input_claim_set_hash=snapshot.claim_set_hash,
            brief_hash=(run.brief or run.rejected_brief).brief_hash()
            if (run.brief or run.rejected_brief)
            else "",
            tool_events=run.tool_events,
            schema_valid=run.schema_valid,
            precedent_consulted=list(run.brief.precedent_consulted) if run.brief else [],
            failure=run.failure,
            failure_category=(
                run.failure_category.value if run.failure_category else ""
            ),
            attempts=run.attempts,
            # A rejected brief is still persisted: an auditor must see the
            # claim that was refused, not merely that something was.
            brief=(run.brief or run.rejected_brief).model_dump(mode="json")
            if (run.brief or run.rejected_brief)
            else {},
            brief_rejected=run.brief is None and run.rejected_brief is not None,
        )

    def _quality_decision(
        self,
        record: DecisionRecord,
        events: EventLog,
        lot_id: str,
        category: FailureCategory,
        reason: str,
    ) -> DecisionOutcome:
        """Every non-autonomous exit routes here. No mutation, typed failure,
        human escalation — and the failure channel is preserved, never
        laundered into a disposition."""
        record.fail(category, reason)
        record.human.review_id = f"QA-{record.record_id}"
        record.human.review_status = "OPEN"

        reason_code = {
            FailureCategory.MATERIAL_DISAGREEMENT: "DISAGREEMENT",
            FailureCategory.SECURITY_QUARANTINE: "INJECTION",
            FailureCategory.DOMAIN_INSUFFICIENT_EVIDENCE: "INSUFFICIENT",
        }.get(category, "ABSTAIN")

        events.emit(
            EventType.QUALITY_DECISION_REQUIRED, record.record_id,
            reason=reason_code, lot_id=lot_id, category=category.value,
        )
        # P1-1: an escalated decision is exactly the one an auditor will read.
        self._persist(record, events)
        return DecisionOutcome(
            decision_record_id=record.record_id,
            lot_id=lot_id,
            failure_category=category.value,
            quality_decision_required=True,
            reason=reason,
            record=record,
            events=events.as_dicts(),
        )


__all__ = ["DecisionOutcome", "VouchV2"]
