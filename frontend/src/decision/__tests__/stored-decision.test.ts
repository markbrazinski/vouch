/**
 * The stored-decision reconstruction, pinned to a REAL 2-run decision.
 *
 * `hero-b-stored-capture.json` is a verbatim capture of `get_decision` and
 * `get_events` for DR-herob000001 taken from the live production backend. It is
 * a 2-run decision — run 1 abstained to QUALITY_DECISION_REQUIRED, a human
 * supplied evidence, and run 2 RELEASED — which is exactly the shape that
 * exposes `record.events` as unusable.
 *
 * These tests exist because a single-run capture cannot catch this: on a 1-run
 * decision both sources project identically, which is precisely why the earlier
 * dev baseline (a 1-run Hero A capture) never surfaced the defect.
 */

import { describe, expect, it } from 'vitest';
import {
  ChronologyUnavailable,
  projectFromRecordEventsForTest,
  projectStoredDecision,
  stripEvents,
  type StoredDecisionInput,
} from '../fromRecord';
import type { LifecycleEventDTO, SourceArtifactDTO } from '../dto';
import capture from './hero-b-stored-capture.json';

const CAPTURE = capture as unknown as {
  decision_record_id: string;
  record: Record<string, unknown>;
  sources: SourceArtifactDTO[];
  events: LifecycleEventDTO[];
};

const input = (): StoredDecisionInput => ({
  decisionRecordId: CAPTURE.decision_record_id,
  record: CAPTURE.record,
  sources: CAPTURE.sources,
  events: CAPTURE.events,
  material: 'MAT-POLY-3',
  receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
});

describe('the capture is the shape this test needs', () => {
  it('is a multi-run decision whose record summary is shorter than its history', () => {
    expect(CAPTURE.record.run_count).toBe(2);
    const summary = CAPTURE.record.events as LifecycleEventDTO[];
    expect(summary.length).toBe(38);
    expect(CAPTURE.events.length).toBe(168);
  });

  it('the record summary is missing event types project() consumes', () => {
    const summary = new Set((CAPTURE.record.events as LifecycleEventDTO[]).map((e) => e.event));
    const authoritative = new Set(CAPTURE.events.map((e) => e.event));
    for (const required of ['QUALITY_DECISION_REQUIRED', 'BRIEF_VALIDATION_FAILED']) {
      expect(authoritative.has(required)).toBe(true);
      expect(summary.has(required)).toBe(false);
    }
  });
});

describe('full get_events reconstructs the correct state and history', () => {
  const vm = projectStoredDecision(input());

  /**
   * The record's own terminal facts: `disposition: RELEASE`, gate `ALLOWED`,
   * `release_lot` committed, no failure category.
   *
   * This previously asserted 'QUALITY DECISION', which was wrong on this
   * capture: run 1's escalation is durable and stays in the stream forever, and
   * the projection read it as still outstanding even though a human answered it
   * and run 2 committed a real mutation. The live `evaluate` response hid the
   * defect by carrying only the CURRENT run's events; `get_events` returns the
   * whole history, which is what this path reads.
   */
  it('reaches the release the record actually committed', () => {
    expect(vm.outcome.headline).toBe('Released into usable inventory');
    expect(vm.dispositionLabel).toBe('RELEASE');
  });

  it('shows run 1 disagreement in the history, not as the terminal state', () => {
    expect(CAPTURE.events.some((e) => e.event === 'QUALITY_DECISION_REQUIRED')).toBe(true);
    expect(vm.spine.find((n) => n.key === 'disposition')?.state).toBe('terminal');
  });

  it('carries the history of BOTH runs', () => {
    expect(vm.activity.length).toBe(84);
    expect(Math.max(...vm.activity.map((a) => a.runNumber ?? 1))).toBe(2);
    expect(vm.activity.some((a) => a.runNumber === 1)).toBe(true);
  });
});

describe('substituting record.events loses the history', () => {
  it('reaches the same outcome but discards almost all of run 1', () => {
    const authoritative = projectStoredDecision(input());
    const summary = projectFromRecordEventsForTest({
      decisionRecordId: CAPTURE.decision_record_id,
      record: CAPTURE.record,
      sources: CAPTURE.sources,
      material: 'MAT-POLY-3',
      receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
    });

    // Both now reach the release that was actually committed — the terminal
    // OUTCOME is no longer where the two sources diverge.
    //
    // The rule stands on the AUDIT TRAIL instead, which is the stronger reason
    // for it: a summary that agrees about the ending while silently dropping
    // 46 of run 1's 50 events is a worse trap than one that visibly disagrees,
    // because nothing about the terminal frame reveals the loss.
    expect(summary.outcome.headline).toBe(authoritative.outcome.headline);
    expect(summary.spine.find((n) => n.key === 'disposition')?.state).toBe('terminal');

    // ...and it silently loses almost all of run 1. The summary keeps only
    // the 4 trailing events that preceded the human evidence, against the 50
    // the authoritative chronology holds, so the first run's investigation is
    // absent from the audit trail rather than merely abbreviated.
    const runOne = (vm: typeof authoritative) =>
      vm.activity.filter((a) => (a.runNumber ?? 1) === 1).length;
    expect(summary.activity.length).toBeLessThan(authoritative.activity.length);
    expect(runOne(authoritative)).toBe(50);
    expect(runOne(summary)).toBe(4);
  });
});

describe('the production adapter refuses the fallback', () => {
  it('strips record.events before the record reaches project()', () => {
    expect('events' in CAPTURE.record).toBe(true);
    expect('events' in stripEvents(CAPTURE.record)).toBe(false);
    // Everything else survives — the claims the context column needs included.
    expect(stripEvents(CAPTURE.record).evidence).toBe(CAPTURE.record.evidence);
  });

  it('throws rather than falling back when the chronology is missing', () => {
    expect(() => projectStoredDecision({ ...input(), events: [] })).toThrow(ChronologyUnavailable);
  });

  it('a record carrying a full summary still yields nothing without get_events', () => {
    // The exact trap: the record LOOKS sufficient. It must still refuse.
    expect(() => projectStoredDecision({ ...input(), events: [] })).toThrow(
      /chronology could not be read/,
    );
  });
});
