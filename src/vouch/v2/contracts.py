"""V2 foundation contracts.

The architectural line these types enforce:

    the model decides what governs and what applies;
    deterministic code decides what happens.

So the model's ONLY consequential output is an `EvidenceApplicabilityBrief` —
a claim about basis and applicability. There is no disposition field on it, by
construction, and no amount of prompt injection can add one.

Authority sourcing (contract S9) is enforced here at the type layer: a field
that confers authority (governing basis, equivalence, deviation) accepts only
an `AUTHORITATIVE_INTERNAL` object id. Supplier claims and advisory precedent
carry id prefixes that these validators reject, so a hijacked model output
fails validation instead of establishing authority.
"""

from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ==========================================================================
# trust
# ==========================================================================


class TrustLabel(str, Enum):
    """The four locked labels (contract revision #5). Semantically distinct —
    never collapse these. Only AUTHORITATIVE_INTERNAL confers authority."""

    AUTHORITATIVE_INTERNAL = "AUTHORITATIVE_INTERNAL"
    UNTRUSTED_SUPPLIER = "UNTRUSTED_SUPPLIER"
    HUMAN_AUTHORIZED = "HUMAN_AUTHORIZED"
    ADVISORY_PRECEDENT = "ADVISORY_PRECEDENT"


# Authoritative objects live in the internal system of record and are the only
# things that may populate a basis/equivalence/deviation field. The prefix is
# the cheap structural check; `basis_checks` re-resolves every id against the
# corpus regardless, so a forged prefix still fails (contract D9/D11).
AUTHORITATIVE_PREFIXES = ("SPEC-", "EQV-", "DEV-", "QUAL-", "OVL-", "MAT-", "REQ-")
PRECEDENT_PREFIX = "PREC-"
SUPPLIER_CLAIM_PREFIX = "CLM-"


class AuthorityViolation(ValueError):
    """A non-authoritative id was used where authority is required.

    Raised at schema-validation time, so it is a TECHNICAL/schema failure of the
    model output — never silently downgraded into a domain answer.
    """


def _require_authoritative(value: str, field: str) -> str:
    """Reject precedent ids, supplier claim ids, and free text as authority."""
    if value.startswith(PRECEDENT_PREFIX):
        raise AuthorityViolation(
            f"{field}: precedent id {value!r} may never establish authority"
        )
    if value.startswith(SUPPLIER_CLAIM_PREFIX):
        raise AuthorityViolation(
            f"{field}: supplier claim {value!r} may never establish authority"
        )
    if not value.startswith(AUTHORITATIVE_PREFIXES):
        raise AuthorityViolation(
            f"{field}: {value!r} is not an AUTHORITATIVE_INTERNAL object id"
        )
    return value


def content_hash(payload: Any) -> str:
    """Stable SHA-256 over any JSON-able structure. Used for claim-set hashes,
    brief hashes, and snapshot freezing."""
    blob = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# ==========================================================================
# S1 — immutable original
# ==========================================================================


class ScanStatus(str, Enum):
    """Truthful malware-scan outcome (P0-7).

    The audit found the backend recording `malware_scanned = true` with no AV
    engine anywhere in the process. Recording NOT_RUN is not a weaker security
    posture than lying about it; it is the only honest one, and it lets an
    operator see that this deployment has no scanner wired.
    """

    NOT_RUN = "NOT_RUN"
    PASSED = "PASSED"
    FLAGGED = "FLAGGED"
    FAILED = "FAILED"


class GuardrailOutcome(str, Enum):
    """Whether prompt-attack detection actually ran, and what it found."""

    NOT_RUN = "NOT_RUN"
    CLEAN = "CLEAN"
    DETECTED = "DETECTED"
    ERROR = "ERROR"


class SecurityInspection(BaseModel):
    """Outcome of the S2 hostile-content inspection. Persisted so an auditor can
    answer 'did detection actually run, and with what config' (contract S10)."""

    model_config = ConfigDict(frozen=True)

    performed: bool = False
    config_version: str = ""
    file_type_ok: bool = False
    size_ok: bool = False
    #: P0-7: the actual scan outcome. NOT_RUN when no AV engine is configured —
    #: never asserted as clean merely because nothing looked.
    malware_scan: ScanStatus = ScanStatus.NOT_RUN
    malware_detail: str = ""
    #: P0-6: Guardrails provenance. Which guardrail, which version, when, and
    #: whether detection genuinely executed.
    guardrail_outcome: GuardrailOutcome = GuardrailOutcome.NOT_RUN
    guardrail_id: str = ""
    guardrail_version: str = ""
    inspected_at: str = ""
    prompt_attack_detected: bool = False
    detector: str = ""  # e.g. "bedrock-guardrails:<id>:<version>"
    detail: str = ""
    #: P0-4: what the artifact claimed about itself, and whether that survived
    #: validation against the authoritative receiving record.
    claimed_identity: dict = Field(default_factory=dict)
    binding_mismatches: list[str] = Field(default_factory=list)

    @property
    def malware_found(self) -> bool:
        return self.malware_scan in (ScanStatus.FLAGGED, ScanStatus.FAILED)

    @property
    def binding_ok(self) -> bool:
        return not self.binding_mismatches

    @property
    def blocked(self) -> bool:
        """Any positive signal quarantines the artifact for human review.

        Detection is NOT the trust boundary (D7) — it is one layer. The
        structural controls still hold if this returns False wrongly.
        """
        return (
            self.malware_found
            or self.prompt_attack_detected
            or bool(self.binding_mismatches)
            or not (self.file_type_ok and self.size_ok)
        )


class ArtifactStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUARANTINED_SECURITY = "QUARANTINED_SECURITY"
    #: P0-4. Distinct from a security quarantine: the artifact may be perfectly
    #: benign and simply belong to a different lot.
    EVIDENCE_BINDING_MISMATCH = "EVIDENCE_BINDING_MISMATCH"
    EXTRACTED = "EXTRACTED"
    REJECTED = "REJECTED"


class ExternalEvidenceArtifact(BaseModel):
    """The immutable original supplier document.

    Original bytes never mutate. Everything downstream references this by
    `content_hash`, so a claim can always be traced back to the exact bytes it
    came from.
    """

    model_config = ConfigDict(frozen=True)

    artifact_id: str
    source: str
    supplier_id: str
    supplier_site: str = ""
    lot_id: str = ""
    material_id: str = ""
    received_at: str
    document_identity: str
    storage_ref: str  # s3://bucket/key
    content_hash: str  # SHA-256 of the original bytes
    object_version: str = ""  # S3 version id — WORM/versioned original
    security_inspection: SecurityInspection = Field(default_factory=SecurityInspection)
    status: ArtifactStatus = ArtifactStatus.RECEIVED
    #: Trust label the claims from this artifact inherit (S6).
    trust_label: TrustLabel = TrustLabel.UNTRUSTED_SUPPLIER
    #: P0-4: did the document state its own identity at all? A document that
    #: states nothing is a different case from one that states a contradiction.
    identity_stated: bool = False
    #: P0-8: text the deterministic parser recovered, how much of the artifact
    #: it could actually read, and why it failed if it did.
    extraction_text: str = ""
    parse_confidence: float = 1.0
    parse_error: str = ""


# ==========================================================================
# S4/S5/S6 — canonical claims
# ==========================================================================


class ExtractionMethod(str, Enum):
    DETERMINISTIC_PARSER = "DETERMINISTIC_PARSER"
    MODEL_FALLBACK = "MODEL_FALLBACK"
    HUMAN_SUPPLIED = "HUMAN_SUPPLIED"


class CanonicalEvidenceClaim(BaseModel):
    """One normalized, provenance-bound assertion extracted from an artifact.

    A claim is DATA. It never carries authority regardless of what it says —
    a supplier claim reading "Plant Quality approved this lot" is just a claim
    with trust_label=UNTRUSTED_SUPPLIER, and no authority field will accept it.

    `value` is deliberately typed loose: not every claim is numeric (a claim can
    assert a method name, a date, a conformance statement).
    """

    model_config = ConfigDict(frozen=True)

    claim_id: str
    evidence_artifact_id: str
    lot_id: str
    material_id: str
    claim_type: str  # e.g. "measurement" | "statement" | "attribute"
    characteristic: str = ""
    value: float | str | None = None
    units: str = ""
    method: str = ""
    condition: str = ""
    claimed_spec: str = ""  # what the SUPPLIER says governs — never authority
    # -- provenance (S5): unbound claims are rejected before any model sees them
    source_locator: str  # page/coords/row within the source object
    extraction_method: ExtractionMethod
    extraction_version: str
    extraction_confidence: float = 1.0
    trust_label: TrustLabel
    source_hash: str  # content_hash of the artifact these bytes came from

    @field_validator("source_hash", "source_locator", "extraction_version")
    @classmethod
    def _provenance_required(cls, v: str) -> str:
        if not v:
            raise ValueError("claim provenance binding is incomplete")
        return v


class ProvenanceError(ValueError):
    """A claim reached the decision boundary without a complete provenance bind."""


# ==========================================================================
# S7 — frozen snapshot
# ==========================================================================


class EvidenceSnapshot(BaseModel):
    """The frozen fact-set for exactly one decision run.

    Freezing is what makes the decision re-derivable and what makes the
    state-version binding meaningful: the capability issued at the end of the
    run is bound to the versions recorded here.
    """

    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    decision_record_id: str
    claim_set_hash: str
    claim_ids: tuple[str, ...]
    lot_id: str
    lot_state_version: int
    order_state_versions: dict[str, int] = Field(default_factory=dict)
    created_at: str

    @staticmethod
    def hash_claims(claims: list[CanonicalEvidenceClaim]) -> str:
        return content_hash(
            sorted(c.model_dump(mode="json") for c in claims)  # type: ignore[type-var]
        )


# ==========================================================================
# the canonical model output
# ==========================================================================


class RequiredTest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    threshold: str = ""  # rendered form, e.g. ">= 480 MPa"; numbers re-checked deterministically
    required_method: str = ""
    required_condition: str = ""


class CoverageItem(BaseModel):
    """How one required test is (or is not) covered by applicable evidence."""

    model_config = ConfigDict(frozen=True)

    test: str
    evidence_ref: str | None = None  # claim_id
    method_match: bool = False
    equivalence_record_id: str | None = None
    value: float | str | None = None
    units: str = ""

    @field_validator("equivalence_record_id")
    @classmethod
    def _equivalence_must_be_authoritative(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return _require_authoritative(v, "coverage.equivalence_record_id")

    @field_validator("evidence_ref")
    @classmethod
    def _evidence_ref_not_authority_object(cls, v: str | None) -> str | None:
        # Evidence must be a claim, never a precedent masquerading as evidence.
        if v is not None and v.startswith(PRECEDENT_PREFIX):
            raise AuthorityViolation(
                f"coverage.evidence_ref: precedent id {v!r} is not evidence"
            )
        return v


class GoverningBasis(BaseModel):
    model_config = ConfigDict(frozen=True)

    spec_id: str
    revision: str

    @field_validator("spec_id")
    @classmethod
    def _basis_must_be_authoritative(cls, v: str) -> str:
        return _require_authoritative(v, "governing_basis.spec_id")


class DeviationRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    deviation_id: str

    @field_validator("deviation_id")
    @classmethod
    def _deviation_must_be_authoritative(cls, v: str) -> str:
        return _require_authoritative(v, "deviations_applied.deviation_id")


class MissingItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    test: str
    reason: str


class Sufficiency(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class EvidenceApplicabilityBrief(BaseModel):
    """The canonical model output — what governs, and what applies.

    There is deliberately NO disposition field. The model cannot express
    RELEASE or QUARANTINE in this vocabulary at all; disposition is computed
    deterministically downstream from these facts (contract D10).
    """

    model_config = ConfigDict(frozen=True)

    governing_basis: GoverningBasis
    required_tests: list[RequiredTest] = Field(default_factory=list)
    coverage: list[CoverageItem] = Field(default_factory=list)
    deviations_applied: list[DeviationRef] = Field(default_factory=list)
    sufficiency: Sufficiency
    missing: list[MissingItem] = Field(default_factory=list)
    # Non-authoritative. Recorded for the operator, never consumed by any
    # deterministic step, never treated as an audit artifact.
    investigation_notes: str = ""
    precedent_consulted: list[str] = Field(default_factory=list)

    def material_fingerprint(self) -> dict:
        """Exactly the fields the Reconciler compares (D9).

        Everything omitted here — notes, ordering, phrasing, precedent — is
        non-material by definition.
        """
        return {
            "spec_id": self.governing_basis.spec_id,
            "revision": self.governing_basis.revision,
            "required_tests": sorted(t.name for t in self.required_tests),
            "coverage": sorted(
                [
                    {
                        "test": c.test,
                        "evidence_ref": c.evidence_ref,
                        "method_match": c.method_match,
                        "equivalence_record_id": c.equivalence_record_id,
                    }
                    for c in self.coverage
                ],
                key=lambda d: d["test"],
            ),
            "deviations_applied": sorted(d.deviation_id for d in self.deviations_applied),
            "sufficiency": self.sufficiency.value,
        }

    def brief_hash(self) -> str:
        return content_hash(self.material_fingerprint())


# ==========================================================================
# disposition / failure vocabulary
# ==========================================================================


class Disposition(str, Enum):
    RELEASE = "RELEASE"
    QUARANTINE = "QUARANTINE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    # Human-policy terminal state. Never derived from model judgment (D10).
    REJECT = "REJECT"


class ReconciliationOutcome(str, Enum):
    MATCH = "MATCH"
    NON_MATERIAL_DIFFERENCE = "NON_MATERIAL_DIFFERENCE"
    MATERIAL_DISAGREEMENT = "MATERIAL_DISAGREEMENT"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class FailureCategory(str, Enum):
    """Separate channels (contract §21). MODEL_FAILURE is never collapsed into
    INSUFFICIENT_EVIDENCE — that was the confirmed V1 defect."""

    DOMAIN_INSUFFICIENT_EVIDENCE = "DOMAIN_INSUFFICIENT_EVIDENCE"
    MATERIAL_DISAGREEMENT = "MATERIAL_DISAGREEMENT"
    INVESTIGATOR_SCHEMA_FAILURE = "INVESTIGATOR_SCHEMA_FAILURE"
    VERIFIER_SCHEMA_FAILURE = "VERIFIER_SCHEMA_FAILURE"
    MODEL_TIMEOUT = "MODEL_TIMEOUT"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    TOOL_FAILURE = "TOOL_FAILURE"
    SECURITY_QUARANTINE = "SECURITY_QUARANTINE"
    #: P0-4. The artifact contradicts the target it was submitted for.
    EVIDENCE_BINDING_MISMATCH = "EVIDENCE_BINDING_MISMATCH"
    #: P0-8. Extraction was too uncertain to support an autonomous decision.
    EXTRACTION_LOW_CONFIDENCE = "EXTRACTION_LOW_CONFIDENCE"
    PERSISTENCE_FAILURE = "PERSISTENCE_FAILURE"
    STATE_CONFLICT = "STATE_CONFLICT"
    POLICY_REFUSAL = "POLICY_REFUSAL"


#: Which categories a retry could plausibly clear. Everything else is terminal
#: for this run and escalates rather than looping.
RETRYABLE: frozenset[FailureCategory] = frozenset(
    {
        FailureCategory.INVESTIGATOR_SCHEMA_FAILURE,
        FailureCategory.VERIFIER_SCHEMA_FAILURE,
        FailureCategory.MODEL_TIMEOUT,
        FailureCategory.MODEL_UNAVAILABLE,
        FailureCategory.TOOL_FAILURE,
        FailureCategory.PERSISTENCE_FAILURE,
        FailureCategory.STATE_CONFLICT,
    }
)


class VouchFailure(Exception):
    """A typed failure carrying its channel, so callers cannot accidentally
    turn a technical problem into a domain answer."""

    def __init__(self, category: FailureCategory, detail: str) -> None:
        self.category = category
        self.detail = detail
        super().__init__(f"{category.value}: {detail}")

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE


__all__ = [
    "AUTHORITATIVE_PREFIXES",
    "ArtifactStatus",
    "AuthorityViolation",
    "CanonicalEvidenceClaim",
    "CoverageItem",
    "DeviationRef",
    "Disposition",
    "EvidenceApplicabilityBrief",
    "EvidenceSnapshot",
    "ExternalEvidenceArtifact",
    "ExtractionMethod",
    "FailureCategory",
    "GuardrailOutcome",
    "GoverningBasis",
    "MissingItem",
    "PRECEDENT_PREFIX",
    "ProvenanceError",
    "ReconciliationOutcome",
    "RequiredTest",
    "ScanStatus",
    "SecurityInspection",
    "Sufficiency",
    "TrustLabel",
    "VouchFailure",
    "content_hash",
]
