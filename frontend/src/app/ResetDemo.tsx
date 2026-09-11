/**
 * The reset control — one button, two entirely separate implementations.
 *
 * This is the sharpest mode boundary in the product, so it is drawn here once
 * and nowhere else:
 *
 *   LIVE MODE   `↻ Reset live demo`
 *               Calls the ONE canonical server-side reset. The authoritative
 *               corpus is re-seeded, so the five lots return to RECEIVED and
 *               the three production orders to AWAITING QUALITY.
 *               It is not a React state reset and not a reload — those would
 *               leave the plant exactly as the previous run left it, which is
 *               the failure this control exists to prevent.
 *
 *   DEMO MODE   `↻ Reset demo`
 *               Clears archived playback state locally. Issues no request at
 *               all: `resetDemoPlayback` imports no adapter and contains no
 *               fetch, so Demo Mode has no code path to the live reset.
 *
 * The two failure modes this prevents, both named in the commission:
 *
 *   - Demo Mode must never call the live reset. It cannot: the branch below
 *     selects a function that cannot reach the network.
 *   - Live Mode must never merely reset React state and tell the operator the
 *     backend was reset. It does not: the live branch awaits the real call and
 *     the label says "live".
 *
 * What the live reset deliberately is not: it takes no parameters, so it cannot
 * be used to reset a chosen lot or write a chosen value; and it does not erase
 * history — operating state is restored while DecisionRecords are untouched. An
 * audit ledger a demo can tidy is not an audit ledger.
 *
 * The confirmation step is there because a reset during an evaluation discards
 * work in progress, and the button sits in permanent furniture where a misclick
 * is plausible.
 */

import { useState } from 'react';
import { resetDemo } from '../adapter/client';
import { demoEnabled } from '../demo/mode';
import { resetDemoPlayback } from '../demo/reset';
import { MONO, SANS } from '../decision/primitives';

export function ResetDemo({ onReset }: { onReset: (message: string) => void }) {
  const [asking, setAsking] = useState(false);
  const [busy, setBusy] = useState(false);
  // Read at render, not captured once: toggling the mode changes which reset
  // this control IS, and a stale value here would be the exact confusion the
  // separation exists to prevent.
  const demo = demoEnabled();

  async function run() {
    setBusy(true);
    try {
      if (demo) {
        // Local only. No request is issued, so there is nothing to await and
        // nothing that can reach a live deployment.
        resetDemoPlayback();
        onReset('Demo reset · every run replayable');
      } else {
        await resetDemo();
        onReset('Demo reset · ready');
      }
      setAsking(false);
    } catch {
      // Surfaced by the caller's toast, which knows where to put it. A silent
      // failure would leave an operator believing they had a clean board.
      setAsking(false);
      onReset('Reset failed · the corpus may be unchanged');
    } finally {
      setBusy(false);
    }
  }

  const label = demo ? 'Reset demo' : 'Reset live demo';
  const prompt = demo
    ? 'Replay all five archived runs from the beginning?'
    : 'Reset the live demo to its starting state?';

  const action = {
    flex: 1,
    padding: '6px 0',
    borderRadius: 6,
    border: 'none',
    font: `600 11px ${SANS}`,
    cursor: 'pointer',
  };

  return (
    <div style={{ padding: '12px', borderTop: '1px solid rgba(255,255,255,.09)' }}>
      {asking ? (
        <div>
          <div style={{ font: `500 11px/1.45 ${SANS}`, color: '#B3AC9E', marginBottom: 9 }}>
            {prompt}
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              type="button"
              onClick={run}
              disabled={busy}
              style={{ ...action, background: '#F6F3EC', color: '#211F1B', opacity: busy ? 0.6 : 1 }}
            >
              {busy ? 'Resetting…' : label}
            </button>
            <button
              type="button"
              onClick={() => setAsking(false)}
              disabled={busy}
              style={{ ...action, background: 'transparent', color: '#B3AC9E' }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setAsking(true)}
          style={{
            width: '100%',
            textAlign: 'left',
            background: 'transparent',
            border: 'none',
            padding: '7px 10px',
            borderRadius: 8,
            cursor: 'pointer',
            font: `500 11.5px ${MONO}`,
            color: '#8F887A',
          }}
        >
          ↻ {label}
        </button>
      )}
    </div>
  );
}
