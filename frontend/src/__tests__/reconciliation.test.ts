import { describe, expect, it } from 'vitest';
import { fixtureState, selectView } from '../view-models/fixture-adapter';
import { LINES } from '../dev/fixtures/production';

describe('locked counts reconcile', () => {
  it('incoming normal: 6 + 17 + 164 = 187', () => {
    const { incoming } = selectView(fixtureState('incoming-normal'));
    const r = incoming!.rail;
    expect(r.needDecision).toBe(6);
    expect(r.needDecision + r.inProgress + r.completed).toBe(r.arrived);
    expect(r.arrived).toBe(187);
  });

  it('completed: 151 released + 13 quarantined = 164', () => {
    const { incoming } = selectView(fixtureState('incoming-normal'));
    const c = incoming!.completed;
    expect(c.released + c.quarantined).toBe(incoming!.rail.completed);
    expect(c.reopened).toBe(0);
  });

  it('incident: 18 grouped + 6 individual = 24', () => {
    const { incoming, navBadge } = selectView(fixtureState('incoming-incident'));
    const grouped = incoming!.needsYou.filter((r) => r.groupedCount);
    expect(grouped).toHaveLength(1);
    expect(grouped[0].groupedCount).toBe(18);
    expect(grouped[0].groupedCount! + (incoming!.needsYou.length - 1)).toBe(24);
    // The count is lots, not rows: 18 grouped + 6 individual.
    expect(incoming!.rail.needDecision).toBe(24);
    expect(navBadge).toBe(24);
    // Still one bounded decision row, never 18 cards.
    expect(incoming!.needsYou).toHaveLength(7);
  });

  it('today normal: 40 + 3 + 0 = 43', () => {
    const { today } = selectView(fixtureState('today-normal'));
    const counts = Object.fromEntries(today!.readiness.map((r) => [r.readiness, r.count]));
    expect(counts).toEqual({ READY: 40, AT_RISK: 3, BLOCKED: 0 });
    expect(today!.readiness.reduce((n, r) => n + r.count, 0)).toBe(43);
  });

  it('today disrupted: 39 + 3 + 1 = 43', () => {
    const { today } = selectView(fixtureState('today-disrupted'));
    const counts = Object.fromEntries(today!.readiness.map((r) => [r.readiness, r.count]));
    expect(counts).toEqual({ READY: 39, AT_RISK: 3, BLOCKED: 1 });
    expect(today!.readiness.reduce((n, r) => n + r.count, 0)).toBe(43);
  });

  it('8 lines carry all 43 orders', () => {
    expect(LINES).toHaveLength(8);
    expect(LINES.reduce((n, l) => n + l.orders.length, 0)).toBe(43);
  });
});
