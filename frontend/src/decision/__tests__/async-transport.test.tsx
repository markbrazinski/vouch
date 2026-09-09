/**
 * The async transport, and the Incoming repair.
 *
 * Both exist because of one measured fact: API Gateway's HTTP API times out at
 * 30s and cannot be raised, while a real two-agent evaluation ran 35-110s. The
 * synchronous BFF therefore returned 503 for decisions the runtime completed
 * correctly.
 *
 * These tests fail if the UI ever goes back to waiting for the POST, or if
 * Incoming re-acquires copy asserting something the backend contradicts.
 */

import { describe, expect, it, vi, afterEach } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { useDecisionRun } from '../useDecisionRun';
import { MemoryRouter } from 'react-router-dom';
import { IncomingRoute } from '../IncomingRoute';

const ENTRY = {
  lotId: 'LOT-1002',
  material: 'MAT-ALLOY-7',
  receiptMeta: 'SUP-EAST · site SITE-E1 · 400 kg',
  document: 'Certificate of Analysis - Lot LOT-1002',
  contentType: 'text/plain',
};

/** A decision that settles only after several polls, as a real one does. */
function backend({ terminalAfter = 3 }: { terminalAfter?: number } = {}) {
  const calls: string[] = [];
  let polls = 0;
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      });

    if (url.includes('/api/evaluate') || url.includes('/api/evidence')) {
      // 202 STARTED: an acknowledgement carrying no outcome.
      return json({ ok: true, decision_record_id: 'DR-abc123', status: 'STARTED' }, 202);
    }
    if (url.includes('/events')) {
      polls += 1;
      // The record becomes queryable at EVIDENCE_SNAPSHOT_CREATED, which is
      // what gates the terminal check — the real backend 400s before it.
      const event = polls === 1 ? 'EVIDENCE_SNAPSHOT_CREATED' : 'INVESTIGATOR_STARTED';
      return json({ ok: true, events: [{ event, sequence: polls, at: `2026-01-0${polls}` }] });
    }
    if (url.includes('/sources')) return json({ ok: true, sources: [] });
    if (url.includes('/api/decisions/')) {
      // Not terminal until the run has actually progressed.
      const done = polls >= terminalAfter;
      return json({
        ok: true,
        record: done
          ? { terminal: true, disposition: { disposition: 'QUARANTINE' }, failure_category: '' }
          : { terminal: false },
        events: [],
      });
    }
    if (url.includes('/api/decisions')) return json({ ok: true, rows: [], counts: {} });
    return json({ ok: true });
  });
  return { fetchMock, calls: () => calls };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('B1 — evaluation is started, never awaited', () => {
  it('does not wait for a terminal outcome before returning from the POST', async () => {
    const { fetchMock, calls } = backend();
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDecisionRun('DR-abc123'));
    await act(async () => {
      await result.current.start({ lotId: 'LOT-1002', document: 'x' });
    });

    // The POST has resolved. A synchronous implementation could only get here
    // after the whole decision finished; this one is still running it.
    const evaluate = calls().filter((u) => u.includes('/api/evaluate'));
    expect(evaluate).toHaveLength(1);
    expect(result.current.running).toBe(true);
  });

  it('recovers the terminal result by polling, not from the POST body', async () => {
    const { fetchMock } = backend({ terminalAfter: 2 });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDecisionRun('DR-abc123'));
    await act(async () => {
      await result.current.start({ lotId: 'LOT-1002', document: 'x' });
    });

    await waitFor(() => expect(result.current.running).toBe(false), { timeout: 5000 });
    // The 202 carried no disposition, so the record is the only source.
    expect(result.current.record?.terminal).toBe(true);
  });

  it('shows lifecycle events while the decision is still running', async () => {
    const { fetchMock } = backend({ terminalAfter: 99 });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDecisionRun('DR-abc123'));
    await act(async () => {
      await result.current.start({ lotId: 'LOT-1002', document: 'x' });
    });

    await waitFor(() => expect(result.current.events.length).toBeGreaterThan(0), {
      timeout: 5000,
    });
    // Still running: the events arrived DURING the decision, which is the
    // whole point of polling rather than awaiting.
    expect(result.current.running).toBe(true);
  });

  it('stops on an abstention that opens a QA review, not only on a disposition', async () => {
    // The defect this pins, found by running Hero B live: the backend sets
    // `terminal` only when the LOT WAS DISPOSITIONED, and deliberately leaves
    // it false for an abstention that is awaiting a person. Watching
    // `terminal` alone left the rail spinning forever on a decision that had
    // already finished deciding.
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown, status = 200) =>
        new Response(JSON.stringify(body), {
          status,
          headers: { 'content-type': 'application/json' },
        });
      if (url.includes('/api/evaluate')) {
        return json({ ok: true, decision_record_id: 'DR-abc123', status: 'STARTED' }, 202);
      }
      if (url.includes('/events'))
        return json({
          ok: true,
          events: [{ event: 'EVIDENCE_SNAPSHOT_CREATED', sequence: 1, at: '2026-01-01' }],
        });
      if (url.includes('/sources')) return json({ ok: true, sources: [] });
      if (url.includes('/api/decisions/')) {
        return json({
          ok: true,
          record: {
            terminal: false,
            disposition: { disposition: 'INSUFFICIENT_EVIDENCE' },
            failure_category: '',
            human: { review_status: 'OPEN' },
          },
          events: [],
        });
      }
      return json({ ok: true });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDecisionRun('DR-abc123'));
    await act(async () => {
      await result.current.start({ lotId: 'LOT-1003', document: 'x' });
    });

    await waitFor(() => expect(result.current.running).toBe(false), { timeout: 5000 });
    // The abstention is an OUTCOME, not a technical failure.
    expect(result.current.failure).toBeNull();
  });

  it('surfaces a startup failure immediately rather than polling forever', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes('/api/evaluate')) {
        return new Response(
          JSON.stringify({ ok: false, error: 'could not start', failure_class: 'TECHNICAL_FAILURE' }),
          { status: 502, headers: { 'content-type': 'application/json' } },
        );
      }
      return new Response(JSON.stringify({ ok: true }), {
        headers: { 'content-type': 'application/json' },
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDecisionRun('DR-abc123'));
    await act(async () => {
      await result.current.start({ lotId: 'LOT-1002', document: 'x' });
    });

    expect(result.current.running).toBe(false);
    expect(result.current.failure).not.toBeNull();
  });

  it('starts Hero B run 2 on the SAME record without awaiting it', async () => {
    const { fetchMock, calls } = backend({ terminalAfter: 2 });
    vi.stubGlobal('fetch', fetchMock);

    const { result } = renderHook(() => useDecisionRun('DR-abc123'));
    await act(async () => {
      await result.current.resume({ lotId: 'LOT-1003', authoritySource: 'QA-LEAD', document: 'x' });
    });

    const evidence = calls().filter((u) => u.includes('/api/evidence'));
    expect(evidence).toHaveLength(1);
    // Same record: a resumed run continues the decision on screen.
    expect(calls().some((u) => u.includes('DR-abc123'))).toBe(true);
  });
});

describe('B2 — Incoming reads the real decision list', () => {
  it('issues a real /api/decisions request', async () => {
    const { fetchMock, calls } = backend();
    vi.stubGlobal('fetch', fetchMock);

    render(
      <MemoryRouter initialEntries={['/incoming']}>
        <IncomingRoute arrivals={{ [ENTRY.lotId]: ENTRY }} />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(calls().some((u) => u.includes('/api/decisions'))).toBe(true),
    );
  });

  it('never claims enumeration is unprovisioned while it succeeds', async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (body: unknown) =>
        new Response(JSON.stringify(body), { headers: { 'content-type': 'application/json' } });
      if (url.includes('/api/decisions') && !url.includes('/events')) {
        return json({
          ok: true,
          rows: [
            {
              decision_record_id: 'DR-aa96520371ae',
              lot_id: 'LOT-1004',
              material_id: 'MAT-ALLOY-7',
              material_name: 'Alloy 7 billet',
              supplier_id: 'SUP-CENTRAL',
              supplier_name: 'Central Forgeworks',
              supplier_site: 'SITE-C1',
              quantity: 200,
              units: 'kg',
              row_state: 'SECURITY_HOLD',
              attention_required: true,
              disposition: '',
            },
          ],
          counts: {},
        });
      }
      return json({ ok: true });
    });
    vi.stubGlobal('fetch', fetchMock);

    render(
      <MemoryRouter initialEntries={['/incoming']}>
        <IncomingRoute arrivals={{ [ENTRY.lotId]: ENTRY }} />
      </MemoryRouter>,
    );

    // The row the backend served must render...
    await waitFor(() => expect(screen.getAllByText('Central Forgeworks').length).toBeGreaterThan(0));
    // ...and the stale notice must be gone for good.
    expect(screen.queryByText(/not available in this environment/i)).toBeNull();
    expect(screen.queryByText(/has not been provisioned/i)).toBeNull();
  });

  it('still offers the undecided arrival that starts the decision', () => {
    const { fetchMock } = backend();
    vi.stubGlobal('fetch', fetchMock);

    render(
      <MemoryRouter initialEntries={['/incoming']}>
        <IncomingRoute arrivals={{ [ENTRY.lotId]: ENTRY }} />
      </MemoryRouter>,
    );
    expect(screen.getByTestId('incoming-row')).toBeTruthy();
  });
});
