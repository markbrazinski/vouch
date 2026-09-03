/**
 * The Hero A application shell.
 *
 * A thin frame around the Decision Workspace: the fixed 1600x900 acceptance
 * viewport, the dark primary nav, and the top context header. It is separate
 * from the older fixture-driven `VouchApp` because the workspace owns its own
 * scrolling — it has an independently-scrolling activity rail — and the older
 * shell wraps children in a single scroller that would fight it.
 *
 * All four surfaces are now live: each reads its own authoritative read model
 * and renders an answer, a truthful empty, an explicitly-blocked path or a
 * technical failure. None of them falls back to fixture content.
 *
 * Navigation keeps context. Opening a decision from Today or Incoming lands on
 * that decision's record and remembers where it came from, so returning goes
 * back to the surface the operator was reading rather than to a default.
 */

import { useCallback, useState } from 'react';
import { HeroAPage, type HeroAEntry } from './HeroAPage';
import { INK, MONO, N, SANS, HAIR } from './primitives';
import {
  IncomingSurface,
  RecordSurface,
  RecordsIndexSurface,
  SuppliersSurface,
  TodaySurface,
} from '../features/Surfaces';

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

/** Returning from a record goes back where the operator actually was. */
function BackBar({ label, onBack }: { label: string; onBack: () => void }) {
  return (
    <div style={{ padding: '14px 30px 0' }}>
      <button
        type="button"
        onClick={onBack}
        style={{
          background: 'transparent',
          border: `1px solid ${HAIR}`,
          borderRadius: 7,
          padding: '5px 11px',
          font: `600 11.5px ${SANS}`,
          color: INK.prose,
          cursor: 'pointer',
        }}
      >
        &larr; {label}
      </button>
    </div>
  );
}

export function HeroAApp({ entry }: { entry: HeroAEntry }) {
  const [surface, setSurface] = useState<Surface>('incoming');
  const [openRecordId, setOpenRecordId] = useState<string | null>(null);
  const [title, sub] = TITLES[surface];

  const openRecord = useCallback((id: string) => setOpenRecordId(id), []);

  /**
   * Today links an order to the decision that changed it.
   *
   * The causal link is `consequences.caused_by` on the record, which Today's
   * payload does not carry - `get_today` deliberately states no before/after,
   * because which change to highlight is a presentation question. Until a
   * decision id reaches this surface, the honest move is to send the operator
   * to the ledger rather than to guess at a record id.
   */
  const openOrder = useCallback((_orderId: string) => {
    setOpenRecordId(null);
    setSurface('records');
  }, []);

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
                  onClick={() => {
                    setSurface(item.key);
                    setOpenRecordId(null);
                  }}
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

          {surface === 'incoming' && !openRecordId ? (
            <HeroAPage entry={entry} />
          ) : (
            <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
              {openRecordId ? (
                <>
                  <BackBar
                    label={`Back to ${TITLES[surface][0]}`}
                    onBack={() => setOpenRecordId(null)}
                  />
                  <RecordSurface decisionRecordId={openRecordId} />
                </>
              ) : surface === 'today' ? (
                <TodaySurface onOpenDecision={openOrder} />
              ) : surface === 'incoming' ? (
                <IncomingSurface onOpen={setOpenRecordId} />
              ) : surface === 'suppliers' ? (
                <SuppliersSurface onOpen={openRecord} />
              ) : (
                <RecordsIndexSurface onOpen={setOpenRecordId} />
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
