/**
 * The human gate, played on the REAL beat clock.
 *
 * Split from `film.test.tsx` because these run the actual timers — ~84s for the
 * four of them. They are excluded from the inner loop (`make fast`) and run in
 * `make gate` and `make full`, the same treatment `async-transport.test.tsx`
 * gets for the same reason.
 *
 * They are not mocked, deliberately. The property under test is that NO timer
 * advances the run past the question; faking the clock would test the fake.
 */

import { describe, expect, it, afterEach } from 'vitest';
import { act, cleanup, render, renderHook } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { FilmRoute } from '../FilmRoute';
import { useGoldenReplay } from '../useGoldenReplay';

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

/**
 * Play until a control appears, rather than until a stopwatch says it should.
 *
 * The beat clock is real and the reveal is staggered, so the exact moment a
 * gate lands shifts whenever the timing table or the stagger changes. A fixed
 * sleep pins today's numbers as if they were the contract; what these tests
 * actually assert is that the gate arrives and waits.
 */
const playUntilText = async (
  container: HTMLElement,
  pattern: RegExp,
  budgetMs = 40000,
): Promise<boolean> => {
  for (let waited = 0; waited < budgetMs; waited += 250) {
    if (pattern.test(container.textContent ?? '')) return true;
    await wait(250);
  }
  return false;
};

const playUntil = async (
  container: HTMLElement,
  pattern: RegExp,
  budgetMs = 40000,
): Promise<HTMLButtonElement | undefined> => {
  for (let waited = 0; waited < budgetMs; waited += 250) {
    const found = Array.from(container.querySelectorAll('button')).find((b) =>
      pattern.test(b.textContent ?? ''),
    );
    if (found) return found as HTMLButtonElement;
    await wait(250);
  }
  return undefined;
};

/**
 * The gate is the whole reason film view exists as more than a fast-forward.
 *
 * These are slow tests on purpose: they play the real beat clock up to the
 * question, prove it does not move on, press the real button, and prove the run
 * continues. Mocking the timers would test the mock.
 */
describe('the run parks on the question and the button resumes it', () => {
  const buttonsOf = (container: HTMLElement) =>
    Array.from(container.querySelectorAll('button')).map((b) => b.textContent?.trim() ?? '');

  it('LOT-1003 offers the real authority controls and waits', async () => {
    const { container } = renderFilm('LOT-1003');
    expect(await playUntil(container, /Establish this evidence/)).toBeTruthy();

    // The operator's actual choice, as the run recorded it.
    const labels = buttonsOf(container);
    expect(labels.filter((t) => /Establish this evidence/.test(t)).length).toBe(2);
    expect(labels.some((t) => /Keep held/.test(t))).toBe(true);

    // Nothing advances it. A timer here would mime the decision.
    const before = container.textContent ?? '';
    await wait(12000);
    expect(container.textContent).toBe(before);
    expect(before).toMatch(/MATERIAL_DISAGREEMENT/);
    expect(before).not.toMatch(/RELEASE/);
  }, 120000);

  it('LOT-1003 continues to RELEASE once the button is pressed', async () => {
    const { container } = renderFilm('LOT-1003');
    const establish = await playUntil(container, /Establish this evidence/);
    expect(establish, 'the gate must offer a button to press').toBeTruthy();

    await act(async () => {
      establish!.click();
    });
    expect(await playUntilText(container, /RELEASE/), 'run 2 must reach RELEASE').toBe(true);

    const text = container.textContent ?? '';
    expect(text).toMatch(/RELEASE/);
    expect(text).toMatch(/Run 2/);
  }, 120000);

  it('LOT-1004 asks the identity question and never pre-announces run 2', async () => {
    const { container } = renderFilm('LOT-1004');
    expect(await playUntil(container, /Confirm binding/)).toBeTruthy();

    const labels = buttonsOf(container);
    expect(labels.some((t) => /Confirm binding/.test(t))).toBe(true);
    expect(labels.some((t) => /Keep unbound/.test(t))).toBe(true);

    // The second run has not started: the operator is what starts it. The
    // stored record says run_count 2 because it was written afterwards, and
    // reading that through announced the resumption while still asking the
    // question that causes it.
    expect(container.textContent).not.toMatch(/Run 2/);
  }, 120000);

  it('LOT-1004 confirms the binding and reaches RELEASE', async () => {
    const { container } = renderFilm('LOT-1004');
    const confirm = await playUntil(container, /Confirm binding/);
    expect(confirm).toBeTruthy();

    await act(async () => {
      confirm!.click();
    });
    expect(await playUntilText(container, /RELEASE/), 'run 2 must reach RELEASE').toBe(true);

    const text = container.textContent ?? '';
    expect(text).toMatch(/RELEASE/);
    expect(text).toMatch(/identity confirmation/i);
  }, 180000);
});

/**
 * Tool calls arrive one at a time, the way they really did.
 *
 * Revealing a beat's whole span at once dropped an agent's tool calls onto the
 * screen together, which reads as a batch lookup. The real investigator took
 * 2.6s to reach its first tool and ~1.4s between the rest, because it was
 * deciding what to ask for next — that rhythm IS the reasoning being visible.
 */
describe('an agent reaches for its tools one at a time', () => {
  it('reveals the investigator beat progressively, never all at once', async () => {
    const { result } = renderHook(() => useGoldenReplay('LOT-1001'));
    await wait(200);

    const counts: number[] = [];
    for (let i = 0; i < 55; i += 1) {
      await wait(400);
      counts.push(result.current.events.length);
    }

    // The investigator's span is sequences 6-13. If it landed in one step the
    // count would jump by 8; it must climb.
    const jumps = counts.map((n, i) => (i ? n - counts[i - 1] : 0));
    expect(Math.max(...jumps), `biggest single jump: ${Math.max(...jumps)}`).toBeLessThan(5);

    // And it must actually progress, not stall.
    expect(counts[counts.length - 1]).toBeGreaterThan(counts[0]);
  }, 120000);

  it('shows a tool call before its result, never the pair together', async () => {
    const { result } = renderHook(() => useGoldenReplay('LOT-1001'));
    await wait(200);

    let sawPendingCall = false;
    for (let i = 0; i < 70; i += 1) {
      await wait(300);
      const events = result.current.events;
      const last = events[events.length - 1];
      // A TOOL_CALLED at the tip means the request is on screen with no answer
      // yet — the moment that makes tool use visible rather than implied.
      if (last?.event === 'TOOL_CALLED') sawPendingCall = true;
    }
    expect(sawPendingCall, 'a tool call must be visible while still pending').toBe(true);
  }, 120000);

  /**
   * The display may never go backwards.
   *
   * It did: the beat's final reveal fired at the beat's START, so every event
   * in the span appeared at once and the staggered steps then rewound the
   * count. On camera that is a visible flicker.
   */
  it.each(['LOT-1001', 'LOT-1002'])('%s never un-reveals an event', async (lot) => {
    const { result } = renderHook(() => useGoldenReplay(lot));
    let previous = 0;
    for (let i = 0; i < 165; i += 1) {
      await wait(350);
      const n = result.current.events.length;
      expect(n, `${lot} went backwards: ${previous} -> ${n}`).toBeGreaterThanOrEqual(previous);
      previous = n;
    }
    expect(result.current.finished).toBe(true);
  }, 180000);
});
