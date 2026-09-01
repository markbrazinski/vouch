# VOUCH V2 — Backend Conformance

**Answers:** `contracts/frontend/VOUCH_V2_FRONTEND_DATA_CONTRACT.md` (normative for
what the UI requires) and `VOUCH_V2_UI_COMPONENT_DATA_REQUIREMENTS.md`.

**Backend audited at:** `46b64585df47f20dfcc5e16525adfa951544060c`
(branch `finish/vouch-v2-backend`), working tree clean.

**Mode:** read-only audit. No backend code changed to produce this document.

Classifications, one per requirement:

| Code | Meaning |
|---|---|
| `SUPPORTED_AS_IS` | Backend already supplies the required truth directly. |
| `SUPPORTED_VIA_ADAPTER` | Backend truth exists; the frontend needs a projection. |
| `BACKEND_GAP` | The UI requirement is legitimate; the frozen backend lacks the truth. |
| `FE_CHANGE_REQUIRED` | The contract asks for something that cannot be supplied truthfully. |

Where a gap is closed by a pre-authorized bounded change, it is marked
`BACKEND_GAP → SUPPORTED after change <X>` and the change is named. The four
authorized changes are A (incremental event sink), B (per-run audit archive),
C (evidence I/O: C1 presigned retrieval, C2 PDF input + persisted document
classification), D (browser-safe transport seam).

---

## D1 — Executive verdict

# READY_FOR_ADAPTER_WITH_BOUNDED_CHANGES

The decision architecture is real, complete, and richer than the frontend
contract assumed. All 22 lifecycle event types the UI requires exist in
`EventType` and **every one has a live emit site**. Events are persisted with
monotonic per-record sequence numbers, stable derived event ids, and idempotent
appends. The DecisionRecord carries 17 structured segments including
reconciliation values, capability/mutation provenance, and human continuation.
Chain-of-thought leakage is structurally impossible, not merely discouraged.

What was missing was almost entirely the **read surface**. The AgentCore
entrypoint was a synchronous typed-action RPC with no way to list decisions,
fetch one, read events after a cursor, or serve an evidence document to a
browser. Those read paths existed as library calls and were simply unwired.

Two genuine semantic gaps were found beyond the read surface: events were
persisted only at terminal exit (change A), and Run 2 overwrote Run 1's
structured agent evidence (change B).

**Status at this revision.** Changes A and B have landed, and five read actions
— `list_decisions`, `get_decision`, `get_events`, `get_source`, `get_today` —
are shipped and strictly additive: 338 insertions to `app/Gatehouse/main.py`, no
deletions, and no change to any decision-semantic module. Gaps 1–5 in the
register are closed. What remains open is evidence content retrieval and PDF
input (change C), browser transport (change D), and the demo reseed.

`get_source` deliberately returns `view_ref: null` and
`retrieval_available: false` until change C. That is the correct answer, not a
placeholder — see D6.

**Corrections to the two prior audits.** `BACKEND_MAPPING_AUDIT.md` (`ea4c61f`)
and `BACKEND_CONTRACT_AUDIT_89d058a.md` (`89d058a`) predate the V2 rewrite and
audit `src/vouch/{state,tools,gates,workflow,schemas}.py` — a module layout that
no longer exists. Their findings were re-verified rather than trusted. Materially
revised:

- **"`AT_RISK` has no backend state" — WRONG for V2.** `Readiness.AT_RISK`
  exists (`consequences.py:31`) with `AT_RISK_THRESHOLD = 0.9` (`:39`).
- **"No DecisionRecord entity" — WRONG for V2.** `DecisionRecord`
  (`decision_record.py:227`) is a durable 17-segment entity with a stable id.
- **"Recovery reduces to one chosen action" — WRONG for V2.**
  `enumerate_recovery` (`consequences.py:307`) returns *every* candidate with a
  `verdict` and `reason_code`; `ELIGIBLE`/`REFUSED`/`NOT_FEASIBLE` coexist.
- **"Evidence attach is a hardcoded fixture writer" — WRONG for V2.**
  `supply_human_evidence` (`workflow.py:832`) takes caller-supplied bytes through
  the real ingestion boundary. The V1 fixture writer is gone.

---

## D2 — §1 Shared enums

| FE enum | Backend | Class |
|---|---|---|
| `TrustClass` (4 values) | `TrustLabel` (`contracts.py:34-41`) — `AUTHORITATIVE_INTERNAL`, `UNTRUSTED_SUPPLIER`, `HUMAN_AUTHORIZED`, `ADVISORY_PRECEDENT` | **SUPPORTED_AS_IS** — exact 4-for-4 match |
| `ReconciliationOutcome` | `ReconciliationOutcome` (`contracts.py:651-655`) — `MATCH`, `NON_MATERIAL_DIFFERENCE`, `MATERIAL_DISAGREEMENT`, `TECHNICAL_FAILURE` | **SUPPORTED_VIA_ADAPTER** — 3 of 4 match exactly; FE's `PENDING` is a pre-state, backend's `TECHNICAL_FAILURE` maps to FE §9 `TECHNICAL_FAILURE` |
| `Disposition` | `Disposition` (`contracts.py:643-648`) — `RELEASE`, `QUARANTINE`, `INSUFFICIENT_EVIDENCE`, `REJECT` | **SUPPORTED_VIA_ADAPTER** — verb→state mapping: `RELEASE`→`RELEASED`, `QUARANTINE`→`QUARANTINED`, `INSUFFICIENT_EVIDENCE`→`QUALITY_DECISION_REQUIRED`. `REJECT` is never engine-produced (`disposition.py:9-12`, refused at `authority.py:490`) — human policy only |
| `Readiness` | `Readiness` (`consequences.py:29-33`) — `READY`, `AT_RISK`, `BLOCKED`, `COMPLETE` | **SUPPORTED_VIA_ADAPTER** — FE's three match; backend `COMPLETE` has no FE target |
| `SecurityState` | Derived from `SecurityInspection` (`contracts.py:114-166`) | **SUPPORTED_VIA_ADAPTER** — `blocked`→`QUARANTINED`, `performed && !blocked`→`CLEARED`, else `PENDING` |
| `RecoveryVerdict` | `Verdict` (`consequences.py:254-260`) — `ELIGIBLE`, `NOT_FEASIBLE`, `REFUSED` | **SUPPORTED_AS_IS** — exact 3-for-3 match |
| `ActorType`, `ResultStatus`, `DecisionStageKey` | presentational | **SUPPORTED_VIA_ADAPTER** — derived from event `actor`/emitter |

**§1's unknown-value rule** (unrecognized enum → technical-failure for that
datum) is an adapter obligation; the backend cannot enforce it.

### Three enum traps the adapter must normalize

1. **`Sufficiency.INSUFFICIENT_EVIDENCE` (`contracts.py:493`) and
   `Disposition.INSUFFICIENT_EVIDENCE` (`:646`) are the same string in different
   enums with different meanings** — a model claim about *coverage* versus a
   computed *outcome*. Type separately in TS.
2. **Three representations of binding state**: `BindingStatus`
   (`evidence.py:473-489`) uses `MISMATCH`; `ArtifactStatus` (`contracts.py:169-183`)
   uses `EVIDENCE_BINDING_MISMATCH`; `FailureCategory` (`:671-676`) uses the
   latter too. Same condition, different strings.
3. **`Action` values are lowercase snake_case** (`authority.py:66-72`,
   e.g. `"release_lot"`) while every other enum is UPPER.

---

## D3 — §2 Read models

### §2.1 IncomingOverview / IncomingDecisionSummary

**`SUPPORTED_VIA_ADAPTER`** for the rows (`action: "list_decisions"`, shipped);
**`FE_CHANGE_REQUIRED`** for two of the four counts.

`list_decisions` queries the decisions-by-recency index and returns one row per
decision with `row_state` computed server-side, as §2.1 requires. Each row
carries `decision_record_id`, `lot_id`, `material_id`, `supplier_id`,
`received_at`, `quantity`, `units`, `lot_status`, `disposition`,
`failure_category`, `row_state`, `attention_required`, `decided_at`.

`counts` returns `{"returned": n}` only. `arrivedToday` is derivable from
`Lot.received_at` and can be added; **`inProgress` and `completedByVouch` are
not returned and must be removed from the FE contract** — invocation is
synchronous, so nothing is ever persisted mid-flight, and the model attributes
no decision to Vouch rather than a human. Any number for either would be fiction
rendered as fact.

Historical note — the gap this closed: `DynamoCorpus.all(kind)`
exists (`state.py:264`) but `DynamoRecordStore.list_ids()` **raises by design**
(`persistence.py:224-228`: "listing all records requires a GSI; query by record
id"). Every per-row datum is otherwise backed:

| Field | Source |
|---|---|
| `decisionRecordId` | `DecisionRecord.record_id` (`decision_record.py:230`) |
| `lotId` / `material` / `supplierName` | `Lot`, `Material`, `Supplier` (`corpus.py`) |
| `receivedAt` | `Lot.received_at` |
| `disposition` | `DispositionSegment.disposition` (`decision_record.py:152-154`) |
| `securityState` | `SecuritySegment` (`:55-77`) |
| `downstreamCommitment` | `ConsequenceSegment.caused_by` (`:211`) |
| `rowState` | Derivable from `decision_type` (`:280-299`) + `human.review_status` + `security.blocked` |

`rowState` **must be computed server-side** — §2.1 explicitly forbids the FE
deriving it from `stage` + `disposition` heuristics.

**`counts` is a partial `FE_CHANGE_REQUIRED`.** `arrivedToday` is derivable from
`Lot.received_at`. But `inProgress` is **not observable**: invocation is
synchronous, so no decision is ever persisted in a running state (change A makes
events visible mid-run but does not create an in-flight *record* state). And
`completedByVouch` requires a Vouch-versus-human attribution concept that does
not exist anywhere in the model. **Resolution: remove or rename both rather than
inventing backend state.**

### §2.2 DecisionWorkspace — `SUPPORTED_VIA_ADAPTER`

Served by `action: "get_decision"`, which returns the **whole stored document**
— all 17 segments plus `run_count`, `terminal` and `archived_runs` — rather than
the lossy `_record_summary`. It also returns `sources` (§2.5) and
`last_event_sequence`, so a workspace load is one call.

`lastEventSequence` is real and authoritative: `StorageSegment.last_event_sequence`
(`decision_record.py:202`), written at `workflow.py:1141-1143` as
`next_sequence(record_id) - 1`.

`currentStageKey` derives from the latest §7 boundary event. §2.2's requirement
that it "MUST NOT change on individual tool calls" is satisfiable because
`TOOL_CALLED` (`tools.py:134`) is distinct from every boundary event.

`currentRunNumber` = `DecisionRecord.run_count` (`decision_record.py:231`).

### §2.3 DecisionSpine — `SUPPORTED_VIA_ADAPTER`

Four nodes project from event presence + `reconciliation.outcome` + `disposition`.

§2.3's load-bearing rule — "the verifier lane value MUST NOT be derived from the
investigator lane" — is **structurally satisfied**: `record.investigator` and
`record.verifier` are separate `AgentSegment`s (`decision_record.py:239-240`),
each with its own `brief`, `brief_hash` and `tool_events`, and the verifier never
receives the investigator's brief (asserted `test_pipeline.py:119`).

`reconciliationSeal` maps from `ReconciliationOutcome` plus a `HALTED` case for
`FailureCategory.SECURITY_QUARANTINE`.

**Adapter note:** read the verifier lane from `record.verifier.brief`, **not**
from `VERIFIER_BRIEF_COMPLETED` — that event carries only `brief_hash`
(`agents.py:328` gates the other four keys to the investigator role).

### §2.4 CaseContext — `SUPPORTED_VIA_ADAPTER`

`governingBasis` from `BasisSegment.{spec_id, revision}` (`decision_record.py:144-148`).
`boundFact` from the `CanonicalEvidenceClaim` bound to the governing requirement
(`evidence.canonical_claims`, `contracts.py:238-268`).

§2.4's prohibition on carrying supplier or disposition is an FE concern; the
backend forces no duplication.

### §2.5 SourceArtifact

| Field | Backend | Class |
|---|---|---|
| `artifactId` | `f"ART-{uuid4().hex[:12]}"` (`evidence.py:253`) | AS_IS |
| `trustClass` | `TrustLabel` | AS_IS |
| `versionId` | S3 `VersionId` (`aws.py:167`) → `evidence.object_versions[i]` | AS_IS |
| `hash` | SHA-256 → `evidence.source_artifact_hashes[i]` | AS_IS |
| `securityState` | `SecurityInspection` | ADAPTER |
| `excludedFromDecisionUse` | `artifact_id` ∈ `quarantined_artifact_ids` ∪ `rejected_artifact_ids` ∪ `unbound_artifact_ids` (`decision_record.py:69-76`) | ADAPTER |
| `pageCount` / `sourceLocators` | Claims carry `"page:N/line:M"` (`evidence.py:751-752`) | ADAPTER |
| `declaredClaims` / `highlightedClaims` | `evidence.canonical_claims` | ADAPTER |
| `displayName` | none | ADAPTER (compose) |
| `documentType` | **not persisted** — see below | GAP → SUPPORTED after **C2** |
| `viewRef` | **none** | GAP → SUPPORTED after **C1** |
| `hostileContentExcerpt` | **none, deliberately** | **FE_CHANGE_REQUIRED** |

**`documentType` gap.** `content_type` is accepted at ingestion
(`evidence.py:107-165`) and emitted on `EVIDENCE_RECEIVED` (`:260-274`), but is
**not persisted on the artifact**: `EvidenceSegment` (`decision_record.py:36-51`)
holds eight parallel per-artifact lists and none carries it. Change C2 adds it,
index-aligned. **The alignment invariant at `decision_record.py:342-366` covers
five lists in its `aligned` tuple plus a separate `binding_statuses` check; the
new list must be added there or it will drift silently while the check passes.**

**`viewRef` gap.** `S3EvidenceStore.get_original` (`aws.py:172-181`) returns raw
bytes **in-process**, has **zero callers in `src/`**, and no presigned-URL
generation exists anywhere (`grep -r 'presign\|generate_presigned' src/ app/
scripts/` → nothing). IAM already grants `s3:GetObject` and `s3:GetObjectVersion`
on `${BUCKET}/evidence/*` (`iam/agent_runtime_policy.json`, Sid
`EvidenceObjectsReadWriteNoDelete`), so the permission to sign exists. There is
also no `storage_ref` → `(bucket, key)` parser; `storage_ref` is written as
`f"s3://{bucket}/{full_key}"` (`aws.py:169`) and nothing parses it back.

**`hostileContentExcerpt` — FE_CHANGE_REQUIRED.** The backend deliberately never
puts attack text in an event: `lifecycle._FORBIDDEN_KEYS` (`lifecycle.py:64`)
structurally rejects reasoning-shaped payload keys, and echoing injection strings
into an audit surface is its own risk. The artifact **is** retained
(`test_security_redteam.py:345-350`). **Resolution: the viewer opens the retained
quarantined source via `viewRef`; the field is dropped from the contract.**

### §2.6 AgentStage / StageEnvelope — `SUPPORTED_VIA_ADAPTER`

`AgentSegment` (`decision_record.py:96-116`) carries `model_id`, `prompt_version`,
`prompt_hash`, `brief_hash`, `tool_events`, `schema_valid`, `attempts`,
`brief_rejected`, `brief`, `failure`, `failure_category`.

`recordsConsulted` projects from `TOOL_RESULT_BOUND` (`tools.py:138-142`:
`agent`, `tool`, `result_count`, `object_refs` capped at 20, `elapsed_ms`).
§2.6's rule that per-call chronology belongs in `ActivityEvent` and not here is
an FE concern.

`state` mapping: `DOMAIN_INSUFFICIENCY` ← brief `sufficiency ==
Sufficiency.INSUFFICIENT_EVIDENCE`; `TECHNICAL_FAILURE` ← `AgentSegment.failure_category`
∈ {schema failure, timeout, unavailable, tool failure}.

### §2.7 Reconciliation — `SUPPORTED_AS_IS`

`ReconciliationSegment` (`decision_record.py:120-127`) holds `outcome`,
`differing_fields`, **and** `investigator_values` / `verifier_values` dicts —
precisely §2.7's `dimensions[]`.

§2.7's "`dimensions` MUST contain only material dimensions; the FE MUST NOT
filter" is **already satisfied**: `differing_fields` is drawn from the seven
`material_fingerprint()` keys (`reconcile.py:102`, fingerprint at
`contracts.py:579-632`), which is by construction the material comparison
surface. Non-material differences (e.g. `investigation_notes`) produce
`NON_MATERIAL_DIFFERENCE` with an empty `differing_fields` (`reconcile.py:108`).

### §2.8 Disposition_VM — `SUPPORTED_VIA_ADAPTER`

`disposition`/`reason` from `DispositionSegment`; `requirementValue` from the
governing `Requirement` (`corpus.py`); `boundValue` from the canonical claim;
`basisChain` composed from `BasisSegment` + `PolicySegment` + `CapabilitySegment`;
`stateMutation` from `MutationSegment` (`decision_record.py:173-189`:
`before_version`, `after_version`, `inventory_delta`, `ledger_sequence`).

`qdrQuestion` / `materialDifferences` from the `QUALITY_DECISION_REQUIRED` event
`reason` code (`workflow.py:1198-1202`, one of `DISAGREEMENT` / `INJECTION` /
`INSUFFICIENT` / `ABSTAIN`) plus `differing_fields`.

§2.8's rule that a QDR must not imply a mutation is **structurally supported**:
`record.fail()` (`decision_record.py:255-262`) never rewrites disposition, and an
abstention's only mutation is `create_qa_review`.

### §2.9 Consequence / RecoveryEvaluation — `SUPPORTED_AS_IS`

`ConsequenceSegment` (`decision_record.py:206-211`) holds `coverage_changes`,
`readiness_changes`, `recovery`, `caused_by`.

§2.9's central requirement — "MUST include every evaluated candidate with its
verdict, including refused/infeasible ones" — is **already met**:
`enumerate_recovery` (`consequences.py:307-425`) returns the full option list and
`RecoveryOption.as_dict()` (`:281-286`) emits `{kind, candidate_id, verdict,
reason_code, facts}`. `REFUSED` and `NOT_FEASIBLE` are deliberately distinct
(`:257-259`: "could physically do but is not permitted to") and **must render
differently**.

`executed` from `RECOVERY_EXECUTED` (`workflow.py:802-814`).

### §2.10 QualityContinuation — `SUPPORTED_VIA_ADAPTER`

`HumanContinuationSegment` (`decision_record.py:215-221`) holds
`evidence_supplied`, `authority_source`, `content_hashes`, `resumed_run_ids`,
`review_id`, `review_status`, `final_outcome`.

§2.10's requirement that "a resume MUST be the same `decisionRecordId` with an
incremented `runNumber`" is **exactly what the backend does**:
`supply_human_evidence` (`workflow.py:832`) hydrates the same record, calls
`rerun()` (`:915`), and re-enters `evaluate_lot` on the same id (`:935-937`).

### §2.11 OutcomeSummary — `SUPPORTED_VIA_ADAPTER`

No precomputed outcome projection exists (answering D23 Q3: **compose FE-side**).
All four `kind`s and their required `facts` are reachable from `disposition` +
`failure_category` + `basis` + `consequences` + `security`.

### §2.12 TodayPlan — `SUPPORTED_VIA_ADAPTER` (`action: "get_today"`, shipped)

`get_today` recomputes readiness for every order through the same
`compute_readiness` the decision path uses, so the read cannot drift from what a
decision would conclude (asserted by test). It returns `readiness_counts` and
orders grouped by resource, each with `planned_slot`, `status`, `readiness`,
`reason`, `coverage`, `requirements`, `customer_committed`, `need_by` and
`state_version`.

There is deliberately **no before/after and no change banner**. Which change to
highlight is a presentation question the frontend answers from `caused_by`
links; a backend that guessed would be inventing operational history. §2.12
already classes that presentation as DERIVED_UI.

`compute_readiness` (`consequences.py:78-105`) returns `{order_id, readiness,
coverage, reason}` per order. `causedByDecisionRecordId` from
`caused_by[].decision_record_id` (`consequences.py:156-165`) — §2.12 requires it
on any order whose readiness changed, and the backend supplies it.

Gap: `action: "readiness"` is per-order; a board-level read needs `get_today`.

### §2.13 DecisionRecord (durable audit)

**`SUPPORTED_AS_IS`** (change B shipped; served by `get_decision`).

`archived_runs` holds every completed run and `runs()` returns history plus the
current run. Verified across a cold restart: a `JsonRecordStore` reopened in a
fresh process returns Run 1's `INSUFFICIENT_EVIDENCE` brief alongside Run 2's
`RELEASE`, with typed hydration (`ArchivedRun` → `AgentSegment`) intact.

Historical note — the loss this closed. The record was **flat single-run**: `investigator`, `verifier`, `reconciliation`
are singular segments (`decision_record.py:239-241`). `rerun()` (`:262-265`)
increments `run_count` and appends a run id, but **Run 2 overwrites Run 1's
brief, tool events and reconciliation values**. §2.13's `runs[]` is therefore not
reconstructible from the record alone.

It *is* partially reconstructible from the durable event stream (partition on
`DECISION_RESUMED`), since `APPLICABILITY_BRIEF_COMPLETED`,
`VERIFIER_BRIEF_COMPLETED` and `RECONCILIATION_COMPLETED` persist per run at
increasing sequences — but the event payloads carry hashes and counts, not brief
bodies. Change B adds a bounded per-run archive (structured briefs, hashes, tool
metadata; no chain-of-thought).

§2.13's "MUST be served as a stable projection; the FE MUST NOT reconstruct by
replaying events" is satisfied by `get_decision` returning the stored document.

---

## D4 — §3 Event contract

All 22 FE-required event types exist in `EventType` (`lifecycle.py:25-59`) and
**every one has a live emit site**. No FE event needs fabricating. Full matrix:

| FE event | Emit site | Class |
|---|---|---|
| `EVIDENCE_RECEIVED` | `evidence.py:260` | AS_IS |
| `EVIDENCE_SECURITY_COMPLETED` | `evidence.py:344` | AS_IS |
| `EVIDENCE_EXTRACTED` | `evidence.py:882` | ADAPTER (no page_count/locators in payload) |
| `EVIDENCE_BINDING_COMPLETED` | `evidence.py:365` | AS_IS |
| `EVIDENCE_SNAPSHOT_CREATED` | `evidence.py:1015` | AS_IS |
| `INVESTIGATOR_STARTED` | `agents.py:291` | AS_IS |
| `TOOL_CALLED` | `tools.py:134` | AS_IS |
| `TOOL_RESULT_BOUND` | `tools.py:138` | AS_IS |
| `APPLICABILITY_BRIEF_COMPLETED` | `agents.py:336` | AS_IS |
| `VERIFIER_STARTED` | `agents.py:291` | AS_IS |
| `VERIFIER_BRIEF_COMPLETED` | `agents.py:336` | ADAPTER — **`brief_hash` only** (`agents.py:328`) |
| `RECONCILIATION_COMPLETED` | `reconcile.py:93`, `:117` | AS_IS |
| `DISPOSITION_COMPUTED` | `disposition.py:157` | AS_IS |
| `POLICY_EVALUATED` | `authority.py:459`, `:522`, `:554`, `:618` | ADAPTER — two shapes, `reason` XOR `action` |
| `CAPABILITY_ISSUED` | `authority.py:526`, `:622` | AS_IS |
| `MUTATION_COMPLETED` | `authority.py:894` | AS_IS |
| `CONSEQUENCE_RECALCULATED` | `consequences.py:188` | AS_IS |
| `RECOVERY_EVALUATED` | `workflow.py:752` | ADAPTER — counts only; candidates from the record |
| `RECOVERY_EXECUTED` | `workflow.py:802` | AS_IS |
| `QUALITY_DECISION_REQUIRED` | `workflow.py:696`, `:1204` | ADAPTER — two shapes |
| `HUMAN_EVIDENCE_RECEIVED` | `workflow.py:882` | AS_IS |
| `DECISION_RESUMED` | `workflow.py:924` | AS_IS |

**Backend events outside the FE vocabulary** — must be schema-tolerated, not
rendered as unknown-enum failures: `EVIDENCE_BINDING_MISMATCH`
(`evidence.py:379`), `BRIEF_VALIDATION_FAILED` (`workflow.py:1026`),
`READINESS_TRANSITIONED` (`consequences.py:241`). The last is genuinely useful to
Today and **should be added** to the FE vocabulary.

**`PRECEDENT_CONSULTED`** is declared (`lifecycle.py:58-59`) and **never
emitted** — grep confirms zero emit sites. §3's reserved-but-unrendered treatment
is correct (answering D23 Q10).

### §3's four delivery rules

| Rule | Status |
|---|---|
| Strictly increasing `sequence` per record | **SUPPORTED_AS_IS** — `sk` is `EVENT#%06d` (`persistence.py:235-241`); `next_sequence` continues past the prior run (`:246-271`) so continuations extend history |
| `sequence` is the dedupe key; re-delivery idempotent | **SUPPORTED_AS_IS** — stable derived `event_id` (`:57-60`) + `ConditionExpression="attribute_not_exists(sk)"` (`:243`) |
| No chain-of-thought on any field | **SUPPORTED_AS_IS, structurally** — `_FORBIDDEN_KEYS` (`lifecycle.py:64`) raises on any payload key containing `chain_of_thought`, `reasoning`, `rationale`, `raw_prompt`, `prompt_text` |
| Expandable detail only on three types | FE concern |

### Two wire shapes for the same event — adapter must pick one

- `EventLog.as_dicts()` (`lifecycle.py:103-108`) — key `"event"`, payload
  **flattened**, **no `sequence`, no `event_id`**. This is what the runtime
  returns today inside `evaluate_lot`.
- `persistence._event_row()` (`persistence.py:54-68`) — key `"event"`, payload
  **nested**, **with `event_id` and `sequence`**. This is what is durable.

**The read API must serve the persisted shape**, since `sequence` is the
contract's dedupe key.

### Payload naming traps

- `ledger_seq` (`MUTATION_COMPLETED` `authority.py:894`, `READINESS_TRANSITIONED`
  `consequences.py:241`) versus `ledger_sequence` (`RECOVERY_EXECUTED`
  `workflow.py:802`).
- `READINESS_TRANSITIONED` has a payload key literally named **`from`**, passed
  via `**{"from": ...}` because it is a Python keyword.

---

## D5 — §4 Commands

### §4.1 ProvideHumanAuthorizedEvidence — `SUPPORTED_AS_IS` (semantics) / `SUPPORTED_VIA_ADAPTER` (shape)

`VouchV2.supply_human_evidence` (`workflow.py:832-841`, keyword-only), exposed as
`action: "supply_evidence"` (`main.py:168-192`).

| §4.1 requirement | Status |
|---|---|
| Resume the **same** `decisionRecordId` at `runNumber + 1` | **Met** — `resume()` hydrates the same record (`:850`), `rerun()` increments (`:915`) |
| Emit `HUMAN_EVIDENCE_RECEIVED` then `DECISION_RESUMED` | **Met** — `:882` then `:924`, in that order |
| Idempotent under retry for the same evidence | **Met** — content-hash guard (`:868-874`) returns early with `reason="evidence already attached to this record"`; no `rerun()`, no duplicate |
| Domain refusal distinct from technical failure | **Met structurally** — `disposition` and `failure_category` are separate channels; `record.fail()` never rewrites disposition (`decision_record.py:255-262`) |
| MUST NOT be modeled as "approve the AI" | **Met** — the command takes evidence bytes + `authority_source`, labels it `TrustLabel.HUMAN_AUTHORIZED` (`:865`), and the release is recomputed deterministically |

Shape gaps (adapter/backend-additive): no `expectedRunNumber` optimistic
concurrency parameter; `documentType` not accepted; `accountableAuthority` is a
bare `authority_source` string rather than `{id}`.

### §4.2 KeepDecisionHeld — `FE_CHANGE_REQUIRED`

**No such transition exists.** `LOT_TRANSITIONS` (`authority.py:404-410`) has no
hold state, and `PENDING_QA` is already entered automatically by
`create_qa_review`. Per §4.2's own escape clause the backend declares this, and
the control is **reclassified UI-only**. The FE must not fabricate a hold state.
(Answers D23 Q5.)

§4's prohibition on progression commands (start-investigation, run-verifier,
recalculate, continue, next) is satisfied — no such action exists in `main.py`.

---

## D6 — §5 Source-document retrieval

**`SUPPORTED_VIA_ADAPTER`** for metadata (`action: "get_source"`, shipped);
**`BACKEND_GAP`** for content retrieval (change C1).

`get_source` returns every artifact on a record, or one by `artifact_id`, with
`content_type`, `trust_class`, `security_state`, `content_hash`,
`object_version`, `storage_ref`, `binding_status`, `received_at`, `claim_count`,
`excluded_from_decision_use` and `prompt_attack_detected`.

`view_ref` is `null` on every artifact and the response states
`retrieval_available: false`. That is the correct answer at this checkpoint, not
a placeholder: faking a reference would make a frontend render a broken viewer
instead of §5's "source unavailable" state.

**One implementation note the earlier audit missed.** `EvidenceSegment` carries
hashes, refs and versions in index-aligned lists but **no `artifact_id`**. The id
appears only in event payloads and the security exclusion sets, so `get_source`
assembles artifacts from the event stream and joins exclusions by id. The
metadata is all there; it simply is not on the segment.

A quarantined artifact is returned, never omitted, with
`excluded_from_decision_use: true` — verified against `COA_HOSTILE`. Detail in
D3 §2.5 above.

§5's fallback is already honored by design: when no frontend-safe retrieval
exists the backend returns `viewRef` absent and the FE renders "source
unavailable" **while still showing metadata**. Metadata sufficient to render
without fetching (`displayName`, `documentType`, `trustClass`, `securityState`,
`versionId`, `hash`, `excludedFromDecisionUse`) is available after C2.

§5's rule that a quarantined artifact must still return metadata and must not be
silently omitted is **structurally satisfied** — the artifact is retained, not
dropped (`test_security_redteam.py:345-350`).

---

## D7 — §6 Data delivery

**`SUPPORTED_VIA_ADAPTER`** for ordering, dedupe and cursor (shipped);
**`BACKEND_GAP`** for browser transport only (change D).

`action: "get_events"` serves the persisted row shape — `event_id`, `sequence`,
`event`, `decision_record_id`, `at`, nested `payload` — with `after_sequence`
and `limit`. Verified: strictly ascending and gapless across
Run 1 → `DECISION_RESUMED` → Run 2 (33 → 67 events, run-1 prefix byte-identical),
stable unique `event_id`s of the form `{record_id}#{sequence:06d}`, and a poll at
the high-water mark returning `[]` without rewinding the cursor.

Historical note — what this replaced.

Today: invocation is a synchronous typed-action RPC (`main.py:248`); there is no
`async`, generator, SSE or WebSocket anywhere in the repo; and **events are
persisted once, at terminal exit** — `_persist` (`workflow.py:1115`) is the only
writer, called on every exit path (`:330`, `:702`, `:1209`). Polling mid-run
therefore returns nothing.

`EventLog.__init__` already accepts `sinks` (`lifecycle.py:86`), invoked
synchronously in `emit` (`:93-94`), and **no production caller passes any**. That
is the intended hook for change A and requires no change to `lifecycle.py`.

| §6 requirement | Status after A + D + read API |
|---|---|
| Load a workspace projection, then events after `lastEventSequence` | **Met** — `get_decision` + `get_events(after_sequence)` |
| Re-read authoritative projection after mutation events | **Met** — `get_decision` |
| Transport-agnostic; ordering, dedupe, resumable cursor, terminal signal | **Met** — polling with a sequence cursor |
| Timers MUST NOT drive state transitions | **Met** — all motion event-bound |

**Terminal-state detection.** `DecisionRecord.terminal`
(`decision_record.py:252`) **is written**, at `workflow.py:701`:

```python
record.terminal = result.disposition in (Disposition.RELEASE, Disposition.QUARANTINE)
```

So it is `True` only for a settled RELEASE/QUARANTINE and `False` for an
abstention — which is exactly right, since §6 requires a QUALITY_DECISION_REQUIRED
case to stay held open. Note it is assigned **only on the autonomous path**; the
`_quality_decision` escalation path (`workflow.py:1185-1215`) leaves it at its
`False` default, and a security quarantine or technical failure therefore also
reads `terminal == False`.

`terminal` alone is thus necessary but not sufficient: it distinguishes settled
from open, but not "open awaiting a human" from "open because it failed". Combine
it with `decision_type` (`:280-299`, one of `AUTHORIZED_ESCALATION` /
`AUTONOMOUS_MUTATION` / `ESCALATED` / `INCOMPLETE`), `human.review_status`, and
`DecisionOutcome.quality_decision_required` for the full terminal signal §6 asks
for.

**Read-surface inventory.** These exist as library calls and are **not exposed by
any action**: `RecordStore.load` (`persistence.py:215`), `EventStore.events_for`
(`:290`), `VouchV2.resume` (`workflow.py:193`), `S3EvidenceStore.get_original`
(`aws.py:172`). Only `ledger_for` is reachable, via `action: "ledger"`.

**Two defects in the existing read path**, to fix while wiring it up:
1. `DynamoRecordStore.events_for` (`persistence.py:290-309`) **does not
   paginate** — no `LastEvaluatedKey` handling, so a record with >1MB of events
   silently truncates.
2. It has **no `after_sequence` parameter** — all-or-nothing reads only.

**`_record_summary` is lossy** (`main.py:87-133`) and must not back the
workspace: it omits `evidence` entirely, plus `extraction`, `corpus`, `storage`,
`human`, `consequences.coverage_changes/readiness_changes/recovery`,
`reconciliation.differing_fields` and the two values dicts, brief bodies (only
`len(tool_events)`), `disposition.reason`, `policy.refusal_reason`, and
`mutation.result`/`inventory_before`/`inventory_after`.

---

## D8 — §7 Active-stage derivation — `SUPPORTED_AS_IS`

Every boundary event in §7's table exists and is emitted (D4). `TOOL_CALLED` is
distinct from all of them, so §7's "MUST NOT change the active stage" holds.

On `DECISION_RESUMED` the active stage returns to INVESTIGATOR at the new
`runNumber` — supported, since `supply_human_evidence` re-enters `evaluate_lot`
on the same record (`workflow.py:935-937`) and prior-run events remain at lower
sequences.

---

## D9 — §9 Failure taxonomy — `SUPPORTED_VIA_ADAPTER`

`FailureCategory` (17 members, `contracts.py:658-686`) maps onto the FE's six
classes:

| FE `FailureClass` | Backend `FailureCategory` |
|---|---|
| `DOMAIN_ABSTENTION` | `DOMAIN_INSUFFICIENT_EVIDENCE`, `MATERIAL_DISAGREEMENT` |
| `TECHNICAL_FAILURE` | `INVESTIGATOR_SCHEMA_FAILURE`, `VERIFIER_SCHEMA_FAILURE`, `MODEL_TIMEOUT`, `MODEL_UNAVAILABLE`, `TOOL_FAILURE`, `PERSISTENCE_FAILURE` |
| `SECURITY_HOLD` | `SECURITY_QUARANTINE` |
| `CONFLICT_STALE` | `STATE_CONFLICT` |
| `POLICY_REFUSAL` | `POLICY_REFUSAL`, `BRIEF_CONTRACT_VIOLATION` |
| `SOURCE_UNAVAILABLE` | `EXTRACTION_LOW_CONFIDENCE`, `EVIDENCE_BINDING_MISMATCH`, `EVIDENCE_UNBOUND`, `EVIDENCE_IDENTITY_CONFLICT`, plus absent `viewRef` |

§9's "a `TECHNICAL_FAILURE` MUST NOT imply or display any disposition" is
**structurally supported**: `record.fail()` (`decision_record.py:255-262`) never
rewrites disposition, so a technical failure leaves it empty.

Retry affordances are honest only where `RETRYABLE` (`contracts.py:691-701`)
includes the category: schema failures, timeouts, unavailability, tool failure,
persistence failure, state conflict.

Every failure payload carries `failure_category` explicitly (`main.py:229-240`),
so §9's "MUST NOT require the FE to infer the class from HTTP status or free
text" is met — **except** for the `KeyError` and generic-`Exception` handlers
(`main.py:241-245`), which return a bare `{"ok": false, "error": ...}` with no
`failure_category`, no `action` and no `backend`. The adapter must treat those as
`TECHNICAL_FAILURE`.

---

## D10 — §10 Canonical demo dataset — `RESEED`

The backend's demo world (`fixtures.py`, seeded by `scripts/seed_demo_corpus.py`)
is complete and coherent but differently named. Causal structure matches
exactly. Full mapping is in the plan's D8; the load-bearing points:

- **Already canonical:** `C-417` / `C-418` / `C-419` (`fixtures.py:222/230/238`),
  `462` (`:37`, in `COA_HERO`), `480.0` (`:112`, `REQ-A7-C-1.min_value`).
- **Pure rename:** lots, spec, suppliers, method, equivalence, slot.
- **Not a rename — semantic:** the docs' `900 kg` is LOT-9001's *substitute
  stock* (`:205,216`), while C-417 actually requires **800.0** of MAT-ALLOY-7
  (`:224`). Decision taken: change the fixture to 900.0 so the story is backed by
  real state.
- **Not a rename — semantic:** the docs use one material (`Resin R-17`) for both
  heroes; the backend correctly uses two (`MAT-ALLOY-7` alloy / `MAT-RESIN-3`
  polymer) governed by different specs with different characteristics. Decision
  taken: preserve the distinction rather than assert a false equivalence.
- **`QA-Δ-118` is UNSUPPORTED as a literal.** QA ids are derived:
  `f"QA-{record_id}"` (`workflow.py:694`) over `f"DR-{uuid4().hex[:12]}"`
  (`:320`). Render the real derived id.

§10's "the FE MUST NOT carry these as hard-coded fixtures in production" is an FE
obligation, asserted by the production-build test.

---

## D11 — §11 Information ownership — `SUPPORTED_AS_IS`

The backend forces no duplication that would let two owners disagree. Each
concept has exactly one authoritative home: chronology in the event stream,
causal state in the record segments, source content in `EvidenceSegment`,
agent work in the two `AgentSegment`s, comparison in `ReconciliationSegment`,
deterministic result in `DispositionSegment`, factory impact in
`ConsequenceSegment`, durable audit in the record document.

---

## D12 — Answers to §D23 backend contract questions

1. **Streaming or polled?** Polled, ordered by `sequence`. No streaming exists;
   none is recommended. Ordering is guaranteed by the `EVENT#%06d` sort key.
2. **Stable source reference?** `storage_ref` + `object_version` + `content_hash`
   are persisted. Locators and claims come from the backend
   (`CanonicalEvidenceClaim.source_locator`); highlighting is FE-derived.
3. **Precomputed Outcome projection?** No — compose FE-side from authoritative
   fields.
4. **Human-evidence command?** `supply_evidence` →
   `VouchV2.supply_human_evidence`. Accepted/refused/failed are distinguishable:
   `disposition` (domain) versus `failure_category` (technical), plus the
   idempotent `reason="evidence already attached to this record"`.
5. **Is "Keep held" real?** No. UI-only.
6. **Today readiness read model?** `compute_readiness` per order exists;
   a board-level `get_today` must be added.
7. **Completed stage as stable projection?** Yes for the current run
   (`get_decision`); per-run history needs change B.
8. **Run boundaries explicit?** `run_count` is on the record and on
   `DECISION_RESUMED`; most other event payloads do **not** carry `run_number`,
   so the adapter partitions on `DECISION_RESUMED`.
9. **Security exclusion vs merely untrusted?** Distinct and structural.
   *Untrusted* is `TrustLabel.UNTRUSTED_SUPPLIER` — normal supplier evidence that
   still yields claims. *Excluded* is membership in
   `security.quarantined_artifact_ids` / `rejected_artifact_ids` /
   `unbound_artifact_ids`, which yields **zero claims** and halts the spine.
10. **`PRECEDENT_CONSULTED` inactive?** Confirmed — declared, never emitted.

---

## D13 — Gap register

| # | Gap | Class | Closure |
|---|---|---|---|
| # | Gap | Class | Status |
|---|---|---|---|
| 1 | No decision/lot list read path | BACKEND_GAP | **CLOSED** — `list_decisions` on the GSI |
| 2 | No `get_decision` / `get_events` / `get_today` actions | BACKEND_GAP | **CLOSED** — all three shipped |
| 3 | `events_for` has no cursor and no pagination | BACKEND_GAP | **CLOSED** — `after_sequence`, `limit`, `LastEvaluatedKey` |
| 4 | Events persisted only at terminal exit | BACKEND_GAP | **CLOSED** — change A |
| 5 | Run 2 overwrites Run 1 agent evidence | BACKEND_GAP | **CLOSED** — change B |
| 6 | No presigned/browser-safe evidence retrieval | BACKEND_GAP | open — change C1 |
| 7 | PDF unreachable from the runtime entrypoint | BACKEND_GAP | open — change C2 |
| 8 | `documentType` not persisted at ingestion | BACKEND_GAP | open — change C2 |
| 9 | No browser-safe transport (no CORS, SigV4 only) | BACKEND_GAP | open — change D |
| 10 | `hostileContentExcerpt` | FE_CHANGE_REQUIRED | Viewer opens retained source |
| 11 | `KeepDecisionHeld` | FE_CHANGE_REQUIRED | UI-only |
| 12 | `inProgress` / `completedByVouch` counts | FE_CHANGE_REQUIRED | **Confirmed** — not returned by `list_decisions` |
| 13 | Demo identifiers + two semantic mismatches | RESEED | open — reseed; C-417 → 900.0 |

**Also found while implementing the read actions**, and worth recording because
neither audit had it:

| # | Finding | Where |
|---|---|---|
| 14 | `EvidenceSegment` carries no `artifact_id`; the id lives only in event payloads and the security exclusion sets | `decision_record.py:36-51` |
| 15 | The staged runtime copy under `app/Gatehouse/src/` shadows `src/` on `sys.path` and was stale; the deployed runtime can silently serve older code | `main.py:37`, `scripts/stage_runtime.py` |

Nothing in this register requires rearchitecting, and none of it touches agent
prompts, decision semantics, disposition, authority or mutation.

---

VOUCH V2 BACKEND CONFORMANCE COMPLETE
