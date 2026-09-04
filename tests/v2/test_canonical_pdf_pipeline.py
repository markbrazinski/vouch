"""The canonical PDFs through the REAL evidence pipeline.

`test_canonical_pdf_assets.py` proves the documents still SAY the right things.
This file proves Vouch still DOES the right things with them: same runtime
entrypoint, same `evaluate_lot` action, same `document_b64` input the browser
uses. No PDF-only path exists, and adding one would make these results
meaningless.

Local reasoners are deterministic here, so this qualifies the evidence
architecture — extraction, binding, security, authority and consequence — not
the live model's judgement. Live Nova qualification is recorded separately.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "demo" / "evidence"
ENTRYPOINT = ROOT / "app" / "Gatehouse" / "main.py"

PDF1 = EVIDENCE / "eastern-metals-coa-lot-1002.pdf"
PDF2 = EVIDENCE / "northern-alloys-mtr-lot-1001.pdf"
PDF3 = EVIDENCE / "central-forgeworks-coa-lot-1004.pdf"


@pytest.fixture(scope="module")
def runtime():
    previous = os.environ.get("VOUCH_MODE")
    os.environ["VOUCH_MODE"] = "local"
    staged = str(ROOT / "app" / "Gatehouse" / "src")
    for path in [p for p in sys.path if p == staged]:
        sys.path.remove(path)

    spec = importlib.util.spec_from_file_location("vouch_canonical_pdf_entrypoint", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module

    if previous is None:
        os.environ.pop("VOUCH_MODE", None)
    else:
        os.environ["VOUCH_MODE"] = previous


def _evaluate(runtime, pdf: Path, lot_id: str, document_type: str) -> dict:
    """The ordinary browser input path: base64 PDF bytes, nothing special."""
    return runtime.invoke({
        "action": "evaluate_lot",
        "lot_id": lot_id,
        "document_b64": base64.b64encode(pdf.read_bytes()).decode(),
        "content_type": "application/pdf",
        "document_type": document_type,
    })


def _events(outcome: dict) -> list[str]:
    return [e["event"] for e in outcome.get("events", [])]


# ==========================================================================
# PDF 1 — the conventional COA reaches the canonical Hero A outcome
# ==========================================================================


def test_pdf1_runs_the_whole_hero_a_chain(runtime):
    outcome = _evaluate(runtime, PDF1, "LOT-1002", "COA")
    assert outcome["ok"]
    # Deterministic recompute against the GOVERNING revision, not the cited one.
    assert outcome["disposition"] == "QUARANTINE"
    assert outcome["failure_category"] == ""

    events = _events(outcome)
    assert "INVESTIGATOR_STARTED" in events
    assert "VERIFIER_STARTED" in events
    assert "MUTATION_COMPLETED" in events

    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": outcome["decision_record_id"],
    })["record"]
    assert record["evidence"]["content_types"] == ["application/pdf"]
    # Two claims, read by the ORDINARY parser out of a real PDF.
    assert len(record["extraction"]["per_claim"]) == 2
    assert record["basis"]["spec_id"] == "SPEC-A7"
    assert record["basis"]["revision"] == "C"

    # The operational consequence, asserted on the run that CAUSED it. The
    # runtime fixture is module-scoped and mutation is idempotent, so a later
    # re-evaluation of this lot reports no further readiness change; checking
    # it there would assert a replay rather than a result.
    changes = (outcome.get("consequences") or {}).get("readiness_changes") or []
    c417 = next(c for c in changes if c["order_id"] == "C-417")
    assert (c417["from"], c417["to"]) == ("READY", "BLOCKED")


def test_pdf1_never_needs_a_structured_extractor(runtime):
    """If this document ever needs Textract, PDF 2 proves nothing."""
    outcome = _evaluate(runtime, PDF1, "LOT-1002", "COA")
    extracted = next(
        e for e in outcome["events"] if e["event"] == "EVIDENCE_EXTRACTED"
    )
    assert extracted.get("structured_extraction") is False
    assert extracted.get("method") != "TEXTRACT_TABLES"


# ==========================================================================
# PDF 2 — the table defeats the ordinary path and fails SAFE
# ==========================================================================


def test_pdf2_cannot_be_read_by_the_ordinary_path_and_mutates_nothing(runtime):
    """The table is unreadable line-by-line, so Vouch abstains rather than guesses.

    This is the honest state of PDF 2 until Textract is granted: no claims, no
    disposition, no mutation. An abstention is a first-class outcome, and it is
    emphatically not a quality finding against the lot.
    """
    outcome = _evaluate(runtime, PDF2, "LOT-1001", "MILL_TEST_REPORT")
    assert outcome["ok"]
    assert outcome["disposition"] == ""
    assert outcome["quality_decision_required"] is True
    assert outcome["mutation"] == {}

    events = _events(outcome)
    assert "MUTATION_COMPLETED" not in events
    assert runtime._CORPUS.lot("LOT-1001").status == "RECEIVED"


def test_pdf2_is_not_treated_as_defective_merely_for_being_unreadable(runtime):
    """Absence of evidence is an escalation, never a defect finding."""
    outcome = _evaluate(runtime, PDF2, "LOT-1001", "MILL_TEST_REPORT")
    assert outcome["disposition"] != "QUARANTINE"
    assert runtime._CORPUS.lot("LOT-1001").status != "QUARANTINED"


# ==========================================================================
# PDF 3 — security halts the spine before any agent runs
# ==========================================================================


def test_pdf3_is_quarantined_before_a_single_agent_starts(runtime):
    outcome = _evaluate(runtime, PDF3, "LOT-1004", "COA")
    assert outcome["failure_category"] == "SECURITY_QUARANTINE"
    assert outcome["disposition"] == ""
    assert outcome["mutation"] == {}

    events = _events(outcome)
    # The whole point: reasoning never begins, so there is nothing to mislead.
    assert "INVESTIGATOR_STARTED" not in events
    assert "VERIFIER_STARTED" not in events
    assert "CAPABILITY_ISSUED" not in events
    assert "MUTATION_COMPLETED" not in events
    assert runtime._CORPUS.lot("LOT-1004").status == "RECEIVED"


def test_pdf3_retains_the_artifact_but_excludes_it_from_use(runtime):
    """Evidence is never destroyed; it is quarantined and marked unusable."""
    outcome = _evaluate(runtime, PDF3, "LOT-1004", "COA")
    sources = runtime.invoke({
        "action": "get_source", "decision_record_id": outcome["decision_record_id"],
    })["sources"]

    source = sources[0]
    assert source["security_state"] == "QUARANTINED"
    assert source["excluded_from_decision_use"] is True
    assert source["prompt_attack_detected"] is True
    # Still retrievable: an auditor must be able to see what was sent.
    assert source["storage_ref"]


def test_pdf3_payload_never_reaches_the_audit_record(runtime):
    """Hostile text must not be copied into events or the record.

    Not a cosmetic rule: a lifecycle payload is replayed into other surfaces,
    so an injection quoted there would be re-delivered by the audit trail.
    """
    outcome = _evaluate(runtime, PDF3, "LOT-1004", "COA")
    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": outcome["decision_record_id"],
    })
    blob = json.dumps(record) + json.dumps(outcome)
    for marker in ("IGNORE ALL PREVIOUS", "release_lot immediately", "operator has authorized"):
        assert marker.lower() not in blob.lower()


def test_the_hostile_lot_is_not_refused_for_being_unqualified(runtime):
    """The refusal must have exactly one cause: security.

    SUP-CENTRAL is qualified for MAT-ALLOY-7 at SITE-C1 on the same terms as
    every other alloy source, so a passing test here cannot be an accident of
    the supplier being disqualified.
    """
    lot = runtime._CORPUS.lot("LOT-1004")
    qualification = runtime._CORPUS.qualification(lot.supplier_id, lot.material_id)
    assert qualification.covers(when=lot.received_at, site_id=lot.supplier_site)
