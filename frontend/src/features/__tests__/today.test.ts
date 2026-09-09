/**
 * Today, against a REAL `get_today` captured from the deployed runtime.
 *
 * The capture is what the live AgentCore runtime returned on the canonical
 * corpus: C-417 stored READY while computing BLOCKED, short by the canonical
 * 900.0. Testing against a hand-written fixture would only prove the adapter
 * agrees with my assumptions about the shape.
 */

import { describe, expect, it } from 'vitest';
import capture from '../../decision/__tests__/today-capture.json';
import { slotClock, toToday } from '../today/model';
import type { TodayDTO } from '../../decision/dto';

const dto = capture as unknown as TodayDTO;
const vm = toToday(dto);
const order = (id: string) =>
  vm.lines.flatMap((l) => l.orders).find((o) => o.orderId === id)!;

describe('the capture is the world we think it is', () => {
  it('came from the production backend and is durable', () => {
    expect(dto.ok).toBe(true);
    expect(vm.durable).toBe(true);
  });

  it('carries the canonical 900.0 requirement, never the retired 800.0', () => {
    const c417 = order('C-417');
    expect(c417.coverage[0].required).toBe('900');
    expect(c417.requirements[0].quantity).toBe('900');
    expect(JSON.stringify(vm)).not.toContain('800');
  });
});

describe('stored status and computed readiness stay separate', () => {
  it('keeps C-417 stored READY while it computes BLOCKED', () => {
    const c417 = order('C-417');
    expect(c417.status).toBe('READY');
    expect(c417.readiness).toBe('BLOCKED');
    expect(c417.divergent).toBe(true);
  });

  it('does not mark an order divergent when the two agree', () => {
    expect(order('C-418').divergent).toBe(false);
    expect(order('C-419').divergent).toBe(false);
  });

  it('surfaces exactly the divergent orders', () => {
    expect(vm.divergent.map((o) => o.orderId)).toEqual(['C-417']);
  });
});

describe('all arithmetic stays in the backend', () => {
  it('copies the shortage rather than recomputing required minus available', () => {
    const c417 = order('C-417');
    expect(c417.coverage[0].shortBy).toBe('900');
    expect(c417.coverage[0].available).toBe('0');
    expect(c417.coverage[0].short).toBe(true);
  });

  it('uses the backend sentence verbatim', () => {
    expect(order('C-417').reason).toBe('MAT-ALLOY-7 short by 900.0 (need 900.0, have 0)');
  });

  it('reports the backend readiness tally, not a recount of the rows', () => {
    const counts = Object.fromEntries(vm.counts.map((c) => [c.readiness, c.count]));
    // AWAITING_QUALITY is always present in the display order, at whatever
    // the payload reports — 0 here, since this capture is post-decision.
    expect(counts).toEqual({ READY: 2, AWAITING_QUALITY: 0, AT_RISK: 0, BLOCKED: 1 });
  });

  it('does not treat a covered order as short', () => {
    // C-418 has 900 available against 400 required. The equal-900 coincidence
    // with C-417's requirement must never make anything look covered or short.
    const c418 = order('C-418');
    expect(c418.coverage[0].available).toBe('900');
    expect(c418.coverage[0].short).toBe(false);
    expect(c418.readiness).toBe('READY');
  });
});

describe('presentation is formatting, never derivation', () => {
  it('renders a planned slot as a clock time', () => {
    expect(slotClock('2026-08-15T08:00')).toBe('08:00');
    expect(order('C-417').slot).toBe('08:00');
  });

  it('counts lines and orders from the payload rather than a fixed number', () => {
    expect(vm.lineCount).toBe(2);
    expect(vm.orderCount).toBe(3);
  });

  it('marks a line disturbed only when one of its orders is not READY', () => {
    expect(vm.lines.find((l) => l.lineId === 'LINE-1')!.disturbed).toBe(true);
    expect(vm.lines.find((l) => l.lineId === 'LINE-2')!.disturbed).toBe(false);
  });
});

describe('empty and unknown inputs stay truthful', () => {
  it('renders no lines and zero counts rather than inventing a plan', () => {
    const empty = toToday({ ok: true } as TodayDTO);
    expect(empty.lines).toEqual([]);
    expect(empty.orderCount).toBe(0);
    expect(empty.counts.every((c) => c.count === 0)).toBe(true);
    expect(empty.durable).toBe(false);
  });

  it('does not claim divergence when the stored status is absent', () => {
    const [line] = toToday({
      ok: true,
      lines: [{ line_id: 'L', orders: [{ order_id: 'C-1', readiness: 'READY' }] }],
    } as TodayDTO).lines;
    expect(line.orders[0].divergent).toBe(false);
  });
});

describe('pre-decision is not a negative verdict', () => {
  /** The capture, with one order rewritten to the pre-decision state. */
  const awaiting = (readiness: string, status = 'READY'): TodayDTO =>
    ({
      ...dto,
      lines: (dto.lines ?? []).map((line) => ({
        ...line,
        orders: (line.orders ?? []).map((o) =>
          o.order_id === 'C-417' ? { ...o, readiness, status } : o,
        ),
      })),
    }) as TodayDTO;

  it('labels AWAITING_QUALITY without borrowing AT RISK or BLOCKED', () => {
    const vm2 = toToday(awaiting('AWAITING_QUALITY'));
    const c417 = vm2.lines.flatMap((l) => l.orders).find((o) => o.orderId === 'C-417')!;
    expect(c417.readiness).toBe('AWAITING_QUALITY');
    const label = vm2.counts.find((c) => c.readiness === 'AWAITING_QUALITY')!.label;
    expect(label).toBe('AWAITING QUALITY');
    // Never the words the brief ruled out for this state.
    expect(['AT RISK', 'BLOCKED', 'READY']).not.toContain(label);
  });

  it('is toned as an open question, not a warning', () => {
    const vm2 = toToday(awaiting('AWAITING_QUALITY'));
    const c417 = vm2.lines.flatMap((l) => l.orders).find((o) => o.orderId === 'C-417')!;
    expect(c417.tone).toBe('decision');
    expect(c417.tone).not.toBe('atrisk');
    expect(c417.tone).not.toBe('blocked');
  });

  it('does NOT claim plan and evidence disagree before a decision exists', () => {
    // Stored READY vs computed AWAITING_QUALITY is an open question, not a
    // contradiction. Counting it as divergence is what put the alarming
    // "PLAN AND EVIDENCE DISAGREE" banner on an untouched fresh seed.
    const vm2 = toToday(awaiting('AWAITING_QUALITY'));
    expect(vm2.divergent.map((o) => o.orderId)).toEqual([]);
    expect(vm2.awaitingQuality.map((o) => o.orderId)).toEqual(['C-417']);
  });

  it('still reports divergence once evidence really does contradict the plan', () => {
    const vm2 = toToday(awaiting('BLOCKED'));
    expect(vm2.divergent.map((o) => o.orderId)).toEqual(['C-417']);
    expect(vm2.awaitingQuality).toEqual([]);
  });
});
