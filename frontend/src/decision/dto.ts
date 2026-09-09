/**
 * Raw backend DTOs, exactly as VOUCH_V2_FE_BE_INTEGRATION_CONTRACT.md freezes
 * them. Nothing here is renamed, reshaped or made convenient.
 *
 * This file is deliberately the ONLY place snake_case appears in the frontend.
 * The adapter turns these into view models; components never see a DTO. Keeping
 * the two apart is what lets a backend field move without a component rewrite —
 * and, more importantly, stops a component from quietly depending on a shape
 * the contract does not promise.
 *
 * Where a field is optional here it is optional in the contract. `?` is not a
 * defensive habit: an absent `view_ref` is a real product state (the source
 * cannot be signed), and an absent `structured_extraction` is an ordinary
 * document. Both must render, neither is an error.
 */

/** Every action returns this. §1 of the integration contract. */
export interface EnvelopeDTO {
  ok: boolean;
  action?: string;
  backend?: BackendDTO;
  /** Present only when `ok === false`. Never accompanied by a disposition. */
  error?: string;
  failure_category?: string;
  /** Added by the BFF for transport failures, not by the runtime. */
  failure_class?: 'TECHNICAL_FAILURE';
}

export interface BackendDTO {
  mode?: string;
  /** false ⇒ results are NOT authoritative and must not be presented as such. */
  durable?: boolean;
  corpus?: string;
  evidence_store?: string;
  reasoners?: string;
}

/** §2. The synchronous evaluate response. */
export interface EvaluateDTO extends EnvelopeDTO {
  decision_record_id: string;
  /**
   * Present on `evaluate_lot`. **Absent on `supply_evidence`**, which was
   * verified against a live run-2 capture rather than assumed: the resume
   * response identifies the decision, not the lot. Callers already know the
   * lot they are viewing, so this is optional rather than a reason to make the
   * backend echo it back.
   */
  lot_id?: string;
  /** '' when no disposition was reached — an abstention, not an error. */
  disposition: '' | 'RELEASE' | 'QUARANTINE' | 'INSUFFICIENT_EVIDENCE';
  failure_category: string;
  quality_decision_required: boolean;
  reason: string;
  /** {} when nothing changed. Never infer a state change from its absence. */
  mutation: Record<string, unknown>;
  consequences?: ConsequencesDTO;
  decision_record?: RecordSummaryDTO;
  events?: LifecycleEventDTO[];
}

export interface ConsequencesDTO {
  readiness_changes?: { order_id: string; from: string; to: string }[];
  recovery?: {
    executed: boolean;
    candidates?: RecoveryCandidateDTO[];
    /** The candidate the engine chose. Null when no lawful option existed. */
    selected?: RecoveryCandidateDTO | null;
    [key: string]: unknown;
  };
  [key: string]: unknown;
}

export interface RecoveryCandidateDTO {
  candidate_id: string;
  verdict: 'ELIGIBLE' | 'REFUSED' | 'NOT_FEASIBLE';
  /** A CODE, not prose. The UI composes the sentence; the backend states why. */
  reason_code?: string;
  kind?: string;
  /** Computed facts behind the verdict. All arithmetic already done. */
  facts?: Record<string, unknown>;
}

/**
 * §4. The one disputed applicability question a MATERIAL_DISAGREEMENT raised.
 *
 * Every field is structured: the frontend composes the sentence an operator
 * reads, but every noun in it comes from here. Nothing is inferred, and no
 * wording is invented for facts the backend did not state.
 */
export interface QualityQuestionDTO {
  question_id: string;
  question_type: string;
  characteristic: string;
  options: QualityOptionDTO[];
  investigator_evidence_ref: string;
  verifier_evidence_ref: string;
  equivalence_id: string;
  method_from: string;
  method_to: string;
  condition: string;
  status: 'OPEN' | 'RESOLVED' | 'HELD' | string;
}

export interface QualityOptionDTO {
  claim_id: string;
  value: number | string | null;
  units: string;
  method: string;
  condition: string;
  equivalence_id: string;
  selected_by: 'INVESTIGATOR' | 'VERIFIER' | string;
}

/** §3. A scoped authority fact. Never a disposition. */
export interface HumanAuthorityDecisionDTO {
  authority_decision_id: string;
  decision_record_id: string;
  lot_id: string;
  source_run: number;
  evidence_snapshot_id: string;
  claim_set_hash: string;
  question_id: string;
  question_type: string;
  characteristic: string;
  authorized_evidence_refs: string[];
  disputed_evidence_refs: string[];
  equivalence_id: string;
  method_from: string;
  method_to: string;
  condition: string;
  decision: 'AUTHORIZE_APPLICABILITY' | 'KEEP_HELD' | string;
  accountable_actor: string;
  authority_source: string;
  created_at: string;
}

export interface QualityAuthorityDTO {
  question?: QualityQuestionDTO;
  decisions?: HumanAuthorityDecisionDTO[];
}

export interface RecordSummaryDTO {
  record_id?: string;
  lot_id?: string;
  run_count?: number;
  disposition?: string;
  quality_authority?: QualityAuthorityDTO;
  [key: string]: unknown;
}

/**
 * One lifecycle event. The payload is open by design: the event vocabulary is
 * frozen at 26 types but individual payload keys differ per type, and the
 * adapter reads only what it understands.
 *
 * What can NEVER appear here: prompts, chain-of-thought, rationale. That is
 * enforced in the backend by a structural guard on payload KEYS, not by
 * convention, so the frontend does not need to filter it.
 */
export interface LifecycleEventDTO {
  event: string;
  decision_record_id: string;
  at: string;
  sequence?: number;
  event_id?: string;
  [key: string]: unknown;
}

export interface EventsDTO extends EnvelopeDTO {
  events?: LifecycleEventDTO[];
  /** Highest sequence the server holds; the cursor for the next poll. */
  last_sequence?: number;
  complete?: boolean;
}

export interface DecisionDTO extends EnvelopeDTO {
  decision_record?: Record<string, unknown>;
  record?: Record<string, unknown>;
  events?: LifecycleEventDTO[];
  artifacts?: SourceArtifactDTO[];
  [key: string]: unknown;
}

/** §5 / D10. `view_ref` is a transient bearer credential — never persist it. */
export interface SourceArtifactDTO {
  artifact_id: string;
  display_name?: string;
  document_type?: string;
  content_type?: string;
  /** Live responses use `trust_class`; the record path uses `trust_label`. */
  trust_class?: string;
  trust_label?: string;
  /** UPPERCASE on the live path: CLEARED | QUARANTINED. */
  security_state?: string;
  document_identity?: string;
  prompt_attack_detected?: boolean;
  claim_count?: number;
  status?: string;
  version_id?: string;
  object_version?: string;
  content_hash?: string;
  storage_ref?: string;
  page_count?: number;
  excluded_from_decision?: boolean;
  /** The live spelling. */
  excluded_from_decision_use?: boolean;
  /** Absent when a URL could not be signed. A designed state, not a failure. */
  view_ref?: string;
  view_url?: string;
  claims?: SourceClaimDTO[];
  /** Sponsor depth. Absent for ordinary documents. */
  structured_extraction?: boolean;
  extraction_method?: string;
  extraction_confidence?: number;
  confidence_gate_passed?: boolean;
  identity_trusted?: boolean;
  structured_reason?: string;
  source_locators?: SourceLocatorDTO[];
  [key: string]: unknown;
}

export interface SourceClaimDTO {
  claim_id?: string;
  /** The artifact these bytes came from. The join key against a source. */
  evidence_artifact_id?: string;
  characteristic?: string;
  value?: number | string | null;
  units?: string;
  method?: string;
  condition?: string;
  source_locator?: string;
  trust_label?: string;
  [key: string]: unknown;
}

/** Sponsor depth §6. Optional; ordinary sources carry a plain string locator. */
export interface SourceLocatorDTO {
  page?: number;
  table?: number;
  row_label?: string;
  column_label?: string;
  cell?: string;
  line?: number;
  confidence?: number;
}

export interface SourcesDTO extends EnvelopeDTO {
  artifacts?: SourceArtifactDTO[];
  sources?: SourceArtifactDTO[];
  [key: string]: unknown;
}

/** §3. Today, used by Hero A only for the C-417 consequence read. */
export interface TodayDTO extends EnvelopeDTO {
  readiness_counts?: Record<string, number>;
  lines?: TodayLineDTO[];
  /** What the recorded decisions did to this plan. Replayed, not derived. */
  causal_history?: CausalEventDTO[];
}

/**
 * One `caused_by` link the consequence engine wrote when a mutation happened.
 *
 * `decision_record_id` is the record that caused it, so the UI can link to the
 * real document rather than searching for a plausible one.
 */
export interface CausalEventDTO {
  kind: string;
  lot_id?: string;
  disposition?: string;
  order_id?: string;
  from?: string;
  to?: string;
  material_id?: string;
  inventory_delta?: number;
  from_slot?: string;
  to_slot?: string;
  blocked_order_id?: string;
  /** The governing basis a quarantine was decided against. */
  spec_id?: string;
  revision?: string;
  decision_record_id?: string;
  ledger_sequence?: number;
  candidates?: RecoveryCandidateDTO[];
  /** The order's coverage as it stands now, for the explanatory sentence. */
  required?: number;
  available?: number;
  planned?: number;
  uncovered?: number;
  planned_sources?: PlannedSourceDTO[];
}

export interface TodayLineDTO {
  line_id: string;
  orders: TodayOrderDTO[];
}

export interface TodayOrderDTO {
  order_id: string;
  product?: string;
  planned_slot?: string;
  /** Stored order state. NOT the same as `readiness`; never collapse them. */
  status?: string;
  /** Computed readiness. */
  readiness?: string;
  reason?: string;
  coverage?: CoverageDTO[];
  requirements?: { material_id: string; quantity: number }[];
  customer_committed?: boolean;
  need_by?: string;
  state_version?: number;
}

export interface PlannedSourceDTO {
  lot_id: string;
  quantity?: number;
  lot_status?: string;
}

export interface CoverageDTO {
  material_id: string;
  required: number;
  available: number;
  short_by: number;
  ratio: number;
  /** Queued against THIS order by an explicit allocation. Never inferred. */
  planned?: number;
  /** What neither released nor queued material accounts for. */
  uncovered?: number;
  planned_sources?: PlannedSourceDTO[];
}
