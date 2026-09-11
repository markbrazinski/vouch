/**
 * The archived backend: `/api/*`, answered from checked-in canonical assets.
 *
 * This exists so a clone with NO cloud credentials runs the real product rather
 * than a stripped-down imitation of it. Every surface — `Authenticated`,
 * Incoming, Today, Suppliers, Records, the workspace — keeps its own code path
 * unchanged; the only thing that differs is who answers the fetch.
 *
 * Intercepting at the FETCH boundary is deliberate, and it is the reason this
 * is one file rather than a demo branch in every component. A second data path
 * threaded through the surfaces would be a second product, and the two would
 * drift: the whole claim of Demo Mode is that a cloner sees Vouch, not a
 * simulator of Vouch.
 *
 * THREE THINGS THIS REFUSES TO DO
 *
 *   1. It never answers a MUTATION. `POST /evaluate` and the two authority
 *      POSTs are not served here — Demo Mode opens `/demo/:lotId`, which plays
 *      an archived run and posts nothing. If one is ever reached in demo mode
 *      it fails loudly rather than returning a plausible fake, because a demo
 *      that invents a decision is the one thing this must not be.
 *
 *   2. It never answers the LIVE RESET. `POST /reset-demo` re-seeds the
 *      authoritative corpus; in Demo Mode there is no corpus to seed and
 *      calling it would reach a real deployment. Demo reset is local and lives
 *      in `reset.ts`.
 *
 *   3. It is never a FALLBACK. It is installed only when Demo Mode is
 *      explicitly on. A live call that fails reports its failure.
 */

import board from './opening-board.json';
import { decidedRows, decidedToday } from './decided';

/** The lots with an archived run. Incoming shows exactly these. */
export const DEMO_LOTS = ['LOT-1001', 'LOT-1002', 'LOT-1003', 'LOT-1004', 'LOT-1005'] as const;

interface Board {
  today: Record<string, unknown>;
  decisions: { rows?: Record<string, unknown>[]; [k: string]: unknown };
}

const OPENING = board as unknown as Board;

/** Mutations, which Demo Mode answers for nobody. */
const MUTATIONS = ['/evaluate', '/evidence', '/quality-authority', '/reset-demo'];

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });

/**
 * Answer one archived read, or `null` for a path Demo Mode does not serve.
 *
 * Exported for the tests, which assert the routing directly rather than through
 * a patched global.
 */
export function answer(method: string, path: string): Response | null {
  const url = new URL(path, 'http://demo.local');
  const parts = url.pathname.replace(/^\/api/, '').split('/').filter(Boolean);

  if (method === 'POST') {
    /**
     * A mutation in Demo Mode is a BUG, and it is surfaced as one.
     *
     * Returning a synthetic success would be inventing a decision; returning a
     * synthetic failure would blame the network for a routing mistake. A typed
     * refusal names the actual cause, and the tests assert no demo interaction
     * ever reaches here.
     */
    if (MUTATIONS.some((m) => url.pathname.endsWith(m))) {
      return json(
        {
          ok: false,
          failure_category: 'DEMO_MODE_REFUSED',
          error:
            `Demo Mode does not execute ${url.pathname}. Archived runs are replayed, ` +
            'never re-decided. Turn Demo Mode off to use the live runtime.',
        },
        409,
      );
    }
    return null;
  }

  if (method !== 'GET') return null;

  // The session gate. Demo Mode has no user to authenticate and no server to
  // ask, so it answers as a local demo session rather than showing a sign-in
  // form no credential could satisfy.
  if (parts[0] === 'auth' && parts[1] === 'session') {
    return json({ ok: true, authenticated: true, username: 'demo' });
  }

  if (parts[0] === 'today') return json(decidedToday(OPENING.today));

  if (parts[0] === 'decisions' && parts.length === 1) {
    const rows = decidedRows((OPENING.decisions.rows ?? []) as Record<string, unknown>[]);
    return json({ ...OPENING.decisions, rows, counts: { returned: rows.length } });
  }

  // A single archived DecisionRecord, its events, or its sources. These are
  // reached from Records after a run has been played; the packages hold the
  // real captured documents.
  if (parts[0] === 'decisions' && parts.length >= 2) {
    return null; // served by `recordRoutes`, wired in `install`
  }

  return null;
}

/** Whether the interceptor is currently installed. */
let installed: (() => void) | null = null;

/**
 * Route `/api/*` to the archive for as long as Demo Mode is on.
 *
 * Wrapping `window.fetch` rather than swapping the adapter keeps ONE client in
 * the product. `adapter/client.ts` is untouched: it still builds the same
 * request, still parses the same envelope, still classifies the same failures.
 * Whatever is wrong with a demo answer is wrong with a live one too.
 *
 * Anything that is not `/api` — a bundled PDF asset, a blob URL — passes
 * straight through to the real fetch.
 */
export function installDemoBackend(
  recordRoutes?: (parts: string[], url: URL) => Promise<Response | null>,
): () => void {
  if (installed) return installed;
  const real = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const href =
      typeof input === 'string' ? input : input instanceof URL ? input.href : input.url;
    const method = (init?.method ?? (input instanceof Request ? input.method : 'GET')).toUpperCase();

    if (!href.includes('/api/')) return real(input as RequestInfo, init);

    const direct = answer(method, href);
    if (direct) return direct;

    if (recordRoutes) {
      const url = new URL(href, 'http://demo.local');
      const parts = url.pathname.replace(/^\/api/, '').split('/').filter(Boolean);
      const found = await recordRoutes(parts, url);
      if (found) return found;
    }

    // An /api path Demo Mode does not know is NOT quietly passed to the
    // network: in a clone there is nothing there, and in a deployment it would
    // reach the live backend from a mode that must not touch it.
    return json(
      {
        ok: false,
        failure_category: 'DEMO_MODE_UNSUPPORTED',
        error: `Demo Mode has no archived answer for ${method} ${href}.`,
      },
      404,
    );
  };

  installed = () => {
    window.fetch = real;
    installed = null;
  };
  return installed;
}

export function uninstallDemoBackend(): void {
  installed?.();
}
