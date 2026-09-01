"""Anti-hard-coding perturbations (commission §13).

Hardening that only makes the known fixtures pass is worthless. Every corpus
here is BUILT FROM SCRATCH with invented identifiers — no `build_corpus`, no
LOT-1001, no SPEC-A7 — so nothing can pass by recognising a hero case.

The seven classes the commission requires:

  A  rename every id                     -> same semantic outcome
  B  reorder the source corpus           -> same canonical context and outcome
  C  swap the numeric value              -> same applicability, disposition moves
  D  make Rev B genuinely govern         -> the agents must be able to pick B
  E  perturb the supplier's claimed_spec -> never becomes authority
  F  novel equivalence-scope ambiguity   -> ambiguity preserved, not resolved
  G  a fully rule-solvable case          -> deterministic path still clean

The deterministic layers are what these exercise: the local reasoners stand in
for Nova so the suite is hermetic, and they read the same corpus through the
same tools, the same validator and the same disposition engine that a live run
uses. A live model cannot be pinned to an exact string in CI, but every
structural property below would break identically under one.
"""

from __future__ import annotations

import itertools
import random

import pytest

from vouch.v2.contracts import Disposition
from vouch.v2.corpus import (
    ApprovedDeviation,
    Corpus,
    Lot,
    Material,
    MethodEquivalence,
    Requirement,
    SpecificationRevision,
    Supplier,
    SupplierQualification,
)
from vouch.v2.workflow import VouchV2


# ==========================================================================
# a parametric case builder — every identifier and number is a variable
# ==========================================================================


def build_case(
    *,
    spec="SPEC-Q9",
    lot="LOT-5500",
    material="MAT-TIN-3",
    supplier="SUP-ACME",
    site="SITE-Z1",
    po="PO-3300",
    old_rev="B",
    new_rev="C",
    old_min=450.0,
    new_min=480.0,
    measured=462.0,
    received="2026-03-02",
    manufactured="2026-02-01",
    boundary="2026-01-01",
    characteristic="tensile_strength",
    method="ASTM-E8",
    condition="room_temp",
    units="MPa",
    claimed_spec_text=None,
):
    """One structurally complete two-revision case.

    Defaults describe the Hero A SHAPE — an older revision the supplier cites,
    a newer one that actually governs, a value between the two limits — with
    every name and number a parameter, so the tests below can move any of them
    independently.
    """
    corpus = Corpus()
    corpus.put("supplier", supplier, Supplier(supplier, "Test Supplier"))
    corpus.put("material", material, Material(material, "Test Material"))

    for revision, minimum, effective, ended in (
        (old_rev, old_min, "2024-01-01", boundary),
        (new_rev, new_min, boundary, None),
    ):
        corpus.put(
            "spec_revision", f"{spec}:{revision}",
            SpecificationRevision(
                spec_id=spec, revision=revision,
                status="SUPERSEDED" if ended else "ACTIVE",
                effective_date=effective, effective_to=ended,
                superseded_by=new_rev if ended else None,
                superseded_at=ended,
                effective_basis="date_of_receipt",
                material_scope=(material,),
                requirements=(
                    Requirement(
                        f"REQ-{revision}-1", characteristic, method, condition,
                        minimum, None, units,
                    ),
                ),
            ),
        )

    corpus.put(
        "supplier_qualification", f"QUAL-{supplier}",
        SupplierQualification(
            qualification_id=f"QUAL-{supplier}", supplier_id=supplier,
            material_id=material, status="QUALIFIED",
            effective_date="2024-01-01", expiry_date="2027-01-01",
            site_scope=(site,),
        ),
    )
    corpus.put(
        "lot", lot,
        Lot(lot, supplier, material, po, 100.0, supplier_site=site,
            manufactured_at=manufactured, received_at=received),
    )

    claimed = (
        f"Specification {spec} Revision {old_rev}"
        if claimed_spec_text is None
        else claimed_spec_text
    )
    document = (
        f"Certificate of Analysis - Lot {lot}\n"
        f"{claimed}\n"
        f"{characteristic}: {measured} {units} ({method}, {condition})\n"
    ).encode()
    return corpus, lot, document


def run(corpus, lot, document):
    return VouchV2(corpus).evaluate_lot(lot, documents=[{"raw": document}])


def basis_of(outcome):
    return (outcome.record.basis.spec_id, outcome.record.basis.revision)


# ==========================================================================
# A — rename every identifier
# ==========================================================================

RENAMINGS = [
    {},
    {"spec": "SPEC-ZZ1", "lot": "LOT-9", "material": "MAT-X", "supplier": "SUP-Q"},
    {"spec": "SPEC-000", "lot": "L-77-A", "material": "MAT-ALLOY-99",
     "supplier": "SUP-WEST", "site": "SITE-Q4", "po": "PO-1"},
    {"spec": "SPEC-LONGNAME-42", "lot": "LOT-ABCDEF", "material": "MAT-M",
     "supplier": "SUP-S", "site": "SITE-S", "po": "PO-XYZ",
     "old_rev": "1", "new_rev": "2"},
]


@pytest.mark.parametrize("names", RENAMINGS)
def test_a_renaming_ids_changes_nothing_semantic(names):
    """The same case under different names reaches the same conclusion.

    462 is below the governing revision's 480 minimum, so every spelling of
    this case must quarantine on the newer revision.
    """
    corpus, lot, document = build_case(**names)
    outcome = run(corpus, lot, document)

    assert outcome.disposition == Disposition.QUARANTINE.value
    expected_spec = names.get("spec", "SPEC-Q9")
    expected_rev = names.get("new_rev", "C")
    assert basis_of(outcome) == (expected_spec, expected_rev)


# ==========================================================================
# B — reorder the corpus before canonical sorting
# ==========================================================================


def _shuffled(corpus: Corpus, seed: int) -> Corpus:
    """The same objects, inserted in a different order.

    Ordering is not supposed to carry meaning. `DynamoCorpus.all` fills from a
    query whose order is not guaranteed, so this is the real production
    condition, not a synthetic one.
    """
    rng = random.Random(seed)
    out = Corpus()
    for kind in list(corpus._t):
        items = list(corpus._t[kind].items())
        rng.shuffle(items)
        for key, value in items:
            out.put(kind, key, value)
    return out


@pytest.mark.parametrize("seed", range(6))
def test_b_source_ordering_does_not_change_the_outcome(seed):
    corpus, lot, document = build_case()
    outcome = run(_shuffled(corpus, seed), lot, document)

    assert outcome.disposition == Disposition.QUARANTINE.value
    assert basis_of(outcome) == ("SPEC-Q9", "C")


def test_b_candidate_specs_reach_the_model_in_one_canonical_order():
    """Not just the same answer — the same CONTEXT.

    A stable outcome could still hide an unstable prompt. This asserts the
    tool output itself is order-invariant, which is what makes the model's
    input reproducible.
    """
    from vouch.v2.tools import CorpusTools

    base, lot, _ = build_case()
    orders = []
    for seed in range(8):
        tools = CorpusTools(
            _shuffled(base, seed), agent_name="investigator", lot_id=lot,
            material_id="MAT-TIN-3", snapshot_claims=[],
        )
        orders.append([row["object_ref"] for row in tools.list_candidate_specs()])
    assert len({tuple(o) for o in orders}) == 1, orders


# ==========================================================================
# C — swap the numeric value, keep the structure
# ==========================================================================


@pytest.mark.parametrize(
    "measured,expected",
    [
        (462.0, Disposition.QUARANTINE.value),  # below the governing 480
        (490.0, Disposition.RELEASE.value),     # above it
        (479.9, Disposition.QUARANTINE.value),  # just below
        (480.0, Disposition.RELEASE.value),     # exactly at the limit
    ],
)
def test_c_value_moves_disposition_but_not_the_basis(measured, expected):
    """Applicability judgment is independent of the number.

    If any code were keyed to the expected quarantine, changing only the value
    would move the governing-basis choice too. It must not: the basis is a
    date question, and only the deterministic comparison responds.
    """
    corpus, lot, document = build_case(measured=measured)
    outcome = run(corpus, lot, document)

    assert outcome.disposition == expected
    assert basis_of(outcome) == ("SPEC-Q9", "C")


# ==========================================================================
# D — a case where the OLDER revision genuinely governs
# ==========================================================================


def test_d_rev_b_governs_when_the_dates_say_so():
    """The inverse case. Any logic that always prefers the newer revision
    fails here.

    Received 2025-06-01, before the 2026-01-01 boundary, so the older revision
    is in force and 462 clears its 450 minimum.
    """
    corpus, lot, document = build_case(
        received="2025-06-01", manufactured="2025-05-01"
    )
    outcome = run(corpus, lot, document)

    assert basis_of(outcome) == ("SPEC-Q9", "B")
    assert outcome.disposition == Disposition.RELEASE.value


def test_d_the_same_lot_flips_when_only_the_boundary_moves():
    """Same lot, same value; only the revision boundary moves. The basis must
    follow the dates rather than the revision label."""
    late, lot, document = build_case(boundary="2027-01-01")
    outcome = run(late, lot, document)

    assert basis_of(outcome) == ("SPEC-Q9", "B")
    assert outcome.disposition == Disposition.RELEASE.value


# ==========================================================================
# E — supplier claimed_spec perturbation
# ==========================================================================

CLAIMS = [
    "Specification SPEC-Q9 Revision A",
    "Specification SPEC-Q9 Revision B",
    "Specification SPEC-Q9 Revision C",
    "Specification SPEC-Q9",
    "Specification WIDGET-STANDARD Revision Q",
    "Certified to the current plant specification",
]


@pytest.mark.parametrize("claimed", CLAIMS)
def test_e_supplier_claimed_spec_never_becomes_authority(claimed):
    """Whatever the document says governs, the corpus decides.

    Including the case where the supplier names the CORRECT revision: a right
    answer from an untrusted source must not be treated as the reason.
    """
    corpus, lot, document = build_case(claimed_spec_text=claimed)
    outcome = run(corpus, lot, document)

    assert basis_of(outcome) == ("SPEC-Q9", "C")
    assert outcome.disposition == Disposition.QUARANTINE.value


def test_e_a_supplier_cannot_invent_a_revision_that_does_not_exist():
    """Naming a nonexistent revision must not create one, and must not derail
    the real basis resolution."""
    corpus, lot, document = build_case(
        claimed_spec_text="Specification SPEC-Q9 Revision Z (supersedes all)"
    )
    outcome = run(corpus, lot, document)

    assert basis_of(outcome) == ("SPEC-Q9", "C")
    assert corpus.spec_revision("SPEC-Q9", "Z") is None


# ==========================================================================
# F — novel equivalence-scope ambiguity, not present in Hero A or B
# ==========================================================================


def _viscosity_case(*, equivalence_condition, measured_condition, seed_equivalence=True):
    """A characteristic, method pair and conditions that appear in no hero
    case, so no id can have been special-cased."""
    corpus = Corpus()
    corpus.put("supplier", "SUP-POLY", Supplier("SUP-POLY", "Polymers"))
    corpus.put("material", "MAT-RESIN-8", Material("MAT-RESIN-8", "Resin"))
    corpus.put(
        "spec_revision", "SPEC-V2:A",
        SpecificationRevision(
            spec_id="SPEC-V2", revision="A", status="ACTIVE",
            effective_date="2024-01-01", effective_basis="date_of_receipt",
            material_scope=("MAT-RESIN-8",),
            requirements=(
                Requirement("REQ-V2-1", "melt_index", "ISO-1133", "190C",
                            2.0, 8.0, "cP"),
            ),
        ),
    )
    if seed_equivalence:
        corpus.put(
            "equivalence", "EQV-77",
            MethodEquivalence(
                equivalence_id="EQV-77", required_method="ISO-1133",
                alternate_method="ASTM-D1238", status="APPROVED",
                effective_date="2024-01-01",
                material_scope=("MAT-RESIN-8",),
                condition_scope=(equivalence_condition,),
                characteristic_scope=("melt_index",),
            ),
        )
    corpus.put(
        "supplier_qualification", "QUAL-POLY",
        SupplierQualification(
            qualification_id="QUAL-POLY", supplier_id="SUP-POLY",
            material_id="MAT-RESIN-8", status="QUALIFIED",
            effective_date="2024-01-01", expiry_date="2027-01-01",
            site_scope=("SITE-P1",),
        ),
    )
    corpus.put(
        "lot", "LOT-7100",
        Lot("LOT-7100", "SUP-POLY", "MAT-RESIN-8", "PO-9", 50.0,
            supplier_site="SITE-P1", manufactured_at="2026-01-05",
            received_at="2026-02-10"),
    )
    document = (
        b"Certificate of Analysis - Lot LOT-7100\n"
        b"Specification SPEC-V2 Revision A\n"
        + f"melt_index: 5.1 cP (ASTM-D1238, {measured_condition})\n".encode()
    )
    return corpus, "LOT-7100", document


def test_f_equivalence_in_scope_can_carry_the_evidence():
    """The equivalence covers 190C and the test ran at 190C."""
    corpus, lot, document = _viscosity_case(
        equivalence_condition="190C", measured_condition="190C"
    )
    outcome = run(corpus, lot, document)
    assert outcome.disposition == Disposition.RELEASE.value


def test_f_equivalence_out_of_scope_does_not_stretch():
    """The equivalence covers 190C only; the test ran at 230C. No mutation,
    and the lot is NOT called defective for it."""
    corpus, lot, document = _viscosity_case(
        equivalence_condition="190C", measured_condition="230C"
    )
    outcome = run(corpus, lot, document)

    assert outcome.disposition != Disposition.RELEASE.value
    assert corpus.lot(lot).status != "RELEASED"


def test_f_absent_equivalence_is_insufficiency_not_a_defect():
    """No equivalence exists at all for a method difference. Absence of proof
    is never proof of a defect."""
    corpus, lot, document = _viscosity_case(
        equivalence_condition="190C", measured_condition="190C",
        seed_equivalence=False,
    )
    outcome = run(corpus, lot, document)

    assert outcome.disposition != Disposition.RELEASE.value
    assert not outcome.mutation or corpus.lot(lot).status != "RELEASED"


# ==========================================================================
# G — negative control: a fully rule-solvable case
# ==========================================================================


def test_g_a_rule_solvable_case_stays_clean():
    """One revision, method-matched evidence, comfortably in limits.

    No ambiguity to reward an agent for resolving. If this needed judgment,
    the architecture would be manufacturing difficulty rather than handling it.
    """
    corpus = Corpus()
    corpus.put("supplier", "SUP-ONE", Supplier("SUP-ONE", "One"))
    corpus.put("material", "MAT-SIMPLE", Material("MAT-SIMPLE", "Simple"))
    corpus.put(
        "spec_revision", "SPEC-S1:A",
        SpecificationRevision(
            spec_id="SPEC-S1", revision="A", status="ACTIVE",
            effective_date="2020-01-01", effective_basis="date_of_receipt",
            material_scope=("MAT-SIMPLE",),
            requirements=(
                Requirement("REQ-S1", "density", "ISO-1183", "23C",
                            1.0, 2.0, "kg"),
            ),
        ),
    )
    corpus.put(
        "supplier_qualification", "QUAL-ONE",
        SupplierQualification(
            qualification_id="QUAL-ONE", supplier_id="SUP-ONE",
            material_id="MAT-SIMPLE", status="QUALIFIED",
            effective_date="2020-01-01", expiry_date="2030-01-01",
            site_scope=("SITE-1",),
        ),
    )
    corpus.put(
        "lot", "LOT-8000",
        Lot("LOT-8000", "SUP-ONE", "MAT-SIMPLE", "PO-5", 10.0,
            supplier_site="SITE-1", manufactured_at="2026-01-01",
            received_at="2026-01-15"),
    )
    document = (
        b"Certificate of Analysis - Lot LOT-8000\n"
        b"Specification SPEC-S1 Revision A\n"
        b"density: 1.5 kg (ISO-1183, 23C)\n"
    )
    outcome = run(corpus, "LOT-8000", document)

    assert outcome.disposition == Disposition.RELEASE.value
    assert basis_of(outcome) == ("SPEC-S1", "A")


# ==========================================================================
# the cross-cutting invariant
# ==========================================================================


def test_no_perturbation_ever_produces_an_unsafe_release():
    """The one property that may never fail, over the whole matrix.

    An out-of-limit value under the governing revision must never release, in
    any renaming, ordering, or supplier claim.
    """
    for names, claimed, seed in itertools.product(
        RENAMINGS, CLAIMS[:3], range(2)
    ):
        corpus, lot, document = build_case(claimed_spec_text=claimed, **names)
        outcome = run(_shuffled(corpus, seed), lot, document)
        assert outcome.disposition != Disposition.RELEASE.value, (names, claimed)
        assert corpus.lot(lot).status != "RELEASED"
