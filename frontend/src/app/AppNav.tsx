import type { Screen } from '../view-models/types';

const NAV: { key: Screen; label: string; dot: string }[] = [
  { key: 'today', label: 'Today', dot: '#3E6B54' },
  { key: 'incoming', label: 'Incoming', dot: '#45508C' },
  { key: 'suppliers', label: 'Suppliers', dot: '#7C776B' },
  { key: 'records', label: 'Records', dot: '#8A8478' },
];

export function AppNav({
  screen,
  incomingBadge,
  onNavigate,
}: {
  screen: Screen;
  incomingBadge: number;
  onNavigate: (s: Screen) => void;
}) {
  return (
    <nav
      aria-label="Primary"
      style={{ padding: '14px 12px', display: 'flex', flexDirection: 'column', gap: 2 }}
    >
      {NAV.map((n) => {
        // The Decision record lives under Records; keep that nav item lit.
        const on = screen === n.key || (n.key === 'records' && screen === 'record');
        return (
          <button
            key={n.key}
            onClick={() => onNavigate(n.key)}
            aria-current={on ? 'page' : undefined}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 11,
              width: '100%',
              padding: '10px 13px',
              border: 'none',
              borderRadius: 9,
              cursor: 'pointer',
              font: `${on ? 700 : 500} 13.5px 'Public Sans'`,
              color: on ? '#FAFAFA' : '#B3AC9E',
              background: on ? 'rgba(255,255,255,.1)' : 'transparent',
            }}
          >
            <span
              aria-hidden="true"
              style={{ width: 7, height: 7, borderRadius: 2, background: n.dot, flex: 'none' }}
            />
            <span style={{ flex: 1, textAlign: 'left' }}>{n.label}</span>
            {n.key === 'incoming' && (
              <span
                style={{
                  font: "700 10px 'IBM Plex Mono'",
                  color: '#fff',
                  background: '#45508C',
                  borderRadius: 20,
                  padding: '2px 7px',
                }}
              >
                {incomingBadge}
              </span>
            )}
          </button>
        );
      })}
    </nav>
  );
}
