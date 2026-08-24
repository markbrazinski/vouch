import type { DecisionRow } from '../../view-models/types';
import { StatusPill } from '../../components/StatusPill';

export function IncomingDecisionRow({
  row,
  onOpen,
}: {
  row: DecisionRow;
  onOpen: (lotId: string) => void;
}) {
  const spine = row.tone === 'quarantine' ? '#9A5A2A' : row.hot ? '#45508C' : '#B9B3C4';
  const border = row.hot
    ? row.tone === 'quarantine'
      ? 'rgba(154,90,42,.32)'
      : 'rgba(69,80,140,.3)'
    : 'rgba(0,0,0,.1)';
  return (
    <button
      className="nz"
      onClick={() => onOpen(row.lotId)}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        width: '100%',
        textAlign: 'left',
        borderRadius: 10,
        cursor: 'pointer',
        padding: '11px 14px 11px 0',
        background: row.hot ? '#FBF9F3' : '#F4F1EA',
        border: `1px solid ${border}`,
        overflow: 'hidden',
      }}
    >
      <span
        aria-hidden="true"
        style={{ width: 4, alignSelf: 'stretch', background: spine, borderRadius: 3, flex: 'none' }}
      />
      <div style={{ flex: 'none', width: 158 }}>
        <div style={{ font: "600 14px 'IBM Plex Mono'", color: '#211F1B' }}>{row.lotId}</div>
        <div style={{ font: "400 11.5px 'IBM Plex Mono'", color: '#8A8478', marginTop: 2 }}>
          {row.material}
        </div>
      </div>
      <StatusPill tone={row.tone} label={row.disposition} size="lg" />
      <div style={{ flex: 1, minWidth: 0, overflow: 'hidden' }}>
        <div
          style={{
            font: "400 13px 'Public Sans'",
            color: '#413D35',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {row.reason}
        </div>
      </div>
      <div style={{ flex: 'none', textAlign: 'right', width: 150 }}>
        <div style={{ font: "500 11.5px 'IBM Plex Mono'", color: row.hot ? '#8E2B24' : '#8A8478' }}>
          {row.impact}
        </div>
        {row.clock && (
          <div style={{ font: "700 12px 'IBM Plex Mono'", color: '#8E2B24', marginTop: 2 }}>
            {row.clock}
          </div>
        )}
      </div>
      <span
        aria-hidden="true"
        style={{ font: "400 20px 'IBM Plex Mono'", color: '#B7B0A2', flex: 'none' }}
      >
        ›
      </span>
    </button>
  );
}
