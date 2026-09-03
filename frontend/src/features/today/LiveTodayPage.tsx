/**
 * Today — authoritative production state.
 *
 * Every value rendered here came from `get_today`. The page formats and orders;
 * it never computes readiness, coverage, shortage or a ratio, because those are
 * deterministic Python and a second implementation in the browser could
 * disagree with the decision that produced them.
 *
 * The page's job is to make a disposition's OPERATIONAL consequence legible:
 * which order changed, why, and what is still uncovered. It deliberately does
 * not claim a blocked order was repaired — recovery moves a different order
 * into a vacated slot, and saying otherwise would misrepresent the plan.
 */

import type { TodayOrderVM, TodayVM } from './model';
import { T } from '../../components/tokens';
import { ReadinessPill, StatusPill } from '../../components/StatusPill';

function CountTile({
  count,
  label,
  readiness,
}: {
  count: number;
  label: string;
  readiness: TodayOrderVM['readiness'];
}) {
  const color =
    readiness === 'BLOCKED' ? '#8E2B24' : readiness === 'AT_RISK' ? '#8a6318' : '#3E6B54';
  // A zero count stays calm rather than alarming: nothing is wrong.
  const quiet = count === 0;
  return (
    <div
      style={{
        background: quiet ? T.panel : '#FCFBF7',
        border: `1px solid ${quiet ? T.hairline : color + '4d'}`,
        borderRadius: 10,
        padding: '9px 15px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
      }}
    >
      <span
        style={{
          font: "800 20px 'Public Sans'",
          color: quiet ? T.faint : color,
          lineHeight: 1,
        }}
      >
        {count}
      </span>
      <span
        style={{
          font: "700 10.5px 'IBM Plex Mono'",
          letterSpacing: '.05em',
          color: quiet ? T.faint : color,
        }}
      >
        {label}
      </span>
    </div>
  );
}

/**
 * Stored status beside computed readiness.
 *
 * Rendered as two labelled facts rather than one merged badge. When they
 * disagree the plan has not yet caught up with what Vouch established, and that
 * gap is the operational point of the surface.
 */
function StatusVsReadiness({ order }: { order: TodayOrderVM }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      <span style={{ font: "400 9.5px 'IBM Plex Mono'", color: T.faint }}>PLAN</span>
      <StatusPill tone="progress" label={order.status || '—'} size="sm" />
      <span aria-hidden="true" style={{ color: '#A39C8D', font: "600 12px 'IBM Plex Mono'" }}>
        →
      </span>
      <span style={{ font: "400 9.5px 'IBM Plex Mono'", color: T.faint }}>VOUCH</span>
      <ReadinessPill readiness={order.readiness} size="sm" />
    </div>
  );
}

function CoverageRow({ order }: { order: TodayOrderVM }) {
  if (order.coverage.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginTop: 8 }}>
      {order.coverage.map((c) => (
        <div
          key={c.materialId}
          style={{
            display: 'flex',
            alignItems: 'baseline',
            gap: 10,
            font: "400 11px 'IBM Plex Mono'",
            color: c.short ? '#8E2B24' : T.muted,
          }}
        >
          <span style={{ minWidth: 118, color: T.ink70 }}>{c.materialId}</span>
          <span>
            need {c.required} · have {c.available}
          </span>
          {/* Shown only when the backend reported a shortfall. */}
          {c.short && <span style={{ fontWeight: 700 }}>short {c.shortBy}</span>}
        </div>
      ))}
    </div>
  );
}

function OrderCard({
  order,
  onOpenDecision,
}: {
  order: TodayOrderVM;
  onOpenDecision?: (orderId: string) => void;
}) {
  const alarming = order.readiness === 'BLOCKED';
  return (
    <div
      data-order={order.orderId}
      data-readiness={order.readiness}
      data-status={order.status}
      style={{
        background: alarming ? '#FBF3F1' : '#FCFBF7',
        border: `1px solid ${alarming ? 'rgba(142,43,36,.38)' : T.hairline}`,
        borderRadius: 10,
        padding: '12px 14px',
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint }}>{order.slot}</span>
        <span style={{ font: "700 14px 'IBM Plex Mono'", color: T.ink }}>{order.orderId}</span>
        {order.materialLabel && (
          <span style={{ font: "400 11px 'Public Sans'", color: T.muted }}>
            {order.materialLabel}
          </span>
        )}
        {order.customerCommitted && (
          <span
            style={{
              font: "600 9px 'IBM Plex Mono'",
              letterSpacing: '.06em',
              color: '#45508C',
              border: '1px solid rgba(69,80,140,.3)',
              borderRadius: 4,
              padding: '2px 6px',
            }}
          >
            COMMITTED
          </span>
        )}
        <span style={{ marginLeft: 'auto' }}>
          <StatusVsReadiness order={order} />
        </span>
      </div>

      {/* The backend's own sentence, verbatim. */}
      {order.reason && (
        <div
          style={{
            marginTop: 8,
            font: `${alarming ? 600 : 400} 12px 'Public Sans'`,
            color: alarming ? '#8E2B24' : T.muted,
          }}
        >
          {order.reason}
        </div>
      )}

      <CoverageRow order={order} />

      {order.divergent && onOpenDecision && (
        <button
          onClick={() => onOpenDecision(order.orderId)}
          style={{
            marginTop: 10,
            padding: '6px 12px',
            background: 'transparent',
            border: '1px solid rgba(0,0,0,.18)',
            borderRadius: 7,
            font: "600 11.5px 'Public Sans'",
            color: T.ink70,
            cursor: 'pointer',
          }}
        >
          Why did this change? →
        </button>
      )}
    </div>
  );
}

export function LiveTodayPage({
  vm,
  onOpenDecision,
}: {
  vm: TodayVM;
  onOpenDecision?: (orderId: string) => void;
}) {
  return (
    <div style={{ padding: '20px 30px 50px', maxWidth: 1240, margin: '0 auto' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div
            style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}
          >
            {/* Counted from what the payload returned, never a fixed number. */}
            PRODUCTION · {vm.lineCount} {vm.lineCount === 1 ? 'LINE' : 'LINES'} ·{' '}
            {vm.orderCount} {vm.orderCount === 1 ? 'ORDER' : 'ORDERS'}
          </div>
          <h2
            style={{
              margin: '5px 0 0',
              font: "800 24px 'Public Sans'",
              letterSpacing: '-.02em',
              color: T.ink,
            }}
          >
            Production plan
          </h2>
        </div>
        <div style={{ display: 'flex', gap: 9 }}>
          {vm.counts.map((c) => (
            <CountTile
              key={c.readiness}
              count={c.count}
              label={c.label}
              readiness={c.readiness}
            />
          ))}
        </div>
      </div>

      {/* What a disposition did to the plan, stated before the full grid. */}
      {vm.divergent.length > 0 && (
        <div
          data-testid="today-divergence"
          style={{
            marginTop: 16,
            background: '#F6EEE6',
            border: '1px solid rgba(154,90,42,.36)',
            borderRadius: 11,
            padding: '13px 16px',
          }}
        >
          <div
            style={{
              font: "600 10px 'IBM Plex Mono'",
              letterSpacing: '.1em',
              color: '#9A5A2A',
            }}
          >
            PLAN AND EVIDENCE DISAGREE
          </div>
          <div style={{ marginTop: 5, font: "400 12.5px/1.6 'Public Sans'", color: '#5C4326' }}>
            {vm.divergent.length === 1 ? 'One order is' : `${vm.divergent.length} orders are`}{' '}
            still scheduled as planned, but the material that would cover{' '}
            {vm.divergent.length === 1 ? 'it' : 'them'} is not usable. The stored plan is
            unchanged; the readiness below is what the evidence now supports.
          </div>
        </div>
      )}

      <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 16 }}>
        {vm.lines.map((line) => (
          <section key={line.lineId}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 10,
                marginBottom: 8,
              }}
            >
              <h3
                style={{
                  margin: 0,
                  font: "700 13px 'Public Sans'",
                  color: T.ink,
                }}
              >
                {line.lineId}
              </h3>
              <span style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint }}>
                {line.disturbed ? 'attention required' : 'all covered'}
              </span>
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
                gap: 10,
              }}
            >
              {line.orders.map((order) => (
                <OrderCard
                  key={order.orderId}
                  order={order}
                  onOpenDecision={onOpenDecision}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
