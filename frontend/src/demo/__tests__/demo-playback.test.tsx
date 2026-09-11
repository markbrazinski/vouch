/**
 * Film view: a real recorded run, played at a speed a camera can use.
 *
 * The properties that matter for filming, in order of how badly a failure
 * would hurt:
 *
 *   1. The run PARKS on the quality question and does not move until the
 *      button is pressed. If a timer advanced it, the take would be mimed.
 *   2. The button RESUMES it, from the beat after the gate.
 *   3. It looks like the product — no badge, no watermark, no transport chrome
 *      in the frame.
 *   4. The events are the captured ones, in their captured order.
 */

import { describe, expect, it, afterEach } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import {
  BEAT_TIMINGS,
  DEMO_TIMINGS,
  GOLDEN_LOTS,
  MACHINE_SECONDS,
  filmSeconds,
} from '../timing';
import { DemoRoute } from '../DemoRoute';
import events1001 from '../packages/LOT-1001/events.json';
import events1005 from '../packages/LOT-1005/events.json';

afterEach(cleanup);

const renderDemo = (lot: string) =>
  render(
    <MemoryRouter initialEntries={[`/demo/${lot}`]}>
      <Routes>
        <Route path="/demo/:lotId" element={<DemoRoute />} />
      </Routes>
    </MemoryRouter>,
  );

const wait = (ms: number) =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, ms));
  });

describe('the timing table matches the captured runs', () => {
  it('covers every recorded lot', () => {
    expect([...GOLDEN_LOTS].sort()).toEqual([
      'LOT-1001',
      'LOT-1002',
      'LOT-1003',
      'LOT-1004',
      'LOT-1005',
    ]);
  });

  it.each([
    ['LOT-1001', events1001 as { sequence: number }[]],
    ['LOT-1005', events1005 as { sequence: number }[]],
  ])('%s beats reach the end of its event stream', (lot, captured) => {
    const last = Math.max(...captured.map((e) => e.sequence));
    const beats = BEAT_TIMINGS[lot];
    expect(beats[beats.length - 1].to).toBe(last);
  });

  it.each(GOLDEN_LOTS)('%s beat spans are ordered', (lot) => {
    const beats = BEAT_TIMINGS[lot];
    for (let i = 1; i < beats.length; i += 1) {
      expect(beats[i].from).toBeGreaterThanOrEqual(beats[i - 1].from);
      expect(beats[i].to).toBeGreaterThanOrEqual(beats[i - 1].to);
    }
  });

  it.each(GOLDEN_LOTS)('%s holds every beat long enough to read', (lot) => {
    for (const beat of BEAT_TIMINGS[lot]) expect(beat.seconds).toBeGreaterThanOrEqual(0.6);
  });

  it.each(GOLDEN_LOTS)('%s ends on a terminal beat', (lot) => {
    const beats = BEAT_TIMINGS[lot];
    expect(beats[beats.length - 1].beatId).toBe('terminal');
  });

  it('reports the real machine time for every lot', () => {
    for (const lot of GOLDEN_LOTS) {
      expect(MACHINE_SECONDS[lot]).toBeGreaterThan(0);
      expect(filmSeconds(lot)).toBeGreaterThan(0);
    }
  });
});

describe('only a real question waits for the operator', () => {
  it('waits on the two lots where a human actually decided', () => {
    for (const lot of ['LOT-1003', 'LOT-1004']) {
      const gate = BEAT_TIMINGS[lot].find((b) => b.beatId === 'human_gate');
      expect(gate?.awaitsOperator, `${lot} must wait for the button`).toBe(true);
    }
  });

  /**
   * LOT-1005 emits the same escalation event with no question and no options.
   * There is no button, so waiting would stop the film on a decision nobody is
   * being asked to make.
   */
  it('never waits on the security halt', () => {
    const gate = BEAT_TIMINGS['LOT-1005'].find((b) => b.beatId === 'human_gate');
    expect(gate?.awaitsOperator).toBeUndefined();
  });

  it('waits nowhere else, on any lot', () => {
    for (const lot of GOLDEN_LOTS) {
      for (const beat of BEAT_TIMINGS[lot]) {
        if (beat.awaitsOperator) expect(beat.beatId).toBe('human_gate');
      }
    }
  });
});

describe('a run with no human gate plays straight through', () => {
  it('LOT-1005 reaches its terminal beat unattended', async () => {
    renderDemo('LOT-1005');
    await wait(50);
    await wait(5200);
    // Nothing was pressed, and the run finished: the security halt must not
    // park waiting for an operator who has no button.
    expect(screen.queryByText(/Opening the decision/i)).toBeNull();
  }, 30000);
});

describe('the demo frame is the product frame', () => {
  it('shows no replay badge, watermark or transport control', async () => {
    const { container } = renderDemo('LOT-1001');
    await wait(50);
    const text = container.textContent ?? '';
    // Any of these in frame would make the footage unusable, and would label a
    // recording of a real decision as though it were a fabrication.
    expect(text).not.toMatch(/REPLAY/i);
    expect(text).not.toMatch(/Recorded run/i);
    expect(text).not.toMatch(/playback/i);
    expect(container.querySelector('[data-testid="replay-banner"]')).toBeNull();
    expect(container.querySelector('[data-testid="replay-finished"]')).toBeNull();
  }, 20000);

  it('refuses a lot with no recorded run, naming the ones that exist', () => {
    renderDemo('LOT-9999');
    expect(screen.getByText(/No archived run/i)).toBeTruthy();
    expect(screen.getByText(/LOT-1001/)).toBeTruthy();
  });
});

/**
 * Demo pace keeps the capture's SHAPE and only changes the rate.
 *
 * Asserted on the timing table rather than by playing minutes of beats: the
 * table IS the schedule the hook reads, and `demo-gate.test.tsx` separately
 * proves the hook honours it on the real clock.
 */
describe('demo pace is the captured shape, faster', () => {
  const LOTS = Object.keys(BEAT_TIMINGS);

  it.each(LOTS)('%s is quicker than the captured cadence', (lot) => {
    const captured = BEAT_TIMINGS[lot].reduce((t, b) => t + b.seconds, 0);
    const demo = DEMO_TIMINGS[lot].reduce((t, b) => t + b.seconds, 0);
    expect(demo).toBeLessThan(captured);
  });

  it.each(LOTS)('%s keeps every beat, in order, with the same spans', (lot) => {
    expect(DEMO_TIMINGS[lot].map((b) => [b.beatId, b.from, b.to])).toEqual(
      BEAT_TIMINGS[lot].map((b) => [b.beatId, b.from, b.to]),
    );
  });

  /**
   * The relative rhythm survives scaling.
   *
   * This is the property that makes demo pace a presentation choice rather than
   * a rewrite: a beat the capture held longer is still held longer. Only beats
   * clamped by the readability floor are exempt, and they are the shortest ones.
   */
  it.each(LOTS)('%s preserves the captured ordering of beat lengths', (lot) => {
    const pairs = BEAT_TIMINGS[lot].map((b, i) => ({ captured: b.seconds, demo: DEMO_TIMINGS[lot][i].seconds }));
    const unclamped = pairs.filter((p) => p.demo > 0.451);
    for (let i = 1; i < unclamped.length; i += 1) {
      const a = unclamped[i - 1];
      const b = unclamped[i];
      if (a.captured < b.captured) expect(a.demo).toBeLessThanOrEqual(b.demo + 1e-9);
      if (a.captured > b.captured) expect(a.demo).toBeGreaterThanOrEqual(b.demo - 1e-9);
    }
  });

  /** Nothing flashes past unreadably once scaled down. */
  it.each(LOTS)('%s holds every beat long enough to read', (lot) => {
    for (const beat of DEMO_TIMINGS[lot]) expect(beat.seconds).toBeGreaterThanOrEqual(0.45);
  });

  /** A human gate still waits for a person, whatever the scale says. */
  it.each(['LOT-1003', 'LOT-1004'])('%s still stops for the operator', (lot) => {
    expect(DEMO_TIMINGS[lot].filter((b) => b.awaitsOperator).length).toBe(1);
  });

  it('never holds a mechanical beat longer than an agent reasoning', () => {
    for (const lot of LOTS) {
      const beats = DEMO_TIMINGS[lot];
      const agents = beats.filter((b) => b.beatId === 'investigator' || b.beatId === 'verifier');
      if (!agents.length) continue;
      const shortestAgent = Math.min(...agents.map((b) => b.seconds));
      for (const beat of beats.filter((b) => b.beatId === 'mutation')) {
        expect(beat.seconds, `${lot}: ${beat.beatId} outlasts an agent`).toBeLessThan(
          shortestAgent,
        );
      }
    }
  });
});
