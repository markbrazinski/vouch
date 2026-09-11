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
import { act, cleanup, render } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { FilmRoute } from '../FilmRoute';

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
    await wait(13000);

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
    await wait(13000);
    const establish = Array.from(container.querySelectorAll('button')).find((b) =>
      /Establish this evidence/.test(b.textContent ?? ''),
    );
    expect(establish, 'the gate must offer a button to press').toBeTruthy();

    await act(async () => {
      establish!.click();
    });
    await wait(16000);

    const text = container.textContent ?? '';
    expect(text).toMatch(/RELEASE/);
    expect(text).toMatch(/Run 2/);
  }, 120000);

  it('LOT-1004 asks the identity question and never pre-announces run 2', async () => {
    const { container } = renderFilm('LOT-1004');
    await wait(4500);

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
    await wait(4500);
    const confirm = Array.from(container.querySelectorAll('button')).find((b) =>
      /Confirm binding/.test(b.textContent ?? ''),
    );
    expect(confirm).toBeTruthy();

    await act(async () => {
      confirm!.click();
    });
    await wait(14000);

    const text = container.textContent ?? '';
    expect(text).toMatch(/RELEASE/);
    expect(text).toMatch(/identity confirmation/i);
  }, 120000);
});
