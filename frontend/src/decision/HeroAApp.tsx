/**
 * The Hero A application shell.
 *
 * A thin frame around the Decision Workspace: the fixed 1600x900 acceptance
 * viewport, the dark primary nav, and the top context header. It is separate
 * from the older fixture-driven `VouchApp` because the workspace owns its own
 * scrolling — it has an independently-scrolling activity rail — and the older
 * shell wraps children in a single scroller that would fight it.
 *
 * Only the surfaces Hero A needs exist here. Today, Records and Suppliers are
 * rendered as navigable but out of scope for this gate, and say so rather than
 * showing fabricated content.
 */

import { useState } from 'react';
import { HeroAPage, IncomingBlockedNotice, type HeroAEntry } from './HeroAPage';
import { INK, MONO, N, SANS, HAIR } from './primitives';

type Surface = 'incoming' | 'today' | 'suppliers' | 'records';

const NAV: { key: Surface; label: string }[] = [
  { key: 'today', label: 'Today' },
  { key: 'incoming', label: 'Incoming' },
  { key: 'suppliers', label: 'Suppliers' },
  { key: 'records', label: 'Records' },
];

const TITLES: Record<Surface, [string, string]> = {
  incoming: ['Incoming', 'Quality · arrivals awaiting decision'],
  today: ['Today', 'Production readiness'],
  suppliers: ['Suppliers', 'Approved material sources'],
  records: ['Records', 'Every disposition, searchable'],
};

function OutOfScope({ surface }: { surface: string }) {
  return (
    <div
      data-testid="out-of-scope"
      style={{
        margin: '18px 26px',
        background: N.fill,
        border: `1px solid ${HAIR}`,
        borderRadius: 13,
        padding: '15px 22px',
        maxWidth: 640,
      }}
    >
      <div style={{ font: `600 9px ${MONO}`, letterSpacing: '.1em', color: INK.label }}>
        {surface.toUpperCase()}
      </div>
      <div style={{ font: `400 12.5px/1.5 ${SANS}`, color: INK.prose, marginTop: 6 }}>
        Not built in this gate. Hero A is the scope; this surface comes later rather than being
        filled with placeholder content.
      </div>
    </div>
  );
}

export function HeroAApp({ entry }: { entry: HeroAEntry }) {
  const [surface, setSurface] = useState<Surface>('incoming');
  const [title, sub] = TITLES[surface];

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 14,
        padding: '20px 0 40px',
        background: '#CFC9BD',
      }}
    >
      <div
        data-testid="acceptance-frame"
        style={{
          width: 1600,
          height: 900,
          maxWidth: '100%',
          display: 'flex',
          position: 'relative',
          background: N.frame,
          overflow: 'hidden',
          boxShadow: '0 1px 0 rgba(0,0,0,.04)',
        }}
      >
        <aside
          style={{
            width: 224,
            flex: 'none',
            background: INK.primary,
            color: N.chip,
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{ padding: '24px 22px 20px', borderBottom: '1px solid rgba(255,255,255,.09)' }}
          >
            <div
              style={{
                fontFamily: "'Jost', sans-serif",
                fontWeight: 700,
                fontSize: 27,
                letterSpacing: '-.02em',
                color: '#FAFAFA',
                lineHeight: 1,
              }}
            >
              Vouch
            </div>
            <div
              style={{
                font: `500 10px/1 ${MONO}`,
                letterSpacing: '.12em',
                color: '#8F887A',
                marginTop: 8,
              }}
            >
              ÅBY&nbsp;PLANT
            </div>
          </div>

          <nav style={{ padding: '10px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}>
            {NAV.map((item) => {
              const on = surface === item.key;
              return (
                <button
                  key={item.key}
                  type="button"
                  onClick={() => setSurface(item.key)}
                  style={{
                    textAlign: 'left',
                    background: on ? 'rgba(255,255,255,.08)' : 'transparent',
                    border: 'none',
                    borderRadius: 9,
                    padding: '9px 12px',
                    cursor: 'pointer',
                    font: `600 12.5px ${SANS}`,
                    color: on ? '#FAFAFA' : '#B3AC9E',
                  }}
                >
                  {item.label}
                </button>
              );
            })}
          </nav>
        </aside>

        <main
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
            background: N.frame,
          }}
        >
          <header
            style={{
              height: 58,
              flex: 'none',
              borderBottom: `1px solid ${HAIR}`,
              background: N.card,
              display: 'flex',
              alignItems: 'center',
              padding: '0 26px',
              gap: 16,
            }}
          >
            <h1
              style={{
                margin: 0,
                font: `700 15px ${SANS}`,
                color: INK.primary,
                letterSpacing: '-.01em',
              }}
            >
              {title}
            </h1>
            <div style={{ font: `400 12px ${MONO}`, color: INK.label }}>{sub}</div>
          </header>

          {surface === 'incoming' ? (
            <HeroAPage entry={entry} />
          ) : surface === 'today' ? (
            <div style={{ overflowY: 'auto' }}>
              <IncomingBlockedNotice detail="Today is a later gate; the readiness read model is live but unrendered." />
            </div>
          ) : (
            <div style={{ overflowY: 'auto' }}>
              <OutOfScope surface={surface} />
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
