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
    DeviationRef,
    EvidenceApplicabilityBrief,
    GoverningBasis,
    MissingItem,
    RequiredTest,
    Sufficiency,
)
from .tools import CorpusTools


def _claim_for(claims: list[dict], characteristic: str) -> dict | None:
    for claim in claims:
        if claim["characteristic"] == characteristic:
            return claim
    return None


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


def _resolve_coverage(
    tools: CorpusTools,
    requirements: list[dict],
    claims: list[dict],
    context: dict,
) -> tuple[list[CoverageItem], list[MissingItem], list[DeviationRef]]:
    """Map each requirement to applicable evidence, citing equivalences only
    where an authoritative record actually covers method+characteristic+condition."""
    equivalences = tools.list_equivalence_records()
    coverage: list[CoverageItem] = []
    missing: list[MissingItem] = []
    deviations: list[DeviationRef] = []

    for requirement in requirements:
        characteristic = requirement["characteristic"]
        claim = _claim_for(claims, characteristic)

        if claim is None:
            missing.append(MissingItem(test=characteristic, reason="no evidence reported"))
            coverage.append(CoverageItem(test=characteristic, evidence_ref=None))
            continue

        method_match = claim["method"] == requirement["method"]
        condition_match = claim["condition"] == requirement["condition"]
        equivalence_id = None

        if not method_match:
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
                        or characteristic in record["characteristic_scope"]
                    )
                ):
                    equivalence_id = record["equivalence_id"]
                    break

            if equivalence_id is None:
                missing.append(
                    MissingItem(
                        test=characteristic,
                        reason=(
                            f"evidence used {claim['method']} but {requirement['method']} is "
                            "required and no authoritative equivalence covers it"
                        ),
                    )
                )
                coverage.append(
                    CoverageItem(
                        test=characteristic, evidence_ref=claim["claim_id"],
                        method_match=False, value=claim["value"], units=claim["units"],
                    )
                )
                continue

        if not condition_match and equivalence_id is None:
            missing.append(
                MissingItem(
                    test=characteristic,
                    reason=(
                        f"evidence condition {claim['condition']} does not match required "
                        f"{requirement['condition']}"
                    ),
                )
            )
            coverage.append(
                CoverageItem(
                    test=characteristic, evidence_ref=claim["claim_id"],
                    method_match=method_match, value=claim["value"], units=claim["units"],
                )
            )
            continue

        coverage.append(
            CoverageItem(
                test=characteristic,
                evidence_ref=claim["claim_id"],
                method_match=method_match,
                equivalence_record_id=equivalence_id,
                value=claim["value"],
                units=claim["units"],
            )
        )

    return coverage, missing, deviations


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
    coverage, missing, deviations = _resolve_coverage(tools, requirements, claims, context)

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
        deviations_applied=deviations,
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
    coverage, missing, deviations = _resolve_coverage(tools, requirements, claims, context)

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
        deviations_applied=deviations,
        sufficiency=(
            Sufficiency.INSUFFICIENT_EVIDENCE if missing else Sufficiency.SUFFICIENT
        ),
        missing=missing,
        investigation_notes="independent reconstruction",
    )


__all__ = ["investigator_reasoner", "verifier_reasoner"]
