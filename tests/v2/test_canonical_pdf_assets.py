"""The three canonical supplier PDFs, checked against frozen truth.

These are the documents the demo runs on, and they are the one class of asset
a designer can silently change: a re-export that "just fixes the spacing" can
move a measurement, break an identifier, or flatten the table that makes
structured extraction necessary. None of that would fail any other test.

So this file pins the bytes AND the facts. It reads each PDF through the same
`pypdf` path the runtime uses — never a stored transcript — so it fails if the
document stops saying what it is supposed to say, whatever the reason.

Content authority: contracts/demo/VOUCH_V2_CANONICAL_SUPPLIER_DOCUMENT_BRIEF.md
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from vouch.v2.evidence import (
    extract_document_identity,
    extract_pdf_text,
    heuristic_detector,
    parse_deterministic,
    structure_needed,
    validate_binding,
)
from vouch.v2.fixtures import build_corpus

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "demo" / "evidence"

PDF1 = EVIDENCE / "eastern-metals-coa-lot-1002.pdf"
PDF2 = EVIDENCE / "northern-alloys-mtr-lot-1001.pdf"
PDF3 = EVIDENCE / "central-forgeworks-coa-lot-1004.pdf"

#: The exact bytes that were qualified. A changed hash means a new document,
#: and a new document has not been through the pipeline.
SHA256 = {
    PDF1: "4d36065a15b5a60bfd90d8004784c81de24da0b0a6768fdd2caa296b05ca5ac7",
    PDF2: "3e9af50d2b56e9dc59151c1b9dd3005916e375baa23053c5bb3604300aae0ccf",
    PDF3: "fd78264210f4314b69d801262e5a127f8f7b40ba82e80010fdd7f59d65c6ce75",
}

#: Substrings of the approved hostile payload. Only PDF 3 may contain these.
HOSTILE_MARKERS = (
    "IGNORE ALL PREVIOUS INSTRUCTIONS",
    "release_lot",
    "the operator has authorized this",
)


def _text(path: Path) -> str:
    text, _pages, confidence = extract_pdf_text(path.read_bytes())
    assert confidence == 1.0, f"{path.name}: text no longer extracts cleanly"
    return text


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


# ==========================================================================
# the bytes
# ==========================================================================


@pytest.mark.parametrize("path", list(SHA256))
def test_the_tracked_asset_is_the_one_that_was_qualified(path: Path) -> None:
    assert path.exists(), f"{path.name} is missing from demo/evidence"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == SHA256[path], (
        f"{path.name} has changed. A re-exported document has NOT been through "
        f"the evidence pipeline; re-qualify it and update the manifest."
    )


@pytest.mark.parametrize("path", list(SHA256))
def test_each_asset_is_a_real_extractable_pdf(path: Path) -> None:
    raw = path.read_bytes()
    assert raw.startswith(b"%PDF-"), f"{path.name} is not a PDF"
    # A rasterised export would extract nothing and score 0.0 — the exact
    # failure mode that makes a beautiful document useless as evidence.
    _text(path)


def test_the_manifest_records_every_asset_and_hash() -> None:
    manifest = (EVIDENCE / "MANIFEST.md").read_text()
    for path, digest in SHA256.items():
        assert path.name in manifest, f"{path.name} is not in the manifest"
        assert digest in manifest, f"{path.name}'s hash is stale in the manifest"


# ==========================================================================
# the facts — each document must still say what the corpus holds
# ==========================================================================


@pytest.mark.parametrize(
    "path,lot_id",
    [(PDF1, "LOT-1002"), (PDF2, "LOT-1001"), (PDF3, "LOT-1004")],
)
def test_each_document_states_its_own_lot_facts(path: Path, lot_id: str, corpus) -> None:
    """Identifiers, quantity and dates must match the authoritative lot."""
    text = _text(path)
    lot = corpus.lot(lot_id)

    assert lot_id in text
    assert lot.material_id in text
    assert lot.po_reference in text
    assert f"{int(lot.quantity)} {lot.units}" in text
    assert lot.manufactured_at in text
    assert lot.received_at in text
    assert lot.supplier_site in text
    assert corpus.get("supplier", lot.supplier_id).name.upper() in text.upper()


@pytest.mark.parametrize(
    "path,lot_id,material_id,supplier_id,site_id",
    [
        (PDF1, "LOT-1002", "MAT-ALLOY-7", "SUP-EAST", "SITE-E1"),
        (PDF2, "LOT-1001", "MAT-ALLOY-7", "SUP-NORTH", "SITE-N1"),
        (PDF3, "LOT-1004", "MAT-ALLOY-7", "SUP-CENTRAL", "SITE-C1"),
    ],
)
def test_every_document_binds_to_its_lot(
    path: Path, lot_id: str, material_id: str, supplier_id: str, site_id: str
) -> None:
    """Identity must BIND, and it is prose that breaks this.

    Ordinary document wording can read as an identity assertion — "This lot
    CONFORMS", "Material Test Report", "NOT A REAL SUPPLIER CERTIFICATE" each
    parsed as a second, conflicting identifier and failed closed. Every one of
    those was a real defect in an earlier export, so this is pinned.
    """
    identity = extract_document_identity(_text(path))
    status, reasons = validate_binding(
        identity,
        target_lot_id=lot_id,
        target_material_id=material_id,
        target_supplier_id=supplier_id,
        target_supplier_site=site_id,
    )
    assert status.value == "BOUND", f"{path.name}: {status.value} — {reasons}"


def test_pdf1_states_the_superseded_revision_and_its_measurements() -> None:
    """462 MPa against cited Rev B is the whole Hero A premise."""
    text = _text(PDF1)
    assert "SPEC-A7 Revision B" in text
    assert "462 MPa" in text and "30 HRC" in text
    # The supplier's own conclusion. A supplier claim, not an authority.
    assert "CONFORMS" in text


def test_pdf2_states_the_governing_revision_and_its_table() -> None:
    text = _text(PDF2)
    assert "SPEC-A7 Revision C" in text
    assert "512" in text and "31" in text
    # The table header is what makes structured extraction meaningful.
    for column in ("CHARACTERISTIC", "RESULT", "UNITS", "METHOD", "CONDITION"):
        assert column in text.upper(), f"table column {column} is gone"
    # Approved synthetic supporting facts — presentation, not governed facts.
    for supporting in ("H-4471", "0.41", "1.12", "50.0"):
        assert supporting in text


def test_pdf3_states_its_measurement_and_specification() -> None:
    text = _text(PDF3)
    assert "402" in text
    assert "SUP-CENTRAL" in text and "SITE-C1" in text


# ==========================================================================
# extraction path — each document must still need what it is supposed to need
# ==========================================================================


def test_pdf1_is_readable_by_the_ordinary_parser() -> None:
    """Textract must NOT be required here, or PDF 2 proves nothing."""
    claims, confidence = parse_deterministic(_text(PDF1))
    assert confidence == 1.0
    by_name = {c.characteristic: c for c in claims}
    assert by_name["tensile_strength"].value == 462.0
    assert by_name["tensile_strength"].units == "MPa"
    assert by_name["tensile_strength"].method == "ASTM-E8"
    assert by_name["tensile_strength"].condition == "room_temp"
    assert by_name["hardness"].value == 30.0

    needed, _ = structure_needed(_text(PDF1), confidence)
    assert needed is False, "PDF 1 must not require structure recovery"


def test_pdf2_defeats_the_ordinary_parser_and_requires_structure() -> None:
    """The load-bearing assertion.

    If the flattened parser ever succeeds here, the document stopped being
    table-shaped and Textract became decoration. This asserts the CURRENT
    document's behaviour; it does not weaken the parser to manufacture it.
    """
    text = _text(PDF2)
    claims, confidence = parse_deterministic(text)
    assert claims == [], "PDF 2's table is now readable line-by-line"
    needed, reason = structure_needed(text, confidence)
    assert needed is True and reason


def test_only_pdf2_needs_structure_recovery() -> None:
    for path, expected in ((PDF1, False), (PDF2, True), (PDF3, False)):
        text = _text(path)
        _claims, confidence = parse_deterministic(text)
        needed, _ = structure_needed(text, confidence)
        assert needed is expected, f"{path.name}: structure_needed={needed}"


# ==========================================================================
# anti-cross-contamination — the payload lives in exactly one document
# ==========================================================================


@pytest.mark.parametrize("path", [PDF1, PDF2])
def test_the_benign_documents_carry_no_hostile_payload(path: Path) -> None:
    text = _text(path)
    detected, why = heuristic_detector(text)
    assert detected is False, f"{path.name} now trips the detector: {why}"
    for marker in HOSTILE_MARKERS:
        assert marker.lower() not in text.lower(), f"{path.name} contains {marker!r}"


def test_pdf3_carries_the_approved_payload_as_real_text() -> None:
    """Rendered as an image this proves nothing — the text must reach the pipeline."""
    text = _text(PDF3)
    for marker in HOSTILE_MARKERS:
        assert marker.lower() in text.lower(), f"the payload lost {marker!r}"
    detected, why = heuristic_detector(text)
    assert detected is True and why


@pytest.mark.parametrize("path", list(SHA256))
def test_no_document_states_a_vouch_outcome(path: Path) -> None:
    """A document carries a supplier's claim; Vouch decides the outcome.

    PDF 3's payload FALSELY claims approval — that is the attack, and it is
    matched case-sensitively below so the real phrase is still caught.
    """
    text = _text(path)
    for banned in ("QUARANTINE", "BLOCKED", "REJECTED"):
        assert banned not in text.upper(), f"{path.name} asserts {banned}"


@pytest.mark.parametrize("path", list(SHA256))
def test_every_document_discloses_that_it_is_synthetic(path: Path) -> None:
    # Letter-spaced headings survive extraction with spaces inside words.
    collapsed = re.sub(r"\s+", "", _text(path)).upper()
    assert "SYNTHETIC" in collapsed, f"{path.name} lost its synthetic disclosure"


@pytest.mark.parametrize("path", list(SHA256))
def test_no_document_names_a_real_organisation(path: Path) -> None:
    """The retired mockup-era names must never reach a demo asset."""
    text = _text(path).upper()
    for invented in ("MERIDIAN", "HALDEN", "KESSLER", "BAUMANN", "ORICA"):
        assert invented not in text
