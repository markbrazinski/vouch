/**
 * Incoming — the arrivals queue.
 *
 * Every field here is served by `list_decisions`. Notably `row_state` and the
 * display names are computed SERVER-side (integration contract §4): two clients
 * deriving them independently would eventually disagree about what the same
 * record means, and a client resolving ids itself could render a name the plant
 * does not use. This module therefore maps and groups; it classifies nothing.
 *
 * There is deliberately no `inProgress` or `completedByVouch` counter.
 * Invocation is synchronous, so no decision is ever persisted mid-flight and
 * any such number would be fiction; nothing in the model attributes a decision
 * to Vouch rather than to a human.
 */

import type { EnvelopeDTO } from '../../decision/dto';
import type { SemanticTone } from '../../view-models/types';

/** §4. Server-computed; never derived in the browser. */
export type RowState =
  | 'EVIDENCE_RECEIVED'
  | 'RELEASED'
  | 'QUARANTINED'
  | 'QUALITY_DECISION_REQUIRED'
  | 'SECURITY_HOLD';

export interface IncomingRowDTO {
  decision_record_id: string;
  lot_id: string;
  material_id: string;
  material_name: string;
  supplier_id: string;
  supplier_name: string;
  supplier_site: string;
  received_at: string;
  quantity: number | null;
  units: string;
  lot_status: string;
  disposition: string;
  failure_category: string;
  row_state: RowState;
  attention_required: boolean;
  decided_at: string;
}

export interface ListDecisionsDTO extends EnvelopeDTO {
  rows?: IncomingRowDTO[];
  cursor?: unknown;
  counts?: { returned?: number };
}

export interface IncomingRowVM {
  decisionRecordId: string;
  lotId: string;
  materialId: string;
  /** Joined server-side. Falls back to the id rather than inventing a name. */
  materialName: string;
  supplierName: string;
  supplierSite: string;
  receivedAt: string;
  /** Pre-formatted from the server's number. "—" when there is none. */
  quantity: string;
  lotStatus: string;
  disposition: string;
  failureCategory: string;
  rowState: RowState;
  /** The server's own flag. Not a browser rule. */
  attentionRequired: boolean;
  decidedAt: string;
  stateLabel: string;
  tone: SemanticTone;
}

export interface IncomingVM {
  rows: IncomingRowVM[];
  /** Rows the SERVER flagged as needing a person. */
  needsAttention: IncomingRowVM[];
  settled: IncomingRowVM[];
  /** Only counters with an authoritative meaning. */
  returned: number;
  durable: boolean;
  hasMore: boolean;
}

const STATE_LABEL: Record<RowState, string> = {
  EVIDENCE_RECEIVED: 'EVIDENCE RECEIVED',
  RELEASED: 'RELEASED',
  QUARANTINED: 'QUARANTINED',
  QUALITY_DECISION_REQUIRED: 'QUALITY DECISION',
  SECURITY_HOLD: 'SECURITY HOLD',
};

const STATE_TONE: Record<RowState, SemanticTone> = {
  EVIDENCE_RECEIVED: 'progress',
  RELEASED: 'released',
  QUARANTINED: 'quarantine',
  QUALITY_DECISION_REQUIRED: 'decision',
  SECURITY_HOLD: 'refused',
};

const NUM = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

export function toIncomingRow(dto: IncomingRowDTO): IncomingRowVM {
  const state = (STATE_LABEL[dto.row_state] ? dto.row_state : 'EVIDENCE_RECEIVED') as RowState;
  return {
    decisionRecordId: dto.decision_record_id,
    lotId: dto.lot_id,
    materialId: dto.material_id,
    // An id is a truthful fallback; a made-up display name is not.
    materialName: dto.material_name || dto.material_id,
    supplierName: dto.supplier_name || dto.supplier_id,
    supplierSite: dto.supplier_site,
    receivedAt: dto.received_at,
    quantity:
      typeof dto.quantity === 'number'
        ? `${NUM.format(dto.quantity)}${dto.units ? ` ${dto.units}` : ''}`
        : '—',
    lotStatus: dto.lot_status,
    disposition: dto.disposition,
    failureCategory: dto.failure_category,
    rowState: state,
    attentionRequired: dto.attention_required === true,
    decidedAt: dto.decided_at,
    stateLabel: STATE_LABEL[state],
    tone: STATE_TONE[state],
  };
}

export function toIncoming(dto: ListDecisionsDTO): IncomingVM {
  const rows = (dto.rows ?? []).map(toIncomingRow);
  return {
    rows,
    // Partitioned on the SERVER's flag, not on a disposition rule re-derived here.
    needsAttention: rows.filter((r) => r.attentionRequired),
    settled: rows.filter((r) => !r.attentionRequired),
    returned: dto.counts?.returned ?? rows.length,
    durable: dto.backend?.durable === true,
    hasMore: dto.cursor != null,
  };
}

/**
 * Incoming's authoritative set: one row per CURRENT lot.
 *
 * `list_decisions` is a ledger — its unit is the decision, so a lot evaluated
 * thirty times during qualification returns thirty rows. Rendering those as
 * sibling arrivals told an operator there were thirty arrivals when there were
 * four, and made "open LOT-1002" ambiguous between a current lot and whichever
 * historical execution happened to be that row.
 *
 * Collapsing by `lot_id` and keeping the newest `decided_at` is a projection
 * over data the backend already returned. It invents nothing: the surviving row
 * is a real record, and every field on it is still the server's. Records keeps
 * the ungrouped ledger, which is where repeated lot ids are meaningful because
 * each row is explicitly a different DecisionRecord.
 */
export function toCurrentArrivals(dto: ListDecisionsDTO): IncomingVM {
  const newestByLot = new Map<string, IncomingRowVM>();
  for (const row of (dto.rows ?? []).map(toIncomingRow)) {
    const held = newestByLot.get(row.lotId);
    // String compare is safe and total here: `decided_at` is ISO-8601 UTC from
    // the server. A row with no timestamp never displaces one that has a real
    // one, so a malformed record cannot hide the current state of a lot.
    if (!held || row.decidedAt > held.decidedAt) newestByLot.set(row.lotId, row);
  }
  const rows = [...newestByLot.values()].sort((a, b) => a.lotId.localeCompare(b.lotId));
  return {
    rows,
    needsAttention: rows.filter((r) => r.attentionRequired),
    settled: rows.filter((r) => !r.attentionRequired),
    // The count an operator can act on is the number of LOTS, not the number of
    // ledger entries that happen to be behind them.
    returned: rows.length,
    durable: dto.backend?.durable === true,
    hasMore: false,
  };
}
