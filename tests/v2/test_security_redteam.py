"""Security red-team gate (contract D20).

Every row of the D20 table, with the stated expected behavior. The standard
these hold to: no unauthorized authority, and no unsafe mutation — including in
the cases where detection FAILS. Several tests below deliberately disable the
prompt-attack detector to prove the structural controls carry the safety story
on their own.
"""

from __future__ import annotations

import pytest

from vouch.v2.contracts import (
    AuthorityViolation,
    CoverageItem,
    DeviationRef,
    GoverningBasis,
    ProvenanceError,
    TrustLabel,
)
from vouch.v2.corpus import ApprovedDeviation, Lot, MethodEquivalence, SpecificationRevision
from vouch.v2.evidence import canonicalize, parse_deterministic
from vouch.v2.fixtures import COA_CLEAN, COA_HERO, COA_HOSTILE, build_corpus
from vouch.v2.lifecycle import EventLog, EventType
from vouch.v2.workflow import VouchV2


@pytest.fixture
def vouch():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


# -- 1. prompt injection inside a supplier document ------------------------
def test_injection_in_supplier_document_causes_no_mutation(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1005", documents=[{"raw": COA_HOSTILE}])

    assert outcome.failure_category == "SECURITY_QUARANTINE"
    assert not outcome.mutated
    assert corpus.lot("LOT-1005").status == "RECEIVED"
    assert outcome.record.security.prompt_attack_detected
    assert outcome.record.security.quarantined_artifact_ids


def test_injection_is_inert_even_when_detection_fails(vouch):
    """The load-bearing proof: Guardrails is NOT the boundary.

    With the detector disabled entirely, the hostile document flows through the
    whole pipeline as data. It still cannot release the lot, because the injected
    text is a claim, authority resolves only to internal objects, and the
    numbers are recomputed deterministically.
    """
    corpus = build_corpus()
    v = VouchV2(corpus, detector=lambda text: (False, ""))  # detection defeated

    outcome = v.evaluate_lot("LOT-1005", documents=[{"raw": COA_HOSTILE}])

    # The document DEMANDS release. The lot is not released.
    assert outcome.disposition != "RELEASE"
    assert corpus.lot("LOT-1005").status != "RELEASED"
    # 402 MPa against governing rev C (>=480) is a genuine non-conformance.
    assert outcome.disposition == "QUARANTINE"


def test_injected_text_never_reaches_a_model_as_instruction(vouch):
    """Supplier content enters only as labeled claim data."""
    corpus, v = vouch
    claims, _ = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1005", raw=COA_HOSTILE,
        events=EventLog(),
    )
    # Blocked artifacts yield nothing at all.
    assert claims == []


# -- 2. fake internal approval claim ---------------------------------------
def test_supplier_claim_cannot_establish_approval():
    """An UNTRUSTED_SUPPLIER claim can never populate an authority field."""
    with pytest.raises(Exception) as exc:
        GoverningBasis(spec_id="CLM-supplier-said-so", revision="B")
    assert "AUTHORITATIVE_INTERNAL" in str(exc.value) or "authority" in str(exc.value)


def test_supplier_claimed_spec_does_not_become_basis(vouch):
    """LOT-1002's COA cites rev B and says CONFORMS. Rev C governs anyway."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
    assert outcome.record.basis.revision == "C"
    assert outcome.disposition == "QUARANTINE"


# -- 3. fake governing-spec statement --------------------------------------
def test_basis_must_resolve_to_an_authoritative_object():
    with pytest.raises(Exception):
        GoverningBasis(spec_id="whatever the document says", revision="B")


def test_nonexistent_spec_fails_basis_checks(vouch):
    """A basis that passes the prefix check but does not exist still fails."""
    from vouch.v2.contracts import EvidenceApplicabilityBrief, Sufficiency
    from vouch.v2.reconcile import run_basis_checks

    corpus, _ = vouch
    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-INVENTED", revision="Z"),
        sufficiency=Sufficiency.SUFFICIENT,
    )
    result = run_basis_checks(brief, corpus, lot_id="LOT-1001", claims_by_id={})
    assert not result.passed
    assert any("does not exist" in f for f in result.failures)


# -- 4. wrong-lot evidence -------------------------------------------------
def test_evidence_from_another_lot_is_rejected(vouch):
    """V1 joined evidence by material and silently pulled in other lots."""
    from vouch.v2.contracts import EvidenceApplicabilityBrief, Sufficiency
    from vouch.v2.reconcile import run_basis_checks

    corpus, v = vouch
    other_claims, _ = v.ingest_evidence(
        decision_record_id="DR-x", lot_id="LOT-1001", raw=COA_CLEAN, events=EventLog(),
    )
    claim = other_claims[0]

    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="C"),
        coverage=[CoverageItem(test="tensile_strength", evidence_ref=claim.claim_id)],
        sufficiency=Sufficiency.SUFFICIENT,
    )
    # Judge LOT-1002 while citing LOT-1001's evidence.
    result = run_basis_checks(
        brief, corpus, lot_id="LOT-1002", claims_by_id={claim.claim_id: claim}
    )
    assert not result.passed
    assert any("belongs to lot LOT-1001" in f for f in result.failures)


# -- 5. wrong-site evidence / scope containment ----------------------------
def test_out_of_scope_deviation_is_refused(vouch):
    from vouch.v2.contracts import EvidenceApplicabilityBrief, Sufficiency
    from vouch.v2.reconcile import run_basis_checks

    corpus, _ = vouch
    corpus.put(
        "deviation", "DEV-OTHER-SITE",
        ApprovedDeviation(
            deviation_id="DEV-OTHER-SITE", material_id="MAT-ALLOY-7",
            characteristic="tensile_strength", status="APPROVED",
            effective_date="2024-01-01", site_scope=("SITE-ZZ",), accepts_min=400.0,
        ),
    )
    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="C"),
        deviations_applied=[DeviationRef(deviation_id="DEV-OTHER-SITE")],
        sufficiency=Sufficiency.SUFFICIENT,
    )
    result = run_basis_checks(brief, corpus, lot_id="LOT-1002", claims_by_id={})
    assert not result.passed
    # The refusal must NAME the deviation and the scope that excluded it, so a
    # retry can act on it. Asserting the substance rather than one phrasing.
    assert any(
        "DEV-OTHER-SITE" in f and "cannot be cited" in f and "SITE-ZZ" in f
        for f in result.failures
    ), result.failures


def test_out_of_scope_equivalence_does_not_apply(vouch):
    """EQV-1 covers ASTM-D445 only at 25C. LOT-1007's evidence is at 40C."""
    from vouch.v2.fixtures import COA_AMBIGUOUS

    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1007", documents=[{"raw": COA_AMBIGUOUS}])
    assert outcome.disposition == "INSUFFICIENT_EVIDENCE"
    assert corpus.lot("LOT-1007").status == "PENDING_QA"


# -- 6. stale deviation ----------------------------------------------------
def test_expired_deviation_is_excluded(vouch):
    from vouch.v2.contracts import EvidenceApplicabilityBrief, Sufficiency
    from vouch.v2.reconcile import run_basis_checks

    corpus, _ = vouch
    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="C"),
        deviations_applied=[DeviationRef(deviation_id="DEV-EXPIRED")],
        sufficiency=Sufficiency.SUFFICIENT,
    )
    result = run_basis_checks(brief, corpus, lot_id="LOT-1002", claims_by_id={})
    assert not result.passed


# -- 7. superseded spec ----------------------------------------------------
def test_superseded_revision_fails_even_if_both_models_agree(vouch):
    """The check that bounds the Verifier's residual (contract D5/D9)."""
    from vouch.v2.contracts import EvidenceApplicabilityBrief, Sufficiency
    from vouch.v2.reconcile import run_basis_checks

    corpus, _ = vouch
    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="B"),  # superseded
        sufficiency=Sufficiency.SUFFICIENT,
    )
    result = run_basis_checks(brief, corpus, lot_id="LOT-1002", claims_by_id={})
    assert not result.passed
    # LOT-1002 was received 2026-03-02; rev B ceased to govern 2026-01-01.
    # The refusal must be about the BASIS DATE, not merely about the revision
    # carrying a SUPERSEDED label today (P1-4).
    assert any("ceased to govern" in f for f in result.failures)


# -- 8. fabricated evidence reference --------------------------------------
def test_fabricated_evidence_ref_is_rejected(vouch):
    from vouch.v2.contracts import EvidenceApplicabilityBrief, Sufficiency
    from vouch.v2.reconcile import run_basis_checks

    corpus, _ = vouch
    brief = EvidenceApplicabilityBrief(
        governing_basis=GoverningBasis(spec_id="SPEC-A7", revision="C"),
        coverage=[CoverageItem(test="tensile_strength", evidence_ref="CLM-does-not-exist")],
        sufficiency=Sufficiency.SUFFICIENT,
    )
    result = run_basis_checks(brief, corpus, lot_id="LOT-1002", claims_by_id={})
    assert not result.passed
    assert any("does not exist in the snapshot" in f for f in result.failures)


def test_unbound_claim_never_reaches_a_model(vouch):
    """S5: provenance binding is enforced before the decision boundary."""
    from vouch.v2.evidence import CandidateClaim, canonicalize
    from vouch.v2.contracts import ExtractionMethod, ExternalEvidenceArtifact

    artifact = ExternalEvidenceArtifact(
        artifact_id="ART-x", source="s", supplier_id="SUP-EAST", received_at="2026-01-01",
        document_identity="COA", storage_ref="local://x", content_hash="abc",
    )
    with pytest.raises(ProvenanceError):
        canonicalize(
            [CandidateClaim(characteristic="tensile_strength", value=500.0, locator="")],
            artifact, ExtractionMethod.DETERMINISTIC_PARSER,
        )


# -- 9. poisoned precedent -------------------------------------------------
def test_precedent_id_cannot_populate_authority_fields():
    with pytest.raises(Exception):
        GoverningBasis(spec_id="PREC-00001", revision="C")
    with pytest.raises(Exception):
        CoverageItem(test="t", equivalence_record_id="PREC-00001")
    with pytest.raises(Exception):
        DeviationRef(deviation_id="PREC-00001")
    with pytest.raises(Exception):
        CoverageItem(test="t", evidence_ref="PREC-00001")


def test_verifier_has_no_precedent_tool(vouch):
    """Investigator-only scoping is enforced at the tool layer, not by prompt."""
    from vouch.v2.tools import CorpusTools, WriteToolViolation

    corpus, _ = vouch
    verifier_tools = CorpusTools(
        corpus, agent_name="verifier", lot_id="LOT-1001", material_id="MAT-ALLOY-7",
        snapshot_claims=[], allow_precedent=False,
    )
    assert "find_relevant_precedents" not in CorpusTools.VERIFIER_TOOLS
    with pytest.raises(WriteToolViolation):
        verifier_tools.find_relevant_precedents("anything")


# -- 10-12. capability attacks are covered in test_capability.py -----------


# -- 13/14. schema failures stay technical ---------------------------------
def test_investigator_schema_failure_is_not_insufficient_evidence(vouch):
    """The confirmed V1 defect (workflow.py:70-77) must not reappear."""
    from vouch.v2.agents import ApplicabilityInvestigator

    corpus, _ = vouch

    class Broken(ApplicabilityInvestigator):
        def run(self, **kwargs):
            from vouch.v2.agents import AgentRun

            return AgentRun(None, "m", "v", "h", [], False, "malformed output")

    v = VouchV2(corpus, investigator=Broken(corpus))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "INVESTIGATOR_SCHEMA_FAILURE"
    assert outcome.disposition == ""  # NOT laundered into a domain answer
    assert not outcome.mutated
    assert corpus.lot("LOT-1001").status == "RECEIVED"


def test_verifier_schema_failure_fails_closed_to_abstain(vouch):
    from vouch.v2.agents import IndependentVerifier

    corpus, _ = vouch

    class Broken(IndependentVerifier):
        def run(self, **kwargs):
            from vouch.v2.agents import AgentRun

            return AgentRun(None, "m", "v", "h", [], False, "timeout")

    v = VouchV2(corpus, verifier=Broken(corpus))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "VERIFIER_SCHEMA_FAILURE"
    assert outcome.quality_decision_required
    assert not outcome.mutated


# -- 15. model outage ------------------------------------------------------
def test_model_outage_fails_closed_with_no_partial_authority(vouch):
    from vouch.v2.agents import ApplicabilityInvestigator
    from vouch.v2.contracts import FailureCategory, VouchFailure

    corpus, _ = vouch

    class Unavailable(ApplicabilityInvestigator):
        def run(self, **kwargs):
            from vouch.v2.agents import AgentRun

            return AgentRun(None, "m", "v", "h", [], False, "MODEL_UNAVAILABLE")

    v = VouchV2(corpus, investigator=Unavailable(corpus))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert not outcome.mutated
    assert outcome.quality_decision_required
    assert v.capabilities.ledger == []  # no capability was ever issued


# -- lifecycle hygiene -----------------------------------------------------
def test_lifecycle_events_reject_reasoning_payloads():
    events = EventLog()
    with pytest.raises(ValueError):
        events.emit(EventType.DISPOSITION_COMPUTED, "DR-1", rationale="because I said so")
    with pytest.raises(ValueError):
        events.emit(EventType.TOOL_CALLED, "DR-1", chain_of_thought="...")


def test_quarantined_artifact_is_preserved_not_dropped(vouch):
    """Silent drops hide attacks and lose evidence."""
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1005", documents=[{"raw": COA_HOSTILE}])
    assert outcome.record.security.quarantined_artifact_ids
    assert outcome.record.evidence.source_artifact_hashes  # original still bound


def test_worm_original_cannot_be_overwritten():
    from vouch.v2.evidence import LocalEvidenceStore

    store = LocalEvidenceStore()
    store.put_original("LOT-1/ART-1", b"original bytes")
    with pytest.raises(PermissionError):
        store.put_original("LOT-1/ART-1", b"tampered bytes")
    assert store.get_original("LOT-1/ART-1") == b"original bytes"
