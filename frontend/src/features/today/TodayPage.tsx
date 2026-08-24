import type { Command, ReadinessCell, VouchViewModel } from '../../view-models/types';
import { readinessLabel } from '../../components/tokens';
import { ProductionLine } from './ProductionLine';

const CELL: Record<
  ReadinessCell['readiness'],
  { color: string; bg: string; border: string; blockedZero?: string }
> = {
  READY: { color: '#3E6B54', bg: '#EEF2ED', border: 'rgba(62,107,84,.28)' },
  AT_RISK: { color: '#8a6318', bg: '#F7F1E0', border: 'rgba(181,133,42,.3)' },
  BLOCKED: { color: '#8E2B24', bg: '#FBF3F1', border: 'rgba(142,43,36,.3)' },
};

function ReadinessTile({ cell }: { cell: ReadinessCell }) {
  const c = CELL[cell.readiness];
  // A zero BLOCKED count stays calm rather than alarming.
  const quiet = cell.readiness === 'BLOCKED' && cell.count === 0;
  return (
    <div
      style={{
        background: quiet ? '#F6F3EC' : c.bg,
        border: `1px solid ${quiet ? 'rgba(0,0,0,.1)' : c.border}`,
        borderRadius: 10,
        padding: '9px 14px',
        display: 'flex',
        alignItems: 'center',
        gap: 9,
      }}
    >
      <span style={{ font: "800 20px 'Public Sans'", color: c.color, lineHeight: 1 }}>
        {cell.count}
      </span>
      <div>
        <div style={{ font: "700 11px 'IBM Plex Mono'", color: c.color, letterSpacing: '.03em' }}>
          {readinessLabel[cell.readiness]}
        </div>
        <div style={{ font: "400 10px 'Public Sans'", color: '#8A8478' }}>{cell.sub}</div>
      </div>
    </div>
  );
}

export function TodayPage({
  vm,
  dispatch,
}: {
  vm: NonNullable<VouchViewModel['today']>;
  dispatch: (cmd: Command) => void;
}) {
  return (
    <div style={{ padding: '20px 30px 60px', maxWidth: 1240, margin: '0 auto' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 16,
        }}
      >
        <div>
          <div
            style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: '#8A8478' }}
          >
            PRODUCTION · 8 LINES · 43 ORDERS
          </div>
          <h2
            style={{
              margin: '5px 0 0',
              font: "800 24px 'Public Sans'",
              letterSpacing: '-.02em',
              color: '#211F1B',
            }}
          >
            Production plan · Tue 23 Aug
          </h2>
        </div>
        <div style={{ display: 'flex', gap: 9 }}>
          {vm.readiness.map((r) => (
            <ReadinessTile key={r.readiness} cell={r} />
          ))}
        </div>
      </div>

      <div
        style={{
          marginTop: 18,
          background: '#F6F3EC',
          border: '1px solid rgba(0,0,0,.1)',
          borderRadius: 13,
          overflow: 'hidden',
        }}
      >
        {vm.lines.map((ln) => (
          <ProductionLine key={ln.name} line={ln} disruption={vm.disruption} dispatch={dispatch} />
        ))}
      </div>
    </div>
  );
}
