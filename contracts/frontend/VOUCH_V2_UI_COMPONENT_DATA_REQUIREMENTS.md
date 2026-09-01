# VOUCH V2 — UI Component & Data Requirements

**Claude Design → React / Integration Handoff**
Authoritative source artifact: `Vouch Journey.dc.html` (two-column, TWO_COLUMN locked).
This document states **what the UI needs**. It does **not** define endpoints, transport, or backend schemas — that is the next agent's job.

Conventions for data source-class:
`AUTH` = AUTHORITATIVE_STATE · `EVT` = LIFECYCLE_EVENT · `DERIVED` = DERIVED_UI_STATE · `COPY` = STATIC_PRODUCT_COPY · `SRC` = SOURCE_REFERENCE

---

## D1 — Frozen UI architecture

- **Global shell:** left `PrimaryNavigation` (Today · Incoming · Suppliers · Records) | main workspace | (in a decision) far-right `DecisionActivityRail`.
- **Entry point:** `Incoming` list. A material/evidence event creates a decision row; opening a row opens the full-page decision workspace. No "Start Vouch" control.
- **Decision workspace (two-column inner):**
  - `DecisionHeader` (lot identity + current disposition pill) and `DecisionSpine` span full width at top; `OutcomeSummary` appears beneath the spine when terminal/decision-open.
  - **Left inner column** = `CaseContextColumn` (sticky): persistent source + established truth.
  - **Right inner column** = `ActiveStageSlot` (dominant current stage) + `CompletedStageStack` (collapsed, reopenable) below it.
  - **Reconciliation, Consequence, Recovery** break out to **full inner width** (left column drops) when they are the active stage.
  - Far-right `DecisionActivityRail`: newest-first lifecycle chronology.
- `SourceDocumentViewer` modal for any evidence artifact (never navigates away).
- `Today` = production-readiness / consequence surface. `Records` = durable DecisionRecord/audit. `Suppliers` = shallow.
- **Playback / scrub / layout toggle are DEV HARNESS only — not product UI.** In production the workspace advances solely from lifecycle events.

Locked; do not reopen.

---

## D2 — Component tree

```
VouchAppShell
├─ PrimaryNavigation
├─ TopContextHeader
└─ (route)
   ├─ IncomingOverview
   │  ├─ IncomingSummary            (count strip)
   │  ├─ IncomingDecisionList
   │  │  └─ IncomingDecisionRow ×n
   │  └─ InProgressStrip
   ├─ DecisionWorkspace
   │  ├─ DecisionHeader
   │  ├─ DecisionSpine
   │  ├─ OutcomeSummary             (terminal / decision-open only)
   │  ├─ WorkAreaLayout             (grid ↔ full-bleed switch)
   │  │  ├─ CaseContextColumn       (sticky; hidden on full-bleed stages)
   │  │  │  ├─ SourceEvidenceCard
   │  │  │  │  └─ EvidenceSourceSelector
   │  │  │  └─ EstablishedTruthCard
   │  │  └─ WorkColumn
   │  │     ├─ ActiveStageSlot → one of:
   │  │     │   EvidenceStage · InvestigatorStage · VerifierStage ·
   │  │     │   ReconciliationStage · DispositionStage ·
   │  │     │   QualityContinuationStage · ConsequenceStage(→RecoveryEvaluation)
   │  │     └─ CompletedStageStack
   │  │        └─ CompletedStageSummary ×n → ExpandableStageDetail
   │  ├─ DecisionActivityRail
   │  │  └─ ActivityEventRow ×n
   │  └─ SourceDocumentViewer       (modal, portal)
   ├─ TodayWorkspace
   │  ├─ ReadinessSummary
   │  ├─ OperationalChangeBanner
   │  └─ ProductionLineBoard
   │     └─ ProductionLineRow → ProductionOrderCard ×n / RecoveryResult
   ├─ RecordsWorkspace
   │  ├─ DecisionRecordHeader
   │  └─ DecisionRecordSection ×n   (incl. DecisionRunSection, CapabilityMutationSection, HumanContinuationSection)
   └─ SuppliersWorkspace
      └─ SupplierRow ×n             (shallow)
```

Merged/removed vs. the suggested list: `IncomingTriageDrawer` — **removed** (approved design opens the full workspace directly). `SourceTrustSummary` — **merged** into `SourceEvidenceCard` (trust is a facet of the card, not a separate component). `RecoveryResult` appears in two surfaces (inside `ConsequenceStage` and on `Today`); it is one presentational component fed different VMs.

---

## D3 — Per-component JTBD

| Component | JTBD (one sentence) |
|---|---|
| VouchAppShell | Hold global chrome and route between the four product surfaces. |
| PrimaryNavigation | Move between Today / Incoming / Suppliers / Records and signal where attention is needed. |
| TopContextHeader | Tell the user which surface/case they are on and offer "back to Incoming". |
| IncomingOverview | Show what arrived, what Vouch is handling, and what needs a human. |
| IncomingSummary | Give the day's volume and attention counts at a glance. |
| IncomingDecisionRow | Represent one lot's current decision state and let the user open it. |
| DecisionWorkspace | Host one incoming-material decision end to end. |
| DecisionHeader | Orient the user to the exact lot/material and its current disposition. |
| DecisionSpine | Give a 2-second causal read: Evidence → Investigation/Verification → Disposition → Consequence. |
| OutcomeSummary | State the terminal/decision-open result high on the page once enough truth exists. |
| CaseContextColumn | Keep the source and the stable established truth visible while stages progress. |
| SourceEvidenceCard | Anchor the currently selected source document + its trust/security state and open it. |
| EvidenceSourceSelector | Switch which evidence artifact is the active source. |
| EstablishedTruthCard | Show durable facts (lot, governing basis, bound fact) as they become known. |
| SourceDocumentViewer | Show the exact source document, its declared claims, locator, and trust class. |
| ActiveStageSlot | Always display the single highest-priority current stage. |
| EvidenceStage | Establish what entered and whether it is safe/bound to reason from. |
| InvestigatorStage | Show how Vouch determined what governs and what applies. |
| VerifierStage | Show an independently reconstructed applicability result. |
| ReconciliationStage | Decide whether the two independent results materially agree. |
| DispositionStage | Show the deterministic business state computed from established truth. |
| QualityContinuationStage | Let a human supply the authoritative evidence the system could not invent. |
| ConsequenceStage | Show why the disposition matters to the factory. |
| RecoveryEvaluation | Show which recovery options were evaluated and which executed. |
| CompletedStageStack | Retain completed stages as collapsed, reopenable rows. |
| CompletedStageSummary | Summarize a completed stage in one row. |
| ExpandableStageDetail | Reconstruct a completed stage's full structured content on demand. |
| DecisionActivityRail | Prove the work: newest-first lifecycle/tool chronology. |
| ActivityEventRow | Represent one lifecycle event compactly. |
| TodayWorkspace | Answer "what can we still make today, and what changed?". |
| ReadinessSummary | Count READY / AT_RISK / BLOCKED commitments. |
| OperationalChangeBanner | State the one material change that moved the plan. |
| ProductionLineBoard | Show line-by-line order sequence and readiness. |
| ProductionOrderCard | Represent one scheduled order's slot, material, readiness. |
| RecordsWorkspace | Let the user reconstruct a decision after the fact. |
| DecisionRecordSection / RunSection / CapabilityMutationSection / HumanContinuationSection | Present one durable audit facet of the record. |
| SupplierRow | Show supplier identity, qualification, recent flag (shallow). |

---

## D4 — Per-component data requirements

Only non-obvious components listed; every datum: name · shape · required · class · availability · mutable-after-first-render.

### IncomingDecisionRow
| datum | shape | req | class | avail | mutable |
|---|---|---|---|---|---|
| decision_record_id | string | yes | AUTH | initial | no |
| lot_id | string | yes | AUTH | initial | no |
| material | string | yes | AUTH | initial | no |
| supplier_name | string | yes | AUTH | initial | no |
| received_at | timestamp | yes | AUTH | initial | no |
| stage | enum (row states, D5) | yes | DERIVED | from lifecycle | yes |
| attention_required | bool | yes | DERIVED | from lifecycle | yes |
| downstream_commitment | {order_id, time, severity} \| null | no | AUTH/DERIVED | after consequence calc | yes |
| is_unread | bool | no | DERIVED (client) | initial | yes |

### DecisionHeader
`lot_id` (AUTH), `material` (AUTH), `disposition_label` + `disposition_class` (DERIVED from disposition/lifecycle, mutable), `receipt_meta` string {supplier, site, received_at, quantity} (AUTH).

### DecisionSpine
Four nodes. Per node: `key` (evidence|agents|disposition|consequence), `node_state` (D5), `headline` (DERIVED), `note` (DERIVED). Agents node additionally: `investigator_lane_value`, `verifier_lane_value` (AUTH after each brief; null before), `reconciliation_seal` (DERIVED: pending|match|disagreement|halted).

### OutcomeSummary
See **D11** — structured, not prose.

### SourceEvidenceCard / SourceArtifact
| datum | shape | req | class | avail |
|---|---|---|---|---|
| artifact_id | string | yes | SRC | on EVIDENCE_RECEIVED |
| display_name | string | yes | SRC | on receive |
| document_type | enum(coa,mill_report,addendum,internal_authorization,…) | yes | SRC | on receive |
| trust_class | enum(supplier_untrusted, human_authorized, quarantined) | yes | AUTH | on receive; may change on security |
| security_state | enum(pending, cleared, quarantined) | yes | AUTH | on EVIDENCE_SECURITY_COMPLETED |
| version_id | string | yes | SRC | on EVIDENCE_BINDING_COMPLETED |
| hash_summary | string | yes | SRC | on binding |
| page_count | int | no | SRC | on extract |
| source_locators | [{label, page}] | no | SRC | on extract |
| excluded_from_decision | bool | yes | AUTH | on security |
| key_source_fact | {label, value, highlighted} | no | AUTH | on binding |
| open_ref | opaque source reference | yes | SRC | on receive |

### EstablishedTruthCard
`lot_line` (AUTH, initial), `governing_basis` (AUTH, after APPLICABILITY_BRIEF_COMPLETED / RECONCILIATION_COMPLETED, mutable→stable), `bound_fact` (AUTH, after EVIDENCE_BINDING_COMPLETED). Disposition and supplier are **not** duplicated here (owned by header/spine/outcome).

### Agent stage (Investigator / Verifier)
`run_number`, `agent_role`, `stage_state` (D5), `records_consulted:[{mark,label,value,value_emphasis}]` (built from TOOL_RESULT_BOUND), `result_title` + `result_body` + `result_class` (from *_BRIEF_COMPLETED), `is_independent` (Verifier: true; drives the "Investigator output was not provided" copy). Verifier must **not** receive Investigator output as data.

### ReconciliationStage
`reconciliation_state` (D5), `dimensions:[{dimension, investigator_value, verifier_value, agrees}]` (material dimensions only), `note` (DERIVED/COPY by state).

### DispositionStage
`disposition` (enum), `governing_basis`, `requirement_value`, `bound_value`, `basis_chain:[{label,value,tone}]`, `state_mutation:[string]` (from CAPABILITY_ISSUED/MUTATION_COMPLETED), and for QDR: `qdr_question`, `material_differences:[string]`, `awaiting_human` bool.

### ConsequenceStage / RecoveryEvaluation
`metrics:[{label,value,note,severity}]` (from CONSEQUENCE_RECALCULATED), `recovery_candidates:[{kind,title,detail,verdict∈{NOT_FEASIBLE,REFUSED,ELIGIBLE}}]` (from RECOVERY_EVALUATED), `executed:{tag,line,result,caveat}` (from RECOVERY_EXECUTED).

### ActivityEventRow
See **D7**.

### ProductionOrderCard
`order_id`, `slot_time`, `material`, `readiness` (READY|AT_RISK|BLOCKED), `causal_decision_ref` (nullable), `sequence_change` ({prior_slot,current_slot} | null).

---

## D5 — Component state matrices

- **IncomingDecisionRow:** `NEW · EVIDENCE_RECEIVED · SECURITY_HOLD · INVESTIGATING · VERIFYING · QUALITY_DECISION_REQUIRED · QUARANTINED · RELEASED · COMPLETE/HISTORICAL`.
- **SourceEvidenceCard:** `reference_known_unopened · security_pending · cleared · quarantined · human_authorized · alternate_selected`.
- **DecisionSpine (per node):** `pending · active · completed · halted · material_disagreement · terminal`.
- **InvestigatorStage / VerifierStage:** `waiting · started · tool_activity_arriving · brief_complete · technical_failure · domain_insufficiency` (Verifier: `not_established` is the domain-insufficiency terminal used in Hero B).
- **ReconciliationStage:** `pending · MATCH · NON_MATERIAL_DIFFERENCE · MATERIAL_DISAGREEMENT`.
- **DispositionStage:** `pending · RELEASED · QUARANTINED · QUALITY_DECISION_REQUIRED · technical_failure_no_decision`.
- **OutcomeSummary:** `hidden · evidence_quarantined · quality_decision_required · released · quarantined_with_consequence`.
- **ActivityRail:** `empty_waiting · live · historical_complete` (`paused` = dev harness only).
- **QualityContinuationStage:** `awaiting_evidence · evidence_received · decision_resumed · run2_active · completed`.

---

## D6 — Lifecycle event → component mapping

| Event | Components affected | Visible mutation | Animate | Authoritative? | Prior stage collapses |
|---|---|---|---|---|---|
| EVIDENCE_RECEIVED | Row, EvidenceStage, SourceEvidenceCard, Rail | Row→EVIDENCE_RECEIVED; artifacts appear | row enter | AUTH | — |
| EVIDENCE_SECURITY_COMPLETED | SourceEvidenceCard, EvidenceStage, Spine, Rail, OutcomeSummary(hostile) | security→cleared/quarantined; if quarantined, spine halts + Outcome shows | trust flip | AUTH | — |
| EVIDENCE_EXTRACTED | SourceEvidenceCard | page_count, locators, key fact | none | AUTH | — |
| EVIDENCE_BINDING_COMPLETED | EstablishedTruthCard, SourceEvidenceCard | bound_fact populates | none | AUTH | — |
| EVIDENCE_SNAPSHOT_CREATED | EvidenceStage, Rail | snapshot id shown | none | AUTH | — |
| INVESTIGATOR_STARTED | ActiveStageSlot, Spine, Rail | slot→InvestigatorStage(active); Evidence collapses | slot swap | DERIVED(slot) | Evidence |
| TOOL_CALLED | Rail | new event row (top) | insert-top | presentational | — |
| TOOL_RESULT_BOUND | Investigator/VerifierStage, Rail | records_consulted row appears | grow | AUTH | — |
| APPLICABILITY_BRIEF_COMPLETED | InvestigatorStage, Spine, EstablishedTruthCard | result settles; spine investigator lane fills; basis known | settle | AUTH | — |
| VERIFIER_STARTED | ActiveStageSlot, Spine, Rail | slot→VerifierStage(active); Investigator collapses | slot swap | DERIVED | Investigator |
| VERIFIER_BRIEF_COMPLETED | VerifierStage, Spine | verifier lane fills | settle | AUTH | — |
| RECONCILIATION_COMPLETED | ActiveStageSlot(full-bleed), Spine, Rail | slot→Reconciliation; seal resolves | seal | AUTH | Verifier |
| DISPOSITION_COMPUTED | ActiveStageSlot, Spine, OutcomeSummary, Header, Rail | slot→Disposition; disposition pill; Outcome appears (or QDR) | fade | AUTH | Reconciliation |
| POLICY_EVALUATED | DispositionStage, Rail | policy line in state_mutation | none | AUTH | — |
| CAPABILITY_ISSUED | DispositionStage, Rail | capability line | none | AUTH | — |
| MUTATION_COMPLETED | DispositionStage, EstablishedTruthCard, Rail | mutation committed line; disposition durable | none | AUTH | — |
| CONSEQUENCE_RECALCULATED | ActiveStageSlot(full-bleed), Consequence, Today, OutcomeSummary, Spine, Rail | slot→Consequence; metrics; READY→BLOCKED; Outcome consequence line | status flip | AUTH | Disposition |
| RECOVERY_EVALUATED | RecoveryEvaluation, Rail | candidate cards with verdicts | grow | AUTH | — |
| RECOVERY_EXECUTED | RecoveryEvaluation, Today, Rail | resequence result; Today slot change | resequence | AUTH | — |
| QUALITY_DECISION_REQUIRED | DispositionStage, OutcomeSummary, Spine, Row, Rail | QDR panel; Outcome=quality_decision; decision held open | fade | AUTH | Reconciliation |
| HUMAN_EVIDENCE_RECEIVED | QualityContinuationStage, SourceEvidenceCard, Rail | human artifact added; continuation stage | fade | AUTH | — |
| DECISION_RESUMED | ActiveStageSlot, Rail | Run 2 begins; run label 2 | slot swap | AUTH | QualityContinuation |
| PRECEDENT_CONSULTED | (schema-reserved, inactive) | none now | — | — | — |

---

## D7 — Activity rail projection (ActivityEventVM)

Newest at top; never auto-scrolls user away. Minimum fields:
`event_id · sequence · timestamp · event_type · actor_type(evidence|security|investigator|verifier|system|operations|human) · actor_display_name · tool_id? · short_label · result_summary? · result_status(neutral|good|caution|bad)? · authority_class? · object_refs? · decision_record_id · run_number`.
Rail shows chronology only — no prompts, chain-of-thought, or transcripts.
**Expandable event types** (optional detail on click): `TOOL_RESULT_BOUND` (bound value + object ref), `RECONCILIATION_COMPLETED` (material dimensions), `DISPOSITION_COMPUTED` (requirement vs bound). Others render single-line.

---

## D8 — Active-stage rules

One stage owns the slot at a time; the slot switches **only at major stage boundaries**, never per `TOOL_CALLED`. Owner is derived from the latest stage-boundary event, not from tool traffic.

| Transition | Trigger event | Prev collapsed state | New initial state | Animation | Outcome change |
|---|---|---|---|---|---|
| Evidence→Investigator | INVESTIGATOR_STARTED | Evidence→CompletedStageSummary | started | slot swap 250–400ms | no |
| Investigator→Verifier | VERIFIER_STARTED | Investigator→summary | started | slot swap | no |
| Verifier→Reconciliation | RECONCILIATION_COMPLETED | Verifier→summary | resolved (seal) | seal | no |
| Reconciliation→Disposition | DISPOSITION_COMPUTED | Reconciliation→summary | terminal disposition | fade | **yes** (appears) |
| Disposition→Consequence | CONSEQUENCE_RECALCULATED | Disposition→summary | metrics populating | status flip | yes (consequence line) |
| (Hero B) Disposition→Quality | QUALITY_DECISION_REQUIRED | Disposition stays QDR | awaiting_evidence | fade | yes (quality_decision) |
| Quality→Run2 Investigator | DECISION_RESUMED | Quality→summary (retained) | started (run 2) | slot swap | no |
| Run2 → … → Consequence | as above | Run 1 retained collapsed | — | — | terminal RELEASED |

Full-bleed (drop left column) when active stage ∈ {Reconciliation, Consequence}. Recovery renders full-width inside Consequence.

---

## D9 — Completed-stage projections

Stable view-models retained per stage so a reopen does not replay lifecycle logic:

- **EvidenceCompletedVM:** artifacts[], trust/security per artifact, snapshot id.
- **AgentCompletedVM:** run_number, agent_role, result_title/body/class, governing_basis, records_consulted[], completion_status. (Verifier VM never contains Investigator output.)
- **ReconciliationCompletedVM:** dimensions[] (material only), outcome, differences[].
- **DispositionCompletedVM:** disposition, governing_basis, requirement_value, bound_value, mutation_summary[].
- **ConsequenceCompletedVM:** metrics[], recovery_candidates[], executed.
- **QualityContinuationCompletedVM:** evidence_added, authority, resumed_run_ref.

Each `CompletedStageSummary` row needs: `stage_key, run_number?, one_line_summary, summary_pill(label+class), reopenable=true`.

---

## D10 — Source document requirements

Per artifact the UI must receive: `artifact_id, display_name, document_type, source_classification, trust_class, security_state, version_id, hash_summary, page_count?, source_locators[], open_ref, excluded_from_decision, highlighted_claims[]{label,value,locator}`.

Viewer variants: **normal supplier** (declared claims tagged SUPPLIER-DECLARED, locator footer, untrusted badge), **hostile supplier** (instruction-like text shown verbatim in a quarantine block, "preserved / not used in decision" footer, quarantined badge), **human-authorized** (authoritative badge, authority id).

Hero assets the viewer must support:
- **Hero A:** COA (declares CONFORMS), mill/test report showing bound **462 MPa** (highlighted vs ≥480).
- **Hero B:** supplier COA with **M-12** result; later human-authorized **EQ-17** scope evidence (authority QA-Δ-118).
- **Hostile:** supplier addendum containing visible instruction-like content.

---

## D11 — Outcome Summary model (OutcomeSummaryVM)

Structured, never prose-derived: `visible: bool`, `kind ∈ {evidence_quarantined, quality_decision_required, released, quarantined_with_consequence}`, `headline`, `class`, `lines: string[] (composed from fields below)`, `chip: {label,class}?`.

Backing structured concepts by kind:
- **quarantined_with_consequence (Hero A):** disposition=QUARANTINED, governing_basis, bound_fact, requirement_threshold, affected_commitment(order), readiness_result, recovery_result.
- **quality_decision_required (Hero B open):** state=QDR, material_disagreement_summary, hold_no_release=true.
- **released (Hero B terminal):** disposition=RELEASED, authorized_evidence_summary, independent_match=true, restored_commitment/readiness.
- **evidence_quarantined (Hostile):** security_reason, agents_started=false, mutation_occurred=false.

---

## D12 — Incoming data needs

Row: lot/material, supplier, receipt time, decision_status, current_lifecycle_stage, attention_required, downstream_commitment?, evidence/security state, decision_record_id, is_unread(derived).
Summary counts: arrived_today, need_quality_decision, in_progress, completed_by_vouch — plus an in-progress breakdown [{count,label}]. All AUTH except is_unread and stage (DERIVED).

---

## D13 — Today data needs

Per line: line_id/name, orders[] {order_id, slot_time, material_requirement, readiness}. Per readiness bucket: counts READY/AT_RISK/BLOCKED. Change context: `causal_decision_ref`, `plan_sequence`, `prior_slot?`, `current_slot`, `recovery_result`, and a before/after presentation flag.
Distinguish **authoritative schedule/readiness** (AUTH) from **derived before/after visual** (DERIVED). No scheduling API is assumed.

---

## D14 — Records data needs (DecisionRecordVM)

Stable projection, not event replay: record_id, lot/material/source identity; evidence/provenance; run_history[] each {run_number, investigator_output, verifier_output, reconciliation, disposition}; policy/capability; mutation; operational_consequence; recovery; human_continuation. Prefer server-side stable projection over FE reconstruction.

---

## D15 — Human commands / intents

| Intent | Issuing component | Class | Min input | Success state | Refusal/failure state |
|---|---|---|---|---|---|
| Navigate surface | PrimaryNavigation | UI_ONLY | route | surface shown | — |
| Open/select decision | IncomingDecisionRow | UI_ONLY (read) | decision_record_id | workspace opens | not-found empty state |
| Open evidence source | SourceEvidenceCard/artifact | UI_ONLY (read) | artifact_id/open_ref | viewer opens | "source cannot be loaded" |
| Select alternate source | EvidenceSourceSelector | UI_ONLY | artifact_id | card/viewer switches | — |
| Expand completed stage | CompletedStageSummary | UI_ONLY | stage_key | detail expands | — |
| **Provide human-authorized evidence** | QualityContinuationStage | **BACKEND_COMMAND_REQUIRED** | decision_record_id, evidence ref/attachment, accountable authority | decision resumes as Run 2; continuation stage populates | refusal: evidence rejected/insufficient (domain, not red error); failure: submission could not be recorded |
| **Keep held** | DispositionStage(QDR) | **BACKEND_COMMAND_REQUIRED** (if a real hold command exists) | decision_record_id | hold confirmed, reversible | failure: hold not recorded |

No fake progression commands (start investigation / run verifier / recalculate / continue) exist.

---

## D16 — Failure / empty / degraded states

Distinct treatments, none a generic red error:
- **Domain abstention** (insufficient evidence, material disagreement) → calm, blue/indigo "Quality decision required" language; decision stays open.
- **Technical failure** (model/tool/persistence) → neutral "could not complete" with retry affordance where a real retry exists; never implies a disposition.
- **Security quarantine** → rust quarantine treatment; spine halts; agents not started.
- **Evidence identity mismatch** → block reasoning; flag mismatch on SourceEvidenceCard.
- **Stale state / mutation refusal** → non-alarming "state changed, refresh decision" notice.
- **Transport interruption** → rail shows "reconnecting"; last authoritative state retained, not cleared.
- **No source document / reference unloadable** → viewer shows "source unavailable" with hash/version still visible.
- **Decision still running when opened** → active stage renders live from current authoritative state.
- **Decision completed before user opens** → renders terminal + full completed stacks; rail historical.

---

## D17 — Animation trigger map

Every animation is bound to a state/event change, never a timer (timers = dev harness only):
new Incoming row ← row added to authoritative list · rail row ← each new lifecycle event (insert-top) · source trust flip ← EVIDENCE_SECURITY_COMPLETED · Investigator/Verifier record rows ← TOOL_RESULT_BOUND · agent result settle ← *_BRIEF_COMPLETED · reconciliation seal ← RECONCILIATION_COMPLETED · Outcome appears ← DISPOSITION_COMPUTED / QUALITY_DECISION_REQUIRED / security quarantine · READY→BLOCKED ← CONSEQUENCE_RECALCULATED · recovery candidates ← RECOVERY_EVALUATED · resequence ← RECOVERY_EXECUTED · Run 2 begins ← DECISION_RESUMED · AT_RISK→READY ← CONSEQUENCE_RECALCULATED (run 2).

---

## D18 — Information ownership / duplication audit

| Information | Owner (full detail) | Others may show |
|---|---|---|
| Lifecycle chronology | DecisionActivityRail | — |
| Causal state (where are we) | DecisionSpine | Row (coarse) |
| Source content | SourceDocumentViewer / SourceEvidenceCard | EstablishedTruthCard (bound fact only) |
| Governing basis / applicability work | Investigator/Verifier stage | Spine lane, EstablishedTruthCard, Outcome (summary) |
| Agent comparison | ReconciliationStage | Spine seal (summary) |
| Deterministic business result | DispositionStage | Header pill, Outcome, Spine (summary) |
| Executive terminal summary | OutcomeSummary | — |
| Factory impact | ConsequenceStage / Today | Outcome (one line) |
| Durable audit | Records | — |

Flagged & resolved duplications: disposition previously repeated in header + context column → **removed from CaseContextColumn**. Supplier repeated in header + context → **removed from context**. Tool calls previously in agent stage + rail → **rail owns chronology; agent stage shows meaning (records consulted) only**.

---

## D19 — React component responsibility classification

- **Pure/presentational (view-model in, render only):** PrimaryNavigation, TopContextHeader, IncomingSummary, IncomingDecisionRow, DecisionHeader, DecisionSpine, OutcomeSummary, EstablishedTruthCard, all *Stage bodies, CompletedStageSummary, ActivityEventRow, ReadinessSummary, OperationalChangeBanner, ProductionOrderCard, DecisionRecordSection, SupplierRow, RecoveryEvaluation.
- **Stateful UI (local state only):** CaseContextColumn / SourceEvidenceCard (selected source), SourceDocumentViewer (open/close), CompletedStageStack (expansion), WorkAreaLayout (grid↔full-bleed derivation), ActiveStageSlot (which stage owns slot — derived, but memoized locally).
- **Data-connected containers (bind to read model + lifecycle stream + commands):** VouchAppShell, IncomingOverview, DecisionWorkspace, DecisionActivityRail, TodayWorkspace, RecordsWorkspace.

No specific query/socket/router library is mandated by the design.

---

## D20 — View-model inventory (conceptual, not backend schema)

- **IncomingDecisionSummaryVM** — {counts, in_progress[], rows: IncomingRowVM[]}
- **IncomingRowVM** — {decision_record_id, lot_id, material, supplier_name, received_at, stage, attention_required, downstream_commitment?, is_unread}
- **DecisionWorkspaceVM** — {header: DecisionHeaderVM, spine: DecisionSpineVM, outcome: OutcomeSummaryVM, context: CaseContextVM, active_stage_key, stages: StageVM[], activity: ActivityEventVM[], sources: SourceArtifactVM[]}
- **DecisionSpineVM** — {nodes:[{key,node_state,headline,note}], investigator_lane, verifier_lane, reconciliation_seal}
- **CaseContextVM** — {primary_source: SourceArtifactVM, lot_line, governing_basis?, bound_fact?}
- **SourceArtifactVM** — see D10 fields
- **OutcomeSummaryVM** — see D11
- **AgentStageVM** — {run_number, agent_role, stage_state, is_independent, records_consulted[], result_title, result_body, result_class}
- **ReconciliationVM** — {reconciliation_state, dimensions[], note}
- **DispositionVM** — {disposition, governing_basis, requirement_value, bound_value, basis_chain[], state_mutation[], qdr_question?, material_differences?, awaiting_human?}
- **ConsequenceVM** — {metrics[], recovery: RecoveryVM}
- **RecoveryVM** — {candidates:[{kind,title,detail,verdict}], executed?}
- **ActivityEventVM** — see D7
- **TodayPlanVM** — {readiness_counts, change_banner?, lines:[{line_id,name,orders: ProductionOrderVM[], recovery_result?}]}
- **ProductionOrderVM** — {order_id, slot_time, material, readiness, causal_decision_ref?, sequence_change?}
- **DecisionRecordVM** — see D14

---

## D21 — Event inventory (UI consumes)

For each real lifecycle event: **consumers** and **required payload concepts** (visible effect per D6).
- EVIDENCE_RECEIVED → Row, EvidenceStage, SourceEvidenceCard, Rail · {decision_record_id, artifacts[], received_at}
- EVIDENCE_SECURITY_COMPLETED → SourceEvidenceCard, Spine, OutcomeSummary, Rail · {artifact_id, security_state, reason?}
- EVIDENCE_EXTRACTED → SourceEvidenceCard · {artifact_id, page_count, locators[], key_fact?}
- EVIDENCE_BINDING_COMPLETED → EstablishedTruthCard, SourceEvidenceCard · {version_id, hash, bound_fact}
- EVIDENCE_SNAPSHOT_CREATED → EvidenceStage, Rail · {snapshot_id, claim_count}
- INVESTIGATOR_STARTED / VERIFIER_STARTED → ActiveStageSlot, Spine, Rail · {run_number, agent_role}
- TOOL_CALLED → Rail · {tool_id, label, actor}
- TOOL_RESULT_BOUND → Agent stage, Rail · {tool_id, result_summary, object_ref?}
- APPLICABILITY_BRIEF_COMPLETED / VERIFIER_BRIEF_COMPLETED → Agent stage, Spine, EstablishedTruthCard · {run_number, result_class, governing_basis?, applicability?}
- RECONCILIATION_COMPLETED → ReconciliationStage, Spine, Rail · {outcome, dimensions[]}
- DISPOSITION_COMPUTED → DispositionStage, Header, OutcomeSummary, Spine, Rail · {disposition, requirement_value, bound_value, governing_basis}
- POLICY_EVALUATED / CAPABILITY_ISSUED / MUTATION_COMPLETED → DispositionStage, Rail · {policy_ref/capability_ref/mutation_summary}
- CONSEQUENCE_RECALCULATED → ConsequenceStage, Today, OutcomeSummary, Rail · {metrics[], affected_orders[]}
- RECOVERY_EVALUATED → RecoveryEvaluation, Rail · {candidates[]}
- RECOVERY_EXECUTED → RecoveryEvaluation, Today, Rail · {executed}
- QUALITY_DECISION_REQUIRED → DispositionStage, OutcomeSummary, Row, Rail · {qdr_question, material_differences[]}
- HUMAN_EVIDENCE_RECEIVED → QualityContinuationStage, SourceEvidenceCard, Rail · {artifact, authority}
- DECISION_RESUMED → ActiveStageSlot, Rail · {run_number:2, snapshot_ref}

---

## D22 — Command inventory (UI needs)

Backend-relevant only (UI-only reads omitted):
- **ProvideHumanAuthorizedEvidence** — issuer QualityContinuationStage · intent: attach authoritative evidence to an open decision · input: {decision_record_id, evidence_ref/attachment, accountable_authority} · expected result: same record resumes (Run 2) · refusal: evidence insufficient/rejected (domain) · failure: not recorded.
- **KeepDecisionHeld** — issuer DispositionStage(QDR) · intent: hold lot pending evidence · input: {decision_record_id} · result: reversible hold confirmed · failure: not recorded. *(Include only if a real hold command exists; else reclassify UI_ONLY.)*

---

## D23 — BACKEND CONTRACT QUESTIONS

1. Is the decision lifecycle delivered as a **streaming** event feed or **polled ordered** events? What ordering/sequence guarantee backs the rail's newest-first and the active-slot derivation?
2. What **stable source reference** is available to open/retrieve a source document (id + version/hash), and are highlighted source claims/locators provided by backend or derived by FE?
3. Does the backend expose a **precomputed Outcome projection**, or should the FE compose OutcomeSummaryVM from DecisionRecord + consequence state?
4. What is the exact **command for attaching human-authorized evidence**, and what does its accepted/refused/failed response look like at the domain level (so we can distinguish abstention from technical failure)?
5. Is **"Keep held"** a real backend command or purely explanatory UI?
6. Is there a **read model returning current Today readiness after a mutation**, or must FE recompute readiness from orders + disposition state?
7. Can a **completed stage be fetched as a stable projection** (D9 VMs), or only reconstructed by replaying lifecycle events?
8. Are **run boundaries** (Run 1 / Run 2) explicit in event payloads (run_number) or must FE infer them from DECISION_RESUMED?
9. What identifies **security exclusion** on an artifact vs. a merely-untrusted artifact (both are "supplier" but only one halts)?
10. Confirm **PRECEDENT_CONSULTED** remains inactive and should be schema-tolerated but not rendered.

Do not answer these from design; they are the input to the integration-contract commission.

---

## D24 — Handoff verdict

The two-column workspace, its stages, spine, outcome summary, activity rail, source viewer, Today, and Records are specified with per-component data, states, event mappings, view models, and command/event inventories sufficient for a React build and a subsequent FE↔BE contract. Open items are enumerated in D23 and require backend confirmation, not design changes.

**READY_FOR_INTEGRATION_CONTRACT**

VOUCH V2 UI DATA REQUIREMENTS READY FOR INTEGRATION CONTRACT
