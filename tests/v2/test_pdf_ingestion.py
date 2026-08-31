"""P0-8 — PDF ingestion through a real parser.

The audit found PDF handling implemented as `bytes.decode("utf-8")`, which for
a real PDF yields mojibake or nothing. Every test here uses ACTUAL PDF bytes.

`make_pdf` writes a genuinely valid PDF (xref table, page tree, content
streams) rather than adding a writer dependency for tests. If pypdf can read
it, it is a PDF.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import ArtifactStatus, ExtractionMethod
from vouch.v2.evidence import (
    PdfExtractionError,
    extract_pdf_text,
    parse_deterministic,
    text_for_content_type,
)
from vouch.v2.fixtures import build_corpus
from vouch.v2.lifecycle import EventLog, EventType
from vouch.v2.workflow import VouchV2


def make_pdf(pages: list[str]) -> bytes:
    """Build a valid multi-page PDF whose pages carry the given text lines."""

    def esc(text: str) -> str:
        return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    objects: dict[int, bytes] = {}
    count = len(pages)
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(count))
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Count {count} /Kids [{kids}] >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"

    for index, text in enumerate(pages):
        parts = ["BT", "/F1 11 Tf", "50 750 Td", "14 TL"]
        for line in text.splitlines() or [""]:
            parts.extend([f"({esc(line)}) Tj", "T*"])
        parts.append("ET")
        stream = "\n".join(parts).encode()
        content_num, page_num = 4 + 2 * index + 1, 4 + 2 * index
        objects[content_num] = (
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )
        objects[page_num] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>"
        ).encode()

    out = bytearray(b"%PDF-1.4\n")
    offsets: dict[int, int] = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"

    xref_at = len(out)
    highest = max(objects)
    out += f"xref\n0 {highest + 1}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, highest + 1):
        out += f"{offsets.get(num, 0):010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


COA_PDF = make_pdf(
    [
        "Certificate of Analysis - Lot LOT-1001\nSpecification SPEC-A7 Revision C",
        "tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
        "hardness: 31 HRC (HRC, as_received)",
    ]
)

WRONG_LOT_PDF = make_pdf(
    [
        "Certificate of Analysis - Lot LOT-9999\nSpecification SPEC-A7 Revision C",
        "tensile_strength: 512 MPa (ASTM-E8, room_temp)\n"
        "hardness: 31 HRC (HRC, as_received)",
    ]
)

#: A PDF with no extractable text — the scanned-document case.
IMAGE_ONLY_PDF = make_pdf(["", ""])


@pytest.fixture
def vouch():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


# ==========================================================================
# the parser itself
# ==========================================================================


def test_fixture_is_a_real_pdf_that_needs_a_real_parser():
    """The fixture is a structured PDF container, not text with a .pdf label.

    Note the generator writes UNCOMPRESSED content streams, so raw bytes happen
    to contain the literal text. What a utf-8 decode cannot do is recover the
    document STRUCTURE: page boundaries, reading order, and which page a value
    sits on. Those are what the locators depend on, and they come only from
    parsing the container.
    """
    assert COA_PDF.startswith(b"%PDF-")
    assert b"/Type /Page" in COA_PDF and b"xref" in COA_PDF

    naive = COA_PDF.decode("utf-8", errors="replace")
    assert "[[page:" not in naive  # no page structure recoverable by decoding

    claims_from_decode, _ = parse_deterministic(naive)
    parsed_text, _, _ = extract_pdf_text(COA_PDF)
    claims_from_parser, _ = parse_deterministic(parsed_text)

    # Only the parsed path yields page-bound claims.
    assert all(c.locator.startswith("page:") for c in claims_from_parser)
    assert not any(c.locator.startswith("page:") for c in claims_from_decode)


def test_real_pdf_yields_text_and_page_locators():
    text, per_page, confidence = extract_pdf_text(COA_PDF)
    assert "tensile_strength: 512 MPa" in text
    assert len(per_page) == 2
    assert confidence == 1.0
    assert "[[page:1]]" in text and "[[page:2]]" in text


def test_claims_carry_page_locators():
    """P0-8 requires a page/coordinate-equivalent source locator."""
    text, _, _ = extract_pdf_text(COA_PDF)
    claims, _ = parse_deterministic(text)
    assert {c.characteristic for c in claims} == {"tensile_strength", "hardness"}
    assert all(c.locator.startswith("page:") for c in claims)
    tensile = next(c for c in claims if c.characteristic == "tensile_strength")
    assert tensile.locator.startswith("page:2/")
    assert tensile.value == 512.0


def test_image_only_pdf_reports_low_confidence():
    """A scanned PDF must not silently look like a document with no findings."""
    _, _, confidence = extract_pdf_text(IMAGE_ONLY_PDF)
    assert confidence == 0.0


def test_malformed_pdf_raises_rather_than_decoding():
    with pytest.raises(PdfExtractionError):
        extract_pdf_text(b"%PDF-1.4\nthis is not really a pdf")


def test_unknown_content_type_is_not_forced_through_utf8():
    text, confidence = text_for_content_type(b"\x00\x01\x02", "application/octet-stream")
    assert text == ""
    assert confidence == 0.0


def test_page_bound_is_enforced():
    """A hostile PDF must not be able to exhaust the parser."""
    from vouch.v2.evidence import MAX_PDF_PAGES

    big = make_pdf([f"page {i}" for i in range(MAX_PDF_PAGES + 10)])
    _, per_page, _ = extract_pdf_text(big)
    assert len(per_page) == MAX_PDF_PAGES


# ==========================================================================
# through the real ingestion path
# ==========================================================================


def test_pdf_coa_releases_through_the_full_pipeline(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": COA_PDF, "content_type": "application/pdf"}],
    )
    assert outcome.disposition == "RELEASE"
    assert corpus.lot("LOT-1001").status == "RELEASED"

    per_claim = outcome.record.extraction.per_claim
    assert per_claim
    assert all(v["locator"].startswith("page:") for v in per_claim.values())
    assert all(
        v["method"] == ExtractionMethod.DETERMINISTIC_PARSER.value
        for v in per_claim.values()
    )


def test_pdf_identity_binding_is_enforced(vouch):
    """P0-4 holds for PDFs, not only for plain text."""
    corpus, v = vouch
    outcome = v.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": WRONG_LOT_PDF, "content_type": "application/pdf"}],
    )
    assert outcome.failure_category == "EVIDENCE_BINDING_MISMATCH"
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"


def test_unreadable_pdf_routes_to_human_not_to_a_disposition(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": b"%PDF-1.4\nbroken", "content_type": "application/pdf"}],
    )
    assert outcome.failure_category == "EXTRACTION_LOW_CONFIDENCE"
    assert outcome.disposition == ""
    assert outcome.quality_decision_required
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"


def test_low_confidence_flag_is_truthful(vouch):
    """P0-8: `low_confidence_routed_to_human` must reflect what happened."""
    corpus, v = vouch
    outcome = v.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": IMAGE_ONLY_PDF, "content_type": "application/pdf"}],
    )
    assert outcome.record.extraction.low_confidence_routed_to_human is True
    assert not outcome.mutated

    clean = VouchV2(build_corpus())
    good = clean.evaluate_lot(
        "LOT-1001", documents=[{"raw": COA_PDF, "content_type": "application/pdf"}]
    )
    assert good.record.extraction.low_confidence_routed_to_human is False


def test_extraction_event_reports_confidence(vouch):
    corpus, v = vouch
    events = EventLog()
    v.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": COA_PDF, "content_type": "application/pdf"}],
        events=events,
    )
    extracted = events.of_type(EventType.EVIDENCE_EXTRACTED)
    assert extracted
    assert extracted[0].payload["method"] == "DETERMINISTIC_PARSER"
    assert extracted[0].payload["low_confidence"] is False
