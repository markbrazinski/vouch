"""Deterministic reconciliation and basis checks (contracts D9, §11).

Two separate jobs, both plain Python, no model:

  1. `reconcile` compares the two independently-derived briefs on MATERIAL
     fields only. Prose, ordering, notes, confidence language and precedent are
     ignored by construction.

  2. `run_basis_checks` re-verifies the cited authority against the corpus —
     existence, currency, supersession, scope containment, evidence resolution.
     It runs REGARDLESS of whether the models agreed, because agreement is not
     truth. A superseded revision both models endorsed still fails here.

Disagreement is never resolved by another model.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    EvidenceApplicabilityBrief,
    ReconciliationOutcome,
    Sufficiency,
)
from .corpus import Corpus
from .lifecycle import EventLog, EventType

POLICY_VERSION = "vouch-policy-2.0"


@dataclass
class ReconciliationResult:
    outcome: ReconciliationOutcome
    differing_fields: list[str] = field(default_factory=list)
    detail: str = ""


def reconcile(
    investigator: EvidenceApplicabilityBrief | None,
    verifier: EvidenceApplicabilityBrief | None,
    events: EventLog,
    decision_record_id: str,
) -> ReconciliationResult:
    """Compare material fields. A missing brief is a TECHNICAL failure, never a
    disagreement and never insufficiency."""
    if investigator is None or verifier is None:
        result = ReconciliationResult(
            ReconciliationOutcome.TECHNICAL_FAILURE,
            detail="one or both briefs unavailable",
        )
        events.emit(
            EventType.RECONCILIATION_COMPLETED, decision_record_id,
            outcome=result.outcome.value, differing_fields=[],
        )
        return result

    left = investigator.material_fingerprint()
    right = verifier.material_fingerprint()

    differing = [key for key in left if left[key] != right[key]]

    if not differing:
        outcome = ReconciliationOutcome.MATCH
        # Non-material differences are logged, not acted on.
        if investigator.investigation_notes != verifier.investigation_notes:
            outcome = ReconciliationOutcome.NON_MATERIAL_DIFFERENCE
        result = ReconciliationResult(outcome, detail="material fields agree")
    else:
        result = ReconciliationResult(
            ReconciliationOutcome.MATERIAL_DISAGREEMENT,
            differing_fields=differing,
            detail=f"briefs differ materially on: {', '.join(differing)}",
        )

    events.emit(
        EventType.RECONCILIATION_COMPLETED, decision_record_id,
        outcome=result.outcome.value, differing_fields=result.differing_fields,
    )
    return result


@dataclass
class BasisCheckResult:
    passed: bool
    failures: list[str] = field(default_factory=list)
    #: Requirements resolved from the corpus, NOT from the brief. Disposition is
    #: computed from these, so a model cannot understate what a spec requires.
    resolved_requirements: list = field(default_factory=list)


def run_basis_checks(
    brief: EvidenceApplicabilityBrief,
    corpus: Corpus,
    *,
    lot_id: str,
    claims_by_id: dict,
) -> BasisCheckResult:
    """Deterministic verification of everything the brief cited.

    Runs even on MATCH. This is what bounds the Verifier's residual (D5): two
    models agreeing on a superseded revision is caught here, not by a third
    model.
    """
    failures: list[str] = []
    lot = corpus.lot(lot_id)
    if lot is None:
        return BasisCheckResult(False, [f"lot {lot_id} does not exist"])

    when = lot.received_at or lot.manufactured_at

    # -- basis existence, currency, scope --------------------------------
    revision = corpus.spec_revision(
        brief.governing_basis.spec_id, brief.governing_basis.revision
    )
    if revision is None:
        failures.append(
            f"governing basis {brief.governing_basis.spec_id}:"
            f"{brief.governing_basis.revision} does not exist"
        )
        return BasisCheckResult(False, failures)

    if revision.status == "SUPERSEDED" or revision.superseded_by:
        failures.append(
            f"{revision.key} is superseded by {revision.superseded_by} and cannot govern"
        )
    if revision.status in ("DRAFT", "WITHDRAWN"):
        failures.append(f"{revision.key} has status {revision.status} and cannot govern")
    if not revision.covers_material(lot.material_id):
        failures.append(f"{revision.key} does not cover material {lot.material_id}")
    if when and when < revision.effective_date:
        failures.append(
            f"{revision.key} is not yet effective for this lot ({when} < {revision.effective_date})"
        )

    # -- the requirement set comes from the CORPUS, not the brief ---------
    resolved = list(revision.requirements)
    for ref in revision.incorporates:
        other = corpus.get("spec_revision", ref)
        if other is None:
            failures.append(f"{revision.key} incorporates {ref}, which does not exist")
        else:
            resolved.extend(other.requirements)

    briefed = {t.name for t in brief.required_tests}
    actual = {r.characteristic for r in resolved}
    if briefed and briefed != actual:
        omitted = actual - briefed
        if omitted:
            failures.append(
                f"brief omits required tests present in {revision.key}: {sorted(omitted)}"
            )

    # -- cited equivalences ----------------------------------------------
    for item in brief.coverage:
        if item.equivalence_record_id is None:
            continue
        record = next(
            (
                e
                for e in corpus.all("equivalence")
                if e.equivalence_id == item.equivalence_record_id
            ),
            None,
        )
        if record is None:
            failures.append(f"cited equivalence {item.equivalence_record_id} does not exist")
            continue
        claim = claims_by_id.get(item.evidence_ref)
        requirement = next((r for r in resolved if r.characteristic == item.test), None)
        if claim is None or requirement is None:
            failures.append(
                f"equivalence {record.equivalence_id} cited without resolvable evidence"
            )
            continue
        if not record.covers(
            required_method=requirement.method,
            used_method=claim.method,
            when=when,
            material_id=lot.material_id,
            condition=claim.condition,
            characteristic=item.test,
        ):
            failures.append(
                f"equivalence {record.equivalence_id} does not cover "
                f"{claim.method}->{requirement.method} for {item.test} at {claim.condition}"
            )

    # -- cited deviations -------------------------------------------------
    for reference in brief.deviations_applied:
        deviation = next(
            (
                d
                for d in corpus.all("deviation")
                if d.deviation_id == reference.deviation_id
            ),
            None,
        )
        if deviation is None:
            failures.append(f"cited deviation {reference.deviation_id} does not exist")
            continue
        if not deviation.covers(
            material_id=lot.material_id,
            characteristic=deviation.characteristic,
            when=when,
            site_id=lot.supplier_site,
            po=lot.po_reference,
            lot_id=lot.lot_id,
        ):
            failures.append(
                f"deviation {deviation.deviation_id} is out of scope for this lot "
                f"(site={lot.supplier_site}, po={lot.po_reference}, when={when})"
            )

    # -- evidence refs must resolve, and to THIS lot ----------------------
    for item in brief.coverage:
        if item.evidence_ref is None:
            continue
        claim = claims_by_id.get(item.evidence_ref)
        if claim is None:
            failures.append(f"evidence {item.evidence_ref} does not exist in the snapshot")
        elif claim.lot_id != lot_id:
            # V1 joined evidence by material and silently pulled in other lots.
            failures.append(
                f"evidence {item.evidence_ref} belongs to lot {claim.lot_id}, not {lot_id}"
            )

    return BasisCheckResult(not failures, failures, resolved)


__all__ = [
    "BasisCheckResult",
    "POLICY_VERSION",
    "ReconciliationResult",
    "reconcile",
    "run_basis_checks",
]
