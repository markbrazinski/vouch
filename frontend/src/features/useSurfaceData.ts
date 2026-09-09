/**
 * Loading one read-model surface, with states that stay truthful.
 *
 * The four states are distinct because they mean different things to an
 * operator: `loading` is "on its way", `ready` is an answer, `blocked` is "an
 * authoritative path exists but this deployment cannot reach it" (a missing
 * grant), and `failed` is "the request did not complete — nothing is known".
 *
 * A blocked read is separated from a failed one on the backend's own typed
 * envelope, never on string-matching an error message: the runtime returns
 * `ok: false` with a `failure_category`, and a persistence failure on a read
 * path is a capability gap rather than a fault.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { VouchEnvelope } from '../adapter/client';
import { TransportError } from '../adapter/client';

export type SurfaceStatus = 'loading' | 'ready' | 'blocked' | 'failed';

export interface SurfaceData<T> {
  status: SurfaceStatus;
  data: T | null;
  /** Why, when the status is `blocked` or `failed`. Never a disposition. */
  detail: string;
  reload: () => void;
}

/** Distinguishes one hook instance's request from another's. */
let instances = 0;

/**
 * The last authoritative response for a read model, kept for the session.
 *
 * Measured: each authoritative read costs 3.4-4.5s with NO warm-up decay, so it
 * is fixed runtime overhead rather than a cold start. Surfaces mount on demand,
 * so navigating Today -> Incoming -> Today paid that cost again every time and
 * left the product looking empty for seconds.
 *
 * This retains the last response and serves it immediately on a revisit, then
 * revalidates in the background and swaps in the newer answer. It is a cache of
 * REAL authoritative responses only — a fixture is never stored here and never
 * served. An entry exists only because the backend actually returned it.
 */
const lastGood = new Map<string, VouchEnvelope>();

/**
 * Drop retained responses so the next read is authoritative.
 *
 * Retain-and-revalidate is right for navigation and wrong immediately after a
 * WRITE: evaluating a lot changes lot status, usable inventory, order readiness
 * and the schedule, so a retained `today` or `decisions` response is not merely
 * stale, it contradicts the decision the operator just watched execute. Today
 * showed the pre-release plan until a manual refresh.
 *
 * Clearing rather than refetching keeps this a cache concern: the surfaces
 * re-read on their own terms, and nothing here needs to know which of them are
 * mounted.
 */
export function invalidateSurfaces(keys: string[] = ['today', 'decisions']): void {
  for (const key of keys) {
    lastGood.delete(key);
    shared.delete(key);
  }
}

/** Read failures that mean "this deployment cannot answer", not "it broke". */
const CAPABILITY_GAPS = new Set(['PERSISTENCE_FAILURE']);

export function classifyRead(envelope: VouchEnvelope): {
  status: 'ready' | 'blocked' | 'failed';
  detail: string;
} {
  if (envelope.ok !== false) return { status: 'ready', detail: '' };
  const category = typeof envelope.failure_category === 'string' ? envelope.failure_category : '';
  const detail = typeof envelope.error === 'string' ? envelope.error : '';
  return {
    status: CAPABILITY_GAPS.has(category) ? 'blocked' : 'failed',
    detail,
  };
}

/**
 * Warm the read models the opening frame needs.
 *
 * This exists to overlap the FIRST read's cost, not to duplicate work. Each
 * loader is registered as the in-flight request for its cache key, so a surface
 * mounting a moment later ATTACHES to the prefetch instead of issuing a second
 * identical read.
 *
 * That attachment is the whole point. Firing prefetches alongside each
 * surface's own read sent five concurrent requests on first paint; they queued
 * behind one another server-side and the last one settled at ~14s — slower than
 * doing nothing. One request per read model, shared.
 *
 * Failures are ignored: this is an optimisation, and every surface still
 * classifies and renders its own loading, blocked and failure states.
 */
export function prefetchSurfaces(
  loaders: { key: string; load: () => Promise<VouchEnvelope> }[],
): void {
  for (const { key, load } of loaders) {
    if (lastGood.has(key) || shared.has(key)) continue;
    const promise = load();
    shared.set(key, promise);
    void promise.then(
      (envelope) => {
        if (envelope.ok !== false) lastGood.set(key, envelope);
      },
      () => {
        /* An unavailable prefetch is not a surface state. The surface asks. */
      },
    );
  }
}

/**
 * In-flight reads by cache key, shared across components.
 *
 * A surface that mounts while a read for its key is already running joins it
 * rather than starting a second. Entries are removed once settled, so the next
 * mount performs a genuine new read — this collapses concurrent duplicates, it
 * does not cache.
 */
const shared = new Map<string, Promise<VouchEnvelope>>();

export function useSurfaceData<T>(
  load: () => Promise<VouchEnvelope>,
  project: (envelope: VouchEnvelope) => T,
  deps: unknown[] = [],
  /**
   * Opt in to retain-and-revalidate for this read model. Only stable, shared
   * read models pass one; a per-decision read does not, because there is
   * nothing to revisit.
   */
  cacheKey?: string,
): SurfaceData<T> {
  /**
   * `load` and `project` are fresh closures on every render, and `deps` is a
   * fresh array literal. Depending on them directly would re-run the effect
   * after each state change, resetting the surface to `loading` forever. The
   * effect is keyed on a serialised copy of the caller's own dependencies
   * instead, and reads the current functions through a ref.
   */
  const fns = useRef({ load, project });
  fns.current = { load, project };

  /**
   * Identity of the request this hook instance wants.
   *
   * `deps` alone is not enough: Suppliers and Records both read
   * `list_decisions` with no arguments, so both serialise to `[]` and the
   * second surface would attach to the first's already-settled promise. The
   * instance id keeps one component's request distinct from another's while
   * still letting the SAME component's StrictMode remount share one fetch.
   */
  const instance = useRef(`${++instances}`);
  const key = `${instance.current}:${JSON.stringify(deps)}`;
  const [state, setState] = useState<{ status: SurfaceStatus; data: T | null; detail: string }>(
    () => {
      // A retained authoritative response renders immediately, so a revisit is
      // not a blank panel for four seconds. The effect below still re-reads and
      // replaces it, so what is shown converges on current truth.
      const cached = cacheKey ? lastGood.get(cacheKey) : undefined;
      if (cached) {
        try {
          return { status: 'ready' as SurfaceStatus, data: project(cached), detail: '' };
        } catch {
          /* A retained response that no longer projects is simply not used. */
        }
      }
      return { status: 'loading' as SurfaceStatus, data: null, detail: '' };
    },
  );
  const [nonce, setNonce] = useState(0);

  /**
   * The request in flight for the current key, shared across effect runs.
   *
   * React StrictMode mounts, cleans up and remounts an effect, and the browser
   * serves the remount's identical GET from cache rather than as a second
   * response. So the two textbook guards both strand the surface on `loading`
   * in a real browser while passing every jsdom test:
   *
   *  - a per-effect cancelled flag lets the cleanup cancel the run that owned
   *    the only response;
   *  - a "newest run wins" id rejects that same response as stale.
   *
   * Holding the PROMISE instead removes the race rather than timing around it.
   * A remount with the same key attaches to the request already in flight, so
   * exactly one fetch happens and whichever run is mounted when it settles
   * writes the result. A different key starts a genuinely new request, and a
   * response whose key is no longer current is still discarded.
   */
  const inflight = useRef<{
    key: string;
    promise: Promise<VouchEnvelope>;
    settled: boolean;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Revalidating behind a retained answer must not blank the surface; only a
    // surface with nothing to show goes to `loading`.
    setState((prev) =>
      prev.status === 'ready' && prev.data !== null
        ? prev
        : { status: 'loading', data: null, detail: '' },
    );

    // A settled request is NOT reusable.
    //
    // The in-flight promise exists to collapse StrictMode's mount/cleanup/
    // remount into one fetch. But it is a ref, so it also survives a real
    // unmount — and reusing an ALREADY-SETTLED promise means a surface revisited
    // later re-displays the response from the first visit and never asks again.
    // With retain-and-revalidate on top, that showed a stale decision list
    // indefinitely: new runs were missing from Records.
    //
    // So sharing is limited to a request that has not settled yet. Once it has,
    // the next mount starts a genuine new read, which is what "revalidate"
    // means.
    if (!inflight.current || inflight.current.key !== key || inflight.current.settled) {
      // Join a read already running for this model (a startup prefetch, or
      // another surface reading the same list) rather than issuing a duplicate.
      const joined = cacheKey ? shared.get(cacheKey) : undefined;
      const promise = joined ?? fns.current.load();
      if (cacheKey && !joined) shared.set(cacheKey, promise);
      const entry: { key: string; promise: Promise<VouchEnvelope>; settled: boolean } = {
        key,
        promise,
        settled: false,
      };
      // `.then(on, on)` rather than `.finally`: finally re-throws, which would
      // surface a handled load failure as an unhandled rejection.
      const markSettled = () => {
        entry.settled = true;
        // Stop sharing once settled: the next mount must perform a real read.
        if (cacheKey && shared.get(cacheKey) === promise) shared.delete(cacheKey);
      };
      void entry.promise.then(markSettled, markSettled);
      inflight.current = entry;
    }
    const mine = inflight.current;

    mine.promise
      .then((envelope) => {
        if (cancelled || inflight.current !== mine) return;
        const { status, detail } = classifyRead(envelope);
        if (cacheKey && status === 'ready') lastGood.set(cacheKey, envelope);
        setState({
          status,
          // A non-ok envelope yields no data. `toIncoming` on a failure would
          // return zero rows, which is truthful, but the surface must show WHY
          // it is empty rather than an empty list.
          data: status === 'ready' ? fns.current.project(envelope) : null,
          detail,
        });
      })
      .catch((error: unknown) => {
        if (cancelled || inflight.current !== mine) return;
        setState({
          status: 'failed',
          data: null,
          // A projection that refuses to build (an incomplete chronology, say)
          // carries its own reason, and it is not "unreachable" — the request
          // succeeded and the answer was unusable. Saying the wrong one sends
          // an operator to look at the network.
          detail:
            error instanceof TransportError || error instanceof Error
              ? error.message
              : 'the decision service could not be reached',
        });
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, key]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
