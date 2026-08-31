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


def _brief(revision: str, tests=("tensile_strength",)):
    return EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-X", revision=revision),
        required_tests=[RequiredTest(name=t) for t in tests],
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
