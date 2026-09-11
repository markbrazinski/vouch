/**
 * THE FIVE SCENARIOS — each reaches its archived terminal state, deterministically.
 *
 * This asserts against the packages themselves rather than by playing beats:
 * the archive IS the truth Demo Mode replays, `demo-gate.test.tsx` proves the
 * hook honours the human gates on the real clock, and `golden-playback.test.ts`
 * proves the projection is coherent at every prefix. What is left to prove here
 * is that the five packages a clone ships actually tell the five canonical
 * stories — and that nobody has quietly edited one.
 *
 * Nothing here hard-codes an expected outcome into the product. These are test
 * assertions ABOUT a capture, which is the opposite of a fixture answer fed to
 * an agent: the runs were decided by the deployed runtime before this file
 * could have an opinion.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { DEMO_TIMINGS } from '../timing';

const PKG = join(__dirname, '..', 'packages');
const read = (lot: string, name: string) =>
  JSON.parse(readFileSync(join(PKG, lot, name), 'utf8'));

const LOTS = ['LOT-1001', 'LOT-1002', 'LOT-1003', 'LOT-1004', 'LOT-1005'];

/** The readiness a run recorded itself moving an order to. */
const readinessOf = (lot: string): Record<string, string> => {
  const changes = (read(lot, 'result.json').consequences?.readiness_changes ?? []) as {
    order_id: string;
    to: string;
  }[];
  return Object.fromEntries(changes.map((c) => [c.order_id, c.to]));
};

describe('every canonical lot ships a complete archived package', () => {
  it.each(LOTS)('%s has events, a result, a record and its sources', (lot) => {
    expect((read(lot, 'events.json') as unknown[]).length).toBeGreaterThan(0);
    expect(read(lot, 'result.json').decision_record_id).toBeTruthy();
    expect(read(lot, 'decision-record.json')).toBeTruthy();
    expect((read(lot, 'sources.json') as unknown[]).length).toBeGreaterThan(0);
  });

  /**
   * Every recorded event is inside some beat.
   *
   * A beat table that stops short would silently drop the end of a run — the
   * terminal disposition among it — and playback would simply stop looking
   * finished. Sequences are 1-based, so the last beat's `to` is the last
   * sequence, not the event count.
   */
  it.each(LOTS)('%s has a beat table covering its whole event stream', (lot) => {
    const beats = DEMO_TIMINGS[lot];
    expect(beats?.length).toBeGreaterThan(0);
    const sequences = (read(lot, 'events.json') as { sequence: number }[]).map((e) => e.sequence);
    expect(Math.max(...beats.map((b) => b.to))).toBe(Math.max(...sequences));
    for (const sequence of sequences) {
      expect(
        beats.some((b) => sequence >= b.from && sequence <= b.to),
        `${lot}: sequence ${sequence} is in no beat`,
      ).toBe(true);
    }
  });
});

describe('the five scenarios reach their archived terminal states', () => {
  /** LOT-1001 — agents agree, deterministic PASS, RELEASE. */
  it('LOT-1001 releases', () => {
    expect(read('LOT-1001', 'result.json').disposition).toBe('RELEASE');
  });

  /**
   * LOT-1002 — agents agree, deterministic FAIL, QUARANTINE, and the plan
   * changes: C-417 loses the material it was counting on.
   */
  it('LOT-1002 quarantines and blocks C-417', () => {
    expect(read('LOT-1002', 'result.json').disposition).toBe('QUARANTINE');
    expect(readinessOf('LOT-1002')['C-417']).toBe('BLOCKED');
  });

  /**
   * LOT-1003 — the agents materially disagree, a human resolves it, and the
   * SAME DecisionRecord resumes as run 2 and releases.
   */
  it('LOT-1003 disagrees, takes human authority, and resumes as run 2', () => {
    const result = read('LOT-1003', 'result.json');
    const record = read('LOT-1003', 'decision-record.json');
    expect(result.disposition).toBe('RELEASE');
    expect(result.failure_category).toBe('MATERIAL_DISAGREEMENT');
    expect(record.run_count).toBe(2);
    // One record, two runs — continuity is the point of the scenario.
    expect(result.decision_record_id).toBe(record.record_id);
    expect(record.quality_authority?.decisions?.length).toBeGreaterThan(0);
    expect(readinessOf('LOT-1003')['C-419']).toBe('READY');
  });

  /**
   * LOT-1004 — identity cannot bind, a human confirms the batch/lot binding,
   * and the same record resumes.
   */
  it('LOT-1004 cannot bind until a human confirms, then resumes and releases', () => {
    const result = read('LOT-1004', 'result.json');
    const record = read('LOT-1004', 'decision-record.json');
    expect(result.disposition).toBe('RELEASE');
    expect(result.failure_category).toBe('EVIDENCE_IDENTITY_UNRESOLVED');
    expect(record.run_count).toBe(2);
    expect(result.decision_record_id).toBe(record.record_id);

    // The shape of the scenario: the question is raised, a human answers it,
    // and identity is established afterwards — in that order.
    const events = (read('LOT-1004', 'events.json') as { event: string }[]).map((e) => e.event);
    const asked = events.indexOf('QUALITY_DECISION_REQUIRED');
    const answered = events.indexOf('QUALITY_AUTHORITY_RECORDED');
    const bound = events.indexOf('EVIDENCE_IDENTITY_ESTABLISHED');
    expect(asked).toBeGreaterThanOrEqual(0);
    expect(answered).toBeGreaterThan(asked);
    expect(bound).toBeGreaterThan(answered);
  });

  /**
   * LOT-1005 — a prompt injection is detected and the lot is quarantined on
   * SECURITY grounds. The critical property is that THE AGENTS NEVER RAN: the
   * halt is structural, not a reasoner deciding to be careful.
   */
  it('LOT-1005 halts on security before any agent starts', () => {
    const result = read('LOT-1005', 'result.json');
    expect(result.failure_category).toBe('SECURITY_QUARANTINE');
    const events = read('LOT-1005', 'events.json') as { event?: string }[];
    // A short stream, and no reasoner turn anywhere in it. This is the
    // structural claim: the halt happened before the agents, not because of
    // them.
    expect(events.length).toBeLessThan(8);
    expect(
      events.some((e) =>
        /INVESTIGATOR|VERIFIER|TOOL_CALLED|EVIDENCE_EXTRACTED/.test(String(e.event)),
      ),
    ).toBe(false);
    // No production order moved: a halted lot changes no plan.
    expect(Object.keys(readinessOf('LOT-1005'))).toHaveLength(0);
  });
});

describe('the human-gated lots really pause, and only they do', () => {
  it.each(['LOT-1003', 'LOT-1004'])('%s has exactly one operator gate', (lot) => {
    const gates = DEMO_TIMINGS[lot].filter((b) => b.awaitsOperator);
    expect(gates).toHaveLength(1);
    expect(gates[0].beatId).toBe('human_gate');
  });

  /**
   * LOT-1005 emits the same escalation event with no question and no options,
   * so there is nothing to press. Pausing there would stage a deliberation that
   * never happened.
   */
  it.each(['LOT-1001', 'LOT-1002', 'LOT-1005'])('%s never waits for an operator', (lot) => {
    expect(DEMO_TIMINGS[lot].some((b) => b.awaitsOperator)).toBe(false);
  });
});

/**
 * The frontend's copy of the archive must equal the canonical capture.
 *
 * `scripts/sync_golden_to_frontend.py` maintains `src/demo/packages/` as a copy
 * of `golden-runs/`, because Vite only bundles what lives under the project
 * root. A drifted copy would mean the clone replays something the repository
 * does not claim as truth.
 */
describe('the bundled archive matches golden-runs/', () => {
  const GOLDEN = join(__dirname, '..', '..', '..', '..', 'golden-runs');
  it.each(LOTS)('%s is byte-identical to its capture', (lot) => {
    for (const file of ['events.json', 'result.json', 'decision-record.json', 'sources.json']) {
      expect(
        readFileSync(join(PKG, lot, file), 'utf8'),
        `${lot}/${file} has drifted from golden-runs/`,
      ).toBe(readFileSync(join(GOLDEN, lot, file), 'utf8'));
    }
  });
});
