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

PDF0 = EVIDENCE / "northern-alloys-coa-lot-1001.pdf"
PDF1 = EVIDENCE / "eastern-metals-coa-lot-1002.pdf"
PDF2 = EVIDENCE / "northern-alloys-coa-batch-wp-26-0317-b.pdf"
PDF3 = EVIDENCE / "central-forgeworks-coa-lot-1004.pdf"
PDF4 = EVIDENCE / "western-polymers-coa-lot-1006.pdf"


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
# PDF 2 — reads perfectly, and still cannot be attributed
# ==========================================================================


def test_pdf2_reads_and_extracts_and_still_refuses_to_bind(runtime):
    """The real bytes, through the real entrypoint.

    Everything about the document works — it parses, it clears security, both
    measurements extract at full confidence — and Vouch still refuses, because
    it cannot prove these results describe THIS lot. That separation is the
    product: a valid result for Lot A must never release Lot B.
    """
    outcome = _evaluate(runtime, PDF2, "LOT-1003", "COA")
    assert outcome["ok"]
    assert outcome["failure_category"] == "EVIDENCE_IDENTITY_UNRESOLVED"
    assert outcome["disposition"] == ""
    assert outcome["quality_decision_required"] is True
    assert outcome["mutation"] == {}

    record = outcome["decision_record"]
    # Positively true, so this can never be read as an extraction failure.
    assert record["security"]["blocked"] is False
    assert record["security"]["held_claim_count"] == 2
    # Neither agent ever saw the evidence.
    assert not record["investigator"]["brief_hash"]
    assert not record["verifier"]["brief_hash"]

    events = _events(outcome)
    assert "MUTATION_COMPLETED" not in events
    assert "INVESTIGATOR_STARTED" not in events
    assert runtime._CORPUS.lot("LOT-1003").status == "RECEIVED"


def test_pdf2_asks_a_question_naming_both_identifiers(runtime):
    outcome = _evaluate(runtime, PDF2, "LOT-1003", "COA")
    question = outcome["decision_record"]["quality_authority"]["question"]
    assert question["question_type"] == "IDENTITY_BINDING"
    assert question["supplier_batch"] == "WP-26-0317-B"
    assert question["internal_lot_id"] == "LOT-1003"


def test_pdf2_is_not_treated_as_defective_for_being_unattributable(runtime):
    """An unbindable document says nothing about the material's quality."""
    outcome = _evaluate(runtime, PDF2, "LOT-1003", "COA")
    assert outcome["disposition"] != "QUARANTINE"
    assert runtime._CORPUS.lot("LOT-1003").status != "QUARANTINED"


def test_pdf2_releases_once_a_human_establishes_the_identity(runtime):
    """The whole chain on the real PDF: same record, agents run, RELEASE."""
    first = _evaluate(runtime, PDF2, "LOT-1003", "COA")
    question = first["decision_record"]["quality_authority"]["question"]

    resumed = runtime.invoke({
        "action": "submit_quality_authority",
        "decision_record_id": first["decision_record_id"],
        "decision": "CONFIRM_BINDING",
        "accountable_actor": "QA-LEAD",
        "authority_source": "Plant Quality Authority",
        "question_id": question["question_id"],
        "supplier_batch": question["supplier_batch"],
        "bound_lot_id": question["internal_lot_id"],
        "artifact_id": question["artifact_id"],
        "content_hash": question["content_hash"],
    })

    assert resumed["decision_record_id"] == first["decision_record_id"]
    assert resumed["decision_record"]["run_count"] == 2
    assert resumed["disposition"] == "RELEASE"
    # The agents run for the FIRST time on the resumed run.
    assert resumed["decision_record"]["investigator"]["brief_hash"]
    assert resumed["decision_record"]["verifier"]["brief_hash"]

    assert runtime._CORPUS.lot("LOT-1003").status == "RELEASED"
    inventory = runtime._CORPUS.get("inventory", "LOT-1003")
    assert (inventory.usable, inventory.quantity) == (True, 450.0)


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


# ==========================================================================
# The identity floor, and what PDF 2 no longer proves
# ==========================================================================


def test_the_identity_confidence_floor_is_not_quietly_lowered() -> None:
    """The 0.99 floor still guards OCR-derived identity.

    Its rationale used to rest on PDF 2: live qualification showed Textract
    recovering that document's measurements at a worst-cell confidence below
    this floor, so identity was not trusted and the evidence went unused.

    PDF 2 no longer exercises it — the binding case is on the ordinary
    extraction path by design, because a refusal that turned on OCR confidence
    read as an OCR failure. The floor is kept and still pinned: a mis-read lot
    id binds evidence to the WRONG lot, and every check after it then uses the
    wrong id. `fixtures/textract/` still covers the path itself.
    """
    from vouch.v2.aws import IDENTITY_CONFIDENCE_FLOOR

    assert IDENTITY_CONFIDENCE_FLOOR == 0.99


def test_pdf2_releases_only_after_a_human_establishes_identity() -> None:
    """Guards the documentation against two opposite reversions.

    PDF 2 must not be described as releasing autonomously (it cannot — run 1
    reaches no disposition), and must not be described as never releasing (it
    does, on run 2, once a human confirms the mapping). The manifest has to
    state the human step, not just the outcome on either side of it.
    """
    manifest = (EVIDENCE / "MANIFEST.md").read_text()
    assert "UNRESOLVED_SUPPLIER_BATCH" in manifest
    assert "human confirms" in manifest
    assert "same record, run 2" in manifest
    # The predecessor's OCR-confidence framing must not creep back.
    assert "identityTrusted = false" not in manifest


# ==========================================================================
# PDF 4 — a legitimate document that still cannot be acted on alone
# ==========================================================================


def _equivalence_option(runtime, record_id):
    """The offered path that relies on an equivalence — the one that RELEASES.

    Named explicitly because the two paths lead to different dispositions, so
    which is established decides the lot.
    """
    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": record_id,
    })["record"]
    options = record["quality_authority"]["question"]["options"]
    return next(o for o in options if o["equivalence_id"])["claim_id"]


def test_pdf4_reaches_material_disagreement_from_real_pdf_bytes(runtime):
    """The document is clean, bound and fully readable — and still stops.

    Nothing is wrong with this evidence. It is exactly the case the authority
    model exists for: two applicable readings, no rule ranking them, so the
    autonomous path halts rather than picking one.
    """
    outcome = _evaluate(runtime, PDF4, "LOT-1006", "COA")
    assert outcome["ok"]
    assert outcome["failure_category"] == "MATERIAL_DISAGREEMENT"
    assert outcome["disposition"] == ""
    assert outcome["quality_decision_required"] is True

    events = _events(outcome)
    assert "INVESTIGATOR_STARTED" in events
    assert "VERIFIER_STARTED" in events
    assert "QUALITY_QUESTION_RAISED" in events
    assert "QUALITY_DECISION_REQUIRED" in events
    # The two that must NOT have happened.
    assert "DISPOSITION_COMPUTED" not in events
    assert "MUTATION_COMPLETED" not in events

    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": outcome["decision_record_id"],
    })["record"]
    assert record["evidence"]["content_types"] == ["application/pdf"]
    assert record["evidence"]["binding_statuses"] == ["BOUND"]
    assert record["security"]["prompt_attack_detected"] is False
    # Two claims, ordinary parser, real PDF.
    assert len(record["extraction"]["per_claim"]) == 2

    # `basis` is empty, and that is the point: the basis checks run AFTER
    # reconciliation, so halting on the disagreement means the deterministic
    # stages genuinely never executed. A populated basis here would mean the
    # pipeline had gone further than it should have.
    assert record["basis"]["spec_id"] == ""
    assert record["disposition"]["disposition"] == ""
    assert record["mutation"]["action"] == ""


def test_pdf4_raises_one_answerable_question_about_the_equivalence(runtime):
    outcome = _evaluate(runtime, PDF4, "LOT-1006", "COA")
    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": outcome["decision_record_id"],
    })["record"]
    question = record["quality_authority"]["question"]

    assert question["status"] == "OPEN"
    assert question["question_type"] == "EVIDENCE_APPLICABILITY"
    assert question["characteristic"] == "viscosity"
    # The equivalence is resolved from the CORPUS, never read off the document.
    assert question["equivalence_id"] == "EQV-1"
    assert question["method_from"] == "ASTM-D445"
    assert question["method_to"] == "ASTM-D2196"
    assert question["condition"] == "25C"

    values = {o["value"] for o in question["options"]}
    assert values == {178.0, 312.0}
    # The two paths lead to OPPOSITE dispositions, which is what makes the
    # question load-bearing rather than a ratification.
    by_value = {o["value"]: o for o in question["options"]}
    assert by_value[178.0]["would_disposition"] == "QUARANTINE"
    assert by_value[312.0]["would_disposition"] == "RELEASE"
    assert {o["selected_by"] for o in question["options"]} == {
        "INVESTIGATOR", "VERIFIER"
    }


def test_pdf4_releases_and_recovers_c419_once_quality_answers(runtime):
    """The whole vertical, from real PDF bytes to a factory consequence."""
    outcome = _evaluate(runtime, PDF4, "LOT-1006", "COA")
    record_id = outcome["decision_record_id"]

    resumed = runtime.invoke({
        "action": "submit_quality_authority",
        "decision_record_id": record_id,
        "decision": "ESTABLISH_EVIDENCE",
        "evidence_ref": _equivalence_option(runtime, record_id),
        "accountable_actor": "QA-LEAD",
        "authority_source": "Plant Quality Authority",
    })

    assert resumed["ok"]
    assert resumed["decision_record_id"] == record_id, "the SAME record continues"
    assert resumed["disposition"] == "RELEASE"

    events = _events(resumed)
    assert "QUALITY_AUTHORITY_RECORDED" in events
    assert "DECISION_RESUMED" in events
    # Only NOW may the deterministic engine speak.
    assert "DISPOSITION_COMPUTED" in events
    assert "MUTATION_COMPLETED" in events

    record = runtime.invoke({
        "action": "get_decision", "decision_record_id": record_id,
    })["record"]
    assert record["run_count"] == 2
    assert record["reconciliation"]["outcome"] in ("MATCH", "NON_MATERIAL_DIFFERENCE")
    assert record["mutation"]["action"] == "release_lot"
    assert record["mutation"]["inventory_delta"] == 200.0

    # Run 1 survives the continuation — the disagreement is why a human was
    # asked, and it must stay readable afterwards.
    archived = [r for r in record["archived_runs"] if r["run_number"] == 1]
    assert len(archived) == 1
    assert archived[0]["failure_category"] == "MATERIAL_DISAGREEMENT"
    assert archived[0]["disposition"]["disposition"] == ""

    # The factory consequence, on the run that caused it.
    changes = (resumed.get("consequences") or {}).get("readiness_changes") or []
    assert [(c["order_id"], c["from"], c["to"]) for c in changes] == [
        ("C-419", "AT_RISK", "READY")
    ]


def test_pdf4_never_needs_a_structured_extractor(runtime):
    outcome = _evaluate(runtime, PDF4, "LOT-1006", "COA")
    extracted = next(
        e for e in outcome["events"] if e["event"] == "EVIDENCE_EXTRACTED"
    )
    assert extracted.get("structured_extraction") is False
