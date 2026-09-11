/**
 * Demo Mode — the five archived runs, replayed with no backend at all.
 *
 * Vouch has two execution modes and they are never confused for one another:
 *
 *   LIVE  the deployed runtime decides, and authoritative state really moves.
 *         Genuinely nondeterministic. This is the product, and the judge
 *         deployment runs it.
 *
 *   DEMO  the archived runs under `golden-runs/`, played through the same
 *         projection and the same workspace. Nothing is inferred, nothing is
 *         mutated, and no cloud credentials are needed.
 *
 * What Demo Mode is NOT is a mock. Every event, disposition, human decision,
 * mutation and consequence it shows was produced by the deployed runtime
 * against the real reasoners and the real stores, and is replayed byte for
 * byte. The only thing Demo Mode decides is WHEN each already-real event
 * becomes visible.
 *
 * ENTERED ONLY ON PURPOSE. Nothing here is a fallback. A live call that fails —
 * an unreachable runtime, missing credentials, a decision that timed out —
 * reports that failure. It never quietly serves a recording instead, which
 * would tell an operator the plant answered when it did not.
 */

const KEY = 'vouch.demoMode';

/**
 * Whether this build may offer Demo Mode at all.
 *
 * A BUILD-TIME constant, not a runtime check. Vite replaces the whole
 * expression with a literal at build time, so the bundler then drops the
 * toggle, the interceptor, the archived packages and the `/demo` route as dead
 * code. The judge bundle does not contain a switched-off demo mode; it does not
 * contain demo mode, and neither a stored preference nor a `?demo=1` can reach
 * what is not there. A runtime flag would instead leave the playback code in
 * the bundle behind a condition — and a condition in a browser is something a
 * browser can change.
 *
 * DEFAULTS TO AVAILABLE, and the default is the point.
 *
 * A cloned repo has no AWS account and no deployed runtime, so the live path
 * cannot execute there; Demo Mode is the only way that clone runs at all, and
 * requiring an env file to discover it would make the repository look broken on
 * first launch. `.env` files are gitignored (they are where secrets live), so a
 * committed `.env` could not carry this — the default belongs in code.
 *
 * THE JUDGE / LIVE BUILD MUST THEREFORE OPT OUT EXPLICITLY:
 *
 *     VITE_ENABLE_DEMO_MODE=false npm run build
 *
 * `judge-build-excludes-demo.test.ts` runs that exact build and proves nothing
 * demo-related survives it.
 */
export const DEMO_AVAILABLE = import.meta.env.VITE_ENABLE_DEMO_MODE !== 'false';

/**
 * Whether Demo Mode is on right now.
 *
 * Persisted in `localStorage` so a refresh does not drop a developer out of the
 * mode they chose, and read through `DEMO_AVAILABLE` so a build that disables
 * demo mode cannot be talked into it by a stored value or a URL.
 */
/**
 * The stored preference, with an in-memory fallback.
 *
 * `localStorage` is not always usable: a private window can refuse it, a
 * browser can be set to block site data, and jsdom exposes it without methods.
 * Reading it unguarded throws, and the whole mode would then be unreachable
 * wherever storage is unavailable — so the value is mirrored in module state
 * and storage is treated as the persistence layer, not the source of truth.
 *
 * Failing to `false` on a read error is deliberate: a browser that cannot tell
 * us the operator chose demo mode has not told us they did, and inferring it
 * would be the silent entry this mode must never have.
 */
let current = false;

const storage = (): Storage | null => {
  try {
    const store = window.localStorage;
    return typeof store?.getItem === 'function' ? store : null;
  } catch {
    return null;
  }
};

export function demoEnabled(): boolean {
  if (!DEMO_AVAILABLE) return false;
  const store = storage();
  if (store) {
    try {
      current = store.getItem(KEY) === '1';
    } catch {
      /* Keep whatever this page already decided. */
    }
  }
  return current;
}

export function setDemoEnabled(on: boolean): void {
  if (!DEMO_AVAILABLE) return;
  current = on;
  try {
    if (on) storage()?.setItem(KEY, '1');
    else storage()?.removeItem(KEY);
  } catch {
    /* Storage is persistence only; the mode still holds for this page. */
  }
}

/**
 * `?demo=1` / `?demo=0` in the address bar, applied once at startup.
 *
 * A convenience for a cloned repo, not a second mechanism: it writes the same
 * stored preference the toggle writes, and it is gated on `DEMO_AVAILABLE`, so
 * it cannot enable demo mode in a deployment whose build disabled it.
 */
export function applyDemoParam(search: string): void {
  if (!DEMO_AVAILABLE) return;
  const value = new URLSearchParams(search).get('demo');
  if (value === '1' || value === 'true') setDemoEnabled(true);
  else if (value === '0' || value === 'false') setDemoEnabled(false);
}
