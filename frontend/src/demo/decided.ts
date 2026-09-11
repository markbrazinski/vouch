/**
 * What the archived runs played so far have decided, and what that did to the
 * plan.
 *
 * Demo Mode calls no backend, so nothing records that a lot was just decided.
 * Without this the board kept showing all five lots awaiting a decision after
 * they had been watched being decided, which across a session reads as nothing
 * having happened.
 *
 * TWO RULES THIS MODULE EXISTS TO KEEP
 *
 *   1. ONLY THE OUTCOME IS REMEMBERED. A decided row is the canonical opening
 *      row with its disposition changed — never a row built from scratch. The
 *      captured record carries ids, not display names, so composing a row here
 *      produced "SUP-CENTRAL" and a missing quantity where the board says
 *      "Central Forgeworks · 200 kg". Overlaying keeps every joined field
 *      truthful and leaves exactly one thing to this module: what the run
 *      decided.
 *
 *   2. THE CONSEQUENCE COMES FROM THE RUN, NOT FROM A TABLE. Which orders moved
 *      and where to is read from each run's own recorded `readiness_changes`.
 *      A per-lot table of expected endings here would be a second source of
 *      truth able to contradict the recording being watched.
 *
 * State is module-level and deliberately not persisted: `Reset demo` clears it,
 * and so does a reload. A demo that remembers yesterday's session is a demo
 * nobody can start cleanly.
 */

import type { TodayDTO, TodayOrderDTO } from '../decision/dto';
import { invalidateSurfaces } from '../features/useSurfaceData';

type Row = Record<string, unknown>;

/** What one archived run decided. Not a row — just its outcome. */
interface Decided {
  decisionRecordId: string;
  disposition: string;
  failureCategory: string;
  rowState: string;
}

const decided = new Map<string, Decided>();

/**
 * Where each production order ENDED, after the runs played so far.
 *
 * Keyed by order, not by lot, because the orders are what the runs collide on:
 * C-417 moves across more than one of the five, and only the latest value is
 * still true. Last write wins, which converges on the same answer the ledger
 * would.
 */
const readiness = new Map<string, string>();

export const playedCount = (): number => decided.size;
export const hasPlayed = (lotId: string): boolean => decided.has(lotId);

/** `Reset demo`. Every lot becomes replayable and the board returns to opening. */
export function clearDecided(): void {
  decided.clear();
  readiness.clear();
}

/**
 * The row state a run ended in, read from what it actually did.
 *
 * Never from a per-lot table: the capture knows its own disposition and failure
 * category, and hard-coding "LOT-1002 is quarantined" here would be a second
 * source of truth able to contradict the recording.
 */
function rowStateOf(disposition: string, failureCategory: string): string {
  if (failureCategory === 'SECURITY_QUARANTINE') return 'SECURITY_HOLD';
  if (disposition === 'RELEASE') return 'RELEASED';
  if (disposition === 'QUARANTINE') return 'QUARANTINED';
  if (failureCategory) return 'QUALITY_DECISION_REQUIRED';
  return 'EVIDENCE_RECEIVED';
}

export function markDecided(input: {
  lotId: string;
  decisionRecordId: string;
  disposition: string;
  failureCategory: string;
  /** `readiness_changes` from the run's own recorded consequence. */
  readinessChanges?: { order_id?: string; to?: string }[];
}): void {
  decided.set(input.lotId, {
    decisionRecordId: input.decisionRecordId,
    disposition: input.disposition,
    failureCategory: input.failureCategory,
    rowState: rowStateOf(input.disposition, input.failureCategory),
  });
  for (const change of input.readinessChanges ?? []) {
    if (change.order_id && change.to) readiness.set(change.order_id, change.to);
  }

  /**
   * Drop the retained board responses, exactly as the live path does.
   *
   * Today and Incoming keep their last answer and revalidate behind it. A run
   * that has just settled makes that answer WRONG rather than merely stale — it
   * contradicts the decision the operator watched execute — so the next read
   * must rebuild from the archive.
   *
   * Without this Today showed "3 AWAITING QUALITY" after five runs had visibly
   * blocked one order and cleared another: the overlay was correct and nothing
   * ever asked for it. Caught by `e2e/demo-mode-acceptance.mjs`, which reads
   * the board rather than trusting the module that writes it.
   */
  invalidateSurfaces(['today', 'decisions']);
}

/**
 * The opening arrivals, with any played outcome applied over its own row.
 *
 * Every joined field — supplier name, material name, quantity, site — stays the
 * canonical one. Only what the decision produced is replaced, because that is
 * the only thing a played run actually established.
 */
export function decidedRows(rows: Row[]): Row[] {
  if (!decided.size) return rows;
  return rows.map((row) => {
    const found = decided.get(String(row.lot_id));
    if (!found) return row;
    return {
      ...row,
      decision_record_id: found.decisionRecordId,
      disposition: found.disposition,
      failure_category: found.failureCategory,
      row_state: found.rowState,
      lot_status:
        found.rowState === 'RELEASED'
          ? 'RELEASED'
          : found.rowState === 'QUARANTINED'
            ? 'QUARANTINED'
            : row.lot_status,
      // A settled lot needs nothing from an operator. A security hold and an
      // open question do: both are escalations, and the board keeps saying so.
      attention_required:
        found.rowState === 'SECURITY_HOLD' || found.rowState === 'QUALITY_DECISION_REQUIRED',
      decided_at: new Date().toISOString(),
    };
  });
}

/**
 * The production plan, with the readiness each played run established.
 *
 * Only `readiness` is replaced. Coverage numbers, the reason line and the slot
 * stay the captured corpus's — they describe material the replay did not move,
 * and recomputing them in the browser would be inventing plan arithmetic, which
 * §11 of the operating contract forbids outright.
 *
 * That leaves a knowable gap: a played C-417 reads BLOCKED while its coverage
 * line still shows what was queued before the run. Stated rather than papered
 * over, because a wrong number would be worse than a stale one.
 */
export function decidedToday(dto: unknown): unknown {
  if (!readiness.size) return dto;
  const today = dto as TodayDTO;

  const lines = (today.lines ?? []).map((line) => ({
    ...line,
    orders: (line.orders ?? []).map((order: TodayOrderDTO) => {
      const to = order.order_id ? readiness.get(order.order_id) : undefined;
      return to ? { ...order, readiness: to } : order;
    }),
  }));

  // The header chips are a SEPARATE backend tally, not a sum of the orders, so
  // overlaying only the orders left the cards correct and the chips stale.
  // Recount from the orders just rewritten — the only way the two can agree.
  const counts: Record<string, number> = {};
  for (const line of lines) {
    for (const order of line.orders ?? []) {
      const state = String((order as TodayOrderDTO).readiness ?? '');
      if (state) counts[state] = (counts[state] ?? 0) + 1;
    }
  }

  return { ...today, lines, readiness_counts: counts };
}
