"""The D21 load-bearing evaluation harness.

Three configurations, measured per segment:

    A — the strongest reasonable DETERMINISTIC basis-selector
    B — Investigator only
    C — Investigator + independent Verifier + deterministic reconciliation

The gate: C (or B) must materially beat A on the AGENT_VALUABLE slice, measured
on GOVERNING-BASIS and EVIDENCE-APPLICABILITY accuracy — not on aggregate
disposition accuracy, which is deterministic by design and would always favour A.

Configuration A is written to be genuinely strong, not a strawman. It gets the
same authoritative corpus the agents get, and implements every deterministic
rule a competent engineer would write: revision precedence, effective-date
handling, supersession, material-scope matching, equivalence and deviation scope
containment. What it CANNOT do is resolve ambiguity that is not a total function
of the structured fields — which is precisely the claim under test.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Callable

from .agents import ApplicabilityInvestigator, IndependentVerifier
from .contracts import Sufficiency, TrustLabel
from .corpus import (
    ApprovedDeviation,
    Corpus,
    CustomerOverlay,
    InventoryRecord,
    Lot,
    Material,
    MethodEquivalence,
    Requirement,
    SpecificationRevision,
    SupplierQualification,
)
from .evalcases import CASES, EvalCase, Segment
from .evidence import canonicalize, parse_deterministic
from .lifecycle import EventLog
from .local_reasoners import investigator_reasoner, verifier_reasoner
from .reconcile import reconcile
from .tools import CorpusTools


# ==========================================================================
# build a corpus + claims for one case
# ==========================================================================


def build_case_world(case: EvalCase) -> tuple[Corpus, list]:
    corpus = Corpus()
    erp = case.erp

    corpus.put("material", erp["material_id"], Material(erp["material_id"], erp["material_id"]))
    corpus.put(
        "lot", erp["lot_id"],
        Lot(
            lot_id=erp["lot_id"], supplier_id=erp["supplier_id"],
            material_id=erp["material_id"], po_reference=erp.get("po_reference", ""),
            quantity=100.0, supplier_site=erp.get("supplier_site", ""),
            customer_id=erp.get("customer_id", ""),
            manufactured_at=erp.get("manufactured_at", ""),
            received_at=erp.get("received_at", ""),
        ),
    )
    corpus.put(
        "inventory", erp["lot_id"],
        InventoryRecord(erp["material_id"], erp["lot_id"], 100.0, usable=False),
    )

    for spec in case.corpus_objects.get("specs", []):
        corpus.put(
            "spec_revision", f"{spec['spec_id']}:{spec['revision']}",
            SpecificationRevision(
                spec_id=spec["spec_id"], revision=spec["revision"], status=spec["status"],
                effective_date=spec["effective_date"],
                effective_basis=spec["effective_basis"],
                superseded_by=spec.get("superseded_by"),
                incorporates=tuple(spec.get("incorporates", ())),
                material_scope=tuple(spec.get("material_scope", ())),
                requirements=tuple(Requirement(**r) for r in spec["requirements"]),
            ),
        )

    for record in case.corpus_objects.get("equivalences", []):
        corpus.put(
            "equivalence", record["equivalence_id"],
            MethodEquivalence(
                equivalence_id=record["equivalence_id"],
                required_method=record["required_method"],
                alternate_method=record["alternate_method"],
                status=record["status"], effective_date=record["effective_date"],
                expiry_date=record.get("expiry_date"),
                material_scope=tuple(record.get("material_scope", ())),
                condition_scope=tuple(record.get("condition_scope", ())),
                characteristic_scope=tuple(record.get("characteristic_scope", ())),
            ),
        )

    for record in case.corpus_objects.get("deviations", []):
        corpus.put(
            "deviation", record["deviation_id"],
            ApprovedDeviation(
                deviation_id=record["deviation_id"], material_id=record["material_id"],
                characteristic=record["characteristic"], status=record["status"],
                effective_date=record["effective_date"],
                expiry_date=record.get("expiry_date"),
                site_scope=tuple(record.get("site_scope", ())),
                po_scope=tuple(record.get("po_scope", ())),
                lot_scope=tuple(record.get("lot_scope", ())),
                accepts_min=record.get("accepts_min"), accepts_max=record.get("accepts_max"),
            ),
        )

    for record in case.corpus_objects.get("overlays", []):
        corpus.put(
            "customer_overlay", record["overlay_id"],
            CustomerOverlay(
                overlay_id=record["overlay_id"], customer_id=record["customer_id"],
                spec_id=record["spec_id"], material_id=record["material_id"],
                effective_date=record["effective_date"],
                expiry_date=record.get("expiry_date"),
                requirements=tuple(Requirement(**r) for r in record["requirements"]),
            ),
        )

    for record in case.corpus_objects.get("qualifications", []):
        corpus.put(
            "supplier_qualification",
            f"{record['supplier_id']}:{record['material_id']}",
            SupplierQualification(
                qualification_id=record["qualification_id"],
                supplier_id=record["supplier_id"], material_id=record["material_id"],
                status=record["status"], effective_date=record["effective_date"],
                expiry_date=record.get("expiry_date"),
                site_scope=tuple(record.get("site_scope", ())),
            ),
        )

    # Claims come from the documents through the real extraction path.
    from .contracts import ExtractionMethod, ExternalEvidenceArtifact

    claims = []
    for index, text in enumerate(case.documents):
        artifact = ExternalEvidenceArtifact(
            artifact_id=f"ART-{case.case_id}-{index}", source="eval",
            supplier_id=erp["supplier_id"], supplier_site=erp.get("supplier_site", ""),
            lot_id=erp["lot_id"], material_id=erp["material_id"],
            received_at=erp.get("received_at", ""), document_identity=f"DOC-{index}",
            storage_ref=f"eval://{case.case_id}/{index}",
            content_hash=f"hash-{case.case_id}-{index}",
        )
        candidates, _ = parse_deterministic(text)
        claims.extend(
            canonicalize(
                candidates, artifact, ExtractionMethod.DETERMINISTIC_PARSER,
                TrustLabel.UNTRUSTED_SUPPLIER,
            )
        )
    return corpus, claims


# ==========================================================================
# configuration A — the strong deterministic basis-selector
# ==========================================================================


def deterministic_basis_selector(corpus: Corpus, case: EvalCase, claims: list) -> dict:
    """The best rules a competent engineer writes without a model.

    Deliberately strong. It implements, from structured fields only:
      - candidate enumeration and material-scope filtering
      - supersession and status exclusion
      - effective-date resolution under a STATED basis
      - equivalence and deviation scope containment
      - method/condition matching

    Its structural limit is that it cannot resolve what the structured fields do
    not determine: an unstated effective basis, a requirement that only exists
    inside an incorporated document it was not told to follow, or a customer
    overlay it has no rule to consult. That limit is the thing being measured.
    """
    lot = corpus.lot(case.erp["lot_id"])
    when = lot.received_at or lot.manufactured_at

    candidates = [
        spec
        for spec in corpus.all("spec_revision")
        if spec.covers_material(lot.material_id)
        and spec.status == "ACTIVE"
        and spec.superseded_by is None
    ]
    if not candidates:
        return {"basis": None, "applicability": {}, "disposition": "ABSTAIN"}

    # Effective-date resolution where a basis is stated; latest effective
    # revision otherwise. This is the strongest defensible deterministic rule.
    effective = []
    for spec in candidates:
        if spec.effective_basis == "date_of_manufacture":
            reference = lot.manufactured_at
        elif spec.effective_basis == "date_of_receipt":
            reference = lot.received_at
        else:
            reference = when
        if reference and reference >= spec.effective_date:
            effective.append(spec)

    chosen = max(
        effective or candidates, key=lambda s: (s.effective_date, s.revision)
    )

    # Requirements: the chosen revision's own list PLUS anything it incorporates
    # by reference. A competent engineer absolutely writes this loop, so the
    # baseline gets it — withholding it would manufacture an agent advantage.
    requirements = list(chosen.requirements)
    for reference in chosen.incorporates:
        incorporated = corpus.get("spec_revision", reference)
        if incorporated is not None:
            requirements.extend(incorporated.requirements)

    applicability: dict[str, str] = {}
    failures: list[str] = []
    absent: list[str] = []

    for requirement in requirements:
        claim = next(
            (c for c in claims if c.characteristic == requirement.characteristic), None
        )
        if claim is None:
            applicability[requirement.characteristic] = "ABSENT"
            absent.append(requirement.characteristic)
            continue

        applies = (
            claim.method == requirement.method and claim.condition == requirement.condition
        )
        if not applies:
            for equivalence in corpus.equivalences_for(lot.material_id):
                if equivalence.covers(
                    required_method=requirement.method, used_method=claim.method,
                    when=when, material_id=lot.material_id, condition=claim.condition,
                    characteristic=requirement.characteristic,
                ):
                    applies = True
                    break

        if not applies:
            applicability[requirement.characteristic] = "NOT_APPLICABLE"
            absent.append(requirement.characteristic)
            continue

        applicability[requirement.characteristic] = "APPLIES"
        if isinstance(claim.value, (int, float)) and not requirement.in_limits(
            float(claim.value)
        ):
            covered = any(
                deviation.covers(
                    material_id=lot.material_id,
                    characteristic=requirement.characteristic, when=when,
                    site_id=lot.supplier_site, po=lot.po_reference, lot_id=lot.lot_id,
                )
                and deviation.accepts(float(claim.value))
                for deviation in corpus.deviations_for(lot.material_id)
            )
            if not covered:
                failures.append(requirement.characteristic)

    if failures:
        disposition = "QUARANTINE"
    elif absent:
        disposition = "ABSTAIN"
    else:
        disposition = "RELEASE"

    return {
        "basis": (chosen.spec_id, chosen.revision),
        "applicability": applicability,
        "disposition": disposition,
    }


# ==========================================================================
# configurations B and C
# ==========================================================================


def _brief_to_result(brief, corpus: Corpus, case: EvalCase, claims: list) -> dict:
    """Turn a brief into comparable (basis, applicability, disposition)."""
    from .disposition import compute_disposition
    from .reconcile import run_basis_checks

    if brief is None:
        return {"basis": None, "applicability": {}, "disposition": "ABSTAIN"}

    applicability: dict[str, str] = {}
    for item in brief.coverage:
        if item.evidence_ref is None:
            applicability[item.test] = "ABSENT"
        elif item.method_match or item.equivalence_record_id:
            applicability[item.test] = "APPLIES"
        else:
            applicability[item.test] = "NOT_APPLICABLE"
    for missing in brief.missing:
        applicability.setdefault(missing.test, "ABSENT")

    claims_by_id = {c.claim_id: c for c in claims}
    checks = run_basis_checks(
        brief, corpus, lot_id=case.erp["lot_id"], claims_by_id=claims_by_id
    )
    if not checks.passed:
        disposition = "ABSTAIN"
    else:
        result = compute_disposition(
            brief, checks.resolved_requirements, claims_by_id, corpus,
            lot_id=case.erp["lot_id"],
        )
        disposition = {
            "RELEASE": "RELEASE", "QUARANTINE": "QUARANTINE",
            "INSUFFICIENT_EVIDENCE": "ABSTAIN",
        }[result.disposition.value]

    return {
        "basis": (brief.governing_basis.spec_id, brief.governing_basis.revision),
        "applicability": applicability,
        "disposition": disposition,
    }


def run_agent_config(
    case: EvalCase, *, with_verifier: bool, investigator=None, verifier=None
) -> dict:
    corpus, claims = build_case_world(case)
    events = EventLog()
    context = {
        "lot_id": case.erp["lot_id"],
        "material_id": case.erp["material_id"],
        "manufactured_at": case.erp.get("manufactured_at", ""),
        "received_at": case.erp.get("received_at", ""),
        "supplier_site": case.erp.get("supplier_site", ""),
        "customer_id": case.erp.get("customer_id", ""),
        "po_reference": case.erp.get("po_reference", ""),
    }

    agent = investigator or ApplicabilityInvestigator(
        corpus, local_fn=investigator_reasoner
    )
    run = agent.run(
        context=context, claims=claims, events=events, decision_record_id=case.case_id
    )
    result = _brief_to_result(run.brief, corpus, case, claims)

    if not with_verifier:
        return result

    checker = verifier or IndependentVerifier(corpus, local_fn=verifier_reasoner)
    verification = checker.run(
        context=context, claims=claims, events=events, decision_record_id=case.case_id
    )
    outcome = reconcile(run.brief, verification.brief, events, case.case_id)

    result["reconciliation"] = outcome.outcome.value
    if outcome.outcome.value in ("MATERIAL_DISAGREEMENT", "TECHNICAL_FAILURE"):
        # Disagreement abstains — but the BASIS the investigator proposed is
        # still recorded, so basis accuracy is measurable independently.
        result["disposition"] = "ABSTAIN"
    return result


# ==========================================================================
# scoring
# ==========================================================================


@dataclass
class CaseScore:
    case_id: str
    segment: str
    config: str
    basis_correct: bool
    applicability_correct: bool
    disposition_correct: bool
    predicted_basis: str = ""
    predicted_disposition: str = ""
    reconciliation: str = ""


def score(case: EvalCase, result: dict, config: str) -> CaseScore:
    predicted_basis = result.get("basis")
    basis_correct = predicted_basis == case.gold_basis

    predicted_applicability = result.get("applicability", {})
    applicability_correct = all(
        predicted_applicability.get(test) == expected
        for test, expected in case.gold_applicability.items()
    )

    return CaseScore(
        case_id=case.case_id,
        segment=case.segment,
        config=config,
        basis_correct=basis_correct,
        applicability_correct=applicability_correct,
        disposition_correct=result.get("disposition") == case.gold_disposition,
        predicted_basis=":".join(predicted_basis) if predicted_basis else "none",
        predicted_disposition=result.get("disposition", ""),
        reconciliation=result.get("reconciliation", ""),
    )


def run_all(cases: list[EvalCase] | None = None) -> dict:
    cases = cases or CASES
    scores: list[CaseScore] = []

    for case in cases:
        corpus, claims = build_case_world(case)
        scores.append(
            score(case, deterministic_basis_selector(corpus, case, claims), "A")
        )
        scores.append(score(case, run_agent_config(case, with_verifier=False), "B"))
        scores.append(score(case, run_agent_config(case, with_verifier=True), "C"))

    return {"scores": [asdict(s) for s in scores], "summary": summarize(scores)}


def summarize(scores: list[CaseScore]) -> dict:
    out: dict = {}
    for segment in ("RULE_SOLVABLE", "AGENT_VALUABLE", "HUMAN_ONLY"):
        out[segment] = {}
        for config in ("A", "B", "C"):
            subset = [s for s in scores if s.segment == segment and s.config == config]
            if not subset:
                continue
            out[segment][config] = {
                "n": len(subset),
                "basis": sum(s.basis_correct for s in subset),
                "applicability": sum(s.applicability_correct for s in subset),
                "disposition": sum(s.disposition_correct for s in subset),
            }
    return out


def gate_verdict(summary: dict) -> tuple[bool, str]:
    """The load-bearing gate (contract D21/§26).

    Measured ONLY on AGENT_VALUABLE, and ONLY on basis + applicability.
    """
    slice_ = summary.get("AGENT_VALUABLE", {})
    if not slice_:
        return False, "no AGENT_VALUABLE cases"

    a = slice_["A"]
    best = max(("B", "C"), key=lambda c: slice_[c]["basis"] + slice_[c]["applicability"])
    agent = slice_[best]

    a_total = a["basis"] + a["applicability"]
    agent_total = agent["basis"] + agent["applicability"]
    n = a["n"] * 2

    passed = agent_total > a_total
    detail = (
        f"AGENT_VALUABLE (n={a['n']}): "
        f"A basis {a['basis']}/{a['n']}, applicability {a['applicability']}/{a['n']} "
        f"(total {a_total}/{n}) vs "
        f"{best} basis {agent['basis']}/{a['n']}, "
        f"applicability {agent['applicability']}/{a['n']} (total {agent_total}/{n})"
    )
    return passed, detail


__all__ = [
    "CaseScore",
    "build_case_world",
    "deterministic_basis_selector",
    "gate_verdict",
    "run_agent_config",
    "run_all",
    "summarize",
]
