/**
 * Navigation, as a property of the URL rather than of component state.
 *
 * These tests assert what the operator can DO, not how the shell stores where
 * they are. That distinction is the whole point of the change: the previous
 * shell kept location in three `useState` values at three depths (`surface`,
 * `openRecordId`, `openLot`), and they disagreed. The regression test below
 * reproduces exactly the walk that used to strand a user inside a decision.
 */

import { describe, expect, it, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { RoutedShell } from '../RoutedShell';
import { DecisionRoute } from '../../decision/DecisionRoute';
import { pendingRun } from '../../decision/pendingRun';

const ENTRY = {
  lotId: 'LOT-1002',
  material: 'MAT-ALLOY-7',
  receiptMeta: 'SUP-EAST · site SITE-E1 · 400 kg',
  document: 'Certificate of Analysis - Lot LOT-1002',
  contentType: 'text/plain',
};

const lotRow = (over: Record<string, unknown> = {}) => ({
  decision_record_id: 'DR-0000000001',
  lot_id: 'LOT-1002',
  material_id: 'MAT-ALLOY-7',
  material_name: 'Alloy 7 billet',
  supplier_id: 'SUP-EAST',
  supplier_name: 'Eastern Metals',
  supplier_site: 'SITE-E1',
  received_at: '2026-03-02',
  quantity: 400,
  units: 'kg',
  lot_status: 'RECEIVED',
  disposition: '',
  failure_category: '',
  row_state: 'EVIDENCE_RECEIVED',
  attention_required: false,
  decided_at: '2026-09-08T10:00:00Z',
  ...over,
});

/**
 * A backend that answers every read this shell makes.
 *
 * `evaluate` is counted, because "navigating back must not submit a second
 * evaluation" is one of the properties under test and a count is the only
 * honest way to check it.
 */
function backend(rows = [lotRow()]) {
  const calls: string[] = [];
  const posts: { url: string; body: Record<string, unknown> }[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(url);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      });

    if (url.includes('/api/evaluate')) {
      posts.push({ url, body: JSON.parse(String(init?.body ?? '{}')) });
      return json({ ok: true, status: 'STARTED' }, 202);
    }
    if (url.includes('/events')) return json({ ok: true, events: [] });
    if (url.includes('/sources')) return json({ ok: true, sources: [] });
    if (url.includes('/api/today')) return json({ ok: true, lines: [], readiness_counts: {} });
    const single = url.match(/\/api\/decisions\/(DR-[a-z0-9]+)(\?|$)/i);
    if (single) {
      return json({
        ok: true,
        record: {
          decision_record_id: single[1],
          lot_id: 'LOT-1002',
          terminal: true,
          disposition: { disposition: 'QUARANTINE' },
        },
        sources: [],
        events: [],
      });
    }
    if (url.includes('/api/decisions')) return json({ ok: true, rows, counts: {} });
    return json({ ok: true });
  });
  return { fetchMock, calls: () => calls, posts: () => posts };
}

const shell = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <RoutedShell entry={ENTRY} />
    </MemoryRouter>,
  );

beforeEach(() => pendingRun.reset());
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe('the route is where you are', () => {
  it('/incoming renders the current-arrivals list', async () => {
    vi.stubGlobal('fetch', backend().fetchMock);
    shell('/incoming');
    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
    expect(screen.getByText('Material awaiting disposition')).toBeTruthy();
  });

  it('/ redirects to Today rather than guessing a surface', async () => {
    vi.stubGlobal('fetch', backend().fetchMock);
    shell('/');
    await waitFor(() => expect(screen.getByRole('heading', { name: 'Today' })).toBeTruthy());
  });

  it('/records renders the audit ledger, not the arrivals list', async () => {
    vi.stubGlobal(
      'fetch',
      backend([lotRow(), lotRow({ decision_record_id: 'DR-0000000002' })]).fetchMock,
    );
    shell('/records');
    await waitFor(() => expect(screen.getByTestId('records-page')).toBeTruthy());
    expect(screen.getByText('Decision audit trail')).toBeTruthy();
  });
});

describe('REGRESSION — Incoming after opening a decision', () => {
  /**
   * The exact walk that used to fail.
   *
   * `openLot` lived inside the Incoming page. Clicking Incoming set the
   * shell's `surface` to a value it already held, React had no reason to
   * remount, `openLot` survived, and the list never came back.
   */
  it('Incoming -> decision -> Incoming nav -> the list is visible again', async () => {
    const user = userEvent.setup();
    vi.stubGlobal('fetch', backend().fetchMock);
    shell('/incoming');

    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
    await act(async () => {
      await user.click(screen.getByTestId('incoming-row'));
    });

    await waitFor(() => expect(screen.queryByTestId('incoming-page')).toBeNull());

    await act(async () => {
      await user.click(screen.getByRole('link', { name: 'Incoming' }));
    });
    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
  });
});

describe('deep linking and record identity', () => {
  it('/decisions/:recordId loads that exact DecisionRecord', async () => {
    const { fetchMock, calls } = backend();
    vi.stubGlobal('fetch', fetchMock);
    shell('/decisions/DR-abc123def456');
    await waitFor(() => expect(calls().some((u) => u.includes('DR-abc123def456'))).toBe(true));
  });

  it('/records/:recordId loads that exact audit record', async () => {
    const { fetchMock, calls } = backend();
    vi.stubGlobal('fetch', fetchMock);
    shell('/records/DR-feedfacecafe');
    await waitFor(() => expect(calls().some((u) => u.includes('DR-feedfacecafe'))).toBe(true));
  });

  it('two records for the SAME lot stay independently addressable', async () => {
    const { fetchMock, calls } = backend();
    vi.stubGlobal('fetch', fetchMock);

    const a = shell('/records/DR-run0000000a1');
    await waitFor(() => expect(calls().some((u) => u.includes('DR-run0000000a1'))).toBe(true));
    a.unmount();

    shell('/records/DR-run0000000b2');
    await waitFor(() => expect(calls().some((u) => u.includes('DR-run0000000b2'))).toBe(true));

    expect(calls().some((u) => u.includes('DR-run0000000a1'))).toBe(true);
    expect(calls().some((u) => u.includes('DR-run0000000b2'))).toBe(true);
  });
});

describe('an active run survives navigation', () => {
  const decisionOnly = (recordId: string) =>
    render(
      <MemoryRouter initialEntries={[`/decisions/${recordId}`]}>
        <Routes>
          <Route path="/decisions/:recordId" element={<DecisionRoute entry={ENTRY} />} />
        </Routes>
      </MemoryRouter>,
    );

  /**
   * Leaving a decision must not restart it.
   *
   * The workspace claims its start intent exactly once. A remount — from Back,
   * from a nav round-trip, from a refresh — finds nothing to claim and OBSERVES
   * the authoritative record instead.
   */
  it('re-entering /decisions/:id does not submit a second evaluation', async () => {
    const { fetchMock, posts } = backend();
    vi.stubGlobal('fetch', fetchMock);
    const recordId = 'DR-activerun001';

    pendingRun.set(recordId, { lotId: 'LOT-1002', decisionRecordId: recordId, document: 'x' });

    const first = decisionOnly(recordId);
    await waitFor(() => expect(posts()).toHaveLength(1));
    first.unmount();

    decisionOnly(recordId);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());

    expect(posts()).toHaveLength(1);
    expect(posts()[0].body.decision_record_id).toBe(recordId);
  });

  it('starting a run routes by decision id, and carries the lot in the body', async () => {
    const user = userEvent.setup();
    const { fetchMock, posts } = backend();
    vi.stubGlobal('fetch', fetchMock);
    shell('/incoming');

    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
    await act(async () => {
      await user.click(screen.getByTestId('incoming-row'));
    });

    await waitFor(() => expect(posts()).toHaveLength(1));
    const body = posts()[0].body as { lot_id: string; decision_record_id: string };
    expect(body.lot_id).toBe('LOT-1002');
    expect(String(body.decision_record_id)).toMatch(/^DR-/);
  });
});

describe('the special hero path does not come back', () => {
  it('Incoming has no privileged LOT-1002 card above the list', async () => {
    vi.stubGlobal('fetch', backend().fetchMock);
    shell('/incoming');
    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
    expect(screen.queryByText(/AWAITING A QUALITY DECISION/i)).toBeNull();
    expect(screen.getAllByTestId('incoming-row')).toHaveLength(1);
  });
});

describe('browser Back and Forward', () => {
  /**
   * Real history, not a simulation of it.
   *
   * `MemoryRouter` keeps its own stack, which would let this pass without the
   * browser's history being involved at all. `BrowserRouter` over jsdom's
   * history is the thing the operator actually uses, so it is what is tested.
   */
  it('Incoming -> decision -> Back -> Incoming -> Forward -> the same decision', async () => {
    const user = userEvent.setup();
    const { fetchMock, posts } = backend();
    vi.stubGlobal('fetch', fetchMock);

    window.history.pushState({}, '', '/incoming');
    const { BrowserRouter } = await import('react-router-dom');
    render(
      <BrowserRouter>
        <RoutedShell entry={ENTRY} />
      </BrowserRouter>,
    );

    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
    await act(async () => {
      await user.click(screen.getByTestId('incoming-row'));
    });
    await waitFor(() => expect(screen.queryByTestId('incoming-page')).toBeNull());

    const decisionPath = window.location.pathname;
    expect(decisionPath).toMatch(/^\/decisions\/DR-/);

    // Back: the arrivals list returns.
    await act(async () => {
      window.history.back();
    });
    await waitFor(() => expect(screen.getByTestId('incoming-page')).toBeTruthy());
    expect(window.location.pathname).toBe('/incoming');

    // Forward: the SAME decision, and no second evaluation for it.
    await act(async () => {
      window.history.forward();
    });
    await waitFor(() => expect(window.location.pathname).toBe(decisionPath));
    await waitFor(() => expect(screen.queryByTestId('incoming-page')).toBeNull());
    expect(posts()).toHaveLength(1);
  });
});

describe('the source stays reachable at every stage', () => {
  /**
   * Two ways to the document, never at the same time.
   *
   * While Vouch is establishing the governing truth the source column carries
   * it — that is the moment the certificate matters most. When the consequence
   * takes the full frame the column is gone by design, so the header carries a
   * compact affordance instead. An auditor opening a settled record must never
   * be left with no route to the evidence.
   */
  it('reconciliation is not full-bleed, so the source column survives it', async () => {
    const { FULL_BLEED_STAGES } = await import('../../decision/adapter');
    expect(FULL_BLEED_STAGES).not.toContain('reconciliation');
    expect(FULL_BLEED_STAGES).toContain('consequence');
  });

  it('a full-bleed frame still offers a route to the document', async () => {
    /**
     * A settled quarantine is ALWAYS full-bleed — the backend writes
     * reconciliation, disposition and consequence in one terminal batch, so
     * `active` lands on consequence and the source column is not rendered.
     * An auditor must still be able to reach the certificate, so the identity
     * header carries the affordance instead.
     *
     * Driven through the real projection with a real source shape. The
     * committed captures have their `sources` stripped — a presigned
     * `view_ref` is a bearer credential and must not live in a repository — so
     * the artifact is supplied here rather than undoing that.
     */
    const { DecisionWorkspace } = await import('../../decision/DecisionWorkspace');
    const { project } = await import('../../decision/adapter');

    const vm = project({
      decisionRecordId: 'DR-settled00001',
      lotId: 'LOT-1002',
      events: [
        { event: 'EVIDENCE_RECEIVED', sequence: 1 },
        { event: 'CONSEQUENCE_RECALCULATED', sequence: 2 },
      ] as never,
      result: null,
      sources: [
        {
          artifact_id: 'ART-1',
          document_identity: 'COA',
          content_type: 'application/pdf',
          trust_class: 'UNTRUSTED_SUPPLIER',
          security_state: 'CLEARED',
          content_hash: '4d36065a15b5',
          claim_count: 2,
          view_ref: 'https://example.test/signed',
        },
      ] as never,
      record: null,
      running: false,
      failure: null,
      durable: true,
    });

    render(<DecisionWorkspace vm={vm} />);

    expect(vm.fullBleed).toBe(true);
    // The column is gone on this frame; the header carries the way in.
    expect(screen.queryByText('SOURCE EVIDENCE')).toBeNull();
    expect(screen.getByTestId('header-open-source')).toBeTruthy();
  });
});
