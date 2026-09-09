/**
 * The frontend's own vocabulary for one decision.
 *
 * These are the shapes components render. They are derived from backend DTOs by
 * `adapter.ts` and never contain a raw DTO, so a component cannot accidentally
 * depend on a backend field the contract does not promise.
 *
 * The names follow VOUCH_V2_UI_COMPONENT_DATA_REQUIREMENTS.md (D4/D5/D9),
 * because that document is the frozen UI authority and divergent naming here
 * would make the two impossible to check against each other.
 */

import type { SemanticTone } from '../view-models/types';

export type StageKey =
  | 'evidence'
  | 'investigator'
  | 'verifier'
  | 'reconciliation'
  | 'disposition'
  | 'consequence';

/** D5. A stage is never "loading" — it is waiting, working, or settled. */
export type StageState = 'pending' | 'active' | 'complete' | 'halted';

/** D5, DecisionSpine per-node. */
export type SpineNodeState =
  | 'pending'
  | 'active'
  | 'completed'
  | 'halted'
  | 'material_disagreement'
  | 'terminal';

export type SpineKey = 'evidence' | 'agents' | 'disposition' | 'consequence';

export interface SpineNodeVM {
  key: SpineKey;
  label: string;
  state: SpineNodeState;
  headline: string;
  note: string;
  /** Agents node only. null before the brief lands — never a placeholder. */
  investigatorLane?: string | null;
  verifierLane?: string | null;
  reconciliationSeal?: 'pending' | 'match' | 'disagreement' | 'halted';
  /**
   * Overrides the tone the node's state would otherwise imply.
   *
   * A completed node is normally green, which is right for every stage that
   * completing IS the good outcome. Consequence is the exception: the
   * quarantine's whole point is that an order stopped, and rendering that
   * green read as a successful decision.
   */
  tone?: SemanticTone;
}

/**
 * §11. Six truthful failure classes, deliberately not one error state.
 *
 * The distinction that matters most: TECHNICAL_FAILURE must never render a
 * disposition, and DOMAIN_ABSTENTION must never look like a crash. Vouch
 * abstaining is the product working.
 */
export type FailureKind =
  | 'DOMAIN_ABSTENTION'
  | 'TECHNICAL_FAILURE'
  | 'SECURITY_HOLD'
  | 'CONFLICT_STALE'
  | 'POLICY_REFUSAL'
  | 'SOURCE_UNAVAILABLE';

export interface FailureVM {
  kind: FailureKind;
  headline: string;
  detail: string;
  /** True only for TECHNICAL_FAILURE. Gates every disposition surface. */
  suppressesDisposition: boolean;
}

/** D10 + sponsor-depth §6. */
export interface SourceLocatorVM {
  /** Pre-formatted for display: "Page 3 · Table 1 · Tensile — mean · Result". */
  label: string;
  page?: number;
  table?: number;
  rowLabel?: string;
  columnLabel?: string;
  cell?: string;
  confidence?: number;
  /** True when this came from structured extraction rather than a line offset. */
  structured: boolean;
}

export interface SourceClaimVM {
  label: string;
  value: string;
  /** Where in the document this was read: "line:3", or a structured locator. */
  locator: string;
  /** How it was measured. Provenance, never authority. */
  method: string;
  condition: string;
  trustClass: string;
}

export interface SourceArtifactVM {
  artifactId: string;
  displayName: string;
  documentType: string;
  trustClass: 'supplier_untrusted' | 'human_authorized' | 'quarantined' | 'internal';
  trustLabel: string;
  securityState: 'pending' | 'cleared' | 'quarantined';
  versionId: string;
  hashSummary: string;
  pageCount?: number;
  excludedFromDecision: boolean;
  claims: SourceClaimVM[];
  /**
   * How many claims the backend says it extracted. Distinct from
   * `claims.length`: the live `get_source` returns `claim_count` but not the
   * claims themselves, so "2 claims, not itemized here" and "no claims" are
   * different facts and must not render the same way.
   */
  claimCount: number;
  locators: SourceLocatorVM[];
  /**
   * Sponsor depth. `null` for every ordinary document — the overwhelmingly
   * common case — and the UI must render perfectly without it.
   */
  extraction: ExtractionProvenanceVM | null;
  /**
   * True when the backend could sign a URL for this artifact. The URL itself is
   * NEVER stored on the model: it is a bearer credential with a 300s TTL, so it
   * is fetched at the moment a viewer opens the document and then discarded.
   */
  openable: boolean;
}

/** §6 of the integration contract. Optional, additive, never required. */
export interface ExtractionProvenanceVM {
  method: string;
  /** Meaning-first, per the approved micro-pass. Method is secondary. */
  headline: string;
  structured: boolean;
  confidence?: number;
  confidenceGatePassed?: boolean;
  identityTrusted?: boolean;
  reason?: string;
  claimCount: number;
}

export interface EstablishedTruthVM {
  lotLine: string;
  /** Populates on APPLICABILITY_BRIEF_COMPLETED. null before — not a blank. */
  governingBasis: string | null;
  /** Populates on EVIDENCE_BINDING_COMPLETED. */
  boundFact: { label: string; value: string; emphasis?: boolean } | null;
  /** Only once a disposition genuinely exists. Never revealed early. */
  holdTruth: string | null;
}

export interface RecordConsultedVM {
  mark: string;
  label: string;
  value: string;
  emphasis?: boolean;
}

export interface AgentStageVM {
  role: 'investigator' | 'verifier';
  runNumber: number;
  state: StageState;
  modelId: string;
  recordsConsulted: RecordConsultedVM[];
  resultTitle: string;
  resultBody: string;
  resultTone: SemanticTone;
  /** Verifier only. Drives the "did not receive Investigator output" copy. */
  isIndependent: boolean;
  basis?: string;
  sufficiency?: string;
}

export interface ReconciliationDimensionVM {
  dimension: string;
  investigatorValue: string;
  verifierValue: string;
  agrees: boolean;
}

export interface ReconciliationVM {
  state: 'pending' | 'MATCH' | 'NON_MATERIAL_DIFFERENCE' | 'MATERIAL_DISAGREEMENT';
  dimensions: ReconciliationDimensionVM[];
  note: string;
}

export interface DispositionVM {
  disposition: string;
  tone: SemanticTone;
  governingBasis: string;
  requirementValue: string;
  boundValue: string;
  basisChain: { label: string; value: string; tone?: SemanticTone }[];
  stateMutation: string[];
  qualityDecisionRequired: boolean;
  qdrQuestion?: string;
  materialDifferences: string[];
}

export interface ConsequenceMetricVM {
  label: string;
  value: string;
  note?: string;
  severity?: SemanticTone;
  /** The order's short material, and by how much. Both from the backend's own
   *  arithmetic — used to name the gap without re-deriving it. */
  materialId?: string;
  uncovered?: number;
}

export interface RecoveryCandidateVM {
  candidateId: string;
  kind: string;
  title: string;
  detail: string;
  verdict: 'ELIGIBLE' | 'REFUSED' | 'NOT_FEASIBLE';
  tone: SemanticTone;
  /**
   * This candidate is the one the engine actually selected and acted on.
   *
   * Distinct from `verdict === 'ELIGIBLE'`: eligibility is a property of the
   * candidate, selection is the engine's choice among the eligible. Two
   * candidates could both be feasible; only one moves the factory, and the
   * operator must be able to see which at a glance.
   */
  selected: boolean;
}

export interface ConsequenceVM {
  metrics: ConsequenceMetricVM[];
  readinessChanges: { orderId: string; from: string; to: string }[];
  candidates: RecoveryCandidateVM[];
  executed: { tag: string; line: string; caveat?: string } | null;
}

/** D11. Structured, never prose-derived. */
export interface OutcomeSummaryVM {
  visible: boolean;
  kind:
    | 'evidence_quarantined'
    | 'quality_decision_required'
    | 'released'
    | 'quarantined_with_consequence'
    | 'technical_failure';
  headline: string;
  tone: SemanticTone;
  lines: string[];
  chip?: { label: string; tone: SemanticTone };
  /**
   * The secondary line: true but subordinate context, shown smaller.
   *
   * Kept out of `lines` so the deterministic reason stays the thing the eye
   * lands on. "The supplier declared CONFORMS against Revision B" explains how
   * a plausible-looking document still failed; it is not itself the reason.
   */
  context?: string;
  /**
   * What the operator does next, when the decision leaves something undone.
   *
   * Text only. There is deliberately no action id here — no backend action
   * exists to close this gap, and an affordance that leads nowhere is worse
   * than a sentence that tells the truth.
   */
  nextAction?: string;
  /**
   * The compact production-impact strip: what already happened to the plan.
   *
   * Distinct from `nextAction`, which is what a HUMAN still has to do. Keeping
   * the two apart is what let the terminal frame drop its duplicated
   * per-order readiness cards.
   */
  impact?: string;
}

/**
 * §8. The disputed applicability question, ready to render.
 *
 * `question` is the exact sentence an operator answers, composed from the
 * backend's structured facts rather than written by the frontend. The two
 * positions are stated as what each agent SELECTED, never as which is right —
 * the whole point is that both are defensible.
 */
export interface QualityAuthorityOptionVM {
  claimId: string;
  selectedBy: 'INVESTIGATOR' | 'VERIFIER';
  agentLabel: string;
  /** "470 MPa by ASTM-E8 at room_temp" */
  measurement: string;
  /** How this path is authorized: the named method, or the equivalence. */
  basis: string;
}

export interface QualityAuthorityPanelVM {
  questionId: string;
  /** The exact question, e.g. "Does Quality authorize EQ-2 ...?" */
  question: string;
  characteristic: string;
  equivalenceId: string;
  options: QualityAuthorityOptionVM[];
  /** Concise position lines, one per agent, in a fixed order. */
  investigatorPosition: string;
  verifierPosition: string;
  /** The disputed object, stated plainly for the panel subhead. */
  disputed: string;
  primaryActionLabel: string;
  secondaryActionLabel: string;
}

/**
 * §8. The durable stage that REPLACES the action panel once a human answers.
 *
 * Its presence is what removes the affordance: the workspace renders one or
 * the other, never both, and never a disabled button.
 */
export interface QualityAuthorityRecordVM {
  decision: 'AUTHORIZE_APPLICABILITY' | 'KEEP_HELD';
  /** "Applicability authorized" | "Kept held" */
  headline: string;
  tone: SemanticTone;
  question: string;
  answer: string;
  accountableActor: string;
  authoritySource: string;
  timestamp: string;
  clock: string;
  /** Evidence-snapshot binding, so the record shows what it was answered against. */
  snapshotBinding: string;
}

/** D7. One row in the far-right chronology. */
export interface ActivityEventVM {
  eventId: string;
  sequence: number;
  timestamp: string;
  clock: string;
  eventType: string;
  actorType:
    | 'evidence'
    | 'security'
    | 'investigator'
    | 'verifier'
    | 'system'
    | 'operations'
    | 'human';
  actorDisplayName: string;
  toolId?: string;
  shortLabel: string;
  resultSummary?: string;
  resultStatus?: 'neutral' | 'good' | 'caution' | 'bad';
  runNumber: number;
  /** D7: only these three carry optional detail on click. */
  expandable: boolean;
  detail?: { label: string; value: string }[];
}

export interface CompletedStageVM {
  stageKey: StageKey;
  runNumber?: number;
  title: string;
  oneLine: string;
  pill: { label: string; tone: SemanticTone };
}

/** The whole workspace, as one projection. */
export interface DecisionWorkspaceVM {
  decisionRecordId: string;
  lotId: string;
  material: string;
  receiptMeta: string;
  dispositionLabel: string;
  dispositionTone: SemanticTone;
  running: boolean;
  /** Authoritative once the terminal get_decision has landed. */
  authoritative: boolean;
  durable: boolean;
  spine: SpineNodeVM[];
  outcome: OutcomeSummaryVM;
  activeStage: StageKey | null;
  /** D8: Reconciliation and Consequence drop the left column. */
  fullBleed: boolean;
  completed: CompletedStageVM[];
  sources: SourceArtifactVM[];
  /**
   * An artifact is known to exist but is not fetched yet. Derived from the
   * lifecycle, so it stays true across the gap between the outcome rendering
   * and `get_source` becoming answerable.
   */
  sourcesPending: boolean;
  selectedArtifactId: string | null;
  truth: EstablishedTruthVM;
  investigator: AgentStageVM | null;
  verifier: AgentStageVM | null;
  reconciliation: ReconciliationVM | null;
  disposition: DispositionVM | null;
  consequence: ConsequenceVM | null;
  activity: ActivityEventVM[];
  failure: FailureVM | null;
  /**
   * §8. Present ONLY while a disputed question is open and unanswered. The
   * moment an authority is recorded this becomes null and `qualityAuthority`
   * takes its place, so the controls cannot outlive the decision they made.
   */
  qualityAuthorityPanel: QualityAuthorityPanelVM | null;
  /** The durable answered stage. Persists for the life of the record. */
  qualityAuthority: QualityAuthorityRecordVM | null;
}
