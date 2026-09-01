"""P1-4 historical revision semantics and P1-5 required-test omission.

The audit found two defects here:

  * the basis check used `lot.received_at or lot.manufactured_at` — a truthy
    fallback that answers a policy question with whichever field happened to be
    populated;
  * every SUPERSEDED revision was rejected outright, even where it legitimately
    governed a lot manufactured while it was in force.

Those are different questions. "Is this revision current today?" is not "did
this revision govern this lot?", and only the second one is the right question.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import (
    EvidenceApplicabilityBrief,
    CoverageItem,
    GoverningBasis,
    RequiredTest,
    Sufficiency,
)
from vouch.v2.corpus import Corpus, Lot, Requirement, SpecificationRevision
from vouch.v2.reconcile import (
    BasisDateUndetermined,
    basis_date_for,
    run_basis_checks,
)

TENSILE = Requirement("REQ-1", "tensile_strength", "ASTM-E8", "room_temp", 450.0, None, "MPa")


@pytest.fixture
def corpus():
    """SPEC-X: rev A governed 2024-01-01..2026-01-01, rev B from 2026-01-01,
    rev C not effective until 2027-01-01."""
    c = Corpus()
    c.put(
        "spec_revision", "SPEC-X:A",
        SpecificationRevision(
            spec_id="SPEC-X", revision="A", status="SUPERSEDED",
            effective_date="2024-01-01", effective_to="2026-01-01",
            superseded_by="B", superseded_at="2026-01-01",
            effective_basis="date_of_manufacture",
            material_scope=("MAT-1",), requirements=(TENSILE,),
        ),
    )
    c.put(
        "spec_revision", "SPEC-X:B",
        SpecificationRevision(
            spec_id="SPEC-X", revision="B", status="ACTIVE",
            effective_date="2026-01-01", effective_basis="date_of_manufacture",
            material_scope=("MAT-1",), requirements=(TENSILE,),
        ),
    )
    c.put(
        "spec_revision", "SPEC-X:C",
        SpecificationRevision(
            spec_id="SPEC-X", revision="C", status="ACTIVE",
            effective_date="2027-01-01", effective_basis="date_of_manufacture",
            material_scope=("MAT-1",), requirements=(TENSILE,),
        ),
    )
    return c


def _lot(corpus, lot_id, manufactured_at="", received_at=""):
    corpus.put(
        "lot", lot_id,
        Lot(lot_id, "SUP-1", "MAT-1", "PO-1", 10.0,
            manufactured_at=manufactured_at, received_at=received_at),
    )
    return lot_id


def _claim(claim_id, lot_id, characteristic, *, method, condition, value):
    """One canonical claim, as the frozen snapshot would present it."""
    from vouch.v2.contracts import (
        CanonicalEvidenceClaim,
        ExtractionMethod,
        TrustLabel,
    )

    return CanonicalEvidenceClaim(
        claim_id=claim_id,
        evidence_artifact_id="ART-1",
        lot_id=lot_id,
        material_id="MAT-ALLOY-7",
        claim_type="measurement",
        extraction_method=ExtractionMethod.DETERMINISTIC_PARSER,
        extraction_version="test",
        characteristic=characteristic,
        value=value,
        units="MPa",
        method=method,
        condition=condition,
        source_locator="line 1",
        trust_label=TrustLabel.UNTRUSTED_SUPPLIER,
        source_hash="h",
    )


def _brief(revision: str, tests=("tensile_strength",), coverage=None):
    """A brief for the BASIS tests below.

    Coverage defaults to one null-evidence row per declared test: these cases
    are about which revision governs, not about evidence, and a brief that
    names a required test while saying nothing at all about it is now a
    contract failure in its own right. A null evidence_ref is the brief
    answering "no evidence applies to this test", which is a real answer.
    """
    if coverage is None:
        coverage = [CoverageItem(test=t, evidence_ref=None) for t in tests]
    return EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-X", revision=revision),
        required_tests=[RequiredTest(name=t) for t in tests],
        coverage=coverage,
        sufficiency=Sufficiency.SUFFICIENT,
    )


# ==========================================================================
# P1-4 — the four required scenarios
# ==========================================================================


def test_current_lot_uses_current_revision(corpus):
    """A lot made today is governed by the revision in force today."""
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    result = run_basis_checks(_brief("B"), corpus, lot_id="LOT-NOW", claims_by_id={})
    assert result.passed, result.failures


def test_historical_lot_may_use_the_revision_that_governed_it(corpus):
    """The headline P1-4 case.

    A lot manufactured 2025-06-01 was governed by rev A. Rev A is SUPERSEDED
    today. That must not retroactively invalidate the lot's governing basis.
    """
    _lot(corpus, "LOT-OLD", manufactured_at="2025-06-01")
    result = run_basis_checks(_brief("A"), corpus, lot_id="LOT-OLD", claims_by_id={})
    assert result.passed, result.failures


def test_lot_after_supersession_cannot_use_the_old_revision(corpus):
    """The safety half: history does not become a loophole."""
    _lot(corpus, "LOT-NEW", manufactured_at="2026-06-01")
    result = run_basis_checks(_brief("A"), corpus, lot_id="LOT-NEW", claims_by_id={})
    assert not result.passed
    assert any("ceased to govern" in f for f in result.failures)


def test_future_revision_is_not_yet_effective(corpus):
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    result = run_basis_checks(_brief("C"), corpus, lot_id="LOT-NOW", claims_by_id={})
    assert not result.passed
    assert any("not yet effective" in f for f in result.failures)


def test_lot_before_any_revision_was_effective(corpus):
    _lot(corpus, "LOT-ANCIENT", manufactured_at="2023-01-01")
    result = run_basis_checks(_brief("A"), corpus, lot_id="LOT-ANCIENT", claims_by_id={})
    assert not result.passed
    assert any("not yet effective" in f for f in result.failures)


# ==========================================================================
# P1-4 — the basis DATE rule itself
# ==========================================================================


def test_basis_date_follows_the_revision_not_field_availability(corpus):
    """No truthy fallback: the revision's stated rule decides.

    This lot has BOTH dates, and they fall on opposite sides of rev A's
    supersession. Which one is used must be the revision's rule, not whichever
    field is non-empty.
    """
    _lot(corpus, "LOT-BOTH", manufactured_at="2025-06-01", received_at="2026-06-01")
    revision = corpus.spec_revision("SPEC-X", "A")
    assert basis_date_for(revision, corpus.lot("LOT-BOTH")) == "2025-06-01"

    # rev A keys on manufacture, so this lot IS governed by A despite having
    # been received after A was superseded.
    result = run_basis_checks(_brief("A"), corpus, lot_id="LOT-BOTH", claims_by_id={})
    assert result.passed, result.failures


def test_receipt_basis_uses_receipt_date(corpus):
    corpus.put(
        "spec_revision", "SPEC-X:R",
        SpecificationRevision(
            spec_id="SPEC-X", revision="R", status="ACTIVE",
            effective_date="2026-01-01", effective_basis="date_of_receipt",
            material_scope=("MAT-1",), requirements=(TENSILE,),
        ),
    )
    _lot(corpus, "LOT-BOTH", manufactured_at="2025-06-01", received_at="2026-06-01")
    revision = corpus.spec_revision("SPEC-X", "R")
    assert basis_date_for(revision, corpus.lot("LOT-BOTH")) == "2026-06-01"


def test_missing_basis_date_is_undeterminable_not_guessed(corpus):
    """A lot with no manufacture date cannot be judged on a manufacture basis."""
    _lot(corpus, "LOT-NODATE", received_at="2026-06-01")
    revision = corpus.spec_revision("SPEC-X", "A")
    with pytest.raises(BasisDateUndetermined):
        basis_date_for(revision, corpus.lot("LOT-NODATE"))

    result = run_basis_checks(_brief("A"), corpus, lot_id="LOT-NODATE", claims_by_id={})
    assert not result.passed
    assert any("cannot be established" in f for f in result.failures)


def test_unstated_basis_uses_the_explicit_plant_default(corpus):
    """Where a revision states no basis, the default is explicit and recorded."""
    from vouch.v2.reconcile import DEFAULT_EFFECTIVE_BASIS

    assert DEFAULT_EFFECTIVE_BASIS == "date_of_receipt"
    corpus.put(
        "spec_revision", "SPEC-X:U",
        SpecificationRevision(
            spec_id="SPEC-X", revision="U", status="ACTIVE",
            effective_date="2026-01-01", effective_basis=None,
            material_scope=("MAT-1",), requirements=(TENSILE,),
        ),
    )
    _lot(corpus, "LOT-BOTH", manufactured_at="2025-06-01", received_at="2026-06-01")
    revision = corpus.spec_revision("SPEC-X", "U")
    assert basis_date_for(revision, corpus.lot("LOT-BOTH")) == "2026-06-01"


def test_draft_and_withdrawn_never_govern(corpus):
    for status in ("DRAFT", "WITHDRAWN"):
        corpus.put(
            "spec_revision", f"SPEC-X:{status}",
            SpecificationRevision(
                spec_id="SPEC-X", revision=status, status=status,
                effective_date="2024-01-01", effective_basis="date_of_manufacture",
                material_scope=("MAT-1",), requirements=(TENSILE,),
            ),
        )
        _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
        result = run_basis_checks(
            _brief(status), corpus, lot_id="LOT-NOW", claims_by_id={}
        )
        assert not result.passed


# ==========================================================================
# P1-5 — required_tests cannot be an empty bypass
# ==========================================================================


def test_empty_required_tests_cannot_bypass_the_omission_check(corpus):
    """The audit's omission attack.

    A brief that declares NO required tests previously skipped the comparison
    entirely, so a model that acknowledged no requirements sailed through.
    """
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-X", revision="B"),
        required_tests=[],  # the attack
        sufficiency=Sufficiency.SUFFICIENT,
    )
    result = run_basis_checks(brief, corpus, lot_id="LOT-NOW", claims_by_id={})
    assert not result.passed
    assert any("declares no required tests" in f for f in result.failures)


def test_partial_omission_is_caught(corpus):
    """Dropping one of several requirements is still omission."""
    corpus.put(
        "spec_revision", "SPEC-X:M",
        SpecificationRevision(
            spec_id="SPEC-X", revision="M", status="ACTIVE",
            effective_date="2026-01-01", effective_basis="date_of_manufacture",
            material_scope=("MAT-1",),
            requirements=(
                TENSILE,
                Requirement("REQ-2", "hardness", "HRC", "as_received", 28.0, 36.0, "HRC"),
            ),
        ),
    )
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    result = run_basis_checks(
        _brief("M", tests=("tensile_strength",)), corpus,
        lot_id="LOT-NOW", claims_by_id={},
    )
    assert not result.passed
    assert any("omits required tests" in f and "hardness" in f for f in result.failures)


def test_invented_tests_are_caught(corpus):
    """A brief asserting requirements the spec does not have is also wrong."""
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    result = run_basis_checks(
        _brief("B", tests=("tensile_strength", "invented_test")), corpus,
        lot_id="LOT-NOW", claims_by_id={},
    )
    assert not result.passed
    assert any("asserts tests not in" in f for f in result.failures)


def test_exact_requirement_set_passes(corpus):
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    result = run_basis_checks(
        _brief("B", tests=("tensile_strength",)), corpus,
        lot_id="LOT-NOW", claims_by_id={},
    )
    assert result.passed, result.failures


# ==========================================================================
# the validator's boundary
#
# It may REJECT a brief that contradicts the corpus. It may never supply the
# applicability judgment itself — that is the seam the architecture exists to
# expose, and a deterministic classifier hidden in the validator would erase it
# while every test still passed.
# ==========================================================================


def test_validation_only_rejects_and_never_rewrites_a_brief():
    """Structural: run_basis_checks returns failures, and the brief is frozen.

    The brief is a frozen pydantic model, so a validator that tried to correct
    one would raise rather than silently succeed. This asserts the shape of the
    contract: errors out, no corrected brief.
    """
    import dataclasses

    from vouch.v2.contracts import CoverageItem
    from vouch.v2.reconcile import BasisCheckResult

    fields = {f.name for f in dataclasses.fields(BasisCheckResult)}
    assert fields == {"passed", "failures", "resolved_requirements"}, (
        "BasisCheckResult must not carry a corrected brief; a validator that "
        "returns an answer is a classifier"
    )

    assert CoverageItem.model_config.get("frozen") is True
    assert EvidenceApplicabilityBrief.model_config.get("frozen") is True


def test_validator_does_not_decide_which_candidate_revision_governs(corpus):
    """Two revisions could plausibly be argued; the validator picks neither.

    It only rejects a revision that could not have governed. Where a cited
    revision genuinely governs, validation is silent — the choice stays with
    the model even when another revision also exists.
    """
    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")

    result = run_basis_checks(
        _brief("B"), corpus, lot_id="LOT-NOW", claims_by_id={}
    )

    # B is a real, governing revision for this lot: no opinion is offered about
    # whether some other revision would have been the better citation.
    assert result.passed, result.failures


def test_validator_does_not_decide_whether_ambiguous_evidence_applies(corpus):
    """A method that differs from the requirement is left to the model.

    The validator says only that the identifiers differ, which is a string
    comparison. Whether the difference is nonetheless acceptable is the
    equivalence question, and it is not answered here.
    """
    from vouch.v2.contracts import CoverageItem

    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    brief = _brief(
        "B",
        coverage=[
            CoverageItem(
                test="tensile_strength", evidence_ref=None, method_match=False
            )
        ],
    )

    result = run_basis_checks(
        brief, corpus, lot_id="LOT-NOW", claims_by_id={}
    )

    # No evidence to compare against, so no method claim is contradicted and
    # the validator offers no view on applicability.
    assert result.passed, result.failures


def test_missing_means_absent_not_failing(corpus):
    """A failing value is covered evidence, not a missing test.

    Live Verifier briefs declared tensile_strength missing because the number
    was below the limit, against a claim measured by the required method at the
    required condition. Conformance is computed downstream and the brief has no
    vocabulary for it — which is why a failing value must still be reported as
    covered.
    """
    from vouch.v2.contracts import MissingItem

    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    claim = _claim(
        "CLM-1", "LOT-NOW", "tensile_strength", method="ASTM-E8",
        condition="room_temp", value=100.0,
    )
    brief = _brief("B", coverage=[])
    brief = brief.model_copy(
        update={
            "missing": [
                MissingItem(test="tensile_strength", reason="below the 450 MPa limit")
            ]
        }
    )

    result = run_basis_checks(
        brief, corpus, lot_id="LOT-NOW", claims_by_id={"CLM-1": claim}
    )

    assert not result.passed
    assert any("is listed as missing" in f for f in result.failures)


def test_a_genuinely_inapplicable_method_may_still_be_missing(corpus):
    """The boundary: a DIFFERENT method is left entirely to the model."""
    from vouch.v2.contracts import MissingItem

    _lot(corpus, "LOT-NOW", manufactured_at="2026-06-01")
    claim = _claim(
        "CLM-1", "LOT-NOW", "tensile_strength", method="ASTM-OTHER",
        condition="room_temp", value=500.0,
    )
    brief = _brief("B", coverage=[]).model_copy(
        update={
            "missing": [
                MissingItem(test="tensile_strength", reason="method not established")
            ]
        }
    )

    result = run_basis_checks(
        brief, corpus, lot_id="LOT-NOW", claims_by_id={"CLM-1": claim}
    )

    assert result.passed, result.failures
