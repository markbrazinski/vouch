/**
 * Shift+R — reset the LOT-1003 demo scenario. Dev/film only.
 *
 * Filming a live LOT-1003 run means running it repeatedly: model inference is
 * non-deterministic, so a take that lands on MATERIAL_DISAGREEMENT may take
 * several attempts. This resets that ONE scenario between takes.
 *
 * Three things this deliberately is not:
 *
 *   - It is not a product feature. The whole hook is behind
 *     `import.meta.env.DEV`, which Vite replaces with `false` in a production
 *     build, so the listener is dropped from the shipped bundle entirely.
 *     There is no button anywhere in the product UI.
 *
 *   - It is not browser-refresh. Shift+R, never Cmd/Ctrl+R: rebinding the
 *     browser's own reload is hostile, and the operator needs a real refresh
 *     during filming as much as anyone.
 *
 *   - It is not history deletion. The server-side reset rolls back operating
 *     state for one lot; previous DecisionRecords stay in Records as truthful
 *     history. See `vouch/v2/demo_reset.py`.
 */

import { useEffect, useState } from 'react';

/** Where a keystroke means "type an R", not "reset the scenario". */
function isTyping(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  // Both spellings on purpose. `isContentEditable` is the property browsers
  // compute (it inherits, so it catches a focused child of an editable host),
  // but jsdom does not implement it — so a guard resting on it alone is
  // untestable AND silently absent anywhere else the property is missing. The
  // attribute check is the floor; the property widens it where available.
  if (target.isContentEditable) return true;
  if (target.closest('[contenteditable]:not([contenteditable="false"])')) return true;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

export type FilmResetState = { toast: string | null };

export function useFilmReset(onReset?: () => void): FilmResetState {
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!import.meta.env.DEV) return;

    const onKey = (e: KeyboardEvent) => {
      // `e.key === 'R'` already implies Shift on a US layout, but checking the
      // modifier explicitly keeps it correct where it does not.
      if (!e.shiftKey || e.key !== 'R') return;
      // Never shadow a browser or OS shortcut.
      if (e.metaKey || e.ctrlKey || e.altKey || e.repeat) return;
      if (isTyping(e.target)) return;

      e.preventDefault();
      void (async () => {
        try {
          const response = await fetch('/api/dev/reset-lot', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({ lot_id: 'LOT-1003' }),
          });
          const body = await response.json().catch(() => ({}));
          if (!response.ok || !body.ok) {
            // Say what went wrong. A silent no-op mid-shoot is worse than an
            // ugly toast, because the next take would film stale state.
            setToast(`reset failed · ${body.error ?? response.status}`);
            return;
          }
          setToast('LOT-1003 reset · ready for another run');
          onReset?.();
        } catch {
          setToast('reset failed · is the local BFF running?');
        }
      })();
    };

    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onReset]);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(null), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  return { toast };
}
