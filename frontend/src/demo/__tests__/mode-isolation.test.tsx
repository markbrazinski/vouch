/**
 * MODE ISOLATION — the property the whole Demo Mode design exists to hold.
 *
 * Two executions modes share one UI, so the risk is not that either breaks; it
 * is that they BLEED. A demo that quietly re-seeds a live corpus, or a live
 * mode that resets a React variable and reports the backend was reset, would
 * each be worse than having no demo mode at all.
 *
 * These tests assert the separation is STRUCTURAL — no demo path can reach a
 * mutation or the live reset, and no live path reads the archive as truth —
 * rather than merely currently-correct.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { act, cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { answer, installDemoBackend, uninstallDemoBackend, DEMO_LOTS } from '../backend';
import { resetDemoPlayback } from '../reset';
import { clearDecided, decidedRows, decidedToday, markDecided } from '../decided';
import { ResetDemo } from '../../app/ResetDemo';
import { setDemoEnabled } from '../mode';
import board from '../opening-board.json';

const asJson = async (r: Response) => (await r.json()) as Record<string, unknown>;

beforeEach(() => {
  clearDecided();
  vi.stubEnv('VITE_ENABLE_DEMO_MODE', 'true');
  setDemoEnabled(false);
});
afterEach(() => {
  uninstallDemoBackend();
  cleanup();
  setDemoEnabled(false);
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
});

describe('Demo Mode never executes a decision', () => {
  it.each(['/api/evaluate', '/api/evidence', '/api/quality-authority'])(
    'refuses POST %s instead of inventing an outcome',
    async (path) => {
      const response = answer('POST', path)!;
      expect(response).toBeTruthy();
      expect(response.ok).toBe(false);
      const body = await asJson(response);
      expect(body.ok).toBe(false);
      expect(body.failure_category).toBe('DEMO_MODE_REFUSED');
      // A synthetic success here would be a fabricated decision — the one thing
      // an archive-backed demo must never produce.
      expect(body.disposition).toBeUndefined();
    },
  );

  /**
   * The live reset re-seeds the authoritative DynamoDB corpus. Demo Mode must
   * not be able to reach it even by mistake.
   */
  it('refuses POST /api/reset-demo', async () => {
    const response = answer('POST', '/api/reset-demo')!;
    expect(response.ok).toBe(false);
    expect((await asJson(response)).failure_category).toBe('DEMO_MODE_REFUSED');
  });

  /** An unknown /api path is answered, never forwarded to a real deployment. */
  it('does not fall through to the network for an unknown read', async () => {
    const real = vi.fn(async () => new Response('{}'));
    window.fetch = real as unknown as typeof fetch;
    installDemoBackend();

    const response = await fetch('/api/something-else');
    expect(response.status).toBe(404);
    expect((await asJson(response)).failure_category).toBe('DEMO_MODE_UNSUPPORTED');
    expect(real).not.toHaveBeenCalled();
  });

  /** Anything that is not /api is the browser's business, not the archive's. */
  it('passes a non-api request through untouched', async () => {
    const real = vi.fn(async () => new Response('pdf'));
    window.fetch = real as unknown as typeof fetch;
    installDemoBackend();

    await fetch('/assets/coa-abc123.pdf');
    expect(real).toHaveBeenCalledOnce();
  });
});

describe('Demo Mode serves the canonical opening board with no backend', () => {
  it('answers the session gate so the product renders without credentials', async () => {
    const body = await asJson(answer('GET', '/api/auth/session')!);
    expect(body.authenticated).toBe(true);
  });

  it('lists exactly the five lots that have an archived run', async () => {
    const body = await asJson(answer('GET', '/api/decisions?limit=50')!);
    const rows = body.rows as { lot_id: string; row_state: string }[];
    expect(rows.map((r) => r.lot_id).sort()).toEqual([...DEMO_LOTS].sort());
    // A row that cannot be opened is worse than no row: LOT-1007 is a real
    // corpus lot with no archived run and must not be offered.
    expect(rows.some((r) => r.lot_id === 'LOT-1007')).toBe(false);
    expect(rows.every((r) => r.row_state === 'EVIDENCE_RECEIVED')).toBe(true);
  });

  it('opens with all three orders awaiting quality', async () => {
    const body = await asJson(answer('GET', '/api/today')!);
    const orders = (body.lines as { orders: { order_id: string; readiness: string }[] }[]).flatMap(
      (l) => l.orders,
    );
    expect(orders.map((o) => o.order_id).sort()).toEqual(['C-417', 'C-418', 'C-419']);
    expect(orders.every((o) => o.readiness === 'AWAITING_QUALITY')).toBe(true);
  });

  /**
   * The board is CAPTURED from the real runtime, not hand-written.
   *
   * If someone edits the JSON by hand this still passes; what it guards is the
   * shape the surfaces depend on, so a recapture that changes the contract
   * fails here rather than in a blank page.
   */
  it('carries the fields the surfaces join on', async () => {
    const rows = (board as { decisions: { rows: Record<string, unknown>[] } }).decisions.rows;
    for (const row of rows) {
      expect(row.supplier_name, `${row.lot_id} has no supplier name`).toBeTruthy();
      expect(row.material_name).toBeTruthy();
      expect(row.quantity).toBeTypeOf('number');
    }
  });
});

describe('a played run changes the board from its own recorded consequence', () => {
  it('overlays the outcome onto the real row, never a composed one', () => {
    const rows = (board as { decisions: { rows: Record<string, unknown>[] } }).decisions.rows;
    markDecided({
      lotId: 'LOT-1002',
      decisionRecordId: 'DR-test',
      disposition: 'QUARANTINE',
      failureCategory: '',
      readinessChanges: [{ order_id: 'C-417', to: 'BLOCKED' }],
    });

    const after = decidedRows(rows).find((r) => r.lot_id === 'LOT-1002')!;
    expect(after.row_state).toBe('QUARANTINED');
    expect(after.lot_status).toBe('QUARANTINED');
    // Every joined field stays the canonical one.
    expect(after.supplier_name).toBe('Eastern Metals');
    expect(after.quantity).toBe(400);

    const today = decidedToday((board as { today: unknown }).today) as {
      lines: { orders: { order_id: string; readiness: string }[] }[];
      readiness_counts: Record<string, number>;
    };
    const c417 = today.lines.flatMap((l) => l.orders).find((o) => o.order_id === 'C-417')!;
    expect(c417.readiness).toBe('BLOCKED');
    // The header chips are a separate tally and must agree with the cards.
    expect(today.readiness_counts.BLOCKED).toBe(1);
  });

  it('leaves every other lot and order exactly as it opened', () => {
    const rows = (board as { decisions: { rows: Record<string, unknown>[] } }).decisions.rows;
    markDecided({
      lotId: 'LOT-1002',
      decisionRecordId: 'DR-test',
      disposition: 'QUARANTINE',
      failureCategory: '',
    });
    const others = decidedRows(rows).filter((r) => r.lot_id !== 'LOT-1002');
    expect(others.every((r) => r.row_state === 'EVIDENCE_RECEIVED')).toBe(true);
  });
});

describe('the two resets cannot reach each other', () => {
  /**
   * The demo reset issues NO request. Not "a request to a safe endpoint" — no
   * request at all, which is why `reset.ts` imports no adapter and holds no
   * fetch. This is the single most important assertion in the file.
   */
  it('Reset demo performs zero network calls', async () => {
    setDemoEnabled(true);
    const spy = vi.fn(async () => new Response('{}'));
    window.fetch = spy as unknown as typeof fetch;

    markDecided({
      lotId: 'LOT-1001',
      decisionRecordId: 'DR-x',
      disposition: 'RELEASE',
      failureCategory: '',
      readinessChanges: [{ order_id: 'C-418', to: 'READY' }],
    });

    resetDemoPlayback();

    expect(spy).not.toHaveBeenCalled();
    // And it actually reset: every lot is replayable, the board is back to
    // opening.
    const rows = (board as { decisions: { rows: Record<string, unknown>[] } }).decisions.rows;
    expect(decidedRows(rows).every((r) => r.row_state === 'EVIDENCE_RECEIVED')).toBe(true);
    expect(decidedToday((board as { today: unknown }).today)).toBe(
      (board as { today: unknown }).today,
    );
  });

  /** In demo mode the control is local, and it says so rather than claiming live. */
  it('the control reads "Reset demo" and calls nothing when demo mode is on', async () => {
    setDemoEnabled(true);
    const spy = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    window.fetch = spy as unknown as typeof fetch;

    render(
      <MemoryRouter>
        <ResetDemo onReset={() => {}} />
      </MemoryRouter>,
    );
    await act(async () => screen.getByText(/Reset demo/).click());
    await act(async () => screen.getByRole('button', { name: 'Reset demo' }).click());

    expect(spy).not.toHaveBeenCalled();
  });

  /**
   * And the converse, which matters just as much: live mode must really call
   * the authoritative server-side reset, not quietly clear React state and
   * report success.
   */
  it('the control reads "Reset live demo" and calls the server when demo mode is off', async () => {
    const spy = vi.fn(async () => new Response(JSON.stringify({ ok: true })));
    window.fetch = spy as unknown as typeof fetch;

    render(
      <MemoryRouter>
        <ResetDemo onReset={() => {}} />
      </MemoryRouter>,
    );
    await act(async () => screen.getByText(/Reset live demo/).click());
    await act(async () => screen.getByRole('button', { name: 'Reset live demo' }).click());

    expect(spy).toHaveBeenCalled();
    const called = String(spy.mock.calls[0][0]);
    expect(called).toContain('/reset-demo');
  });
});
