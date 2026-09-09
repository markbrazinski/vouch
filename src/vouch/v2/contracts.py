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
# S1 — the stored original
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
    #: audit-2 F3/F4: the explicit binding outcome. "no mismatches" is NOT the
    #: same as "bound", and conflating them is what let an identity-less COA
    #: release a lot.
    binding_status: str = "BOUND"

    @property
    def malware_found(self) -> bool:
        return self.malware_scan in (ScanStatus.FLAGGED, ScanStatus.FAILED)

    @property
    def binding_ok(self) -> bool:
        """Affirmatively bound. Absence of contradiction is not enough (F3)."""
        return self.binding_status == "BOUND" and not self.binding_mismatches

    @property
    def blocked(self) -> bool:
        """Any positive signal quarantines the artifact for human review.

        Detection is NOT the trust boundary (D7) — it is one layer. The
        structural controls still hold if this returns False wrongly.
        """
        return (
            self.malware_found
            or self.prompt_attack_detected
            or not (self.file_type_ok and self.size_ok)
        )


class ArtifactStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUARANTINED_SECURITY = "QUARANTINED_SECURITY"
    #: P0-4. Distinct from a security quarantine: the artifact may be perfectly
    #: benign and simply belong to a different lot.
    EVIDENCE_BINDING_MISMATCH = "EVIDENCE_BINDING_MISMATCH"
    #: audit-2 F3. The artifact states no identity, so it cannot be
    #: affirmatively tied to the receiving record. Distinct from a mismatch:
    #: nothing contradicts, but nothing binds either.
    EVIDENCE_UNBOUND = "EVIDENCE_UNBOUND"
    #: audit-2 F4. The artifact contradicts ITSELF — two different lots,
    #: materials, suppliers or sites inside one document.
    EVIDENCE_IDENTITY_CONFLICT = "EVIDENCE_IDENTITY_CONFLICT"
    #: The artifact identifies itself precisely, in the SUPPLIER's namespace,
    #: and no authoritative object maps that identifier to an internal lot.
    #: Read successfully, extracted successfully, not attachable — the one
    #: outcome an accountable human can resolve without new evidence.
    EVIDENCE_IDENTITY_UNRESOLVED = "EVIDENCE_IDENTITY_UNRESOLVED"
    EXTRACTED = "EXTRACTED"
    REJECTED = "REJECTED"


class ExternalEvidenceArtifact(BaseModel):
    """The stored original supplier document.

    Original bytes are never rewritten in place, and everything downstream
    references this by `content_hash`, so a claim can always be traced back to
    the exact bytes it came from.

    NOT described as "immutable": in production these are S3 objects with
    versioning, which prevents overwrite-in-place but is not Object Lock. See
    docs/architecture/v2/AWS_STATUS.md for what is and is not enabled.
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
    object_version: str = ""  # S3 VersionId (versioning, not Object Lock)
    security_inspection: SecurityInspection = Field(default_factory=SecurityInspection)
    status: ArtifactStatus = ArtifactStatus.RECEIVED
    #: Trust label the claims from this artifact inherit (S6).
    trust_label: TrustLabel = TrustLabel.UNTRUSTED_SUPPLIER
    #: P0-4: did the document state its own identity at all? A document that
    #: states nothing is a different case from one that states a contradiction.
    identity_stated: bool = False
    #: audit-2 F3/F4: the reconciled binding outcome for this artifact.
    binding_status: str = "BOUND"
    #: P0-8: text the deterministic parser recovered, how much of the artifact
    #: it could actually read, and why it failed if it did.
    extraction_text: str = ""
    parse_confidence: float = 1.0
    parse_error: str = ""
    #: Sponsor depth: did structure recovery (Textract TABLES) run for this
    #: artifact, and what did it establish? False for every ordinary document,
    #: because structure recovery is an exception path rather than a stage.
    structured_extraction: bool = False
    #: Whether the recovered structure was trusted to establish the document's
    #: OWN identity. Separate from `structured_extraction` on purpose: a table
    #: may be good enough to read measurements from and still not good enough
    #: to bind a lot id to (see IDENTITY_CONFIDENCE_FLOOR).
    structured_identity_trusted: bool = False
    #: Why the ordinary path was insufficient. Empty when it was sufficient.
    structured_reason: str = ""
    #: Per-claim source locations recovered from the table: page, table index,
    #: row/column label and cell. Feeds the Source viewer.
    structured_locators: tuple[dict, ...] = ()


# ==========================================================================
# S4/S5/S6 — canonical claims
# ==========================================================================


class ExtractionMethod(str, Enum):
    DETERMINISTIC_PARSER = "DETERMINISTIC_PARSER"
    MODEL_FALLBACK = "MODEL_FALLBACK"
    HUMAN_SUPPLIED = "HUMAN_SUPPLIED"
    #: Sponsor depth. The claim text came from Textract table-structure
    #: recovery, then through the SAME deterministic parser as any other
    #: document. It is a different way of reading the page, not a different
    #: way of deciding what a claim is.
    TEXTRACT_TABLES = "TEXTRACT_TABLES"


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

    name: str = Field(
        description=(
            "The characteristic exactly as the authoritative requirement names "
            "it, e.g. 'viscosity' or 'tensile_strength'. Use the "
            "`characteristic` value the spec tool returned, verbatim. Do NOT "
            "write the method or condition into this field — they have their "
            "own fields below."
        )
    )
    threshold: str = ""  # rendered form, e.g. ">= <min> <units>"; re-checked deterministically
    required_method: str = ""
    required_condition: str = ""


class CoverageItem(BaseModel):
    """How one required test is (or is not) covered by applicable evidence."""

    model_config = ConfigDict(frozen=True)

    test: str = Field(
        description=(
            "The characteristic this row covers, named exactly as the "
            "authoritative requirement names it."
        )
    )
    evidence_ref: str | None = Field(
        default=None,
        description=(
            "The claim_id of the evidence that covers this test, or null if no "
            "evidence in the snapshot applies to it. A claim's `claimed_spec` "
            "is what the SUPPLIER said its document was written against and is "
            "never authority: a measurement taken by the required method at "
            "the required condition covers this test even when the document "
            "cites a different specification revision. Do not withhold an "
            "evidence_ref, and do not set method_match false, on the ground "
            "that the document names another revision — record the measurement "
            "and let the deterministic checks judge it against the governing "
            "revision."
        ),
    )
    #: The `description` is deliberately on the Field, not in a comment: it is
    #: the only form the model ever sees. Pydantic puts it in the JSON schema
    #: Strands sends as the structured-output contract, whereas a `#:` comment
    #: reaches the reader of this file and nobody else. Live runs kept setting
    #: this false for evidence run by the required method whose VALUE failed
    #: its limit, because nothing in the schema said what the field meant.
    method_match: bool = Field(
        default=False,
        description=(
            "True when the evidence used the SAME test method and condition "
            "the requirement names. This is only about the method identifier, "
            "never about whether the measured value passes: evidence run by "
            "the required method that FAILS its limit still has "
            "method_match=true. Conformance is computed separately and is not "
            "yours to state. Set false only when the method or condition "
            "actually differs, in which case an authoritative equivalence "
            "record may still make the evidence apply."
        ),
    )
    equivalence_record_id: str | None = Field(
        default=None,
        description=(
            "The id of an authoritative method-equivalence record that makes "
            "evidence from a DIFFERENT method acceptable for this test, as "
            "returned by `list_equivalence_records`. Cite one only where the "
            "record genuinely covers this characteristic, this condition and "
            "this method pair on the basis date; its scope is re-verified "
            "deterministically after you answer. Leave null when the method "
            "already matches, and leave null when no record covers the "
            "difference — an uncovered method difference is a normal outcome."
        ),
    )
    value: float | str | None = Field(
        default=None,
        description=(
            "The measured value from the cited evidence, copied verbatim. "
            "Recorded for the operator; every numeric comparison is redone "
            "from the frozen claim, so nothing depends on this field."
        ),
    )
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

    spec_id: str = Field(
        description=(
            "The id of the authoritative specification that governs this lot, "
            "exactly as `list_candidate_specs` returned it (e.g. 'SPEC-NNN'). "
            "Only an AUTHORITATIVE_INTERNAL object may govern: a specification "
            "named by a supplier document is a claim about authority, not "
            "authority itself."
        )
    )
    revision: str = Field(
        description=(
            "The revision label of that specification, exactly as the tool "
            "returned it (e.g. 'C'). Choose the revision that governed on this "
            "lot's basis date, using each candidate's effective_date, "
            "effective_to and effective_basis — not necessarily the newest, "
            "and not the one a supplier document cites."
        )
    )

    @field_validator("spec_id")
    @classmethod
    def _basis_must_be_authoritative(cls, v: str) -> str:
        return _require_authoritative(v, "governing_basis.spec_id")


class DeviationRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    deviation_id: str = Field(
        description=(
            "The id of an authoritative deviation that genuinely covers this "
            "lot on date, site, PO and lot scope."
        )
    )

    @field_validator("deviation_id")
    @classmethod
    def _deviation_must_be_authoritative(cls, v: str) -> str:
        return _require_authoritative(v, "deviations_applied.deviation_id")


class MissingItem(BaseModel):
    """A required test for which NO applicable evidence exists.

    Not for evidence that exists and fails: a value outside its limit is
    covered evidence, and what it means is computed separately.
    """

    model_config = ConfigDict(frozen=True)

    test: str = Field(
        description=(
            "The characteristic, named exactly as the authoritative "
            "requirement names it."
        )
    )
    reason: str = Field(
        description=(
            "Why no applicable evidence exists for this test — for example no "
            "claim was submitted for it, or the method used does not establish "
            "the requirement and no equivalence covers it. Do NOT list a test "
            "here because its measured value failed a limit: that evidence is "
            "covered, and conformance is computed separately."
        )
    )


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

    governing_basis: GoverningBasis = Field(
        description=(
            "The single authoritative specification revision that governs this "
            "lot. Resolve it yourself from the candidates: the revision in "
            "force on this lot's basis date, per each candidate's "
            "effective_date, effective_to and effective_basis. The revision a "
            "supplier document names is a claim, not authority, and may be "
            "wrong."
        )
    )
    required_tests: list[RequiredTest] = Field(
        default_factory=list,
        description=(
            "Every requirement of the governing revision, including any it "
            "incorporates by reference, exactly as `get_spec_requirement` "
            "returned them. This must be the complete set — it is compared "
            "against the authoritative corpus, and omitting a requirement is a "
            "contract failure."
        ),
    )
    coverage: list[CoverageItem] = Field(
        default_factory=list,
        description=(
            "EXACTLY ONE row per required test, saying whether evidence in "
            "the frozen snapshot applies to it. Every required test needs a "
            "row (its evidence_ref may be null) or an entry in `missing`; "
            "silence about a requirement is not an answer, and neither is "
            "answering it twice. Where SEVERAL claims could apply to the same "
            "requirement — a result by the required method and another by a "
            "method an equivalence covers — choose the one you are relying on "
            "and give that requirement a single row. Do not list both. The "
            "claims you do not cite remain in the snapshot; choosing between "
            "them is the judgment you are being asked to make, and a brief "
            "with two rows for one requirement is rejected."
        ),
    )
    deviations_applied: list[DeviationRef] = Field(
        default_factory=list,
        description=(
            "Deviations you are relying on to accept a value that would "
            "otherwise fall outside its limit. Cite one ONLY if the "
            "authoritative record covers this lot on every axis it states: "
            "the basis date must fall between its effective_date and its "
            "expiry_date, and its site, PO and lot scopes must include this "
            "lot. A deviation whose expiry_date has passed cannot be cited, "
            "whatever its status field says. Leave this empty if none "
            "qualifies — an out-of-limit value with no covering deviation is "
            "a normal, expected outcome."
        ),
    )
    sufficiency: Sufficiency = Field(
        description=(
            "Whether applicable evidence EXISTS for every required test under "
            "the governing basis you selected. This is a question about "
            "COVERAGE, never about conformance. Set SUFFICIENT when every "
            "required test has applicable evidence, INCLUDING when a measured "
            "value falls outside its limit — a failing number is evidence that "
            "applies, and what it means is computed separately by code you "
            "cannot reach. Set INSUFFICIENT_EVIDENCE only when some required "
            "test has no applicable evidence at all, and name those tests in "
            "`missing`. Supplier qualification, approval status and whether "
            "the lot may lawfully be used are policy questions decided "
            "elsewhere; they never make evidence insufficient."
        )
    )
    missing: list[MissingItem] = Field(
        default_factory=list,
        description=(
            "The required tests for which NO applicable evidence exists. A "
            "test whose evidence exists but reports a failing value is NOT "
            "missing — record it in `coverage` instead. This list must be "
            "consistent with `sufficiency`: empty when SUFFICIENT, non-empty "
            "when INSUFFICIENT_EVIDENCE."
        ),
    )
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
            # `coverage` and `missing` overlap whenever a model states the
            # same conclusion in both vocabularies. One canonical form is
            # chosen before comparison, and the deciding question is whether
            # the coverage row RESOLVES EVIDENCE — because that is the only
            # part of either field the Disposition Engine treats as
            # load-bearing.
            #
            #   * a row that names evidence is always kept, and any `missing`
            #     entry for that test is dropped. The model is remarking that
            #     the value fails its limit; conformance is computed
            #     downstream, and `brief.missing` is consulted only for a
            #     display label. (Hero A run 3.)
            #
            #   * a row that names NO evidence is dropped when the same brief
            #     declares that test missing — "nothing applies" written twice.
            #     (Hero B, both directions.)
            #
            # Every case above was verified to produce the same disposition,
            # failing set and missing set under both spellings, so nothing that
            # decides anything is being discarded. A row carrying evidence for
            # a test is always compared, so a genuine difference about
            # applicability, method match or equivalence still surfaces.
            "coverage": sorted(
                [
                    {
                        "test": c.test,
                        "evidence_ref": c.evidence_ref,
                        "method_match": c.method_match,
                        "equivalence_record_id": c.equivalence_record_id,
                    }
                    for c in self.coverage
                    if c.evidence_ref
                    or c.test not in {m.test for m in self.missing}
                ],
                key=lambda d: d["test"],
            ),
            "missing": sorted(
                m.test
                for m in self.missing
                if m.test not in {c.test for c in self.coverage if c.evidence_ref}
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
    #: audit-2 F3. The artifact states no identity at all, so it cannot be
    #: affirmatively bound. Human review, NOT a defect finding.
    EVIDENCE_UNBOUND = "EVIDENCE_UNBOUND"
    #: audit-2 F4. The artifact asserts contradictory identities internally.
    EVIDENCE_IDENTITY_CONFLICT = "EVIDENCE_IDENTITY_CONFLICT"
    #: The document was read and extracted successfully; the supplier's own
    #: batch identifier is not authoritatively linked to the internal lot.
    #: Fail-closed and HUMAN-RESOLVABLE: an accountable human can establish the
    #: correspondence, and the same record then continues. NOT a defect finding
    #: and NOT a technical failure.
    EVIDENCE_IDENTITY_UNRESOLVED = "EVIDENCE_IDENTITY_UNRESOLVED"
    #: P0-8. Extraction was too uncertain to support an autonomous decision.
    EXTRACTION_LOW_CONFIDENCE = "EXTRACTION_LOW_CONFIDENCE"
    #: The brief was well-formed but contradicts the authoritative corpus, and
    #: still did after the bounded retry. Distinct from a SCHEMA failure (the
    #: shape was fine) and from a DISAGREEMENT (this is one brief against the
    #: corpus, not two briefs against each other).
    BRIEF_CONTRACT_VIOLATION = "BRIEF_CONTRACT_VIOLATION"
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
