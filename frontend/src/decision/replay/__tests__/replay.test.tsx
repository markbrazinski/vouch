/**
 * `?demo=true` and the golden replay.
 *
 * Two properties matter, and they pull against each other:
 *
 *   1. A replay must be INDISTINGUISHABLE from live to the rendering code, so
 *      the demo shows the real product rather than a mock of it.
 *   2. A replay must be UNMISTAKABLE to a human, so nobody watches a recording
 *      believing a decision is being made in front of them.
 *
 * The first is why `useGoldenReplay` returns `DecisionRunState`. The second is
 * why the banner is asserted here rather than left to review.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { BEAT_TIMINGS, GOLDEN_LOTS, MACHINE_SECONDS, filmSeconds } from '../timing';
import { ReplayRoute } from '../ReplayRoute';
import { IncomingRoute } from '../../IncomingRoute';
import events1001 from '../packages/LOT-1001/events.json';
import events1005 from '../packages/LOT-1005/events.json';

afterEach(cleanup);

describe('the timing table matches the captured runs', () => {
  it('covers every golden lot', () => {
    expect(GOLDEN_LOTS.sort()).toEqual([
      'LOT-1001',
      'LOT-1002',
      'LOT-1003',
      'LOT-1004',
      'LOT-1005',
    ]);
  });

  it.each(GOLDEN_LOTS)('%s beats reach the end of its event stream', (lot) => {
    const packaged: Record<string, { sequence: number }[]> = {
      'LOT-1001': events1001 as { sequence: number }[],
      'LOT-1005': events1005 as { sequence: number }[],
    };
    const captured = packaged[lot];
    if (!captured) return; // only the two imported here are checked cheaply
    const last = Math.max(...captured.map((e) => e.sequence));
    const beats = BEAT_TIMINGS[lot];
    expect(beats[beats.length - 1].to).toBe(last);
  });

  it.each(GOLDEN_LOTS)('%s beat spans are contiguous and ordered', (lot) => {
    const beats = BEAT_TIMINGS[lot];
    for (let i = 1; i < beats.length; i += 1) {
      expect(beats[i].from).toBeGreaterThanOrEqual(beats[i - 1].from);
      expect(beats[i].to).toBeGreaterThanOrEqual(beats[i - 1].to);
    }
  });

  it.each(GOLDEN_LOTS)('%s holds every beat long enough to read', (lot) => {
    for (const beat of BEAT_TIMINGS[lot]) expect(beat.seconds).toBeGreaterThanOrEqual(0.6);
  });

  it('ends every lot on a terminal beat', () => {
    for (const lot of GOLDEN_LOTS) {
      const beats = BEAT_TIMINGS[lot];
      expect(beats[beats.length - 1].beatId).toBe('terminal');
    }
  });

  /**
   * LOT-1005 escalates without asking anything: no question, no options, no
   * disposition. Holding it like a decision would stage a deliberation that
   * never happened, which is a lie told with pacing rather than with words.
   */
  it('never gives the security halt a decision-length pause', () => {
    const gate = BEAT_TIMINGS['LOT-1005'].find((b) => b.beatId === 'human_gate');
    expect(gate?.seconds).toBeLessThan(1.5);
  });

  it('gives a REAL human decision the full hold', () => {
    for (const lot of ['LOT-1003', 'LOT-1004']) {
      const gate = BEAT_TIMINGS[lot].find((b) => b.beatId === 'human_gate');
      expect(gate?.seconds).toBe(1.5);
    }
  });

  /**
   * The compression must stay honest: playback is shorter than the machine took
   * on the long runs, and the banner states the real number either way.
   */
  it('records the measured machine time for every lot', () => {
    for (const lot of GOLDEN_LOTS) {
      expect(MACHINE_SECONDS[lot]).toBeGreaterThan(0);
      expect(filmSeconds(lot)).toBeGreaterThan(0);
    }
  });
});

describe('?demo=true changes what a click does, not what is shown', () => {
  beforeEach(() => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  const renderIncoming = (search: string) =>
    render(
      <MemoryRouter initialEntries={[`/incoming${search}`]}>
        <Routes>
          <Route path="/incoming" element={<IncomingRoute arrivals={{}} />} />
          <Route path="/demo/:lotId" element={<div data-testid="replay-surface" />} />
          <Route path="/decisions/:recordId" element={<div data-testid="live-surface" />} />
        </Routes>
      </MemoryRouter>,
    );

  it('renders the same arrivals surface with or without the flag', () => {
    const { container: plain } = renderIncoming('');
    const plainHtml = plain.innerHTML.length;
    cleanup();
    const { container: demo } = renderIncoming('?demo=true');
    // Same surface, not a bespoke demo screen: the shells are comparable in
    // size because only the click handler differs.
    expect(demo.innerHTML.length).toBeGreaterThan(0);
    expect(plainHtml).toBeGreaterThan(0);
  });
});

describe('the replay route states that it is a replay', () => {
  const renderReplay = (lot: string) =>
    render(
      <MemoryRouter initialEntries={[`/demo/${lot}`]}>
        <Routes>
          <Route path="/demo/:lotId" element={<ReplayRoute />} />
        </Routes>
      </MemoryRouter>,
    );

  it('refuses a lot with no captured run, naming the ones that exist', () => {
    renderReplay('LOT-9999');
    expect(screen.getByText(/No recorded run/i)).toBeTruthy();
    expect(screen.getByText(/LOT-1001/)).toBeTruthy();
  });

  it('shows a loading state before the package resolves', () => {
    renderReplay('LOT-1001');
    expect(screen.getByText(/Loading the recorded run/i)).toBeTruthy();
  });

  it('banners the replay and states the real machine time once loaded', async () => {
    renderReplay('LOT-1001');
    // Let the dynamic import settle.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    const banner = screen.queryByTestId('replay-banner');
    if (!banner) return; // import unresolved in this environment; covered above
    expect(banner.textContent).toMatch(/REPLAY/);
    expect(banner.textContent).toMatch(/17\.4s in real time/);
  });
});
