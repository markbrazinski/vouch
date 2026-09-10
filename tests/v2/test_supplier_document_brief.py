"""The canonical supplier/document brief must match the authoritative corpus.

The brief freezes what three synthetic supplier PDFs will contain, and those
PDFs will later be run through the real ingestion pipeline. If the brief drifts
from the corpus, the documents get built against numbers the plant does not
hold, and the demo silently stops proving anything.

So every load-bearing value in the brief is checked against `build_corpus()`
here rather than trusted to have been transcribed correctly.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from vouch.v2.fixtures import COA_CLEAN, COA_HERO, COA_HOSTILE, build_corpus

ROOT = Path(__file__).resolve().parents[2]
BRIEF = ROOT / "contracts" / "demo" / "VOUCH_V2_CANONICAL_SUPPLIER_DOCUMENT_BRIEF.md"


@pytest.fixture(scope="module")
def brief() -> str:
    assert BRIEF.exists(), "the canonical supplier document brief is missing"
    return BRIEF.read_text()


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


def test_supplier_identities_match_the_corpus(brief, corpus) -> None:
    for supplier_id, name in [
        ("SUP-NORTH", "Northern Alloys"),
        ("SUP-EAST", "Eastern Metals"),
        ("SUP-WEST", "Western Polymers"),
        ("SUP-CENTRAL", "Central Forgeworks"),
    ]:
        assert corpus.get("supplier", supplier_id).name == name
        assert supplier_id in brief and name in brief


def test_every_documented_lot_matches_the_corpus(brief, corpus) -> None:
    """Supplier, site, material, quantity and PO for the three demo lots."""
    for lot_id, supplier_id, site, material_id, quantity, po in [
        ("LOT-1002", "SUP-EAST", "SITE-E1", "MAT-ALLOY-7", 400.0, "PO-78"),   # PDF 1
        ("LOT-1001", "SUP-NORTH", "SITE-N1", "MAT-ALLOY-7", 500.0, "PO-77"),  # PDF 2
        ("LOT-1005", "SUP-CENTRAL", "SITE-C1", "MAT-ALLOY-7", 200.0, "PO-80"),  # PDF 3
    ]:
        lot = corpus.lot(lot_id)
        assert lot.supplier_id == supplier_id
        assert lot.supplier_site == site
        assert lot.material_id == material_id
        assert lot.quantity == quantity
        assert lot.po_reference == po
        # And the brief states the same lot and quantity.
        assert lot_id in brief
        assert f"{int(quantity)} kg" in brief


def test_governing_thresholds_are_stated_correctly(brief, corpus) -> None:
    """Rev B >= 450 and Rev C >= 480 are what make Hero A a real decision."""
    rev_b = corpus.get("spec_revision", "SPEC-A7:B")
    rev_c = corpus.get("spec_revision", "SPEC-A7:C")

    tensile_b = next(r for r in rev_b.requirements if r.characteristic == "tensile_strength")
    tensile_c = next(r for r in rev_c.requirements if r.characteristic == "tensile_strength")
    assert tensile_b.min_value == 450.0
    assert tensile_c.min_value == 480.0
    assert rev_b.status == "SUPERSEDED" and rev_b.superseded_by == "C"
    assert rev_c.status == "ACTIVE"
    # Receipt date decides which revision governs.
    assert rev_c.effective_basis == "date_of_receipt"

    assert "450.0" in brief and "480.0" in brief
    assert "date_of_receipt" in brief


def test_pdf1_measurement_still_splits_the_two_revisions(brief) -> None:
    """462 MPa must pass the cited revision and fail the governing one.

    This is the entire Hero A premise. If a future edit moves the value or a
    threshold so the two revisions agree, the demo loses its subject.
    """
    assert b"462" in COA_HERO
    assert b"Revision B" in COA_HERO
    assert 450.0 <= 462.0 < 480.0
    assert "462" in brief


def test_pdf2_measurement_passes_the_governing_revision(brief) -> None:
    """512 MPa is a clean release under Rev C, so PDF 2 stays uncontroversial."""
    assert b"512" in COA_CLEAN
    assert b"Revision C" in COA_CLEAN
    assert 512.0 >= 480.0
    assert "512" in brief


def test_hostile_payload_is_described_and_still_hostile(brief) -> None:
    hostile = COA_HOSTILE.decode()
    for marker in ("IGNORE ALL PREVIOUS INSTRUCTIONS", "release_lot", "Revision B"):
        assert marker in hostile
    assert "402" in brief and b"402" in COA_HOSTILE
    # The brief must say the payload has to be real extractable text.
    assert "selectable document text" in brief or "extractable text" in brief


def test_brief_uses_only_synthetic_identities(brief) -> None:
    """The mockup-era supplier names must never reach the document contract."""
    for invented in ("Meridian", "Halden", "Kessler", "Baumann", "Orica"):
        assert invented not in brief


def test_brief_carries_no_account_targeting_information(brief) -> None:
    assert not re.search(r"\b\d{12}\b", brief)


def test_brief_forbids_encoding_the_outcome(brief) -> None:
    """A document states a claim; Vouch decides. The brief must say so."""
    assert "outcome-neutral" in brief.lower() or "Outcome-neutrality" in brief
    assert "QUARANTINE" in brief  # named only as a thing documents must NOT say
