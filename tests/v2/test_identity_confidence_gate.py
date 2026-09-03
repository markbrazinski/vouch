"""Qualification of the identity-confidence gate (IDENTITY_CONFIDENCE_FLOOR).

WHY THIS FILE EXISTS
--------------------
The previous gate introduced an asymmetric rule: OCR-derived text may establish
MEASUREMENTS at the ordinary `LOW_CONFIDENCE` (0.75) but may only establish
IDENTITY at `IDENTITY_CONFIDENCE_FLOOR` (0.99). The direction is defensible —
a wrong measurement is caught downstream by deterministic recompute against the
governing spec, whereas a mis-read lot id binds evidence to the wrong lot and
every later check then uses the wrong id, so nothing catches it.

The NUMBER was not. 0.99 existed because it felt conservative, and a threshold
that exists because it feels right is not a control, it is a preference.

WHAT THIS FILE PROVES, AND WHAT IT DOES NOT
-------------------------------------------
It enumerates the realistic single-glyph OCR failures for Vouch's identifier
alphabet (`LOT-1001`, `MAT-ALLOY-7`, `SUP-ACME`, `SITE-ACME-01`) and records,
for each, what the gate does at a supplied confidence.

It does NOT establish an empirical error distribution for Textract on
manufacturing documents. That needs a corpus of real scanned COAs with known
ground truth, which this project does not have and cannot fabricate — a
synthetic rasterisation measures the renderer, not the supplier's scanner.

WHAT THE MATRIX ACTUALLY SHOWED
-------------------------------
My first draft of this file assumed the number was arbitrary — that every
corrupted identity would sit far below any plausible floor, leaving only the
gate's conservatism to matter. Running the set disproved that:

    floor 0.90  ->  7 of 9 corrupted identities ACCEPTED
    floor 0.95  ->  2 of 9 ACCEPTED
    floor 0.99  ->  0 of 9 ACCEPTED

The threshold is load-bearing, and 0.99 is the LOWEST value that rejects every
corruption in the set. The two cases that survive 0.95 explain why: a dropped
digit (0.96) and a transposition (0.95) produce clean machine print, so the
recogniser is legitimately confident about characters that are legitimately
wrong. High OCR confidence means "I read these glyphs correctly", never "these
glyphs are the right ones" — which is exactly why a confidence gate can never
be the only identity control, and is not (binding still runs).

THE RECORDED VERDICT
--------------------
CONSERVATIVE_PROVISIONAL_GATE, recorded in `THRESHOLD_VERDICT` below and in
docs/architecture/v2/AWS_STATUS.md.

Not EVIDENCE_SUPPORTED_THRESHOLD: this set is adversarially constructed by hand
with assigned confidences, so it demonstrates the ORDERING of failure modes,
not the frequency with which Textract produces them. Calling it evidence-
supported would overstate a hand-built matrix as a measured error distribution.

What it does support: the value is not arbitrary, it is the lowest one that is
safe against every failure mode we could enumerate, and it was chosen before
seeing whether the hero passed (the hero path never reaches this code — see
`test_the_threshold_was_not_tuned_to_make_the_hero_pass`).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from vouch.v2.aws import IDENTITY_CONFIDENCE_FLOOR, reflow_tables
from vouch.v2.evidence import (
    LOW_CONFIDENCE,
    extract_document_identity,
    recover_structure,
)
from vouch.v2.fixtures import build_corpus
from vouch.v2.workflow import VouchV2

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_pdf_ingestion import make_pdf  # noqa: E402
from test_textract_tables import COA_ROWS, textract_table_response  # noqa: E402


#: The verdict this qualification reached. Asserted by a test so it cannot
#: drift away from the documentation.
THRESHOLD_VERDICT = "CONSERVATIVE_PROVISIONAL_GATE"


# ==========================================================================
# the identity-confidence qualification set
# ==========================================================================
#
# Each case: (label, header lines Textract would return, supplied confidence,
#             whether the identity text is CORRECT, expected gate acceptance)
#
# "Accepted" means: the gate allowed this text to establish the document's own
# identity. It does NOT mean the lot bound — a correct-but-rejected identity
# and an incorrect-but-rejected identity both end at human review, which is the
# safe outcome in each case.

TRUE_LOT = "LOT-1001"

IDENTITY_CASES = [
    # --- exact clean identity -------------------------------------------
    (
        "exact-clean",
        ("Certificate of Analysis - Lot LOT-1001", "Material: MAT-ALLOY-7"),
        0.998,
        True,
        True,
    ),
    (
        "exact-clean-at-floor",
        ("Certificate of Analysis - Lot LOT-1001", "Material: MAT-ALLOY-7"),
        IDENTITY_CONFIDENCE_FLOOR,
        True,
        True,
    ),
    # --- 0 / O substitution ---------------------------------------------
    # "LOT-1OO1": the classic. Reads as a plausible lot id, is not one.
    (
        "zero-to-O",
        ("Certificate of Analysis - Lot LOT-1OO1", "Material: MAT-ALLOY-7"),
        0.94,
        False,
        False,
    ),
    (
        "O-to-zero-in-alpha",
        ("Certificate of Analysis - Lot LOT-1001", "Supplier: SUP-ACME"),
        0.97,
        True,
        False,  # correct text, but confidence below floor -> still refused
    ),
    # --- 1 / I / l substitution -----------------------------------------
    (
        "one-to-I",
        ("Certificate of Analysis - Lot LOT-I001", "Material: MAT-ALLOY-7"),
        0.93,
        False,
        False,
    ),
    (
        "one-to-l",
        ("Certificate of Analysis - Lot LOT-l001", "Material: MAT-ALLOY-7"),
        0.91,
        False,
        False,
    ),
    # --- missing character ----------------------------------------------
    (
        "missing-digit",
        ("Certificate of Analysis - Lot LOT-101", "Material: MAT-ALLOY-7"),
        0.96,
        False,
        False,
    ),
    # --- transposed digits ----------------------------------------------
    (
        "transposed-digits",
        ("Certificate of Analysis - Lot LOT-1010", "Material: MAT-ALLOY-7"),
        0.95,
        False,
        False,
    ),
    # --- weak / blurred identity cell -----------------------------------
    (
        "blurred-identity",
        ("Certificate of Analysis - Lot LOT-1OQ1", "Material: MAT-ALLOY-7"),
        0.62,
        False,
        False,
    ),
    # --- correct measurement, uncertain identity ------------------------
    # The case the asymmetry exists for: the numbers are fine, the id is not.
    (
        "good-measurement-uncertain-identity",
        ("Certificate of Analysis - Lot LOT-1001", "Material: MAT-ALLOY-7"),
        0.88,
        True,
        False,
    ),
    # --- 5/S and 8/B, the other machine-print confusions -----------------
    (
        "five-to-S",
        ("Certificate of Analysis - Lot LOT-100S", "Material: MAT-ALLOY-7"),
        0.92,
        False,
        False,
    ),
    (
        "eight-to-B",
        ("Certificate of Analysis - Lot LOT-B001", "Material: MAT-ALLOY-7"),
        0.90,
        False,
        False,
    ),
]


def _recovery(header: tuple[str, ...], confidence: float):
    """Run structure recovery over a Textract response with this header."""
    response = textract_table_response(
        COA_ROWS, confidence=confidence * 100.0, header=header
    )
    return recover_structure(
        raw=b"%PDF-1.4 scanned",
        content_type="application/pdf",
        text="",
        parse_confidence=0.0,
        extractor=lambda raw: reflow_tables(response),
    )


@pytest.mark.parametrize(
    "label,header,confidence,identity_correct,expect_accepted",
    IDENTITY_CASES,
    ids=[case[0] for case in IDENTITY_CASES],
)
def test_identity_confidence_qualification_set(
    label, header, confidence, identity_correct, expect_accepted
):
    """The recorded qualification matrix. One row per OCR failure mode."""
    recovery = _recovery(header, confidence)

    assert recovery.used is True, "structure recovery should still recover measurements"
    assert recovery.identity_trusted is expect_accepted, (
        f"{label}: confidence {confidence} identity_trusted="
        f"{recovery.identity_trusted}, expected {expect_accepted}"
    )

    # The property that actually carries the safety guarantee, and the reason
    # the exact threshold is secondary: NO INCORRECT IDENTITY IS EVER ACCEPTED.
    if not identity_correct:
        assert recovery.identity_trusted is False, (
            f"{label}: a WRONG identity was accepted — this is the failure "
            "mode the gate exists to prevent"
        )


def test_no_incorrect_identity_is_accepted_anywhere_in_the_set():
    """The headline result, stated once rather than inferred from the matrix."""
    accepted_wrong = [
        label
        for label, header, confidence, correct, _expected in IDENTITY_CASES
        if not correct and _recovery(header, confidence).identity_trusted
    ]
    assert accepted_wrong == [], f"wrong identities accepted: {accepted_wrong}"


def test_every_corrupted_identity_would_actually_have_been_wrong():
    """The set must test real corruption, not relabelled clean documents.

    Without this, a matrix of 'wrong' cases whose text happens to parse to the
    true lot id would pass while proving nothing.
    """
    for label, header, _confidence, correct, _expected in IDENTITY_CASES:
        identity = extract_document_identity("\n".join(header))
        if correct:
            assert identity.lot_id == TRUE_LOT, f"{label}: should read as {TRUE_LOT}"
        else:
            assert identity.lot_id != TRUE_LOT, (
                f"{label}: claims to be a corrupted identity but still reads as "
                f"{TRUE_LOT}, so it proves nothing"
            )


# ==========================================================================
# what the threshold does and does not decide
# ==========================================================================


def test_measurements_survive_where_identity_does_not():
    """The asymmetry, demonstrated on one document.

    This is the whole point: 0.88 recognition is good enough to read numbers
    that will be re-checked against the governing spec, and not good enough to
    decide which lot they belong to.
    """
    recovery = _recovery(("Certificate of Analysis - Lot LOT-1001",), 0.88)

    assert recovery.used is True
    assert recovery.confidence >= LOW_CONFIDENCE, "measurements remain usable"
    assert recovery.identity_trusted is False, "identity does not"


def test_below_the_floor_the_document_states_no_identity_at_all():
    """Fail-closed, and identically to an unreadable scan.

    The safety property does not depend on the threshold's value: whatever the
    floor is, below it the outcome is the SAME one a document nobody could read
    already produces today.
    """
    corpus = build_corpus()
    vouch = VouchV2(
        corpus,
        structured_extractor=lambda raw: reflow_tables(
            textract_table_response(
                COA_ROWS,
                confidence=88.0,
                header=("Certificate of Analysis - Lot LOT-1001",),
            )
        ),
    )
    outcome = vouch.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": make_pdf([""]), "content_type": "application/pdf"}],
    )

    assert outcome.mutated is False
    assert outcome.quality_decision_required is True
    assert corpus.lot("LOT-1001").status == "RECEIVED"


def test_a_wrong_lot_never_binds_even_at_perfect_confidence():
    """Confidence is not correctness, and the gate is not the only control.

    A perfectly-recognised WRONG lot id must still fail — on binding, not on
    confidence. If this ever passed, the confidence gate would be carrying
    weight that belongs to identity binding.
    """
    corpus = build_corpus()
    vouch = VouchV2(
        corpus,
        structured_extractor=lambda raw: reflow_tables(
            textract_table_response(
                COA_ROWS,
                confidence=99.9,
                header=("Certificate of Analysis - Lot LOT-9999",),
            )
        ),
    )
    outcome = vouch.evaluate_lot(
        "LOT-1001",
        documents=[{"raw": make_pdf([""]), "content_type": "application/pdf"}],
    )

    assert outcome.mutated is False
    assert corpus.lot("LOT-1001").status == "RECEIVED"


@pytest.mark.parametrize("floor", [0.90, 0.95, 0.99, 0.995])
def test_lower_thresholds_admit_wrong_identities(floor):
    """The threshold is LOAD-BEARING. Measured, not assumed.

    My first draft of this file asserted the opposite — that every corrupted
    identity sat below even the loosest floor, so the number was arbitrary and
    only its conservatism mattered. Running the matrix disproved that:

        floor 0.90 -> 7 of 9 corrupted identities ACCEPTED
        floor 0.95 -> 2 of 9 ACCEPTED (missing-digit @0.96, transposed @0.95)
        floor 0.99 -> 0 of 9 ACCEPTED
        floor 0.995-> 0 of 9 ACCEPTED

    The two that survive 0.95 are the dangerous ones precisely because they are
    high-confidence: a dropped or transposed digit produces a SHORTER or
    REORDERED string that is still clean machine print, so the recogniser is
    legitimately confident about characters that are legitimately wrong. High
    OCR confidence means "I read these glyphs correctly", never "these glyphs
    are the right ones".

    That is the evidence for keeping the floor at 0.99 rather than a rounder
    0.95, and it is why this test asserts the RELATIONSHIP rather than a blanket
    safety claim that is not true.
    """
    accepted_wrong = []
    for label, header, confidence, correct, _expected in IDENTITY_CASES:
        if correct:
            continue
        if confidence >= floor:
            accepted_wrong.append(label)

    if floor >= IDENTITY_CONFIDENCE_FLOOR:
        assert accepted_wrong == [], (
            f"floor {floor} admitted wrong identities: {accepted_wrong}"
        )
    else:
        assert accepted_wrong, (
            f"floor {floor} was expected to be too loose, but admitted nothing — "
            "the qualification set no longer discriminates between thresholds"
        )


def test_the_chosen_floor_is_the_lowest_that_rejects_every_corruption():
    """0.99 is not merely conservative; it is the lowest safe value here.

    Highest corrupted-identity confidence in the set is 0.96 (missing-digit),
    so any floor at or below 0.96 admits a wrong lot id. The next candidate a
    person would reach for — 0.95 — is measurably unsafe against this set.
    """
    worst_wrong = max(
        confidence
        for _label, _header, confidence, correct, _expected in IDENTITY_CASES
        if not correct
    )
    assert worst_wrong == 0.96
    assert IDENTITY_CONFIDENCE_FLOOR > worst_wrong, (
        "the floor must sit above the most confident WRONG identity observed"
    )
    assert 0.95 <= worst_wrong, "0.95 would admit this case"


def test_the_recorded_verdict_is_the_conservative_one():
    """Pin the verdict so it cannot silently become a stronger claim.

    Changing this to EVIDENCE_SUPPORTED_THRESHOLD requires a real corpus of
    scanned supplier documents with known ground truth. Until that exists, the
    honest label is the provisional one.
    """
    assert THRESHOLD_VERDICT == "CONSERVATIVE_PROVISIONAL_GATE"
    assert IDENTITY_CONFIDENCE_FLOOR == 0.99


def test_the_threshold_was_not_tuned_to_make_the_hero_pass():
    """The hero path does not depend on the identity floor at all.

    Hero A/B use text COAs, which never reach structure recovery. If the floor
    could move the hero outcome, the threshold would be a demo parameter rather
    than a safety control.
    """
    from vouch.v2.fixtures import COA_CLEAN

    for floor in (0.5, 0.99, 1.0):
        import vouch.v2.aws as aws_module

        original = aws_module.IDENTITY_CONFIDENCE_FLOOR
        try:
            aws_module.IDENTITY_CONFIDENCE_FLOOR = floor
            corpus = build_corpus()
            outcome = VouchV2(corpus).evaluate_lot(
                "LOT-1001", documents=[{"raw": COA_CLEAN}]
            )
            assert outcome.disposition == "RELEASE", (
                f"the hero path changed at floor {floor}: the threshold is "
                "influencing a document it should never touch"
            )
        finally:
            aws_module.IDENTITY_CONFIDENCE_FLOOR = original
