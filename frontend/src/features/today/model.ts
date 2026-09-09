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

export interface PlannedSourceVM {
  lotId: string;
  quantity: string;
  lotStatus: string;
  /** False once the lot can no longer honour the allocation. */
  honourable: boolean;
}

export interface CoverageVM {
  materialId: string;
  /** Pre-formatted from backend numbers. Never recomputed. */
  required: string;
  available: string;
  shortBy: string;
  /** Queued against this order by an explicit allocation. */
  planned: string;
  /** Neither released nor queued. Zero means the plan adds up. */
  uncovered: string;
  /** True when the backend reported a shortfall. Not a browser comparison. */
  short: boolean;
  /** Whether anything is queued at all — drives which sentence is shown. */
  hasPlanned: boolean;
  sources: PlannedSourceVM[];
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
  kind: 'readiness' | 'resequence' | 'quarantine';
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
    planned: qty(row.planned ?? 0),
    uncovered: qty(row.uncovered ?? row.short_by),
    hasPlanned: (row.planned_sources ?? []).length > 0,
    sources: (row.planned_sources ?? []).map((source) => ({
      lotId: source.lot_id,
      quantity: qty(source.quantity),
      lotStatus: source.lot_status ?? '',
      honourable: COVERABLE.has(source.lot_status ?? ''),
    })),
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

/**
 * Readiness, in words, and labelled as readiness.
 *
 * `from`/`to` on a causal link are the order's PLAN status catching up to what
 * Vouch computed. Rendering the raw enum as "C-417 is now AT_RISK" read as a
 * plan change and hid which of the two moved — the distinction the whole
 * surface exists to show.
 */
const READINESS_WORDING: Record<string, string> = {
  READY: 'ready',
  AT_RISK: 'at risk',
  BLOCKED: 'blocked',
  COMPLETE: 'complete',
};

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
  const all = rows ?? [];

  /** The shortfall the blocked order still carries, from the recovery facts. */
  const shortfallFor = (blockedOrderId: string): { short: number; material: string } | null => {
    for (const row of all) {
      if (row.kind !== 'resequence' || row.blocked_order_id !== blockedOrderId) continue;
      for (const candidate of row.candidates ?? []) {
        if (candidate.kind !== 'EXISTING_INVENTORY') continue;
        const facts = candidate.facts ?? {};
        return {
          short: (facts.short_by as number) ?? 0,
          material: candidate.candidate_id,
        };
      }
    }
    return null;
  };

  /**
   * A release whose resequence is reported separately is ONE event.
   *
   * The readiness recomputation genuinely produces "C-417 READY -> BLOCKED" on
   * the release, but saying it that way makes the clean lot read as the thing
   * that broke the order. It did not: C-417 was short before anything was
   * released, and releasing 500 kg only made the existing gap measurable. So
   * the two rows are stated as one sentence — what the release ENABLED, then
   * what remains short, then the move that followed.
   */
  const foldedInto = new Set<CausalEventDTO>();
  /** The release facts folded into a resequence, keyed by decision record. */
  const releaseFacts = new Map<string, { delta: number; material: string }>();
  for (const row of all) {
    if (row.kind !== 'resequence') continue;
    for (const other of all) {
      if (
        other.kind !== 'resequence' &&
        other.decision_record_id === row.decision_record_id &&
        other.order_id === row.blocked_order_id
      ) {
        foldedInto.add(other);
        if ((other.inventory_delta ?? 0) > 0) {
          releaseFacts.set(row.decision_record_id ?? '', {
            delta: other.inventory_delta ?? 0,
            material: other.material_id ?? '',
          });
        }
      }
    }
  }

  return all
    .filter((row) => !foldedInto.has(row))
    .map((row) => {
    const lot = row.lot_id ?? '';
    const order = row.order_id ?? '';
    let sentence: string;

    if (row.kind === 'resequence') {
      const blocked = row.blocked_order_id ?? '';
      const gap = shortfallFor(blocked);
      // Who gets credit for the move depends on what the deciding record did.
      // A RELEASE that also freed the slot enabled the alternative; a
      // QUARANTINE ended the plan that was holding the slot. Attributing the
      // resequence to a release when a quarantine caused it reads as the clean
      // lot rescheduling the factory, which is not what happened.
      const released = releaseFacts.get(row.decision_record_id ?? '');
      const enabling = released
        ? `${lot} released ${qty(released.delta)} kg of ${released.material}, ` +
          `making ${order} fully executable. `
        : row.disposition === 'QUARANTINE'
          ? `${lot} was quarantined, so the material queued for ${blocked} can no ` +
            `longer arrive. `
          : row.disposition === 'RELEASE'
            ? `${lot} released the material ${order} needs, making it fully executable. `
            : '';
      const remains = gap
        ? `${blocked} remains ${qty(gap.short)} kg short, so `
        : `${blocked} remains blocked, so `;
      sentence =
        `${enabling}${remains}Vouch moved ${order} into the available ` +
        `${slotClock(row.to_slot ?? '')} slot.`;
    } else if (row.kind === 'readiness' && row.disposition === 'QUARANTINE') {
      // The queued coverage was lost. Never "removed inventory" — a quarantined
      // lot was never usable, and its inventory_delta is correctly 0 — and
      // never a plan change either. The quantity is deliberately not taken from
      // the delta, which would print "0 kg".
      const to = READINESS_WORDING[row.to ?? ''] ?? row.to;
      sentence =
        `The material queued for ${order} from ${lot} is no longer available, ` +
        `so its readiness moved to ${to}. The plan is unchanged.`;
    } else if (row.kind === 'quarantine' || row.disposition === 'QUARANTINE') {
      // Never "removed inventory": a quarantined lot was never usable, so the
      // consequence is a QUALITY one. The basis is named because "quarantined"
      // without the revision it was judged against is not an explanation.
      const basis = [row.spec_id, row.revision && `Revision ${row.revision}`]
        .filter(Boolean)
        .join(' ');
      sentence =
        `${lot} was quarantined against ${basis || 'its governing specification'}. ` +
        `The remaining evidence cannot support release, so ${order || 'the order'} ` +
        `remains blocked.`;
    } else if ((row.inventory_delta ?? 0) > 0) {
      // A release ADDS material, so this is an improvement — and the useful
      // sentence says what the requirement is now MADE of, not which way a
      // readiness enum moved. "C-417 is now AT_RISK" made the one clean
      // decision of the day read as damage; the badges still carry the
      // authoritative PLAN and VOUCH states, so the prose does not need to.
      const released = `${lot} released ${qty(row.inventory_delta)} kg of ${row.material_id ?? ''}.`;
      const queued = (row.planned_sources ?? [])
        .map((source) => `${qty(source.quantity)} kg queued from ${source.lot_id}`)
        .join(' and ');
      const composition =
        (row.uncovered ?? 0) === 0 && queued
          ? ` ${order} is now fully coverable on plan: ${qty(row.available)} kg ` +
            `released and ${queued}, awaiting Quality.`
          : queued
            ? ` ${order} has ${qty(row.available)} kg released and ${queued}, ` +
              `still short ${qty(row.uncovered)} kg.`
            : ` ${order} has ${qty(row.available)} kg of ${qty(row.required)} kg released.`;
      sentence = `${released}${composition} The plan is unchanged.`;
    } else {
      const to = READINESS_WORDING[row.to ?? ''] ?? row.to;
      sentence = `${order} readiness is now ${to} after ${lot} was assessed.`;
    }

    return {
      kind: (row.kind === 'resequence' || row.kind === 'quarantine'
        ? row.kind
        : 'readiness') as CausalEventVM['kind'],
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

/** Lot states in which a queued allocation can still arrive. */
const COVERABLE = new Set(['RECEIVED', 'PENDING_QA']);

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
