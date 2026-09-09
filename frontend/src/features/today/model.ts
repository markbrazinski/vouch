/**
 * Today's view model: authoritative production state, projected for rendering.
 *
 * Every number here is COPIED from `get_today`, never computed. Readiness,
 * coverage, shortage and the ratio are deterministic Python (AGENTS.md §6), and
 * a browser that recomputed any of them could disagree with the decision path
 * that produced them. The adapter's job is formatting and ordering only.
 *
 * The distinction this module exists to preserve: `status` is the STORED order
 * state and `readiness` is the COMPUTED one. They differ legitimately — live
 * C-417 is stored `READY` while computing `BLOCKED` — and collapsing them would
 * erase the fact that a disposition has outrun the plan.
 */

import type {
  CausalEventDTO,
  CoverageDTO,
  RecoveryCandidateDTO,
  TodayDTO,
  TodayOrderDTO,
} from '../../decision/dto';
import type { ProductionReadiness, SemanticTone } from '../../view-models/types';
import { readinessTone } from '../../components/tokens';

/** Readiness values the UI has a visual language for. */
const KNOWN: ProductionReadiness[] = ['READY', 'AT_RISK', 'BLOCKED'];

export interface CoverageVM {
  materialId: string;
  /** Pre-formatted from backend numbers. Never recomputed. */
  required: string;
  available: string;
  shortBy: string;
  /** True when the backend reported a shortfall. Not a browser comparison. */
  short: boolean;
}

export interface TodayOrderVM {
  orderId: string;
  product: string;
  /** "08:00" — presentation of `planned_slot`, not a recalculated time. */
  slot: string;
  plannedSlot: string;
  /** The STORED order state. */
  status: string;
  /** The COMPUTED readiness. Never merged with `status`. */
  readiness: ProductionReadiness;
  /** True when the two disagree — the operationally interesting case. */
  divergent: boolean;
  tone: SemanticTone;
  /** The backend's own sentence. Not assembled here. */
  reason: string;
  coverage: CoverageVM[];
  requirements: { materialId: string; quantity: string }[];
  customerCommitted: boolean;
  needBy: string;
  /** Primary material, for the compact cell. Empty when there is none. */
  materialLabel: string;
}

export interface TodayLineVM {
  lineId: string;
  orders: TodayOrderVM[];
  /** True when any order on this line computes non-READY. */
  disturbed: boolean;
}

export interface ReadinessCountVM {
  readiness: ProductionReadiness;
  count: number;
  label: string;
}

export interface RecoveryCandidateVM {
  kind: string;
  candidateId: string;
  verdict: 'ELIGIBLE' | 'REFUSED' | 'NOT_FEASIBLE';
  reasonCode: string;
  /** The backend's own facts for this candidate, pre-formatted. */
  detail: string;
}

/**
 * One thing a decision did to the plan, replayed from the stored record.
 *
 * These persist after the plan and the evidence converge. The banner used to
 * be keyed on divergence, so the explanation disappeared exactly when the
 * operator most needed it — at the end, looking at a moved order and a blocked
 * one with nothing saying why.
 */
export interface CausalEventVM {
  kind: 'readiness' | 'resequence';
  lotId: string;
  disposition: string;
  orderId: string;
  /** Present for a readiness change. */
  from: string;
  to: string;
  /** Present for a resequence. */
  fromSlot: string;
  toSlot: string;
  blockedOrderId: string;
  decisionRecordId: string;
  /** One truthful sentence. Attribution matters: see `toCausalHistory`. */
  sentence: string;
  candidates: RecoveryCandidateVM[];
}

export interface TodayVM {
  counts: ReadinessCountVM[];
  lines: TodayLineVM[];
  /** Orders whose computed readiness has outrun their stored status. */
  divergent: TodayOrderVM[];
  /** What the recorded decisions did to this plan, oldest first. */
  causalHistory: CausalEventVM[];
  /** Totals straight from the payload — the count of what was returned. */
  orderCount: number;
  lineCount: number;
  durable: boolean;
}

const NUM = new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });

const qty = (value: number | undefined): string =>
  typeof value === 'number' ? NUM.format(value) : '—';

/** "2026-08-15T08:00" -> "08:00". Formatting, not arithmetic. */
export const slotClock = (slot: string): string => {
  const at = slot.indexOf('T');
  return at === -1 ? slot : slot.slice(at + 1, at + 6);
};

const readinessOf = (raw: string | undefined): ProductionReadiness =>
  KNOWN.includes(raw as ProductionReadiness) ? (raw as ProductionReadiness) : 'READY';

function coverageOf(rows: CoverageDTO[] | undefined): CoverageVM[] {
  return (rows ?? []).map((row) => ({
    materialId: row.material_id,
    required: qty(row.required),
    available: qty(row.available),
    shortBy: qty(row.short_by),
    // The backend already decided there is a shortfall by computing short_by.
    // This reads that decision; it does not re-derive it from required minus
    // available, which is exactly the arithmetic the contract keeps in Python.
    short: (row.short_by ?? 0) > 0,
  }));
}

export function toOrder(dto: TodayOrderDTO): TodayOrderVM {
  const readiness = readinessOf(dto.readiness);
  const status = dto.status ?? '';
  const coverage = coverageOf(dto.coverage);
  const requirements = (dto.requirements ?? []).map((r) => ({
    materialId: r.material_id,
    quantity: qty(r.quantity),
  }));

  return {
    orderId: dto.order_id,
    product: dto.product ?? '',
    slot: slotClock(dto.planned_slot ?? ''),
    plannedSlot: dto.planned_slot ?? '',
    status,
    readiness,
    // Stored and computed disagreeing is the signal Today exists to show.
    divergent: status !== '' && status !== readiness,
    tone: readinessTone[readiness],
    reason: dto.reason ?? '',
    coverage,
    requirements,
    customerCommitted: dto.customer_committed === true,
    needBy: dto.need_by ?? '',
    materialLabel: requirements[0]?.materialId ?? coverage[0]?.materialId ?? '',
  };
}

const REFUSAL_WORDING: Record<string, string> = {
  INSUFFICIENT_QUANTITY: 'not enough released material',
  NOT_APPROVED: 'stock exists, but it is not approved for this product',
  RESOURCE_INCOMPATIBLE: 'scheduled on a different line',
  SLOT_OCCUPIED: 'the target slot is taken',
  MATERIALS_NOT_RELEASED: 'its own material is not released yet',
  FEASIBLE: 'material fully released, same line, slot free',
};

function candidateDetail(candidate: RecoveryCandidateDTO): string {
  const facts = candidate.facts ?? {};
  const code = candidate.reason_code ?? '';
  const wording = REFUSAL_WORDING[code] ?? code;
  if (code === 'INSUFFICIENT_QUANTITY') {
    return `${wording} — ${qty(facts.available as number)} of ${qty(facts.required as number)} required`;
  }
  if (code === 'NOT_APPROVED') {
    return `${wording} (${qty(facts.available as number)} on hand)`;
  }
  return wording;
}

/**
 * Turn recorded causal links into sentences Today can show.
 *
 * The attribution rule, and it is the whole reason this function exists rather
 * than a template at the call site: a RELEASE adds usable material, so it is
 * what can make another order executable and what can expose a shortfall a
 * plan had not yet faced. A QUARANTINE removes nothing — the lot was never
 * usable inventory — so it must never be described as having taken material
 * away, or as the reason another order moved.
 */
export function toCausalHistory(rows: CausalEventDTO[] | undefined): CausalEventVM[] {
  return (rows ?? []).map((row) => {
    const lot = row.lot_id ?? '';
    const order = row.order_id ?? '';
    let sentence: string;

    if (row.kind === 'resequence') {
      sentence =
        `${order} moved into ${slotClock(row.to_slot ?? '')} because its material ` +
        `requirements were already fully satisfied by released inventory. ` +
        `${row.blocked_order_id ?? ''} could not run in that slot.`;
    } else if ((row.inventory_delta ?? 0) > 0) {
      // A release. It added material AND revealed what is still uncovered.
      sentence =
        `${lot} released ${qty(row.inventory_delta)} ${row.material_id ?? ''}, ` +
        `which moved ${order} from ${row.from} to ${row.to}.`;
    } else {
      // Not a release. Say what changed without claiming stock was removed.
      sentence = `${order} moved from ${row.from} to ${row.to} after ${lot} was assessed.`;
    }

    return {
      kind: (row.kind === 'resequence' ? 'resequence' : 'readiness') as CausalEventVM['kind'],
      lotId: lot,
      disposition: row.disposition ?? '',
      orderId: order,
      from: row.from ?? '',
      to: row.to ?? '',
      fromSlot: row.from_slot ?? '',
      toSlot: row.to_slot ?? '',
      blockedOrderId: row.blocked_order_id ?? '',
      decisionRecordId: row.decision_record_id ?? '',
      sentence,
      candidates: (row.candidates ?? []).map((c) => ({
        kind: c.kind ?? '',
        candidateId: c.candidate_id,
        verdict: c.verdict,
        reasonCode: c.reason_code ?? '',
        detail: candidateDetail(c),
      })),
    };
  });
}

export function toToday(dto: TodayDTO): TodayVM {
  const lines: TodayLineVM[] = (dto.lines ?? []).map((line) => {
    const orders = (line.orders ?? []).map(toOrder);
    return {
      lineId: line.line_id,
      orders,
      disturbed: orders.some((o) => o.readiness !== 'READY'),
    };
  });

  const counts = dto.readiness_counts ?? {};
  return {
    // Counts are the backend's tally, in a fixed display order. Summing the
    // orders here would produce a second, competing count.
    counts: KNOWN.map((readiness) => ({
      readiness,
      count: counts[readiness] ?? 0,
      label: readiness === 'AT_RISK' ? 'AT RISK' : readiness,
    })),
    lines,
    divergent: lines.flatMap((l) => l.orders).filter((o) => o.divergent),
    causalHistory: toCausalHistory(dto.causal_history),
    orderCount: lines.reduce((n, l) => n + l.orders.length, 0),
    lineCount: lines.length,
    durable: dto.backend?.durable === true,
  };
}
