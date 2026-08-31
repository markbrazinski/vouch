"""Deterministic Disposition Engine (contract D10).

No model runs here, and no model output is trusted as arithmetic. This is the
reframed descendant of V1's `_classify` — its disposition semantics were
correct, so they are kept; what is removed is its use inside the verification
path, where sharing it made agreement automatic.

Input: the reconciled brief (what governs, what applies) plus requirements
resolved from the CORPUS. Output: RELEASE | QUARANTINE | INSUFFICIENT_EVIDENCE.

REJECT is never produced here — it is a human-policy terminal state.

Values are re-read from the frozen claims and re-compared here, so a model that
misreports a number changes nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import (
    CanonicalEvidenceClaim,
    Disposition,
    EvidenceApplicabilityBrief,
    Sufficiency,
)
from .corpus import ApprovedDeviation, Corpus, Requirement
from .lifecycle import EventLog, EventType


@dataclass
class DispositionResult:
    disposition: Disposition
    reason: str
    failing_tests: list[str] = field(default_factory=list)
    missing_tests: list[str] = field(default_factory=list)


def compute_disposition(
    brief: EvidenceApplicabilityBrief,
    requirements: list[Requirement],
    claims_by_id: dict[str, CanonicalEvidenceClaim],
    corpus: Corpus,
    *,
    lot_id: str,
    events: EventLog | None = None,
    decision_record_id: str = "",
) -> DispositionResult:
    """Coverage logic + arithmetic. Deterministic, and the only place a
    disposition is produced."""
    lot = corpus.lot(lot_id)
    when = (lot.received_at or lot.manufactured_at) if lot else ""

    coverage_by_test = {c.test: c for c in brief.coverage}
    missing: list[str] = []
    failing: list[str] = []
    reasons: list[str] = []

    for requirement in requirements:
        item = coverage_by_test.get(requirement.characteristic)

        # -- is there applicable evidence at all? -------------------------
        if item is None or item.evidence_ref is None:
            missing.append(requirement.characteristic)
            reasons.append(f"{requirement.characteristic}: no applicable evidence")
            continue

        claim = claims_by_id.get(item.evidence_ref)
        if claim is None:
            missing.append(requirement.characteristic)
            reasons.append(f"{requirement.characteristic}: evidence does not resolve")
            continue

        # Method must match, or be covered by an equivalence the basis checks
        # already validated. Neither is an arithmetic question.
        if claim.method != requirement.method and item.equivalence_record_id is None:
            missing.append(requirement.characteristic)
            reasons.append(
                f"{requirement.characteristic}: method {claim.method} does not establish "
                f"the requirement ({requirement.method}) and no equivalence applies"
            )
            continue

        if claim.condition != requirement.condition and item.equivalence_record_id is None:
            missing.append(requirement.characteristic)
            reasons.append(
                f"{requirement.characteristic}: condition {claim.condition} does not match "
                f"required {requirement.condition}"
            )
            continue

        # -- numeric comparison, recomputed from the frozen claim ---------
        if not isinstance(claim.value, (int, float)):
            missing.append(requirement.characteristic)
            reasons.append(f"{requirement.characteristic}: no numeric value reported")
            continue

        if requirement.in_limits(float(claim.value)):
            reasons.append(
                f"{requirement.characteristic}: {claim.value}{claim.units} within "
                f"{requirement.threshold_text()}"
            )
            continue

        # Out of limits — a covering deviation can still make it acceptable.
        covering = _covering_deviation(
            corpus, brief, requirement, float(claim.value), lot, when
        )
        if covering is not None:
            reasons.append(
                f"{requirement.characteristic}: {claim.value}{claim.units} outside "
                f"{requirement.threshold_text()} but covered by {covering.deviation_id}"
            )
            continue

        failing.append(requirement.characteristic)
        reasons.append(
            f"{requirement.characteristic}: {claim.value}{claim.units} outside "
            f"{requirement.threshold_text()} with no covering deviation"
        )

    # -- the rules (D10), in order ---------------------------------------
    # A failed requirement is a demonstrated non-conformance and outranks
    # missing evidence: the lot is affirmatively bad, not merely unproven.
    if failing:
        result = DispositionResult(
            Disposition.QUARANTINE,
            "; ".join(reasons),
            failing_tests=failing,
            missing_tests=missing,
        )
    elif missing or brief.sufficiency is Sufficiency.INSUFFICIENT_EVIDENCE:
        # Absence of evidence is never a defect finding.
        result = DispositionResult(
            Disposition.INSUFFICIENT_EVIDENCE,
            "; ".join(reasons) or "required evidence is absent",
            missing_tests=missing or [m.test for m in brief.missing],
        )
    elif not requirements:
        result = DispositionResult(
            Disposition.INSUFFICIENT_EVIDENCE,
            "governing basis resolved no requirements",
        )
    else:
        result = DispositionResult(Disposition.RELEASE, "; ".join(reasons))

    if events is not None:
        events.emit(
            EventType.DISPOSITION_COMPUTED, decision_record_id,
            disposition=result.disposition.value,
            basis=f"{brief.governing_basis.spec_id}:{brief.governing_basis.revision}",
            failing_test_count=len(result.failing_tests),
            missing_test_count=len(result.missing_tests),
        )
    return result


def _covering_deviation(
    corpus: Corpus,
    brief: EvidenceApplicabilityBrief,
    requirement: Requirement,
    value: float,
    lot,
    when: str,
) -> ApprovedDeviation | None:
    """A deviation applies only if the brief CITED it and it genuinely covers
    this material/characteristic/site/PO/lot/date and accepts this value.

    Both halves matter: an uncited deviation is not silently applied, and a
    cited one that does not cover this lot is not honoured.
    """
    cited = {d.deviation_id for d in brief.deviations_applied}
    for deviation in corpus.deviations_for(requirement.characteristic and lot.material_id):
        if deviation.deviation_id not in cited:
            continue
        if not deviation.covers(
            material_id=lot.material_id,
            characteristic=requirement.characteristic,
            when=when,
            site_id=lot.supplier_site,
            po=lot.po_reference,
            lot_id=lot.lot_id,
        ):
            continue
        if deviation.accepts(value):
            return deviation
    return None


__all__ = ["DispositionResult", "compute_disposition"]
