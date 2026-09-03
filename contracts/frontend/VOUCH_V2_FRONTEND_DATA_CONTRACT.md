# VOUCH V2 — Frontend Data Contract

**Normative.** This document states what the React frontend **requires** from any backend integration for the frozen two-column Vouch V2 design to render truthfully. It is authored from the approved design and `VOUCH_V2_UI_COMPONENT_DATA_REQUIREMENTS.md`. The backend responds in a separate conformance pass; nothing here is weakened on assumptions about backend capability.

Key words **MUST**, **MUST NOT**, **SHOULD**, **MAY** are used per RFC 2119.

Global rules:
- All timestamps **MUST** be RFC 3339 UTC strings.
- All identifiers **MUST** be stable strings, unique within their type for the tenant/plant.
- Enum fields **MUST** use exactly the string literals defined here. The frontend **MUST NOT** be required to parse prose to derive state, disposition, readiness, trust, or outcome.
- Any field marked optional **MUST** be either present-and-valid or absent/`null`; it **MUST NOT** be an empty-string placeholder standing in for a real value.
- The backend **MUST NOT** deliver chain-of-thought, prompts, reasoning tokens, or raw model transcripts on any field consumed by any component defined here.

---

## 1. Shared enums

```ts
type DecisionStageKey =
  | "EVIDENCE"
  | "INVESTIGATOR"
  | "VERIFIER"
  | "RECONCILIATION"
  | "DISPOSITION"
  | "QUALITY_CONTINUATION"
  | "CONSEQUENCE";

type Disposition =
  | "PENDING"
  | "RELEASED"
  | "QUARANTINED"
  | "QUALITY_DECISION_REQUIRED";

type Readiness = "READY" | "AT_RISK" | "BLOCKED";

type ReconciliationOutcome =
  | "PENDING"
  | "MATCH"
  | "NON_MATERIAL_DIFFERENCE"
  | "MATERIAL_DISAGREEMENT";

type TrustClass =
  | "AUTHORITATIVE_INTERNAL"
  | "UNTRUSTED_SUPPLIER"
  | "HUMAN_AUTHORIZED"
  | "ADVISORY_PRECEDENT";

type SecurityState = "PENDING" | "CLEARED" | "QUARANTINED";

type ActorType =
  | "EVIDENCE"
  | "SECURITY"
  | "INVESTIGATOR"
  | "VERIFIER"
  | "SYSTEM"
  | "OPERATIONS"
  | "HUMAN";

type RecoveryVerdict = "NOT_FEASIBLE" | "REFUSED" | "ELIGIBLE";

type ResultStatus = "NEUTRAL" | "GOOD" | "CAUTION" | "BAD";
```

The frontend **MUST** treat any unrecognized enum value as a technical-failure condition for that datum (§9), not silently render it.

---

## 2. Read model contracts

### 2.1 IncomingOverview

```ts
type IncomingOverview = {
  counts: {
    arrivedToday: number
    needQualityDecision: number
    inProgress: number
    completedByVouch: number
  }
  inProgressBreakdown: { count: number; label: string }[]   // MAY be empty
  rows: IncomingDecisionSummary[]
}

type IncomingDecisionSummary = {
  decisionRecordId: string
  lotId: string
  material: string
  supplierName: string
  receivedAt: string
  stage: DecisionStageKey | "NEW"           // MUST reflect current lifecycle stage; MAY change
  rowState:
    | "NEW"
    | "EVIDENCE_RECEIVED"
    | "SECURITY_HOLD"
    | "INVESTIGATING"
    | "VERIFYING"
    | "QUALITY_DECISION_REQUIRED"
    | "QUARANTINED"
    | "RELEASED"
    | "COMPLETE"
  attentionRequired: boolean
  disposition: Disposition
  securityState: SecurityState
  downstreamCommitment?: {                   // absent when no material downstream link
    orderId: string
    scheduledAt: string
    severity: Readiness
  }
  impactSummary?: string                     // SHORT operational phrase; MAY be absent
}
```
- `rowState` **MUST** be provided; the frontend **MUST NOT** derive it from `stage` + `disposition` heuristics.
- `attentionRequired` **MUST** be `true` whenever `disposition === "QUALITY_DECISION_REQUIRED"` or `securityState === "QUARANTINED"`.
- `counts` **MUST** be authoritative values; the frontend **MUST NOT** compute them from `rows` (rows MAY be paginated).
- New-arrival ("unread") emphasis is a **DERIVED_UI** state owned by the client; the backend **MUST NOT** be required to supply it.

### 2.2 DecisionWorkspace

```ts
type DecisionWorkspace = {
  decisionRecordId: string
  lot: {
    lotId: string
    material: string
    supplierName: string
    supplierSite?: string
    receivedAt: string
    quantity?: { value: number; unit: string }
  }
  disposition: Disposition
  currentStageKey: DecisionStageKey
  currentRunNumber: number                   // 1 for first run; increments on resume
  spine: DecisionSpine
  caseContext: CaseContext
  outcome: OutcomeSummary | null             // null until a terminal/decision-open state
  sources: SourceArtifact[]
  stages: AgentStage[] | StageEnvelope[]     // see §2.6 StageEnvelope
  activity: ActivityEvent[]                  // chronological ascending; FE reverses for display
  lastEventSequence: number
}
```
- `currentStageKey` **MUST** be derived by the backend from lifecycle truth and change only at major stage boundaries (§7). It **MUST NOT** change on individual tool calls.
- `outcome` **MUST** be `null` while the decision is pre-terminal and not in `QUALITY_DECISION_REQUIRED`.
- `lastEventSequence` **MUST** equal the sequence of the newest event included in `activity`.

### 2.3 DecisionSpine

```ts
type DecisionSpine = {
  nodes: {
    key: "EVIDENCE" | "AGENTS" | "DISPOSITION" | "CONSEQUENCE"
    state: "PENDING" | "ACTIVE" | "COMPLETED" | "HALTED" | "TERMINAL"
    headline: string        // e.g. "S-88 Rev 4", "⊘ QUARANTINED" — short label, not prose
    note?: string
  }[]
  investigatorLane: string | null   // populated after APPLICABILITY_BRIEF_COMPLETED
  verifierLane: string | null       // populated after VERIFIER_BRIEF_COMPLETED
  reconciliationSeal:
    | "PENDING"
    | "RECONSTRUCTING"
    | "MATCH"
    | "MATERIAL_DISAGREEMENT"
    | "HALTED"
}
```
- The AGENTS node **MUST** carry both `investigatorLane` and `verifierLane`; the verifier lane value **MUST NOT** be derived from the investigator lane.

### 2.4 CaseContext (persistent left column)

```ts
type CaseContext = {
  primarySourceArtifactId: string
  lotLine: string                    // "L-2231 · Resin R-17"
  governingBasis: string | null      // populated after applicability established
  boundFact: {
    label: string                    // "Bound tensile"
    value: string                    // "462 MPa · Method M-12"
  } | null
}
```
- CaseContext **MUST NOT** carry supplier or disposition — those are owned by the header/spine/outcome and MUST NOT be duplicated here.
- `governingBasis` and `boundFact` **MUST** be `null` until established, then **MUST** stabilize (they MAY change only across a run boundary).

### 2.5 SourceArtifact

```ts
type SourceArtifact = {
  artifactId: string
  displayName: string
  documentType:
    | "COA"
    | "MILL_TEST_REPORT"
    | "SUPPLIER_ADDENDUM"
    | "INTERNAL_AUTHORIZATION"
    | "OTHER"
  trustClass: TrustClass
  securityState: SecurityState
  versionId: string
  hash: string
  pageCount?: number
  sourceLocators?: { page?: number; section?: string; label?: string }[]
  declaredClaims?: { label: string; value: string; locator?: string }[]
  highlightedClaims?: { label: string; value: string; locator?: string }[]
  hostileContentExcerpt?: string     // present only when securityState === "QUARANTINED"
  excludedFromDecisionUse: boolean
  viewRef?: string                   // opaque, FE-safe retrieval reference (§5)
}
```
- When `securityState === "QUARANTINED"`, `excludedFromDecisionUse` **MUST** be `true` and `hostileContentExcerpt` **SHOULD** be present so the viewer can show the instruction-like text.
- `trustClass === "HUMAN_AUTHORIZED"` **MUST** be used for evidence supplied via the Quality-continuation command (§4.1); supplier documents **MUST** use `UNTRUSTED_SUPPLIER`.

### 2.6 AgentStage & StageEnvelope

```ts
type StageEnvelope = {
  stageKey: DecisionStageKey
  runNumber: number
  status: "WAITING" | "ACTIVE" | "COMPLETED" | "HALTED"
  agent?: AgentStage           // present for INVESTIGATOR / VERIFIER
  reconciliation?: Reconciliation
  disposition?: Disposition_VM
  consequence?: Consequence
  qualityContinuation?: QualityContinuation
  evidence?: EvidenceStage
}

type AgentStage = {
  role: "INVESTIGATOR" | "VERIFIER"
  runNumber: number
  state:
    | "WAITING"
    | "STARTED"
    | "TOOL_ACTIVITY"
    | "BRIEF_COMPLETE"
    | "TECHNICAL_FAILURE"
    | "DOMAIN_INSUFFICIENCY"
  isIndependent: boolean       // true for VERIFIER
  recordsConsulted: {
    mark: string               // "✓"
    label: string
    value: string
    emphasis?: ResultStatus
  }[]
  resultTitle: string | null
  resultBody: string | null
  resultClass: ResultStatus | null
}

type EvidenceStage = {
  snapshotId: string | null
  claimCount: number | null
  artifactIds: string[]
  quarantined: boolean
}
```
- A `VERIFIER` AgentStage **MUST NOT** contain any field derived from the investigator's output. The two lanes **MUST** be independently sourced.
- `recordsConsulted` is the meaning-level projection; per-call tool chronology **MUST** be delivered through `ActivityEvent` (§3), not duplicated here.

### 2.7 Reconciliation

```ts
type Reconciliation = {
  runNumber: number
  outcome: ReconciliationOutcome
  dimensions: {
    dimension: string
    investigatorValue: string
    verifierValue: string
    agrees: boolean
  }[]
  note?: string
}
```
- `dimensions` **MUST** contain only material dimensions. The frontend **MUST NOT** be required to filter non-material rows out of a larger set.

### 2.8 Disposition (view model)

```ts
type Disposition_VM = {
  runNumber: number
  disposition: Disposition
  governingBasis?: string
  requirementValue?: string          // "≥ 480 MPa"
  boundValue?: string                // "462 MPa"
  basisChain?: { label: string; value: string; tone: ResultStatus }[]
  stateMutation?: string[]           // e.g. ["Inventory pending release → quarantined · 900 kg", ...]
  qdrQuestion?: string               // present iff disposition === "QUALITY_DECISION_REQUIRED"
  materialDifferences?: string[]     // present iff QDR
  awaitingHuman?: boolean            // present iff QDR
}
```
- When `disposition === "QUALITY_DECISION_REQUIRED"`, `qdrQuestion` and `materialDifferences` **MUST** be present and `basisChain`/`stateMutation` **MUST NOT** imply any mutation occurred.
- When `disposition === "RELEASED"` or `"QUARANTINED"`, `basisChain` and `stateMutation` **MUST** be present.

### 2.9 Consequence & RecoveryEvaluation

```ts
type Consequence = {
  runNumber: number
  metrics: {
    label: string
    value: string
    note?: string
    severity: ResultStatus
  }[]
  recovery?: RecoveryEvaluation
}

type RecoveryEvaluation = {
  candidates: {
    kind: string          // "EXISTING INVENTORY" | "SUBSTITUTE" | "RESEQUENCE" | ...
    title: string
    detail: string
    verdict: RecoveryVerdict
  }[]
  executed?: {
    tag: string           // "RESEQUENCED"
    line: string
    result: string        // "09:30 SLOT RECOVERED"
    caveat?: string       // "C-417 remains blocked"
  }
}
```
- `RecoveryEvaluation.candidates` **MUST** include every evaluated candidate with its verdict, including refused/infeasible ones. The frontend **MUST NOT** be given only the winning candidate.
- `executed` **MUST** be present only after a recovery action actually executed, and **MUST NOT** imply the originally blocked order was fixed.

### 2.10 QualityContinuation

```ts
type QualityContinuation = {
  status: "AWAITING_EVIDENCE" | "EVIDENCE_RECEIVED" | "RESUMED"
  evidenceAdded?: { label: string; artifactId?: string }
  accountableAuthority?: { id: string; displayName: string; at: string }
  resumesRunNumber?: number          // MUST equal prior run + 1
}
```
- A resume **MUST** be represented as the **same** `decisionRecordId` with an incremented `runNumber`. The backend **MUST NOT** require the frontend to open a new record.

### 2.11 OutcomeSummary

```ts
type OutcomeSummary = {
  kind:
    | "EVIDENCE_QUARANTINED"
    | "QUALITY_DECISION_REQUIRED"
    | "RELEASED"
    | "QUARANTINED_WITH_CONSEQUENCE"
  headline: string
  status: ResultStatus
  chip?: { label: string; status: ResultStatus }
  facts: { label: string; value: string }[]   // structured, ordered display facts
}
```
- `OutcomeSummary.facts` **MUST** be structured label/value pairs. The frontend **MUST NOT** be required to compose the outcome from natural-language description strings.
- Required minimum `facts` by kind:
  - `QUARANTINED_WITH_CONSEQUENCE`: governing basis, bound value, requirement, affected commitment, readiness result, recovery result.
  - `QUALITY_DECISION_REQUIRED`: material-disagreement/insufficiency reason, hold/no-release state.
  - `RELEASED`: authorized-evidence summary, independent-match indicator, restored commitment/readiness.
  - `EVIDENCE_QUARANTINED`: security reason, agents-not-started indicator, no-mutation indicator.

### 2.12 TodayPlan

```ts
type TodayPlan = {
  readinessCounts: Record<Readiness, number>
  changeBanner?: {
    status: ResultStatus
    chip: { label: string; status: ResultStatus }
    text: string
  }
  lines: {
    lineId: string
    name: string
    orders: {
      orderId: string
      scheduledAt: string
      materialRequirement: string
      readiness: Readiness
      causedByDecisionRecordId?: string
      sequenceChange?: { priorSlot: string; currentSlot: string }
    }[]
    recoveryResult?: RecoveryEvaluation["executed"]
  }[]
}
```
- `readiness` per order and `readinessCounts` **MUST** be authoritative. The before/after visual presentation is **DERIVED_UI** and the backend **MUST NOT** be required to supply it.
- `causedByDecisionRecordId` **MUST** be present on any order whose readiness changed due to a decision, so Today can link back to the record.

### 2.13 DecisionRecord (durable audit)

```ts
type DecisionRecord = {
  decisionRecordId: string
  lot: DecisionWorkspace["lot"]
  disposition: Disposition
  evidence: { artifacts: SourceArtifact[]; snapshots: { runNumber: number; snapshotId: string }[] }
  runs: {
    runNumber: number
    investigator: AgentStage
    verifier: AgentStage
    reconciliation: Reconciliation
    disposition: Disposition_VM
  }[]
  humanContinuation?: QualityContinuation
  policyCapability?: { policyRef?: string; capabilityRef?: string; issuedAt?: string }
  mutation?: { summary: string; committedAt: string }
  operationalConsequence?: Consequence
}
```
- Records **MUST** be served as a stable projection. The frontend **MUST NOT** be required to reconstruct the record by replaying `ActivityEvent`s.

---

## 3. Event contract (ActivityEvent)

```ts
type ActivityEvent = {
  eventId: string
  sequence: number                 // strictly increasing per decisionRecordId
  timestamp: string
  eventType: LifecycleEventType
  actorType: ActorType
  actorDisplayName: string
  toolId?: string                  // real tool identifier when eventType === "TOOL_CALLED"/"TOOL_RESULT_BOUND"
  label: string
  resultSummary?: string
  resultStatus?: ResultStatus
  authorityClass?: TrustClass
  objectRefs?: string[]
  decisionRecordId: string
  runNumber?: number
}

type LifecycleEventType =
  | "EVIDENCE_RECEIVED"
  | "EVIDENCE_SECURITY_COMPLETED"
  | "EVIDENCE_EXTRACTED"
  | "EVIDENCE_BINDING_COMPLETED"
  | "EVIDENCE_SNAPSHOT_CREATED"
  | "INVESTIGATOR_STARTED"
  | "TOOL_CALLED"
  | "TOOL_RESULT_BOUND"
  | "APPLICABILITY_BRIEF_COMPLETED"
  | "VERIFIER_STARTED"
  | "VERIFIER_BRIEF_COMPLETED"
  | "RECONCILIATION_COMPLETED"
  | "DISPOSITION_COMPUTED"
  | "POLICY_EVALUATED"
  | "CAPABILITY_ISSUED"
  | "MUTATION_COMPLETED"
  | "CONSEQUENCE_RECALCULATED"
  | "RECOVERY_EVALUATED"
  | "RECOVERY_EXECUTED"
  | "QUALITY_DECISION_REQUIRED"
  | "HUMAN_EVIDENCE_RECEIVED"
  | "DECISION_RESUMED";
```

- The backend **MUST** emit events in strictly increasing `sequence` per `decisionRecordId`. The frontend reverses order for display (newest-first) and **MUST NOT** be required to reorder by timestamp.
- `sequence` **MUST** be the dedupe key; re-delivery of the same `sequence` **MUST** be idempotent for the frontend.
- The backend **MUST NOT** require the frontend to consume any event type outside this list. `PRECEDENT_CONSULTED` **MAY** appear in the schema as reserved but **MUST NOT** be required to render while inactive.
- Events **MUST NOT** carry chain-of-thought or prompt text on any field.
- Expandable detail is permitted only on `TOOL_RESULT_BOUND` (bound value + object ref), `RECONCILIATION_COMPLETED` (material dimensions), and `DISPOSITION_COMPUTED` (requirement vs bound). Other events **SHOULD** be single-line.

---

## 4. Command contract

The frontend requires backend behavior for exactly the actions below. All other UI actions (navigation, opening a document, selecting a source, expanding a completed stage) are **UI-only** and the backend **MUST NOT** model them as commands.

### 4.1 ProvideHumanAuthorizedEvidence
```ts
type ProvideHumanAuthorizedEvidenceInput = {
  decisionRecordId: string
  expectedRunNumber: number           // optimistic concurrency
  evidence: { artifactRef: string; documentType: SourceArtifact["documentType"] }
  accountableAuthority: { id: string }
}
```
- On success the backend **MUST** resume the **same** `decisionRecordId` at `runNumber + 1` and emit `HUMAN_EVIDENCE_RECEIVED` then `DECISION_RESUMED`.
- The command **MUST** be idempotent under retry for the same `(decisionRecordId, expectedRunNumber, artifactRef)`.
- A domain refusal (evidence insufficient/rejected) **MUST** be returned as a distinct result from a technical failure (§9); it **MUST NOT** surface as a generic error.
- This command **MUST NOT** be modeled as "approve the AI"; it supplies evidence only.

### 4.2 KeepDecisionHeld (conditional)
```ts
type KeepDecisionHeldInput = { decisionRecordId: string; expectedRunNumber: number }
```
- The frontend requires this **only if** hold is a real backend state transition. If the backend has no such transition, it **MUST** declare so in conformance and the frontend will reclassify the control as UI-only. The frontend **MUST NOT** fabricate a hold state.

The frontend **MUST NOT** issue any command named start-investigation, run-verifier, compute-disposition, recalculate, continue, or next. Those states **MUST** arise from lifecycle events only.

---

## 5. Source-document retrieval contract

- Each `SourceArtifact` the viewer can open **MUST** carry a `viewRef` that resolves to a frontend-safe means of obtaining the document content (the backend **MAY** implement this as a pre-signed URL or a backend-mediated response; the frontend requires only that `viewRef` is openable without additional secret material).
- The viewer **MUST** receive enough metadata to render without fetching content: `displayName`, `documentType`, `trustClass`, `securityState`, `versionId`, `hash`, and `excludedFromDecisionUse`.
- For a quarantined artifact the backend **MUST** still return metadata and `hostileContentExcerpt`, and **MUST** set `excludedFromDecisionUse: true`; it **MUST NOT** silently omit the artifact.
- If no frontend-safe retrieval exists for an artifact, the backend **MUST** return `viewRef` absent and the frontend will render a "source unavailable" state (§9) while still showing metadata. The frontend **MUST NOT** invent a retrieval route.

---

## 6. Data delivery

- The frontend **MUST** be able to load a `DecisionWorkspace` projection and then obtain new `ActivityEvent`s ordered after a known `lastEventSequence` (cursor semantics on `sequence`).
- After any mutation event (`MUTATION_COMPLETED`, `CONSEQUENCE_RECALCULATED`, `RECOVERY_EXECUTED`, `DECISION_RESUMED`) the frontend **MUST** be able to re-read the authoritative projection to reconcile derived state.
- The contract **MUST NOT** assume a specific transport (stream vs poll). Whichever exists **MUST** provide: strict ordering by `sequence`, idempotent duplicate handling, a resumable cursor, and a terminal-state signal (disposition ∈ {RELEASED, QUARANTINED} with consequence settled, or QUALITY_DECISION_REQUIRED held open).
- Timers **MUST NOT** drive any production state transition; animation is bound to events (§8).

---

## 7. Active-stage derivation

The single active stage **MUST** be derivable deterministically from lifecycle events, switching only at these boundaries:

| New active stage | Entry event | Prior stage completes on |
|---|---|---|
| EVIDENCE | EVIDENCE_RECEIVED | — |
| INVESTIGATOR | INVESTIGATOR_STARTED | APPLICABILITY_BRIEF_COMPLETED |
| VERIFIER | VERIFIER_STARTED | VERIFIER_BRIEF_COMPLETED |
| RECONCILIATION | RECONCILIATION_COMPLETED | (immediate) |
| DISPOSITION | DISPOSITION_COMPUTED / QUALITY_DECISION_REQUIRED | MUTATION_COMPLETED (or held open) |
| QUALITY_CONTINUATION | QUALITY_DECISION_REQUIRED | HUMAN_EVIDENCE_RECEIVED |
| CONSEQUENCE | CONSEQUENCE_RECALCULATED | RECOVERY_EXECUTED / settled |

- `TOOL_CALLED` **MUST NOT** change the active stage.
- On `DECISION_RESUMED` the active stage **MUST** return to INVESTIGATOR at the new `runNumber` while prior-run stages remain available as completed projections.

---

## 8. Animation trigger bindings (event → motion)

Each is normative in that the frontend **MUST** drive the motion from the stated authoritative change, never a timer:
new Incoming row ← row added to `IncomingOverview.rows`; rail insert ← each new `ActivityEvent`; source trust flip ← `EVIDENCE_SECURITY_COMPLETED`; records-consulted row ← `TOOL_RESULT_BOUND`; agent result settle ← `*_BRIEF_COMPLETED`; reconciliation seal ← `RECONCILIATION_COMPLETED`; outcome appears ← `DISPOSITION_COMPUTED` / `QUALITY_DECISION_REQUIRED` / security quarantine; READY→BLOCKED ← `CONSEQUENCE_RECALCULATED`; recovery candidates ← `RECOVERY_EVALUATED`; resequence ← `RECOVERY_EXECUTED`; Run 2 begins ← `DECISION_RESUMED`; AT_RISK→READY ← `CONSEQUENCE_RECALCULATED` (run 2).

---

## 9. Error / failure contract

The backend **MUST** classify every failure into exactly one user-visible class below; the frontend **MUST NOT** collapse them into a generic error, and **MUST** visually distinguish domain abstention from technical failure.

```ts
type FailureClass =
  | "DOMAIN_ABSTENTION"     // insufficient evidence, MATERIAL_DISAGREEMENT → Quality decision, decision stays open
  | "TECHNICAL_FAILURE"     // model schema/timeout/unavailable, tool failure, persistence failure → retry where real
  | "SECURITY_HOLD"         // prompt attack / quarantine → spine halts, agents not started
  | "CONFLICT_STALE"        // optimistic-concurrency / stale mutation refusal → prompt refresh, no data loss
  | "POLICY_REFUSAL"        // policy declined the mutation
  | "SOURCE_UNAVAILABLE";   // viewRef missing or unresolvable → metadata still shown
```
- `DOMAIN_ABSTENTION` **MUST NOT** be presented as an error; it is a valid outcome (`QUALITY_DECISION_REQUIRED`).
- A `TECHNICAL_FAILURE` **MUST NOT** imply or display any disposition.
- `CONFLICT_STALE` **MUST NOT** clear existing authoritative state on screen.
- Every failure payload **MUST** carry `class: FailureClass` and a short display `reason`; it **MUST NOT** require the frontend to infer the class from HTTP status or free text.

---

## 10. Canonical demo dataset

For hero-path conformance the backend **MUST** be seedable with one canonical set the frontend renders verbatim: lots `L-2231` / `L-2262` / `L-2270`, material `Resin R-17` (and `Solvent X-9` for hostile), governing basis `S-88 Rev 4`, requirement `≥ 480 MPa`, bound value `462 MPa` via `Method M-12`, equivalence record `EQ-17`, supplier `Meridian Polymers` (and `Halden Chemical`), orders `C-417` / `C-418` / `C-419`, quantity `900 kg`, recovered slot `09:30`, authority `QA-Δ-118`. The frontend **MUST NOT** carry these as hard-coded fixtures in production; they **MUST** arrive through the read models above.

---

## 11. Information ownership (no duplication)

The frontend requires exactly one owner per concept; the backend **MUST NOT** force duplication that would let two owners disagree:
chronology → `ActivityEvent`; causal state → `DecisionSpine`; source content → `SourceArtifact`/viewer; governing/applicability work → `AgentStage`; agent comparison → `Reconciliation`; deterministic result → `Disposition_VM`; terminal summary → `OutcomeSummary`; factory impact → `Consequence`/`TodayPlan`; durable audit → `DecisionRecord`. Disposition **MUST NOT** be duplicated into `CaseContext`; supplier **MUST NOT** be duplicated into `CaseContext`; per-tool chronology **MUST NOT** be duplicated into `AgentStage`.

---

VOUCH V2 FRONTEND DATA CONTRACT READY FOR BACKEND CONFORMANCE

---

# Addendum — Sponsor Depth (Textract structured extraction)

**Status:** backend implemented, AWS-qualified locally; live Textract call
pending the external IAM grant. **Additive and fully optional.** Every field
below is absent for ordinary documents, so a consumer written before this
addendum reads exactly what it read before, unchanged.

## Why this exists

A table-formatted COA — the dominant real-world COA layout — parsed to ZERO
claims on the ordinary path (`pypdf` recovered every character;
`extraction_confidence` was `0.0`) and escalated to a human. Structure recovery
closes that. What the UI must convey is *why the claims became usable*, never
which vendor did it.

## Optional fields on the extraction projection

```ts
interface ExtractionProvenance {
  // Present on EVERY artifact. `false` for ordinary documents.
  structuredExtraction: boolean

  // Present ONLY when structuredExtraction === true.
  confidenceGatePassed?: boolean   // extraction confidence >= 0.75
  identityTrusted?: boolean        // recognition good enough to bind a lot id
  structuredReason?: string        // why the ordinary path was insufficient
  sourceLocators?: SourceLocator[] // one per recovered claim
}

interface SourceLocator {
  page: number         // 1-based
  table: number        // 1-based, within the page
  rowLabel: string     // e.g. "tensile_strength"
  columnLabel: string  // e.g. "result"
  cell: string         // e.g. "r2c4"
  line: number         // line in the emitted text, for claim -> row mapping
  confidence: number   // 0-1, the WORST cell confidence in that row
}
```

`extractionMethod` gains one value: `"TEXTRACT_TABLES"`, alongside
`DETERMINISTIC_PARSER`, `MODEL_FALLBACK` and `HUMAN_SUPPLIED`. **Treat this
field as an open value set** — render it, do not exhaustively switch on it.

## Lifecycle events

**No new event type.** `EVIDENCE_EXTRACTED` carries one added payload key,
`structured_extraction: boolean`, and its existing `method` field now admits
`TEXTRACT_TABLES`. The operator-visible semantic is unchanged: *evidence was
extracted into usable claims*.

## `identityTrusted` — the one genuinely new UI state

A document may be readable enough to yield measurements yet **not** readable
enough to bind a lot id. That combination cannot occur today and is a security
control, not a quality signal: a wrong measurement is caught downstream by
deterministic recompute against the governing spec, but a mis-read `LOT-1OO1`
binds evidence to the wrong lot and every later check then uses the wrong id.

When `identityTrusted === false` the artifact states no identity, binds to
nothing, and routes to a human — the same fail-closed outcome an unreadable
scan produces today.

## What must NOT be surfaced

- Textract, Amazon or AWS branding in any decision surface.
- Structure recovery as a separate pipeline stage. It sits behind the single
  existing extraction seam; there is one ingestion path by design.
- A second confidence number competing with `extractionConfidence`.
- Any implication that a *model* read the document. Textract is a deterministic
  extractor and is not the confined model fallback.
- Raw Textract response JSON. Only the shaped `SourceLocator` above.

## Hostile path unchanged

Security still halts the spine before extraction. A quarantined artifact
produces no claims, no locators, and no extraction presentation, and never
reaches the extractor at all (`test_a_quarantined_artifact_never_reaches_textract`).
