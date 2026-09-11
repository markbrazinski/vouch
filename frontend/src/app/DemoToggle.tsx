/**
 * The left-nav Demo Mode control.
 *
 * Rendered only when the build enables Demo Mode (`VITE_ENABLE_DEMO_MODE`), so
 * the judge deployment has no toggle, no archived packages and no way to reach
 * either — see `demo/mode.ts` for why that is a build-time constant.
 *
 * SWITCHING IS A FULL RELOAD, deliberately.
 *
 * The two modes disagree about what every read model contains, who answers
 * `/api`, and whether a lot click starts a live evaluation or opens an archived
 * one. Flipping that in place would mean tearing down polling, discarding
 * in-flight requests, clearing retained responses and re-mounting every surface
 * — a lot of bespoke teardown whose failure mode is the worst one available:
 * live state and demo state visible in the same frame.
 *
 * A reload has none of that surface area. The mode is read once at startup, the
 * interceptor is installed or not, and the app builds itself from a single
 * consistent source. It also guarantees the direction the commission cares most
 * about: leaving Demo Mode cannot leave demo projections behind, because
 * nothing survives.
 *
 * A run in progress is the one case worth a question, so the toggle asks before
 * abandoning an open decision rather than disabling itself — a control that
 * silently stops working is harder to understand than one that checks.
 */

import { useState } from 'react';
import { useLocation } from 'react-router-dom';
import { DEMO_AVAILABLE, demoEnabled, setDemoEnabled } from '../demo/mode';
import { MONO, SANS } from '../decision/primitives';

export function DemoToggle() {
  const on = demoEnabled();
  const location = useLocation();
  const [asking, setAsking] = useState(false);

  if (!DEMO_AVAILABLE) return null;

  /** A decision is open. Switching now throws it away, so it is worth asking. */
  const inDecision =
    location.pathname.startsWith('/decisions/') || location.pathname.startsWith('/demo/');

  function apply(next: boolean) {
    setDemoEnabled(next);
    // Land on Today: the mode change altered every board, and returning to a
    // decision URL that the new mode cannot serve would be a dead end.
    window.location.assign('/today');
  }

  function requested() {
    if (inDecision) setAsking(true);
    else apply(!on);
  }

  return (
    <div style={{ marginTop: 'auto', padding: '12px 12px 0' }}>
      {asking ? (
        <div style={{ paddingBottom: 10 }}>
          <div style={{ font: `500 11px/1.45 ${SANS}`, color: '#B3AC9E', marginBottom: 9 }}>
            Leave this decision and switch to {on ? 'live' : 'demo'} mode?
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              onClick={() => apply(!on)}
              style={{
                flex: 1,
                padding: '6px 0',
                borderRadius: 6,
                border: 'none',
                background: '#F6F3EC',
                color: '#211F1B',
                font: `600 11px ${SANS}`,
                cursor: 'pointer',
              }}
            >
              Switch
            </button>
            <button
              type="button"
              onClick={() => setAsking(false)}
              style={{
                flex: 1,
                padding: '6px 0',
                borderRadius: 6,
                border: 'none',
                background: 'transparent',
                color: '#B3AC9E',
                font: `600 11px ${SANS}`,
                cursor: 'pointer',
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          role="switch"
          aria-checked={on}
          aria-label="Demo mode"
          onClick={requested}
          style={{
            width: '100%',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            background: 'transparent',
            border: 'none',
            padding: '7px 10px',
            borderRadius: 8,
            cursor: 'pointer',
          }}
        >
          <span
            style={{
              font: `500 10px ${MONO}`,
              letterSpacing: '.1em',
              color: on ? '#D8D2C4' : '#8F887A',
            }}
          >
            DEMO&nbsp;MODE
          </span>
          <span
            aria-hidden
            style={{
              width: 30,
              height: 16,
              flex: 'none',
              borderRadius: 999,
              background: on ? '#8FA88F' : 'rgba(255,255,255,.13)',
              position: 'relative',
              transition: 'background .15s',
            }}
          >
            <span
              style={{
                position: 'absolute',
                top: 2,
                left: on ? 16 : 2,
                width: 12,
                height: 12,
                borderRadius: '50%',
                background: '#F6F3EC',
                transition: 'left .15s',
              }}
            />
          </span>
        </button>
      )}
    </div>
  );
}

/**
 * The persistent "this is archived" marker.
 *
 * Demo Mode must never present itself as `LIVE`, because what is on screen is a
 * recording — real, but not happening now. It is a quiet chip rather than a
 * watermark: the product should look like the product, and an operator who has
 * turned the mode on does not need to be shouted at about it.
 */
export function DemoBadge() {
  if (!demoEnabled()) return null;
  return (
    <span
      data-testid="demo-badge"
      style={{
        font: `600 9.5px ${MONO}`,
        letterSpacing: '.11em',
        color: '#6E6A60',
        border: '1px solid rgba(0,0,0,.14)',
        borderRadius: 5,
        padding: '3px 7px',
        whiteSpace: 'nowrap',
      }}
    >
      DEMO&nbsp;MODE
    </span>
  );
}
