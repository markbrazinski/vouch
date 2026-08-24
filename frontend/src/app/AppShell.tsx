import type { ReactNode } from 'react';
import type { Screen } from '../view-models/types';
import { AppNav } from './AppNav';
import { SearchField } from '../components/SearchField';

const TITLES: Record<Screen, [string, string]> = {
  incoming: ['Incoming', 'Quality · today’s arrivals'],
  today: ['Today', 'Production · Tue 23 Aug'],
  record: ['Decision record', 'L-2231 · Resin R-17'],
  suppliers: ['Suppliers', 'Approved material sources'],
  records: ['Records', 'Every disposition, searchable'],
};

export function AppShell({
  screen,
  incomingBadge,
  onNavigate,
  children,
  overlay,
}: {
  screen: Screen;
  incomingBadge: number;
  onNavigate: (s: Screen) => void;
  children: ReactNode;
  overlay?: ReactNode;
}) {
  const [title, sub] = TITLES[screen];
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
        style={{
          width: 1440,
          height: 940,
          maxWidth: '100%',
          display: 'flex',
          position: 'relative',
          background: '#F0EDE6',
          overflow: 'hidden',
          boxShadow: '0 1px 0 rgba(0,0,0,.04)',
        }}
      >
        <aside
          style={{
            width: 224,
            flex: 'none',
            background: '#211F1B',
            color: '#EFEBE2',
            display: 'flex',
            flexDirection: 'column',
          }}
        >
          <div
            style={{ padding: '24px 22px 20px', borderBottom: '1px solid rgba(255,255,255,.09)' }}
          >
            <div
              style={{
                fontFamily: "'Jost',sans-serif",
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
                font: "500 10px/1 'IBM Plex Mono',monospace",
                letterSpacing: '.12em',
                color: '#8F887A',
                marginTop: 8,
              }}
            >
              ÅBY&nbsp;PLANT&nbsp;·&nbsp;LINE&nbsp;GROUP&nbsp;2
            </div>
          </div>

          <AppNav screen={screen} incomingBadge={incomingBadge} onNavigate={onNavigate} />

          <div
            style={{
              marginTop: 'auto',
              padding: '14px 16px',
              borderTop: '1px solid rgba(255,255,255,.09)',
              display: 'flex',
              alignItems: 'center',
              gap: 10,
            }}
          >
            <div
              aria-hidden="true"
              style={{
                width: 30,
                height: 30,
                borderRadius: '50%',
                background: '#3E6B54',
                color: '#EFEBE2',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                font: "700 12px 'Public Sans'",
              }}
            >
              DK
            </div>
            <div style={{ lineHeight: 1.25 }}>
              <div style={{ font: "600 12px 'Public Sans'", color: '#EFEBE2' }}>D. Karlsson</div>
              <div style={{ font: "400 10px 'IBM Plex Mono'", color: '#8F887A' }}>
                Quality manager
              </div>
            </div>
          </div>
        </aside>

        <main
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            minWidth: 0,
            background: '#F0EDE6',
            position: 'relative',
          }}
        >
          <header
            style={{
              height: 58,
              flex: 'none',
              borderBottom: '1px solid rgba(0,0,0,.1)',
              background: '#F6F3EC',
              display: 'flex',
              alignItems: 'center',
              padding: '0 26px',
              gap: 16,
            }}
          >
            <h1
              style={{
                margin: 0,
                font: "700 15px 'Public Sans'",
                color: '#211F1B',
                letterSpacing: '-.01em',
              }}
            >
              {title}
            </h1>
            <div style={{ font: "400 12px 'IBM Plex Mono'", color: '#8A8478' }}>{sub}</div>
            <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 14 }}>
              <SearchField placeholder="Search lots, orders, suppliers" style={{ minWidth: 230 }} />
              <div
                style={{
                  font: "500 12px 'IBM Plex Mono'",
                  color: '#6B655B',
                  borderLeft: '1px solid rgba(0,0,0,.12)',
                  paddingLeft: 14,
                  whiteSpace: 'nowrap',
                }}
              >
                Tue 23 Aug · 09:48
              </div>
            </div>
          </header>

          <div className="vh" style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
            {children}
          </div>

          {overlay}
        </main>
      </div>
    </div>
  );
}
