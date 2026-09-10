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

import re

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


def resolve_test_name(name: str, characteristics: set[str]) -> str:
    """Map a test label onto the authoritative characteristic it names.

    Models sometimes write the whole requirement into the name field —
    "viscosity at 25C using ASTM-D2196" for the characteristic `viscosity` —
    because that is how the requirement reads in prose. The characteristic is
    still stated; it is just carrying the method and condition with it, both of
    which the brief has dedicated fields for.

    Resolution is deterministic and refuses to guess: the label must contain
    EXACTLY ONE authoritative characteristic as a whole word. Zero matches or
    two are returned unchanged, so the caller reports the mismatch rather than
    picking a winner. It never invents a characteristic, and it never decides
    whether a test APPLIES — only which authoritative name a label spells.
    """
    if name in characteristics:
        return name
    haystack = _word_tokens(name)
    matches = [c for c in characteristics if _word_tokens(c) <= haystack]
    return matches[0] if len(matches) == 1 else name


def _word_tokens(value: str) -> set[str]:
    """Word-ish tokens, so `viscosity` matches inside a prose label.

    Splitting on non-alphanumerics means `tensile_strength` and
    "tensile strength" tokenize identically, and a bare substring like `vis`
    can never match `viscosity`.
    """
    return {t for t in re.split(r"[^a-z0-9]+", value.lower()) if t}


def _establishes(item, claim, requirement) -> bool:
    """Does this coverage row present evidence that actually applies?

    The same three conditions `compute_disposition` applies: the evidence
    resolves, and either it used the required method at the required condition
    or the row cites an equivalence (whose genuine scope is verified separately
    above). Deliberately says NOTHING about the measured value — a failing
    number is applicable evidence.
    """
    if claim is None:
        return False
    if item.equivalence_record_id is not None:
        return True
    return (
        _normalize_method(claim.method) == _normalize_method(requirement.method)
        and _normalize_method(claim.condition) == _normalize_method(requirement.condition)
    )


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
    actual = {r.characteristic for r in resolved}
    # A label that spells out the whole requirement — "viscosity at 25C using
    # ASTM-D2196" — still names the characteristic `viscosity`. Resolve it to
    # the authoritative name before comparing, so the brief is judged on what
    # it identified rather than on how verbosely it wrote it down. Ambiguous or
    # unrecognised labels are left untouched and still fail the comparison.
    briefed = {resolve_test_name(t.name, actual) for t in brief.required_tests}

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
        requirement = next(
            (r for r in resolved
             if r.characteristic == resolve_test_name(item.test, actual)),
            None,
        )
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
                f"{claim.method}->{requirement.method} for {item.test} at "
                f"{claim.condition}, so it cannot be cited here. Remove the "
                f"equivalence_record_id from this coverage row; whether the "
                f"evidence still applies without it is yours to decide."
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
            # Name the specific reason. "Out of scope (site=…, po=…, when=…)"
            # made the caller work out WHICH of those failed, and an expired
            # deviation was being re-cited across retries because the message
            # never said it had expired.
            why = []
            if deviation.expiry_date and when >= deviation.expiry_date:
                why.append(f"it expired on {deviation.expiry_date}")
            if deviation.effective_date and when < deviation.effective_date:
                why.append(f"it is not effective until {deviation.effective_date}")
            if deviation.site_scope and lot.supplier_site not in deviation.site_scope:
                why.append(f"its site scope is {sorted(deviation.site_scope)}")
            if deviation.po_scope and lot.po_reference not in deviation.po_scope:
                why.append(f"its PO scope is {sorted(deviation.po_scope)}")
            if deviation.lot_scope and lot.lot_id not in deviation.lot_scope:
                why.append(f"its lot scope is {sorted(deviation.lot_scope)}")
            detail = "; ".join(why) or (
                f"it does not cover site={lot.supplier_site}, "
                f"po={lot.po_reference}, date={when}"
            )
            failures.append(
                f"deviation {deviation.deviation_id} cannot be cited for this "
                f"lot (basis date {when}): {detail}. Remove it from "
                f"deviations_applied; what the evidence establishes without it "
                f"is yours to decide."
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
    covered = {resolve_test_name(item.test, actual) for item in brief.coverage}
    # `missing` is the brief's own vocabulary for "this required test has no
    # applicable evidence, and here is why". Naming the wrong field here would
    # close the only legitimate escape hatch and force the model to invent a
    # coverage row it does not believe in.
    declared_missing = {resolve_test_name(item.test, actual) for item in brief.missing}
    for requirement in resolved:
        if requirement.characteristic in covered:
            continue
        if requirement.characteristic in declared_missing:
            continue
        failures.append(
            f"required test {requirement.characteristic} has no coverage entry "
            f"and no `missing` entry; the brief does not say whether any "
            f"evidence applies to it. Add a coverage row (evidence_ref may be "
            f"null) or a `missing` entry naming this test."
        )

    # -- exactly ONE controlling row per requirement (category B) ---------
    # The mirror of the completeness check above: that one says a requirement
    # must not be answered with silence, this one says it must not be answered
    # twice.
    #
    # `compute_disposition` keys coverage by characteristic, so a second row
    # for the same requirement silently replaced the first and the disposition
    # became a function of brief ORDERING. A live Nova run returned both the
    # 178 cP direct result and the 312 cP equivalence-covered one for
    # LOT-1003's single viscosity requirement; the failing row was overwritten
    # and the lot released. Both agents did that, so they reconciled to MATCH
    # and nothing downstream had reason to look.
    #
    # Fixing it in the engine — failing closed on any failing row — was the
    # wrong repair: after Quality establishes one path as controlling, an
    # unselected conflicting claim would still decide the lot, which is exactly
    # the authority the human was asked to exercise.
    #
    # So the CONTRACT is the fix. A brief selects one controlling evidence path
    # per requirement. Several claims may exist in the frozen snapshot — that
    # is normal, and none of them are discarded — but choosing between them is
    # the judgment the agent exists to make, and a brief that declines to
    # choose has not answered.
    by_test: dict[str, list] = {}
    for item in brief.coverage:
        by_test.setdefault(resolve_test_name(item.test, actual), []).append(item)
    for requirement in resolved:
        rows = by_test.get(requirement.characteristic, [])
        if len(rows) <= 1:
            continue
        cited = [r.evidence_ref or "none" for r in rows]
        failures.append(
            f"{requirement.characteristic} has {len(rows)} coverage rows "
            f"({', '.join(cited)}), but a brief states ONE controlling "
            f"evidence path per requirement. Several claims may apply; "
            f"choosing which one establishes this requirement is yours to "
            f"decide. Keep the row for the evidence you are relying on and "
            f"remove the others — they remain in the snapshot either way."
        )

    # -- `missing` must mean absent, not failing (category B) -------------
    # A test is MISSING when no applicable evidence exists for it. It is not
    # missing because the evidence that does exist reports a failing number:
    # conformance is computed deterministically downstream and the brief has no
    # vocabulary for it, which is exactly why a failing value must still be
    # reported as covered.
    #
    # Live runs showed a Verifier declaring tensile_strength missing with the
    # reason "Evidence does not meet the threshold of >= 480.0 MPa", against a
    # claim measured by the required method at the required condition. That is
    # not a judgment this validator is overriding — the brief contradicts the
    # snapshot it was given.
    #
    # This is a claim-EXISTENCE test, not an applicability test. Where the
    # method or condition genuinely differs, the evidence may well not apply
    # and `missing` is correct, so those cases are left entirely alone.
    for item in brief.missing:
        resolved_name = resolve_test_name(item.test, actual)
        requirement = next(
            (r for r in resolved if r.characteristic == resolved_name), None
        )
        if requirement is None:
            continue
        # A test the brief ALSO covers with resolvable evidence is not being
        # asserted as absent — the coverage row is the load-bearing statement
        # and `missing` here is the model restating, in prose, that the value
        # fails its limit. That is redundant rather than contradictory: the
        # Disposition Engine reads `coverage` and recomputes the missing set
        # from the corpus itself, using `brief.missing` only as a display
        # label when its own computed list is empty. Rejecting the brief over
        # a field that decides nothing failed a run whose substantive judgment
        # was correct and whose disposition would have been QUARANTINE either
        # way, so it is normalized away below instead of refused.
        covering = next(
            (c for c in brief.coverage
             if resolve_test_name(c.test, actual) == resolved_name
             and c.evidence_ref in claims_by_id),
            None,
        )
        if covering is not None:
            continue
        matching = [
            claim
            for claim in claims_by_id.values()
            if claim.characteristic == resolved_name
            and claim.lot_id == lot_id
            and _normalize_method(claim.method) == _normalize_method(requirement.method)
            and _normalize_method(claim.condition)
            == _normalize_method(requirement.condition)
        ]
        if matching:
            failures.append(
                f"{item.test} is listed as missing ({item.reason!r}), but the "
                f"snapshot contains evidence {matching[0].claim_id} measured by "
                f"the required method {requirement.method} at the required "
                f"condition {requirement.condition}. That evidence is covered; "
                f"whether its value meets the limit is computed separately and "
                f"is not a reason to call the test missing."
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
            (r for r in resolved
             if r.characteristic == resolve_test_name(item.test, actual)),
            None,
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
                f"{requirement.method}/{requirement.condition} — they are the "
                f"same method and condition, so method_match must be true. "
                f"method_match is about the METHOD only; whether the measured "
                f"value meets the limit is computed separately and is not "
                f"yours to state."
            )
        elif not identical and item.method_match:
            failures.append(
                f"{item.test}: method_match is true, but the evidence used "
                f"{claim.method}/{claim.condition} and the requirement asks for "
                f"{requirement.method}/{requirement.condition} — they differ"
            )

    # -- sufficiency must mean coverage, not conformance (commission §8) ---
    # `sufficiency` answers exactly one question: does applicable evidence
    # exist for every required test under the basis the brief chose? It does
    # NOT say whether a value passed — the brief has no vocabulary for that,
    # and `compute_disposition` computes it from the frozen claims.
    #
    # The Hero A instability that survived every other check was a brief which
    # resolved evidence for every required test and then declared
    # INSUFFICIENT_EVIDENCE because the measured value failed its limit. Paired
    # with a counterpart that said SUFFICIENT over the identical facts, that
    # reconciled to MATERIAL_DISAGREEMENT and failed closed — two models that
    # agreed about the evidence, recorded as though they disagreed.
    #
    # This is not the validator deciding a fuzzy question. The brief
    # contradicts ITSELF: it asserts evidence is absent for a test whose
    # coverage row names resolvable evidence. Where any required test genuinely
    # lacks applicable evidence, INSUFFICIENT_EVIDENCE is correct and untouched
    # — so the abstention path stays fully open.
    if brief.sufficiency is Sufficiency.INSUFFICIENT_EVIDENCE and resolved:
        # "Covered" here must mean what the Disposition Engine means by it:
        # evidence that resolves AND establishes the requirement. A claim
        # measured by another method or at another condition, with no
        # equivalence cited, resolves but does not apply — so a brief calling
        # that insufficient is right, and must not be rejected.
        uncovered = [
            requirement.characteristic
            for requirement in resolved
            if not any(
                resolve_test_name(item.test, actual) == requirement.characteristic
                and _establishes(item, claims_by_id.get(item.evidence_ref), requirement)
                for item in brief.coverage
            )
        ]
        if not uncovered:
            failures.append(
                "sufficiency is INSUFFICIENT_EVIDENCE, but every required test "
                f"({sorted(r.characteristic for r in resolved)}) has a coverage "
                "row naming evidence that resolves in this snapshot, so no "
                "required evidence is absent. sufficiency reports whether "
                "applicable evidence EXISTS for every required test; whether a "
                "measured value meets its limit is computed separately and is "
                "not what this field states. If you meant that a value fails "
                "its limit, leave sufficiency SUFFICIENT and report the "
                "measurement in its coverage row."
            )

    return BasisCheckResult(not failures, failures, resolved)


__all__ = [
    "BasisCheckResult",
    "POLICY_VERSION",
    "ReconciliationResult",
    "reconcile",
    "run_basis_checks",
]
