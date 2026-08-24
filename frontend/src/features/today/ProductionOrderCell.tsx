import type { ProductionOrder } from '../../view-models/types';
import { readinessDot, readinessLabel, readinessTone } from '../../components/tokens';
import { StatusPill } from '../../components/StatusPill';

const BG = { READY: '#FCFBF7', AT_RISK: '#FBF8EF', BLOCKED: '#FBF3F1' } as const;
const BORDER = {
  READY: 'rgba(0,0,0,.1)',
  AT_RISK: 'rgba(181,133,42,.4)',
  BLOCKED: 'rgba(142,43,36,.4)',
} as const;

export function ProductionOrderCell({ order }: { order: ProductionOrder }) {
  return (
    <div
      style={{
        flex: 'none',
        width: 150,
        background: BG[order.readiness],
        border: `1px solid ${BORDER[order.readiness]}`,
        borderRadius: 8,
        padding: '8px 10px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ font: "400 10px 'IBM Plex Mono'", color: '#8A8478' }}>{order.time}</span>
        <span
          aria-hidden="true"
          style={{
            width: 7,
            height: 7,
            borderRadius: 2,
            background: readinessDot[order.readiness],
          }}
        />
      </div>
      <div style={{ font: "700 13px 'IBM Plex Mono'", color: '#211F1B', marginTop: 2 }}>
        {order.id}
      </div>
      <div
        style={{
          font: "400 10px 'Public Sans'",
          color: '#8A8478',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {order.material}
      </div>
      {/* Non-READY always carries its textual label — never color alone. */}
      {order.readiness !== 'READY' && (
        <div style={{ marginTop: 6 }}>
          <StatusPill
            tone={readinessTone[order.readiness]}
            label={readinessLabel[order.readiness]}
            size="sm"
          />
        </div>
      )}
    </div>
  );
}
