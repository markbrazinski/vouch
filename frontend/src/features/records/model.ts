/**
 * Records — the durable audit projection.
 *
 * Records must prove a decision after the live animation is gone, so it reads
 * the STORED DecisionRecord (`get_decision`), not the Activity rail. Rail prose
 * is a narration of a run; the record is what the plant is accountable for.
 *
 * Runs are composed the way the backend composes them (`DecisionRecord.runs()`):
 * `archived_runs` holds every COMPLETED run and the live segments hold the
 * current one, so neither alone is the history. A resumed decision keeps its
 * record id — the continuation is the same case, not a new one, and this module
 * never splits it into two.
 */

import type { SemanticTone } from '../../view-models/types';
import { dispositionTone } from '../../decision/adapter';

/** Anything the record document might carry. Read defensively, never assumed. */
type Doc = Record<string, unknown>;

const obj = (v: unknown): Doc => (v && typeof v === 'object' && !Array.isArray(v) ? (v as Doc) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown, fallback = ''): string => (typeof v === 'string' ? v : fallback);
const bool = (v: unknown): boolean => v === true;

export interface RunAgentVM {
  role: 'investigator' | 'verifier';
  modelId: string;
  /** Structured provenance. Never chain-of-thought — there is no such field. */
  promptVersion: string;
  briefHash: string;
  toolCount: number;
  schemaValid: boolean;
  /** The agent's own governing basis, read from ITS brief only. */
  governingBasis: string;
  /** What this agent independently concluded about coverage. */
  covered: string[];
  missing: string[];
  present: boolean;
}

export interface RunVM {
  runNumber: number;
  investigator: RunAgentVM | null;
  verifier: RunAgentVM | null;
  reconciliation: {
    outcome: string;
    agreed: boolean;
    differingFields: string[];
  };
  disposition: string;
  dispositionReason: string;
  tone: SemanticTone;
  governingBasis: string;
  failureCategory: string;
  /** True when this run reached no disposition — an abstention, not a failure. */
  abstained: boolean;
  archivedAt: string;
}

export interface RecordEvidenceVM {
  artifactId: string;
  documentIdentity: string;
  trustClass: string;
  trustLabel: string;
  securityState: string;
  contentHash: string;
  objectVersion: string;
  claimCount: number;
  excluded: boolean;
  /** True for evidence a human supplied under a named authority. */
  humanAuthorized: boolean;
  openable: boolean;
}

export interface HumanContinuationVM {
  occurred: boolean;
  /** WHO is accountable. Read from the record, never from a UI constant. */
  authoritySource: string;
  evidenceSupplied: string[];
  resumedRunIds: string[];
  reviewId: string;
  reviewStatus: string;
}

export interface MutationVM {
  /** True only when a state change actually happened. */
  occurred: boolean;
  action: string;
  targetType: string;
  targetId: string;
  versionChange: string;
  result: string;
  ledgerSequence: string;
}

export interface RecordConsequenceVM {
  readinessChanges: { orderId: string; from: string; to: string; reason: string }[];
  recoveryCandidates: { candidateId: string; kind: string; verdict: string; reasonCode: string }[];
  recoveryExecuted: boolean;
  blockedOrderId: string;
}

export interface DecisionRecordVM {
  recordId: string;
  lotId: string;
  materialId: string;
  supplierId: string;
  supplierSite: string;
  createdAt: string;
  runCount: number;
  terminal: boolean;
  disposition: string;
  dispositionReason: string;
  tone: SemanticTone;
  failureCategory: string;
  /** True when the decision holds no disposition and is awaiting Quality. */
  qualityDecisionRequired: boolean;
  securityBlocked: boolean;
  auditHash: string;
  runs: RunVM[];
  evidence: RecordEvidenceVM[];
  human: HumanContinuationVM;
  mutation: MutationVM;
  consequence: RecordConsequenceVM;
}

const TRUST_LABEL: Record<string, string> = {
  UNTRUSTED_SUPPLIER: 'Supplier — untrusted',
  HUMAN_AUTHORIZED: 'Human authorized',
  QUARANTINED: 'Quarantined',
  INTERNAL: 'Internal',
};

/**
 * One agent's independent view, from ITS OWN brief.
 *
 * The verifier's conclusions are read from `verifier.brief` and the
 * reconciliation's `verifier_values`. Borrowing the investigator's brief to
 * fill a gap here would make two independent agents look like one, which is
 * precisely the property the architecture exists to prove.
 */
function toAgent(
  raw: unknown,
  role: 'investigator' | 'verifier',
  values: Doc,
): RunAgentVM | null {
  const seg = obj(raw);
  if (Object.keys(seg).length === 0) return null;
  const brief = obj(seg.brief);
  const basis = obj(brief.governing_basis);
  const specId = str(basis.spec_id);
  const revision = str(basis.revision);

  // Coverage comes from the reconciliation's per-role values when present —
  // that is the only place the two agents' answers are recorded side by side.
  const coverage = arr(values.coverage).map((c) => str(obj(c).test)).filter(Boolean);
  const missing = arr(values.missing).map((m) => str(m)).filter(Boolean);

  return {
    role,
    modelId: str(seg.model_id),
    promptVersion: str(seg.prompt_version),
    briefHash: str(seg.brief_hash),
    toolCount: arr(seg.tool_events).length,
    schemaValid: bool(seg.schema_valid),
    governingBasis: specId ? `${specId} Rev ${revision}` : '',
    covered: coverage,
    missing,
    present: true,
  };
}

function toRun(raw: unknown, runNumber: number): RunVM {
  const run = obj(raw);
  const recon = obj(run.reconciliation);
  const disp = obj(run.disposition);
  const basis = obj(run.basis);
  const outcome = str(recon.outcome, 'pending');
  const disposition = str(disp.disposition);
  const specId = str(basis.spec_id);

  return {
    runNumber,
    investigator: toAgent(run.investigator, 'investigator', obj(recon.investigator_values)),
    verifier: toAgent(run.verifier, 'verifier', obj(recon.verifier_values)),
    reconciliation: {
      outcome,
      // MATCH and NON_MATERIAL_DIFFERENCE both mean the two agents agreed on
      // everything that decides the outcome. Only a MATERIAL disagreement is
      // a disagreement for the operator's purposes.
      agreed: outcome === 'MATCH' || outcome === 'NON_MATERIAL_DIFFERENCE',
      differingFields: arr(recon.differing_fields).map((f) => str(f)).filter(Boolean),
    },
    disposition,
    dispositionReason: str(disp.reason),
    tone: dispositionTone(disposition),
    governingBasis: specId ? `${specId} Rev ${str(basis.revision)}` : '',
    failureCategory: str(run.failure_category),
    abstained: disposition === '',
    archivedAt: str(run.archived_at),
  };
}

/**
 * Every run in order, current one last.
 *
 * Mirrors `DecisionRecord.runs()`: archived runs hold the completed history and
 * the live segments hold the run in progress.
 */
export function runsOf(record: Doc): RunVM[] {
  const archived = arr(record.archived_runs);
  const runCount = typeof record.run_count === 'number' ? record.run_count : archived.length + 1;
  const history = archived.map((run, i) => {
    const n = obj(run).run_number;
    return toRun(run, typeof n === 'number' ? n : i + 1);
  });
  const current = toRun(
    {
      investigator: record.investigator,
      verifier: record.verifier,
      reconciliation: record.reconciliation,
      basis: record.basis,
      disposition: record.disposition,
      failure_category: record.failure_category,
    },
    runCount,
  );
  return [...history, current];
}

function toEvidence(raw: unknown): RecordEvidenceVM {
  const s = obj(raw);
  const trust = str(s.trust_class) || str(s.trust_label);
  return {
    artifactId: str(s.artifact_id),
    documentIdentity: str(s.document_identity),
    trustClass: trust,
    trustLabel: TRUST_LABEL[trust] ?? trust,
    securityState: str(s.security_state),
    contentHash: str(s.content_hash),
    objectVersion: str(s.object_version),
    claimCount: typeof s.claim_count === 'number' ? s.claim_count : 0,
    excluded: bool(s.excluded_from_decision_use),
    humanAuthorized: trust === 'HUMAN_AUTHORIZED',
    // `view_ref` is a 300s bearer credential: its PRESENCE is all that is kept,
    // never the value. The viewer re-fetches one when a document is opened.
    openable: str(s.view_ref) !== '',
  };
}

export function toDecisionRecord(
  record: Doc,
  sources: unknown[] = [],
): DecisionRecordVM {
  const identity = obj(record.identity);
  const disp = obj(record.disposition);
  const human = obj(record.human);
  const mutation = obj(record.mutation);
  const consequences = obj(record.consequences);
  const security = obj(record.security);
  const recovery = obj(consequences.recovery);
  const disposition = str(disp.disposition);

  const authoritySource = str(human.authority_source);
  const evidenceSupplied = arr(human.evidence_supplied).map((e) => str(e)).filter(Boolean);

  return {
    recordId: str(record.record_id),
    lotId: str(identity.lot_id) || str(record.lot_id),
    materialId: str(identity.material_id),
    supplierId: str(identity.supplier_id),
    supplierSite: str(identity.supplier_site),
    createdAt: str(record.created_at),
    runCount: typeof record.run_count === 'number' ? record.run_count : 1,
    terminal: bool(record.terminal),
    disposition,
    dispositionReason: str(disp.reason),
    tone: dispositionTone(disposition),
    failureCategory: str(record.failure_category),
    // No disposition and no security block means the case is open for Quality.
    qualityDecisionRequired: disposition === '' && !bool(security.blocked),
    securityBlocked: bool(security.blocked),
    auditHash: str(record.audit_hash),
    runs: runsOf(record),
    evidence: sources.map(toEvidence),
    human: {
      // A continuation is proven by supplied evidence or a named authority,
      // never by run count alone.
      occurred: evidenceSupplied.length > 0 || authoritySource !== '',
      authoritySource,
      evidenceSupplied,
      resumedRunIds: arr(human.resumed_run_ids).map((r) => str(r)).filter(Boolean),
      reviewId: str(human.review_id),
      reviewStatus: str(human.review_status),
    },
    mutation: {
      // `result` is written only when a mutation actually executed. A refused
      // or abstained decision leaves this segment empty, and the UI must show
      // "no state change" rather than an empty mutation panel.
      occurred: str(mutation.result) !== '',
      action: str(mutation.action),
      targetType: str(mutation.target_type),
      targetId: str(mutation.target_id),
      versionChange:
        typeof mutation.before_version === 'number' && typeof mutation.after_version === 'number'
          ? `v${mutation.before_version} → v${mutation.after_version}`
          : '',
      result: str(mutation.result),
      ledgerSequence: str(mutation.ledger_sequence),
    },
    consequence: {
      readinessChanges: arr(consequences.readiness_changes).map((c) => {
        const r = obj(c);
        return {
          orderId: str(r.order_id),
          from: str(r.from),
          to: str(r.to),
          reason: str(r.reason),
        };
      }),
      recoveryCandidates: arr(recovery.candidates).map((c) => {
        const r = obj(c);
        return {
          candidateId: str(r.candidate_id),
          kind: str(r.kind),
          verdict: str(r.verdict),
          reasonCode: str(r.reason_code),
        };
      }),
      recoveryExecuted: bool(recovery.executed),
      blockedOrderId: str(recovery.blocked_order_id),
    },
  };
}
