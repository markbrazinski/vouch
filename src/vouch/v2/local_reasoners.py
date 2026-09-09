"""Scripted reasoners standing in for the models when Bedrock is not configured.

These exist so the deterministic architecture — tools, reconciler, basis checks,
disposition, policy, capability, mutation, consequences — is fully testable
without model access, and so CI proves the control flow rather than the model.

Two properties matter and are deliberately preserved:

  * They call the SAME real tools the Bedrock path calls, so tool scoping and
    the Investigator/Verifier asymmetry are exercised.
  * The Investigator and Verifier reasoners are SEPARATE implementations that
    derive the basis by different routes. V1's fatal flaw was a single
    `_classify` shared by actor and verifier, which made agreement automatic and
    verification decorative (measured 90/90 rubber stamp). Sharing one function
    here would reproduce exactly that, so they are written apart even though the
    duplication looks redundant — the independence IS the point.

They are NOT a deterministic baseline for evaluation purposes. `evaluation.py`
has that, separately, and the load-bearing gate compares against it.
"""

from __future__ import annotations

from .contracts import (
    CoverageItem,
    EvidenceApplicabilityBrief,
    GoverningBasis,
    MissingItem,
    RequiredTest,
    Sufficiency,
)
from .tools import CorpusTools


#: Higher wins when several claims speak to the same characteristic. A QA
#: retest supersedes the supplier COA it was ordered to resolve — otherwise the
#: human-continuation path attaches evidence that is then shadowed by the
#: original claim and nothing ever changes.
_TRUST_RANK = {
    "HUMAN_AUTHORIZED": 2,
    "AUTHORITATIVE_INTERNAL": 2,
    "UNTRUSTED_SUPPLIER": 1,
    "ADVISORY_PRECEDENT": 0,
}


def _claim_for(
    claims: list[dict], characteristic: str, requirement: dict | None = None
) -> dict | None:
    """Pick the most applicable claim for a characteristic.

    Preference order: trust label, then a claim whose method/condition actually
    match the requirement, then the most recently supplied.
    """
    matching = [c for c in claims if c["characteristic"] == characteristic]
    if not matching:
        return None

    def rank(item: tuple[int, dict]) -> tuple:
        index, claim = item
        exact = (
            requirement is not None
            and claim["method"] == requirement["method"]
            and claim["condition"] == requirement["condition"]
        )
        return (_TRUST_RANK.get(claim["trust_label"], 0), int(exact), index)

    return max(enumerate(matching), key=rank)[1]


def _pick_basis_by_effective_date(specs: list[dict], context: dict) -> dict | None:
    """Choose the governing revision from effective dates and stated basis.

    Returns None where the basis genuinely cannot be established — an unstated
    effective basis on a lot that straddles the boundary is not a case for a
    guess.
    """
    current = [s for s in specs if s["is_current"]]
    superseded = [s for s in specs if not s["is_current"]]
    if not specs:
        return None
    if not superseded:
        return current[0] if current else None

    newest = max(specs, key=lambda s: (s["effective_date"], s["revision"]))
    basis = newest.get("effective_basis")
    manufactured = context.get("manufactured_at", "")
    received = context.get("received_at", "")

    if basis == "date_of_manufacture" and manufactured:
        when = manufactured
    elif basis == "date_of_receipt" and received:
        when = received
    else:
        # Basis unstated. If both dates fall the same side of the effective
        # date the answer is the same either way; if they straddle it, the
        # governing revision is genuinely undetermined.
        if manufactured and received:
            effective = newest["effective_date"]
            if (manufactured < effective) != (received < effective):
                return None
            when = received
        else:
            when = received or manufactured
    if not when:
        return None

    if when >= newest["effective_date"]:
        return newest
    older = [s for s in specs if s["revision"] != newest["revision"]]
    return max(older, key=lambda s: s["effective_date"]) if older else None


def _authorized_claim_ids(context: dict) -> set[str]:
    """Evidence paths a scoped human authority has settled for this decision.

    Supplied by the workflow from the durable `HumanAuthorityDecision`, never
    by a document and never by a model. Empty on a first run, which is why the
    two reasoners are free to differ then.
    """
    return set(context.get("authorized_evidence_refs") or ())


def _covering_equivalence(
    equivalences: list[dict], requirement: dict, claim: dict
) -> str | None:
    """The authoritative equivalence that lets this claim's method stand in.

    Mechanical, not a judgment: it re-reads the SAME scope fields
    `MethodEquivalence.covers` enforces and returns an id only where the record
    genuinely covers this method pair, characteristic and condition. Shared by
    both reasoners on purpose — "does EQV-2 say E8M may stand in for E8 at
    room_temp" has one right answer, and two implementations of a lookup would
    be duplication without independence.

    What is NOT shared is whether to USE the resulting path. That is the
    judgment, and the two reasoners reach it separately below.
    """
    for record in equivalences:
        if (
            record["required_method"] == requirement["method"]
            and record["alternate_method"] == claim["method"]
            and record["status"] == "APPROVED"
            and (
                not record["condition_scope"]
                or claim["condition"] in record["condition_scope"]
            )
            and (
                not record["characteristic_scope"]
                or requirement["characteristic"] in record["characteristic_scope"]
            )
        ):
            return record["equivalence_id"]
    return None


def _applicable_paths(
    equivalences: list[dict], requirement: dict, claims: list[dict]
) -> list[tuple[dict, str | None]]:
    """Every (claim, equivalence_id) pair that ESTABLISHES this requirement.

    A path is applicable when the claim either used the required method at the
    required condition, or used a method an authoritative equivalence covers.
    Says nothing about whether the measured value passes — a failing number is
    an applicable path, and conformance is computed downstream.

    Returned in snapshot order. Both reasoners enumerate the same set; they
    differ in which one they then select, which is the whole point.
    """
    paths: list[tuple[dict, str | None]] = []
    for claim in claims:
        if claim["characteristic"] != requirement["characteristic"]:
            continue
        direct = (
            claim["method"] == requirement["method"]
            and claim["condition"] == requirement["condition"]
        )
        if direct:
            paths.append((claim, None))
            continue
        equivalence_id = _covering_equivalence(equivalences, requirement, claim)
        if equivalence_id is not None:
            paths.append((claim, equivalence_id))
    return paths


def _authorized_paths(
    paths: list[tuple[dict, str | None]], authorized: set[str]
) -> list[tuple[dict, str | None]]:
    """Paths a scoped human authority has settled, if any.

    When Quality has authorized a specific evidence path for this decision, it
    stops being one of several defensible readings and becomes the answer.
    Both reasoners consult this, which is how a resolved authority question
    makes them converge without either being told what the other said.
    """
    if not authorized:
        return []
    return [p for p in paths if p[0]["claim_id"] in authorized]


def _uncovered(requirement: dict, claims: list[dict]) -> MissingItem:
    """Why no applicable evidence establishes this requirement."""
    related = [
        c for c in claims if c["characteristic"] == requirement["characteristic"]
    ]
    if not related:
        return MissingItem(
            test=requirement["characteristic"], reason="no evidence reported"
        )
    claim = related[0]
    if claim["method"] != requirement["method"]:
        return MissingItem(
            test=requirement["characteristic"],
            reason=(
                f"evidence used {claim['method']} but {requirement['method']} is "
                "required and no authoritative equivalence covers it"
            ),
        )
    return MissingItem(
        test=requirement["characteristic"],
        reason=(
            f"evidence condition {claim['condition']} does not match required "
            f"{requirement['condition']}"
        ),
    )


def _row(requirement: dict, claim: dict, equivalence_id: str | None) -> CoverageItem:
    return CoverageItem(
        test=requirement["characteristic"],
        evidence_ref=claim["claim_id"],
        method_match=claim["method"] == requirement["method"]
        and claim["condition"] == requirement["condition"],
        equivalence_record_id=equivalence_id,
        value=claim["value"],
        units=claim["units"],
    )


def _investigator_coverage(
    tools: CorpusTools,
    requirements: list[dict],
    claims: list[dict],
    authorized: set[str],
) -> tuple[list[CoverageItem], list[MissingItem]]:
    """Investigator's selection rule: PREFER THE METHOD THE SPEC NAMES.

    Where a requirement names a method and the snapshot contains a result
    measured by exactly that method at exactly that condition, that result is
    the evidence — an equivalence is a way to accept a substitute when the
    named method is absent, not a reason to set aside the named method when it
    is present. Where the named method is absent, an equivalence-covered path
    is used.

    Defensible on any evidence set, not just this one, and stated as a general
    priority rather than a lot-specific branch.
    """
    equivalences = tools.list_equivalence_records()
    coverage: list[CoverageItem] = []
    missing: list[MissingItem] = []

    for requirement in requirements:
        paths = _applicable_paths(equivalences, requirement, claims)
        if not paths:
            missing.append(_uncovered(requirement, claims))
            related = [
                c for c in claims
                if c["characteristic"] == requirement["characteristic"]
            ]
            coverage.append(
                CoverageItem(
                    test=requirement["characteristic"],
                    evidence_ref=related[0]["claim_id"] if related else None,
                    method_match=False,
                    value=related[0]["value"] if related else None,
                    units=related[0]["units"] if related else "",
                )
            )
            continue

        settled = _authorized_paths(paths, authorized)
        pool = settled or paths
        # Highest trust first, then the spec's own method, then snapshot order.
        claim, equivalence_id = max(
            pool,
            key=lambda p: (
                _TRUST_RANK.get(p[0]["trust_label"], 0),
                int(p[1] is None),
                -pool.index(p),
            ),
        )
        coverage.append(_row(requirement, claim, equivalence_id))

    return coverage, missing


def _verifier_coverage(
    tools: CorpusTools,
    requirements: list[dict],
    claims: list[dict],
    authorized: set[str],
) -> tuple[list[CoverageItem], list[MissingItem]]:
    """Verifier's selection rule: RECONSTRUCT EVERY AUTHORIZED PATH, TAKE THE
    MOST RECENT.

    The Verifier does not privilege the method the requirement happens to name.
    It enumerates every path an authoritative record makes applicable — direct
    or equivalence-covered, they are equally authorized once a record covers
    them — and takes the latest such result in the snapshot, on the reasoning
    that the most recently reported applicable measurement is the current state
    of the material.

    A separate derivation, not an inverted one: on a snapshot with a single
    applicable path it returns exactly what the Investigator returns, and on a
    snapshot whose newest result is the direct-method one it prefers that. It
    diverges only where a material genuinely has several equally authorized
    results, which is precisely when a human should decide.
    """
    equivalences = tools.list_equivalence_records()
    coverage: list[CoverageItem] = []
    missing: list[MissingItem] = []

    for requirement in requirements:
        paths = _applicable_paths(equivalences, requirement, claims)
        if not paths:
            missing.append(_uncovered(requirement, claims))
            related = [
                c for c in claims
                if c["characteristic"] == requirement["characteristic"]
            ]
            coverage.append(
                CoverageItem(
                    test=requirement["characteristic"],
                    evidence_ref=related[0]["claim_id"] if related else None,
                    method_match=False,
                    value=related[0]["value"] if related else None,
                    units=related[0]["units"] if related else "",
                )
            )
            continue

        settled = _authorized_paths(paths, authorized)
        pool = settled or paths
        # Highest trust first, then the latest applicable result.
        claim, equivalence_id = max(
            pool,
            key=lambda p: (
                _TRUST_RANK.get(p[0]["trust_label"], 0),
                pool.index(p),
            ),
        )
        coverage.append(_row(requirement, claim, equivalence_id))

    return coverage, missing


def investigator_reasoner(
    tools: CorpusTools, context: dict
) -> EvidenceApplicabilityBrief:
    """Investigator route: resolve basis from candidate specs, then evaluate
    applicability against the chosen basis.

    Note the ordering — basis FIRST, then bounded deterministic evaluation
    against that selected basis. The V1 mistake was precomputing
    governing_spec + OUT_OF_LIMITS and handing the model the answer.
    """
    claims = tools.get_evidence_snapshot()
    specs = tools.list_candidate_specs()
    chosen = _pick_basis_by_effective_date(specs, context)

    if chosen is None:
        fallback = specs[0] if specs else {"spec_id": "SPEC-UNKNOWN", "revision": "0"}
        return EvidenceApplicabilityBrief(
            governing_basis=GoverningBasis(
                spec_id=fallback["spec_id"], revision=fallback["revision"]
            ),
            required_tests=[],
            coverage=[],
            sufficiency=Sufficiency.INSUFFICIENT_EVIDENCE,
            missing=[
                MissingItem(
                    test="governing_basis",
                    reason="effective basis is unstated and the lot straddles the boundary",
                )
            ],
            investigation_notes="basis undetermined among candidate revisions",
        )

    requirements = tools.get_spec_requirement(chosen["spec_id"], chosen["revision"])
    coverage, missing = _investigator_coverage(
        tools, requirements, claims, _authorized_claim_ids(context)
    )

    return EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(
            spec_id=chosen["spec_id"], revision=chosen["revision"]
        ),
        required_tests=[
            RequiredTest(
                name=r["characteristic"], threshold=r["threshold"],
                required_method=r["method"], required_condition=r["condition"],
            )
            for r in requirements
        ],
        coverage=coverage,
        sufficiency=(
            Sufficiency.INSUFFICIENT_EVIDENCE if missing else Sufficiency.SUFFICIENT
        ),
        missing=missing,
        investigation_notes=f"basis {chosen['spec_id']} rev {chosen['revision']}",
    )


def verifier_reasoner(tools: CorpusTools, context: dict) -> EvidenceApplicabilityBrief:
    """Verifier route: reconstruct the basis independently.

    Written as a separate derivation on purpose. It reaches the basis by
    filtering candidates on applicability windows rather than by picking the
    newest and walking back, so a flaw in one route does not silently reproduce
    in the other. Same authoritative inputs, different path to the answer.
    """
    claims = tools.get_evidence_snapshot()
    specs = tools.list_candidate_specs()

    if not specs:
        return EvidenceApplicabilityBrief(
            governing_basis=GoverningBasis(spec_id="SPEC-UNKNOWN", revision="0"),
            sufficiency=Sufficiency.INSUFFICIENT_EVIDENCE,
            missing=[MissingItem(test="governing_basis", reason="no candidate specifications")],
        )

    manufactured = context.get("manufactured_at", "")
    received = context.get("received_at", "")

    # Independent derivation: keep every revision whose effective window has
    # opened for this lot under its OWN stated basis, then take the latest.
    applicable: list[dict] = []
    ambiguous = False
    for spec in specs:
        basis = spec.get("effective_basis")
        if basis == "date_of_manufacture":
            when = manufactured
        elif basis == "date_of_receipt":
            when = received
        else:
            when = ""
            if manufactured and received and manufactured != received:
                effective = spec["effective_date"]
                if (manufactured < effective) != (received < effective):
                    ambiguous = True
            when = received or manufactured
        if when and when >= spec["effective_date"]:
            applicable.append(spec)

    if ambiguous:
        return EvidenceApplicabilityBrief(
            governing_basis=GoverningBasis(
                spec_id=specs[0]["spec_id"], revision=specs[0]["revision"]
            ),
            sufficiency=Sufficiency.INSUFFICIENT_EVIDENCE,
            missing=[
                MissingItem(
                    test="governing_basis",
                    reason="applicability window is ambiguous for this lot's dates",
                )
            ],
            investigation_notes="independent reconstruction: basis ambiguous",
        )

    chosen = (
        max(applicable, key=lambda s: (s["effective_date"], s["revision"]))
        if applicable
        else min(specs, key=lambda s: (s["effective_date"], s["revision"]))
    )

    requirements = tools.get_spec_requirement(chosen["spec_id"], chosen["revision"])
    coverage, missing = _verifier_coverage(
        tools, requirements, claims, _authorized_claim_ids(context)
    )

    return EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(
            spec_id=chosen["spec_id"], revision=chosen["revision"]
        ),
        required_tests=[
            RequiredTest(
                name=r["characteristic"], threshold=r["threshold"],
                required_method=r["method"], required_condition=r["condition"],
            )
            for r in requirements
        ],
        coverage=coverage,
        sufficiency=(
            Sufficiency.INSUFFICIENT_EVIDENCE if missing else Sufficiency.SUFFICIENT
        ),
        missing=missing,
        investigation_notes="independent reconstruction",
    )


__all__ = ["investigator_reasoner", "verifier_reasoner"]
