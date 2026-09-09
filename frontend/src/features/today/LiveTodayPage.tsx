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

/**
 * What a requirement is actually made of.
 *
 * A single "coverage 0" number could not distinguish an order that is short
 * with a named lot queued against it from one that is short with nothing
 * coming — the difference between a plan that may still work and a plan that
 * has already failed. Each component is stated on its own line, and a queued
 * lot says what became of it, because "400 kg unavailable · LOT-1002
 * quarantined" is the sentence that explains the day.
 */
function CoverageRow({ order }: { order: TodayOrderVM }) {
  if (order.coverage.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 9 }}>
      {order.coverage.map((c) => {
        const line = (label: string, value: string, color: string, bold = false) => (
          <div
            key={label}
            style={{
              display: 'flex',
              gap: 8,
              font: `${bold ? 700 : 400} 11px 'IBM Plex Mono'`,
              color,
            }}
          >
            <span style={{ minWidth: 78, textAlign: 'right' }}>{value} kg</span>
            <span>{label}</span>
          </div>
        );
        return (
          <div key={c.materialId} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div style={{ font: "400 10px 'IBM Plex Mono'", color: T.faint }}>
              {c.materialId}
            </div>
            {line('required', c.required, T.ink70)}
            {line('released', c.available, '#3E6B54')}
            {/* Every allocation, honourable or not — a lot that was refused is
                more informative than its absence. */}
            {c.sources.map((source) =>
              line(
                source.honourable
                  ? `queued · ${source.lotId} · awaiting Quality`
                  : `unavailable · ${source.lotId} ${source.lotStatus.toLowerCase()}`,
                source.quantity,
                source.honourable ? '#8a6318' : '#8E2B24',
              ),
            )}
            {c.short && c.uncovered !== '0' && line('short', c.uncovered, '#8E2B24', true)}
          </div>
        );
      })}
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
    <div style={{ padding: '20px 34px 50px', maxWidth: 1560, margin: '0 auto' }}>
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

      {/* What the recorded decisions DID — and it stays after the plan catches
          up, because the final frame is where an operator most needs to know
          which event moved which order. */}
      {vm.causalHistory.length > 0 && (
        <div
          data-testid="today-causal-history"
          style={{
            marginTop: 16,
            background: T.panel,
            border: `1px solid ${T.hairline}`,
            borderRadius: 11,
            padding: '13px 16px',
          }}
        >
          <div
            style={{
              font: "600 10px 'IBM Plex Mono'",
              letterSpacing: '.1em',
              color: T.faint,
            }}
          >
            WHAT CHANGED TODAY
          </div>
          <div style={{ marginTop: 9, display: 'flex', flexDirection: 'column', gap: 11 }}>
            {vm.causalHistory.map((event) => (
              <div key={`${event.decisionRecordId}:${event.kind}:${event.orderId}`}>
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'baseline',
                    gap: 8,
                    flexWrap: 'wrap',
                  }}
                >
                  <span
                    style={{
                      font: "600 10px 'IBM Plex Mono'",
                      letterSpacing: '.06em',
                      color: event.disposition === 'RELEASE' ? '#3E6B54' : '#8E2B24',
                    }}
                  >
                    {event.lotId} · {event.disposition || 'ASSESSED'}
                  </span>
                  <span style={{ font: "400 12.5px/1.6 'Public Sans'", color: T.ink70 }}>
                    {event.sentence}
                  </span>
                  {onOpenDecision && event.decisionRecordId && (
                    <button
                      data-testid={`why-${event.orderId}`}
                      onClick={() => onOpenDecision(event.decisionRecordId)}
                      style={{
                        padding: '2px 8px',
                        background: 'transparent',
                        border: '1px solid rgba(0,0,0,.16)',
                        borderRadius: 6,
                        font: "600 10.5px 'Public Sans'",
                        color: T.ink70,
                        cursor: 'pointer',
                      }}
                    >
                      Why did this change? →
                    </button>
                  )}
                </div>

                {/* The candidates Vouch weighed, on the main canvas rather than
                    behind a panel: a refusal is as much of the answer as the
                    move, and "stock exists but authority does not" is the whole
                    safety story. */}
                {event.candidates.length > 0 && (
                  <ul
                    data-testid={`candidates-${event.orderId}`}
                    style={{
                      margin: '7px 0 0',
                      padding: 0,
                      listStyle: 'none',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: 3,
                    }}
                  >
                    {event.candidates.map((candidate) => (
                      <li
                        key={`${candidate.kind}:${candidate.candidateId}`}
                        style={{
                          display: 'flex',
                          alignItems: 'baseline',
                          gap: 8,
                          font: "400 11.5px 'Public Sans'",
                          color: T.muted,
                        }}
                      >
                        <span
                          style={{
                            font: "600 9.5px 'IBM Plex Mono'",
                            letterSpacing: '.05em',
                            color:
                              candidate.verdict === 'ELIGIBLE'
                                ? '#3E6B54'
                                : candidate.verdict === 'REFUSED'
                                  ? '#8E2B24'
                                  : T.faint,
                            minWidth: 92,
                          }}
                        >
                          {candidate.verdict}
                        </span>
                        <span style={{ color: T.ink70, minWidth: 96 }}>
                          {candidate.candidateId}
                        </span>
                        <span>{candidate.detail}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pre-decision, and deliberately calm. The material has not been
          evaluated yet, so this states a pending question rather than a
          conflict — and it is mutually exclusive with the divergence banner
          below, which asserts something evidence has actually established. */}
      {vm.awaitingQuality.length > 0 && (
        <div
          data-testid="today-awaiting-quality"
          style={{
            marginTop: 16,
            background: '#EAEBF4',
            border: '1px solid rgba(69,80,140,.32)',
            borderRadius: 11,
            padding: '13px 16px',
          }}
        >
          <div
            style={{
              font: "600 10px 'IBM Plex Mono'",
              letterSpacing: '.1em',
              color: '#45508C',
            }}
          >
            MATERIAL DECISIONS PENDING
          </div>
          <div style={{ marginTop: 5, font: "400 12.5px/1.6 'Public Sans'", color: '#3C4468' }}>
            Today&rsquo;s plan depends on incoming material that Quality has not yet
            cleared.
          </div>
        </div>
      )}

      {/* Divergence is a DIFFERENT statement: the plan has not caught up yet. */}
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
