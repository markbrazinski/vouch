"""Sufficiency means coverage, never conformance (commission §8).

The Hero A instability that survives every other contract check is a brief
that resolves evidence for every required test and then declares
`sufficiency=INSUFFICIENT_EVIDENCE` because the measured value FAILS its
limit. Nothing rejected it: `run_basis_checks` validated coverage, `missing`,
`method_match`, equivalences and deviations, but never `sufficiency` itself.

That is not a fuzzy judgment being overridden. The brief contradicts its own
coverage rows — it says evidence is absent for a test it just cited evidence
for — so it is exactly the objective, self-contradictory kind of error the
deterministic validator exists to catch. Whether the number PASSES stays with
`compute_disposition`, and these tests pin that boundary from both sides.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import (
    CanonicalEvidenceClaim,
    CoverageItem,
    EvidenceApplicabilityBrief,
    ExtractionMethod,
    GoverningBasis,
    MissingItem,
    RequiredTest,
    Sufficiency,
    TrustLabel,
)
from vouch.v2.corpus import Corpus, Lot, Requirement, SpecificationRevision
from vouch.v2.reconcile import run_basis_checks

TENSILE = Requirement("REQ-1", "tensile_strength", "ASTM-E8", "room_temp", 480.0, None, "MPa")


@pytest.fixture
def corpus():
    c = Corpus()
    c.put(
        "spec_revision", "SPEC-X:C",
        SpecificationRevision(
            spec_id="SPEC-X", revision="C", status="ACTIVE",
            effective_date="2026-01-01", effective_basis="date_of_receipt",
            material_scope=("MAT-1",), requirements=(TENSILE,),
        ),
    )
    c.put(
        "lot", "LOT-1",
        Lot("LOT-1", "SUP-1", "MAT-1", "PO-1", 10.0, received_at="2026-03-02"),
    )
    return c


def _claim(value):
    return CanonicalEvidenceClaim(
        claim_id="CLM-1", evidence_artifact_id="ART-1", lot_id="LOT-1",
        material_id="MAT-1", claim_type="measurement",
        characteristic="tensile_strength", value=value, units="MPa",
        method="ASTM-E8", condition="room_temp", source_locator="line 1",
        extraction_method=ExtractionMethod.DETERMINISTIC_PARSER,
        extraction_version="test", trust_label=TrustLabel.UNTRUSTED_SUPPLIER,
        source_hash="h",
    )


def _brief(sufficiency, *, evidence_ref="CLM-1", missing=()):
    return EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-X", revision="C"),
        required_tests=[RequiredTest(name="tensile_strength")],
        coverage=[
            CoverageItem(
                test="tensile_strength", evidence_ref=evidence_ref,
                method_match=evidence_ref is not None, value=462.0, units="MPa",
            )
        ],
        missing=[MissingItem(test=t, reason=r) for t, r in missing],
        sufficiency=sufficiency,
    )


def _check(corpus, brief, claims=None):
    if claims is None:
        claims = {"CLM-1": _claim(462.0)}
    return run_basis_checks(brief, corpus, lot_id="LOT-1", claims_by_id=claims)


def test_failing_value_with_full_coverage_is_sufficient(corpus):
    """The Hero A shape: 462 < 480 fails, but the evidence is present.

    Coverage is complete, so the brief must say SUFFICIENT. What the number
    means is not its call.
    """
    assert _check(corpus, _brief(Sufficiency.SUFFICIENT)).passed


def test_insufficient_contradicting_own_coverage_is_rejected(corpus):
    """The unguarded failure. Every required test resolves evidence, yet the
    brief declares the evidence insufficient — it contradicts itself."""
    result = _check(corpus, _brief(Sufficiency.INSUFFICIENT_EVIDENCE))
    assert not result.passed
    joined = " ".join(result.failures)
    assert "sufficiency" in joined
    # §9: feedback states the structural contradiction and the general
    # contract. It must never name this case's disposition — that would be
    # supplying the answer rather than the rule.
    assert "QUARANTINE" not in joined and "RELEASE" not in joined
    assert "462" not in joined


def test_insufficient_is_allowed_when_evidence_genuinely_absent(corpus):
    """The legitimate abstention path stays open: no evidence resolved, the
    test declared missing, sufficiency INSUFFICIENT_EVIDENCE."""
    brief = _brief(
        Sufficiency.INSUFFICIENT_EVIDENCE,
        evidence_ref=None,
        missing=(("tensile_strength", "no claim was submitted for this test"),),
    )
    # Nothing in the snapshot, so "missing" is the truth rather than a
    # complaint about a number.
    assert _check(corpus, brief, claims={}).passed


def test_disposition_still_owns_pass_fail(corpus):
    """The other half of the boundary: a SUFFICIENT brief over a failing value
    must still QUARANTINE. The validator did not make the lot good."""
    from vouch.v2.contracts import Disposition
    from vouch.v2.disposition import compute_disposition

    checks = _check(corpus, _brief(Sufficiency.SUFFICIENT))
    assert checks.passed
    result = compute_disposition(
        _brief(Sufficiency.SUFFICIENT),
        checks.resolved_requirements,
        {"CLM-1": _claim(462.0)},
        corpus,
        lot_id="LOT-1",
    )
    assert result.disposition is Disposition.QUARANTINE
    assert "tensile_strength" in result.failing_tests
