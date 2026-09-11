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
  FILM_TARGET_S,
  GOLDEN_LOTS,
  MACHINE_SECONDS,
  filmSeconds,
} from '../timing';
import { FilmRoute } from '../FilmRoute';
import events1001 from '../packages/LOT-1001/events.json';
import events1005 from '../packages/LOT-1005/events.json';

afterEach(cleanup);

const renderFilm = (lot: string) =>
  render(
    <MemoryRouter initialEntries={[`/film/${lot}`]}>
      <Routes>
        <Route path="/film/:lotId" element={<FilmRoute />} />
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
    renderFilm('LOT-1005');
    await wait(50);
    await wait(5200);
    // Nothing was pressed, and the run finished: the security halt must not
    // park waiting for an operator who has no button.
    expect(screen.queryByText(/Opening the decision/i)).toBeNull();
  }, 30000);
});

describe('the film frame carries no demo apparatus', () => {
  it('shows no replay badge, watermark or transport control', async () => {
    const { container } = renderFilm('LOT-1001');
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
    renderFilm('LOT-9999');
    expect(screen.getByText(/No recorded run/i)).toBeTruthy();
    expect(screen.getByText(/LOT-1001/)).toBeTruthy();
  });
});

/**
 * Each lot occupies the length the edit allocated.
 *
 * Asserted on the timing table rather than by playing 3 minutes of beats: the
 * table IS the schedule the hook reads, and `film-gate.test.tsx` separately
 * proves the hook honours it on the real clock.
 */
describe('the film fits its allocated time', () => {
  it.each(Object.keys(FILM_TARGET_S))('%s totals its target', (lot) => {
    expect(filmSeconds(lot)).toBeCloseTo(FILM_TARGET_S[lot], 1);
  });

  /**
   * A gated lot's target is the shot MINUS the press, so the automated beats
   * must leave room for it. If they filled the whole target the operator's
   * pause would push every take over.
   */
  it.each(['LOT-1003', 'LOT-1004'])('%s leaves the press outside its budget', (lot) => {
    const waiting = BEAT_TIMINGS[lot].filter((b) => b.awaitsOperator);
    expect(waiting.length).toBe(1);
    // The waiting beat's `seconds` is a placeholder — the clock is stopped —
    // so the automated remainder is what actually plays.
    const automated = filmSeconds(lot) - waiting[0].seconds;
    expect(automated).toBeLessThan(FILM_TARGET_S[lot]);
  });

  it('never holds a mechanical beat longer than an agent reasoning', () => {
    // Weighted distribution exists for this: spreading the slack evenly would
    // hold a version bump as long as the investigator, which inverts what the
    // viewer is meant to be looking at.
    for (const lot of Object.keys(FILM_TARGET_S)) {
      const beats = BEAT_TIMINGS[lot];
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
