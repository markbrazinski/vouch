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

import type { CoverageDTO, TodayDTO, TodayOrderDTO } from '../../decision/dto';
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

export interface TodayVM {
  counts: ReadinessCountVM[];
  lines: TodayLineVM[];
  /** Orders whose computed readiness has outrun their stored status. */
  divergent: TodayOrderVM[];
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
    orderCount: lines.reduce((n, l) => n + l.orders.length, 0),
    lineCount: lines.length,
    durable: dto.backend?.durable === true,
  };
}
