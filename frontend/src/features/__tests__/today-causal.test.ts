/**
 * Today's causal history: what changed, and which decision did it.
 *
 * The attribution rule is the point. A RELEASE adds usable material, so it can
 * make another order executable and can expose a shortfall the plan had not
 * faced. A QUARANTINE removes nothing — the lot was never usable inventory — so
 * nothing here may describe it as taking material away or as the reason an
 * order moved.
 */

import { describe, expect, it } from 'vitest';
import { toCausalHistory, toToday } from '../today/model';
import type { CausalEventDTO, TodayDTO } from '../../decision/dto';

const RELEASE_EXPOSES_SHORTFALL: CausalEventDTO = {
  kind: 'readiness',
  lot_id: 'LOT-1001',
  disposition: 'RELEASE',
  order_id: 'C-417',
  from: 'READY',
  to: 'BLOCKED',
  material_id: 'MAT-ALLOY-7',
  inventory_delta: 500,
  decision_record_id: 'DR-aaa',
  ledger_sequence: 2,
};

const RESEQUENCE: CausalEventDTO = {
  kind: 'resequence',
  lot_id: 'LOT-1001',
  disposition: 'RELEASE',
  order_id: 'C-418',
  blocked_order_id: 'C-417',
  from_slot: '2026-08-15T14:00',
  to_slot: '2026-08-15T08:00',
  decision_record_id: 'DR-aaa',
  ledger_sequence: 3,
  candidates: [
    {
      kind: 'EXISTING_INVENTORY',
      candidate_id: 'MAT-ALLOY-7',
      verdict: 'NOT_FEASIBLE',
      reason_code: 'INSUFFICIENT_QUANTITY',
      facts: { required: 900, available: 500, short_by: 400 },
    },
    {
      kind: 'SUBSTITUTE',
      candidate_id: 'MAT-SUB-9',
      verdict: 'REFUSED',
      reason_code: 'NOT_APPROVED',
      facts: { available: 900, needed: 400, approved: false },
    },
    {
      kind: 'RESEQUENCE',
      candidate_id: 'C-418',
      verdict: 'ELIGIBLE',
      reason_code: 'FEASIBLE',
      facts: { materials_ready: true, slot_free: true },
    },
    {
      kind: 'RESEQUENCE',
      candidate_id: 'C-419',
      verdict: 'NOT_FEASIBLE',
      reason_code: 'RESOURCE_INCOMPATIBLE',
      facts: { materials_ready: true },
    },
  ],
};

describe('Today causal history', () => {
  it('credits the RELEASE with the material it made usable', () => {
    const [event] = toCausalHistory([RELEASE_EXPOSES_SHORTFALL]);
    expect(event.sentence).toContain('LOT-1001 released 500 MAT-ALLOY-7');
    expect(event.sentence).toContain('C-417');
    expect(event.decisionRecordId).toBe('DR-aaa');
  });

  it('explains the move by the moved order’s own coverage', () => {
    const [event] = toCausalHistory([RESEQUENCE]);
    expect(event.sentence).toContain('C-418 moved into 08:00');
    expect(event.sentence).toContain('already fully satisfied by released inventory');
  });

  it('never attributes the resequence to the quarantine', () => {
    const [event] = toCausalHistory([RESEQUENCE]);
    expect(event.lotId).toBe('LOT-1001');
    expect(event.sentence).not.toContain('LOT-1002');
  });

  it('never says a quarantine removed usable inventory', () => {
    // A quarantine carries no positive inventory delta, so the "released N"
    // wording must not be reachable for it.
    const [event] = toCausalHistory([
      {
        kind: 'readiness',
        lot_id: 'LOT-1002',
        disposition: 'QUARANTINE',
        order_id: 'C-417',
        from: 'READY',
        to: 'BLOCKED',
        material_id: 'MAT-ALLOY-7',
        inventory_delta: 0,
        decision_record_id: 'DR-bbb',
      },
    ]);
    expect(event.sentence).not.toMatch(/released/i);
    expect(event.sentence).not.toMatch(/removed|took away|reduced/i);
  });

  it('renders every candidate with its refusal reason', () => {
    const [event] = toCausalHistory([RESEQUENCE]);
    const byId = Object.fromEntries(event.candidates.map((c) => [c.candidateId, c]));

    expect(byId['MAT-SUB-9'].verdict).toBe('REFUSED');
    // Availability is not authority — the sentence has to say so.
    expect(byId['MAT-SUB-9'].detail).toContain('not approved for this product');
    expect(byId['MAT-ALLOY-7'].detail).toContain('500 of 900 required');
    expect(byId['C-419'].detail).toContain('different line');
    expect(byId['C-418'].verdict).toBe('ELIGIBLE');
  });

  it('survives a payload with no causal history at all', () => {
    const vm = toToday({ ok: true, lines: [] } as TodayDTO);
    expect(vm.causalHistory).toEqual([]);
  });

  it('carries the history onto the view model in ledger order', () => {
    const vm = toToday({
      ok: true,
      lines: [],
      causal_history: [RELEASE_EXPOSES_SHORTFALL, RESEQUENCE],
    } as TodayDTO);
    expect(vm.causalHistory.map((e) => e.kind)).toEqual(['readiness', 'resequence']);
  });
});
