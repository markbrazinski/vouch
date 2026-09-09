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
  it('states what the release ENABLED, never that it blocked an order', () => {
    // The readiness recomputation really does emit C-417 READY -> BLOCKED on
    // this release, but C-417 was short before anything was released. Saying
    // the clean lot "moved C-417 to BLOCKED" makes the good decision read as
    // the cause of the problem, so the two rows fold into one sentence.
    const [event, ...rest] = toCausalHistory([RELEASE_EXPOSES_SHORTFALL, RESEQUENCE]);
    expect(rest).toHaveLength(0);
    expect(event.sentence).toBe(
      'LOT-1001 released 500 kg of MAT-ALLOY-7, making C-418 fully executable. ' +
        'C-417 remains 400 kg short, so Vouch moved C-418 into the available 08:00 slot.',
    );
    expect(event.sentence).not.toMatch(/READY to BLOCKED/);
    expect(event.decisionRecordId).toBe('DR-aaa');
  });

  it('names an improvement as an improvement, in readiness terms', () => {
    // The link's from/to are the PLAN catching up to computed readiness.
    // Rendering the raw enum ("C-417 is now AT_RISK") read as a plan change and
    // made the day's one clean decision look like damage.
    // Alone — with no resequence to fold into — the readiness link stands on
    // its own sentence, and that sentence says what the requirement is now made
    // of rather than which way a readiness enum moved. The badges carry the
    // authoritative PLAN and VOUCH states; the prose does not repeat them.
    const [event] = toCausalHistory([
      {
        ...RELEASE_EXPOSES_SHORTFALL,
        to: 'AT_RISK',
        required: 900,
        available: 500,
        planned: 400,
        uncovered: 0,
        planned_sources: [{ lot_id: 'LOT-1002', quantity: 400 }],
      },
    ]);
    expect(event.sentence).toBe(
      'LOT-1001 released 500 kg of MAT-ALLOY-7. C-417 is now fully coverable on ' +
        'plan: 500 kg released and 400 kg queued from LOT-1002, awaiting Quality. ' +
        'The plan is unchanged.',
    );
    // Never the raw enums, and never a READY -> AT_RISK narration.
    expect(event.sentence).not.toMatch(/AT_RISK|READY|at risk/);
  });

  it('says the queued coverage was lost, never that stock was removed', () => {
    const [event] = toCausalHistory([
      {
        kind: 'readiness',
        lot_id: 'LOT-1002',
        disposition: 'QUARANTINE',
        order_id: 'C-417',
        from: 'AT_RISK',
        to: 'BLOCKED',
        material_id: 'MAT-ALLOY-7',
        // A quarantined lot was never usable, so the delta is correctly zero.
        inventory_delta: 0,
        decision_record_id: 'DR-ccc',
      },
    ]);
    expect(event.sentence).toContain('queued for C-417 from LOT-1002 is no longer available');
    expect(event.sentence).toContain('readiness moved to blocked');
    expect(event.sentence).toContain('The plan is unchanged');
    // The delta is 0 here; printing it would say "0 kg".
    expect(event.sentence).not.toMatch(/0 kg|removed|took away|reduced/);
  });

  it('names the governing basis a quarantine was decided against', () => {
    const [event] = toCausalHistory([
      {
        kind: 'quarantine',
        lot_id: 'LOT-1002',
        disposition: 'QUARANTINE',
        order_id: 'C-417',
        spec_id: 'SPEC-A7',
        revision: 'C',
        decision_record_id: 'DR-bbb',
      },
    ]);
    expect(event.sentence).toBe(
      'LOT-1002 was quarantined against SPEC-A7 Revision C. The remaining ' +
        'evidence cannot support release, so C-417 remains blocked.',
    );
    expect(event.sentence).not.toMatch(/removed|took away|reduced|released/i);
  });

  it('never attributes the resequence to the quarantine', () => {
    const [event] = toCausalHistory([RESEQUENCE]);
    expect(event.lotId).toBe('LOT-1001');
    expect(event.sentence).not.toContain('LOT-1002');
  });

  it('keeps the quarantine and the release as separate entries', () => {
    const history = toCausalHistory([
      RELEASE_EXPOSES_SHORTFALL,
      RESEQUENCE,
      {
        kind: 'quarantine',
        lot_id: 'LOT-1002',
        disposition: 'QUARANTINE',
        order_id: 'C-417',
        spec_id: 'SPEC-A7',
        revision: 'C',
        decision_record_id: 'DR-bbb',
      },
    ]);
    expect(history.map((e) => e.lotId)).toEqual(['LOT-1001', 'LOT-1002']);
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
    // The readiness row folds into the resequence it caused.
    expect(vm.causalHistory.map((e) => e.kind)).toEqual(['resequence']);
  });
});
