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

export function useSurfaceData<T>(
  load: () => Promise<VouchEnvelope>,
  project: (envelope: VouchEnvelope) => T,
  deps: unknown[] = [],
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
  const [state, setState] = useState<{ status: SurfaceStatus; data: T | null; detail: string }>({
    status: 'loading',
    data: null,
    detail: '',
  });
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
  const inflight = useRef<{ key: string; promise: Promise<VouchEnvelope> } | null>(null);

  useEffect(() => {
    let cancelled = false;
    setState({ status: 'loading', data: null, detail: '' });

    if (!inflight.current || inflight.current.key !== key) {
      inflight.current = { key, promise: fns.current.load() };
    }
    const mine = inflight.current;

    mine.promise
      .then((envelope) => {
        if (cancelled || inflight.current !== mine) return;
        const { status, detail } = classifyRead(envelope);
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
          detail:
            error instanceof TransportError
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
