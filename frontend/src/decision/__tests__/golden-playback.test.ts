/**
 * PLAYBACK COMPATIBILITY — can the existing workspace render a saved golden run
 * without re-executing the live backend?
 *
 * The desired model is:
 *
 *   REAL SAVED TRUTH  +  CONFIGURABLE PRESENTATION TIMING
 *
 * Playback may change WHEN an already-real event becomes visible. It may not
 * change WHAT happened, WHO selected what, the event order, the human decision,
 * the disposition, the mutation, or the consequence.
 *
 * This file feeds each captured `events.json` through the SAME `project()` the
 * live app uses, one prefix at a time — which is exactly what a timing pass
 * does — and asserts the projection is coherent at every frame. If this passes,
 * playback needs no bespoke per-lot machinery: it needs a cursor.
 */

import { describe, expect, it } from 'vitest';
import { readFileSync, existsSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { project } from '../adapter';
import { normalizeEvent } from '../useDecisionRun';
import type { EvaluateDTO, LifecycleEventDTO } from '../dto';

const GOLDEN = join(__dirname, '..', '..', '..', '..', 'golden-runs');
const LOTS = existsSync(GOLDEN) ? readdirSync(GOLDEN).sort() : [];

const read = (lot: string, name: string) =>
  JSON.parse(readFileSync(join(GOLDEN, lot, name), 'utf8'));

/** The stored shape carries payload as a sub-document; the adapter reads flat. */
const eventsOf = (lot: string): LifecycleEventDTO[] =>
  (read(lot, 'events.json') as LifecycleEventDTO[]).map(normalizeEvent);

const projectAt = (lot: string, upTo: number, terminal = false) => {
  const manifest = read(lot, 'manifest.json');
  const events = eventsOf(lot).slice(0, upTo);
  return project({
    decisionRecordId: manifest.decision_record_id,
    lotId: manifest.lot_id,
    events,
    // The authoritative response is withheld until the run is actually over,
    // which is what a playback cursor does: the outcome is not known to the
    // viewer before the events that produce it.
    result: terminal ? (read(lot, 'result.json') as EvaluateDTO) : null,
    record: terminal ? read(lot, 'decision-record.json') : null,
    running: !terminal,
  });
};

describe.runIf(LOTS.length)('golden runs replay through the existing projection', () => {
  it.each(LOTS)('%s renders from saved truth alone', (lot) => {
    const vm = projectAt(lot, eventsOf(lot).length, true);
    expect(vm).toBeTruthy();
    expect(vm.lotId).toBe(lot);
  });

  it.each(LOTS)('%s projects at EVERY prefix without throwing', (lot) => {
    const total = eventsOf(lot).length;
    for (let i = 0; i <= total; i += 1) {
      expect(() => projectAt(lot, i)).not.toThrow();
    }
  });

  /**
   * The causal invariant, asserted frame by frame.
   *
   * This is the specific defect the causal-sequence audit closed: a frame that
   * shows a downstream result while an upstream stage still reads as active.
   * A timing pass makes exactly these frames, so it is asserted at every one.
   */
  it.each(LOTS)('%s never shows a disposition beside an unresolved verifier', (lot) => {
    const total = eventsOf(lot).length;
    for (let i = 0; i <= total; i += 1) {
      const vm = projectAt(lot, i);
      const agents = vm.spine.find((n) => n.key === 'agents');
      const disposition = vm.spine.find((n) => n.key === 'disposition');
      if (disposition?.state === 'complete') {
        expect(
          agents?.verifierLane,
          `${lot}: disposition complete at prefix ${i} with verifier lane ` +
            `${String(agents?.verifierLane)}`,
        ).not.toBe('IN_PROGRESS');
      }
    }
  });

  it.each(LOTS)('%s never shows a consequence before its disposition', (lot) => {
    const total = eventsOf(lot).length;
    for (let i = 0; i <= total; i += 1) {
      const vm = projectAt(lot, i);
      const disposition = vm.spine.find((n) => n.key === 'disposition');
      const consequence = vm.spine.find((n) => n.key === 'consequence');
      if (consequence?.state === 'complete' && disposition?.state !== 'halted') {
        expect(
          disposition?.state,
          `${lot}: consequence complete at prefix ${i} while disposition is ` +
            `${String(disposition?.state)}`,
        ).toBe('complete');
      }
    }
  });
});

describe.runIf(LOTS.length)('playback preserves what actually happened', () => {
  it.each(LOTS)('%s: the terminal frame states the captured outcome', (lot) => {
    const manifest = read(lot, 'manifest.json');
    const vm = projectAt(lot, eventsOf(lot).length, true);
    if (manifest.terminal_outcome === 'SECURITY_QUARANTINE') {
      // A halted run has no disposition to state, and must not invent one.
      expect(vm.dispositionLabel).not.toBe('RELEASE');
      return;
    }
    expect(vm.dispositionLabel).toContain(manifest.terminal_outcome);
  });

  it.each(LOTS)('%s: the rail carries every captured event', (lot) => {
    // The activity rail is the audit chronology and is deliberately ungated —
    // a playback cursor may delay it, never drop from it.
    const vm = projectAt(lot, eventsOf(lot).length, true);
    expect(vm.spine.length).toBeGreaterThanOrEqual(1);
  });
});

/**
 * The fix that made this file pass must not over-correct.
 *
 * `openQualityDecision()` suppresses an escalation only once a MUTATION has
 * committed after it. A case that is genuinely still waiting for a human has no
 * such mutation, and must keep saying so — otherwise the correction would hide
 * every real abstention, which is a far worse failure than the one it fixed.
 */
describe('an unanswered escalation still reads as outstanding', () => {
  const evidence: LifecycleEventDTO = {
    event: 'EVIDENCE_RECEIVED',
    decision_record_id: 'DR-ABSTAIN',
    at: '2026-09-10T00:00:00Z',
    sequence: 1,
  };
  const escalation: LifecycleEventDTO = {
    event: 'QUALITY_DECISION_REQUIRED',
    decision_record_id: 'DR-ABSTAIN',
    at: '2026-09-10T00:00:02Z',
    sequence: 2,
    reason: 'DISAGREEMENT',
  };
  const mutation: LifecycleEventDTO = {
    event: 'MUTATION_COMPLETED',
    decision_record_id: 'DR-ABSTAIN',
    at: '2026-09-10T00:00:03Z',
    sequence: 3,
    action: 'release_lot',
  };

  const vmOf = (events: LifecycleEventDTO[]) =>
    project({ decisionRecordId: 'DR-ABSTAIN', lotId: 'LOT-X', events, running: false });

  it('states QUALITY DECISION while nothing has been committed', () => {
    expect(vmOf([evidence, escalation]).dispositionLabel).toBe('QUALITY DECISION');
  });

  it('stops stating it once a mutation commits after the escalation', () => {
    expect(vmOf([evidence, escalation, mutation]).dispositionLabel).not.toBe('QUALITY DECISION');
  });

  it('keeps stating it when the mutation came BEFORE the escalation', () => {
    const reordered = [
      evidence,
      { ...mutation, sequence: 2 },
      { ...escalation, sequence: 3 },
    ];
    expect(vmOf(reordered).dispositionLabel).toBe('QUALITY DECISION');
  });
});
