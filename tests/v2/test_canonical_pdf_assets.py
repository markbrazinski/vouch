"""The canonical supplier PDFs, checked against frozen truth.

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

PDF0 = EVIDENCE / "northern-alloys-coa-lot-1001.pdf"
PDF1 = EVIDENCE / "eastern-metals-coa-lot-1002.pdf"
PDF2 = EVIDENCE / "northern-alloys-coa-batch-wp-26-0317-b.pdf"
PDF3 = EVIDENCE / "central-forgeworks-coa-lot-1004.pdf"
PDF4 = EVIDENCE / "western-polymers-coa-lot-1006.pdf"

#: The exact bytes that were qualified. A changed hash means a new document,
#: and a new document has not been through the pipeline.
SHA256 = {
    PDF0: "765839cc6520c58e454622ee280b5bea2498d24e7629298a26d32a3b10dee181",
    PDF1: "bf3e80258af52dd098bc5a76e18b3603e024c3276bb56bdf9816f64fd5f459be",
    PDF2: "326b4463ab1bf4222ea8466cc0997508a0f5e4bd0bec51180888054cc8721242",
    PDF3: "5cc20bcbf5b74347158a8cef65894e9243ed4809a008f42ef1debf7275d03947",
    PDF4: "e2ea3ff42082fb6eedf49aaa8249cfb316f0c6296eb6bd50df5ad843718087b4",
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
    [
        (PDF0, "LOT-1001"), (PDF1, "LOT-1002"),
        (PDF3, "LOT-1005"), (PDF4, "LOT-1003"),
    ],
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
        (PDF0, "LOT-1001", "MAT-ALLOY-7", "SUP-NORTH", "SITE-N1"),
        (PDF1, "LOT-1002", "MAT-ALLOY-7", "SUP-EAST", "SITE-E1"),
        (PDF3, "LOT-1005", "MAT-ALLOY-7", "SUP-CENTRAL", "SITE-C1"),
        (PDF4, "LOT-1003", "MAT-RESIN-3", "SUP-WEST", "SITE-W1"),
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


def test_pdf2_names_its_own_batch_and_never_a_vouch_lot() -> None:
    """The load-bearing property of the binding case.

    ANY `LOT-####` string on this page binds the certificate immediately and
    the human question is never asked. Two re-renders reintroduced one — the
    document is derived from the LOT-1001 certificate — so this is asserted on
    the pattern, not on one known-bad value.
    """
    text = _text(PDF2)
    assert "WP-26-0317-B" in text, "the supplier's own batch id is the identifier"
    assert re.findall(r"LOT-\d+", text) == [], (
        "this certificate must state no Vouch lot id; printing one binds it "
        "and the identity case cannot run"
    )


def test_pdf2_states_the_governing_revision_and_its_measurements() -> None:
    """Once identity is established the evidence must be BORING.

    512 passes Rev C (>= 480) and hardness 31 is mid-band, so nothing about
    the measurements is in doubt and the refusal has exactly one cause.
    """
    text = _text(PDF2)
    assert "SPEC-A7 Revision C" in text
    assert "512" in text and "31" in text
    assert "CONFORMS" in text
    # Supporting identity that agrees with the receipt on every axis EXCEPT
    # the lot. That agreement is what makes the missing mapping the only
    # open question rather than one of several.
    for supporting in ("SUP-NORTH", "SITE-N1", "MAT-ALLOY-7", "PO-82", "450 kg"):
        assert supporting in text


def test_pdf2_does_not_phrase_conformance_as_a_supplier_assertion() -> None:
    """`supplier: <value>` is an identity pattern.

    "Supplier conformance statement" parses as a SECOND supplier id, which
    turns the document into an IDENTITY_CONFLICT and routes it away from the
    human question entirely.
    """
    assert "Supplier conformance" not in _text(PDF2)


def test_pdf3_states_its_measurement_and_specification() -> None:
    text = _text(PDF3)
    assert "402" in text
    assert "SUP-CENTRAL" in text and "SITE-C1" in text


def test_pdf4_states_both_viscosity_paths_and_neither_precedence() -> None:
    """The disagreement lives in these two lines, and nowhere else.

    The two values point OPPOSITE ways against SPEC-R3:A's [200, 400] cP
    limit — 178 fails it, 312 passes — which is what makes the human question
    load-bearing rather than ceremonial.

    Both results must survive extraction in the parser's own
    "characteristic: value units (method, condition)" shape, and the document
    must NOT resolve the dispute it creates: no equivalence id, no instruction
    about which method wins, nothing that tells an agent what to conclude.
    """
    text = _text(PDF4)

    assert "SPEC-R3 Revision A" in text
    assert "viscosity: 178 cP (ASTM-D2196, 25C)" in text
    assert "viscosity: 312 cP (ASTM-D445, 25C)" in text

    # The document states the requirement it was written against, and the
    # supplier's own conclusion. Both are claims, neither is authority.
    assert "REQ-R3-A-1" in text
    assert "conform to SPEC-R3 Revision A" in text

    # It must not carry the answer. EQV-1 is an internal authoritative object;
    # a supplier document naming it would be asserting its own applicability,
    # which is precisely the question a human is asked to settle.
    assert "EQV-1" not in text
    assert "EQV" not in text.upper().replace("EQUIVALENT", "")
    for forbidden in ("authorize", "release", "quarantine", "override"):
        assert forbidden not in text.lower(), f"PDF 4 must not say {forbidden!r}"


def test_pdf4_yields_exactly_two_applicable_viscosity_claims() -> None:
    """Ordinary extraction, no Textract, both claims distinct."""
    claims, confidence = parse_deterministic(_text(PDF4))
    assert confidence == 1.0

    viscosity = [c for c in claims if c.characteristic == "viscosity"]
    assert len(viscosity) == 2, "the two evidence paths must both survive"

    by_method = {c.method: c for c in viscosity}
    assert by_method["ASTM-D2196"].value == 178.0
    assert by_method["ASTM-D2196"].condition == "25C"
    assert by_method["ASTM-D445"].value == 312.0
    assert by_method["ASTM-D445"].condition == "25C"
    assert all(c.units == "cP" for c in viscosity)

    needed, _ = structure_needed(_text(PDF4), confidence)
    assert needed is False, "PDF 4 must read on the ordinary path"


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


def test_pdf2_reads_perfectly_on_the_ordinary_path() -> None:
    """The document must NOT be hard to read.

    The old PDF 2 was a table that defeated the flat parser, which made its
    refusal look like an extraction problem. This one is the opposite claim:
    both measurements parse at full confidence, so when Vouch still refuses,
    the only remaining explanation is identity.
    """
    text = _text(PDF2)
    claims, confidence = parse_deterministic(text)
    assert confidence == 1.0
    assert {c.characteristic for c in claims} == {"tensile_strength", "hardness"}
    assert [(c.value, c.units, c.method, c.condition) for c in claims] == [
        (512.0, "MPa", "ASTM-E8", "room_temp"),
        (31.0, "HRC", "HRC", "as_received"),
    ]
    needed, _ = structure_needed(text, confidence)
    assert needed is False, "the binding case must not depend on Textract"


def test_no_canonical_document_needs_structure_recovery() -> None:
    """Structure recovery is now unexercised by the canonical set.

    Recorded rather than hidden: the Textract path still has its own fixtures
    under `fixtures/textract/`, but no DEMO document depends on it since the
    binding case replaced the table-based one.
    """
    for path, expected in (
        (PDF0, False), (PDF1, False), (PDF2, False), (PDF3, False), (PDF4, False),
    ):
        text = _text(path)
        _claims, confidence = parse_deterministic(text)
        needed, _ = structure_needed(text, confidence)
        assert needed is expected, f"{path.name}: structure_needed={needed}"


# ==========================================================================
# anti-cross-contamination — the payload lives in exactly one document
# ==========================================================================


@pytest.mark.parametrize("path", [PDF0, PDF1, PDF2, PDF4])
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
