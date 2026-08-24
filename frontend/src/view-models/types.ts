// The seam between the Vouch product surface and any source of truth.
// Components read VouchViewModel from props and emit Command via CommandGateway.
// The dev FixtureAdapter implements both deterministically; a backend adapter
// later implements the same interfaces with no component rewrite.

/** Three independent state axes. Never collapse into one status. */
export type InventoryState = 'PENDING_RELEASE' | 'RELEASED' | 'QUARANTINED' | 'REJECTED';
export type DispositionState =
  'EVALUATING' | 'RELEASE_VERIFIED' | 'QUARANTINE_VERIFIED' | 'QUALITY_DECISION_REQUIRED';
export type ProductionReadiness = 'READY' | 'AT_RISK' | 'BLOCKED';

export type SemanticTone =
  'decision' | 'released' | 'atrisk' | 'quarantine' | 'blocked' | 'refused' | 'progress';

export type Screen = 'today' | 'incoming' | 'suppliers' | 'records' | 'record';

export interface DecisionRow {
  lotId: string;
  material: string;
  disposition: string;
  tone: SemanticTone;
  hot: boolean;
  reason: string;
  impact: string;
  clock?: string;
  question: string;
  governingBasis: { label: string; body: string };
  suppliedEvidence: { label: string; body: string };
  gap: string;
  consequence: { tag: string; line: string };
  order: string;
  primaryAction: { label: string; sub: string };
  /** 18 for the Halden incident row. One bounded decision, never 18 cards. */
  groupedCount?: number;
}

export interface ProductionOrder {
  time: string;
  id: string;
  material: string;
  readiness: ProductionReadiness;
}

export interface ProductionLine {
  name: string;
  note: string;
  orders: ProductionOrder[];
  expanded?: boolean;
  deEmphasized?: boolean;
}

export interface ReadinessCell {
  count: number;
  readiness: ProductionReadiness;
  sub: string;
}

export interface RecoveryVerdictVM {
  kind: string;
  title: string;
  detail: string;
  verdict: string;
  tone: SemanticTone;
}

export interface SequenceCell {
  time: string;
  id: string;
  readiness: ProductionReadiness;
  tag?: string;
}

export interface BasisStep {
  n: string;
  kind: string;
  head: string;
  body: string;
  pill: string;
  tone: SemanticTone | 'ink';
  loadBearing?: boolean;
}

export interface BasisChainLink {
  label: string;
  value: string;
  tone?: SemanticTone | 'ink';
}

export interface ResumeStep {
  head: string;
  body: string;
}

export interface SupplierRow {
  name: string;
  materials: string;
  qualification: 'QUALIFIED' | 'WATCH' | 'REQUAL PENDING';
  flag: string;
  lots: string;
  lastQualification: string;
}

export interface RecordRow {
  lotId: string;
  material: string;
  supplier: string;
  disposition: string;
  tone: SemanticTone;
  order: string;
  state: string;
  stateTone: SemanticTone | 'muted';
  date: string;
}

export interface VouchViewModel {
  screen: Screen;
  navBadge: number;
  incoming?: {
    rail: { arrived: number; needDecision: number; inProgress: number; completed: number };
    incident?: { headline: string; body: string };
    needsYou: DecisionRow[];
    inProgress: { n: string; label: string }[];
    completed: { released: number; quarantined: number; reopened: number };
  };
  today?: {
    readiness: ReadinessCell[];
    lines: ProductionLine[];
    disruption?: {
      lotId: string;
      material: string;
      coaClaim: string;
      disposition: string;
      consequence: string;
      sequence: SequenceCell[];
      recovery: RecoveryVerdictVM[];
      resequence: { badge: string; line: string; result: string; caveat: string };
    };
  };
  record?: {
    lotId: string;
    material: string;
    meta: string;
    disposition: string;
    dispositionNote: string;
    basisChain: BasisChainLink[];
    steps: BasisStep[];
  };
  drawer?: { row: DecisionRow; resolved: boolean; resumeSteps: ResumeStep[] };
  suppliers?: { rows: SupplierRow[]; shown: string };
  records?: { rows: RecordRow[]; total: string; filters: { label: string; active: boolean }[] };
}

export type Command =
  | { type: 'NAVIGATE'; screen: Screen }
  | { type: 'OPEN_LOT'; lotId: string }
  /** Human provides evidence + accountable authority. Vouch then reassesses. */
  | { type: 'PROVIDE_EVIDENCE'; lotId: string; authority: string }
  | { type: 'CLOSE_DRAWER' };

export interface CommandGateway {
  dispatch(cmd: Command): void;
}

export type FixtureId =
  | 'incoming-normal'
  | 'incoming-incident'
  | 'today-normal'
  | 'today-disrupted'
  | 'decision-record'
  | 'quality-decision'
  | 'resolved'
  | 'suppliers'
  | 'records';

export interface FixtureAdapter {
  getView(id: FixtureId): VouchViewModel;
}
