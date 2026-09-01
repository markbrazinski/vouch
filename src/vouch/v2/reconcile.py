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

POLICY_VERSION = "vouch-policy-2.1"


class BasisDateUndetermined(ValueError):
    """The basis date required by policy is not on the lot's record."""


def basis_date_for(revision, lot) -> str:
    """Which date decides whether this revision governs (P1-4).

    The revision states its own rule in `effective_basis`. There is deliberately
    NO truthy fallback: `lot.received_at or lot.manufactured_at` silently
    answers a policy question with whichever field happened to be populated,
    which means two lots with the same dates can be judged on different bases.

    Where a revision states no basis, the plant default applies and is recorded
    explicitly rather than inferred. Where the required date is ABSENT from the
    lot record, this raises — an undeterminable basis is a case for abstention,
    not for guessing.
    """
    basis = getattr(revision, "effective_basis", None) or DEFAULT_EFFECTIVE_BASIS

    if basis == "date_of_manufacture":
        when = lot.manufactured_at
    elif basis == "date_of_receipt":
        when = lot.received_at
    else:
        raise BasisDateUndetermined(f"unknown effective_basis {basis!r}")

    if not when:
        raise BasisDateUndetermined(
            f"{getattr(revision, 'key', '?')} keys on {basis}, which this lot "
            f"does not record; the governing basis cannot be established"
        )
    return when


#: Plant policy where a revision does not state its own basis. Explicit and
#: versioned, so a change is a visible policy decision rather than a code edit.
DEFAULT_EFFECTIVE_BASIS = "date_of_receipt"


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


def _normalize_method(value: str | None) -> str:
    """Case/whitespace-insensitive form of a method or condition identifier.

    Only for deciding whether two identifiers are THE SAME. It never maps one
    identifier onto another — that is the equivalence question, and it belongs
    to the model and to the authoritative equivalence records.
    """
    return (value or "").strip().upper().replace(" ", "").replace("_", "")


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

    # P1-4. The basis DATE comes from the revision's own stated rule, not from
    # whichever of the lot's date fields happens to be populated.
    try:
        when = basis_date_for(revision, lot)
    except BasisDateUndetermined as exc:
        return BasisCheckResult(False, [str(exc)])

    if revision.status in ("DRAFT", "WITHDRAWN"):
        failures.append(f"{revision.key} has status {revision.status} and cannot govern")
    elif not revision.governed_on(when):
        # P1-4. Being superseded TODAY is not disqualifying; not having governed
        # ON THE BASIS DATE is. These are different questions and the audit
        # found only the first being asked.
        end = revision.ended_at
        if when < revision.effective_date:
            failures.append(
                f"{revision.key} was not yet effective on {when} "
                f"(effective {revision.effective_date})"
            )
        elif end is not None and when >= end:
            failures.append(
                f"{revision.key} ceased to govern on {end}; it cannot govern a lot "
                f"with basis date {when}"
            )
        else:
            failures.append(f"{revision.key} did not govern on {when}")

    if not revision.covers_material(lot.material_id):
        failures.append(f"{revision.key} does not cover material {lot.material_id}")

    # -- the requirement set comes from the CORPUS, not the brief ---------
    resolved = list(revision.requirements)
    for ref in revision.incorporates:
        other = corpus.get("spec_revision", ref)
        if other is None:
            failures.append(f"{revision.key} incorporates {ref}, which does not exist")
        else:
            resolved.extend(other.requirements)

    # P1-5. The omission check must NOT be skipped when the brief declares no
    # required tests at all. An empty required_tests against a non-empty
    # authoritative set was the bypass: it silently satisfied the comparison and
    # let a brief that acknowledged no requirements proceed.
    briefed = {t.name for t in brief.required_tests}
    actual = {r.characteristic for r in resolved}

    if actual and not briefed:
        failures.append(
            f"brief declares no required tests, but {revision.key} requires "
            f"{sorted(actual)}; the brief does not reflect the authoritative "
            f"requirement set"
        )
    elif briefed != actual:
        omitted = sorted(actual - briefed)
        invented = sorted(briefed - actual)
        if omitted:
            failures.append(
                f"brief omits required tests present in {revision.key}: {omitted}"
            )
        if invented:
            failures.append(
                f"brief asserts tests not in {revision.key}: {invented}"
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

    # -- coverage completeness (category B) -------------------------------
    # A brief that names a required test and then reports no coverage row for
    # it has not answered the question it was asked. This is a CONTRACT check,
    # not an applicability judgment: it says the row must exist and be
    # accounted for, never what its verdict should be. A test whose evidence is
    # genuinely absent is stated as a null evidence_ref or listed in
    # missing_evidence — both are answers; silence is not.
    covered = {item.test for item in brief.coverage}
    declared_missing = set(getattr(brief, "missing_evidence", ()) or ())
    for requirement in resolved:
        if requirement.characteristic in covered:
            continue
        if requirement.characteristic in declared_missing:
            continue
        failures.append(
            f"required test {requirement.characteristic} has no coverage entry "
            f"and is not listed as missing evidence; the brief does not say "
            f"whether any evidence applies to it"
        )

    # -- method_match must match the structured facts (category B) --------
    # Whether two method identifiers are EQUAL is a string comparison against
    # authoritative tool output, not an interpretation. Deciding whether a
    # DIFFERENT method is nonetheless acceptable stays with the model — that is
    # the equivalence question, and this check deliberately does not touch it.
    for item in brief.coverage:
        if item.evidence_ref is None:
            continue
        claim = claims_by_id.get(item.evidence_ref)
        requirement = next(
            (r for r in resolved if r.characteristic == item.test), None
        )
        if claim is None or requirement is None:
            continue
        identical = (
            _normalize_method(claim.method) == _normalize_method(requirement.method)
            and _normalize_method(claim.condition)
            == _normalize_method(requirement.condition)
        )
        if identical and not item.method_match:
            failures.append(
                f"{item.test}: method_match is false, but the evidence used "
                f"{claim.method}/{claim.condition} and the requirement asks for "
                f"{requirement.method}/{requirement.condition} — they are the same"
            )
        elif not identical and item.method_match:
            failures.append(
                f"{item.test}: method_match is true, but the evidence used "
                f"{claim.method}/{claim.condition} and the requirement asks for "
                f"{requirement.method}/{requirement.condition} — they differ"
            )

    return BasisCheckResult(not failures, failures, resolved)


__all__ = [
    "BasisCheckResult",
    "POLICY_VERSION",
    "ReconciliationResult",
    "reconcile",
    "run_basis_checks",
]
