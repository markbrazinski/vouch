/**
 * The far-right chronology. Newest first, one row per lifecycle event.
 *
 * This is the surface that proves the work actually happened, so it shows
 * everything the backend emitted — including the high-frequency tool traffic
 * that deliberately does NOT move the active stage. What it never shows is
 * prompts, reasoning or transcripts: those cannot reach the event stream at
 * all, because the backend rejects payload keys that would carry them.
 */

import { useEffect, useRef, useState } from 'react';
import { ACTOR_COLOR, INK, MONO, N, SANS } from './primitives';
import type { ActivityEventVM } from './model';

const RESULT_COLOR: Record<NonNullable<ActivityEventVM['resultStatus']>, string> = {
  neutral: '#57534A',
  good: '#3E6B54',
  caution: '#45508C',
  bad: '#8E2B24',
};

function EventRow({
  event,
  newest,
  entering,
}: {
  event: ActivityEventVM;
  newest: boolean;
  /**
   * True only for a row that arrived on THIS projection change. The rail
   * re-renders on every 900ms poll, so animating on presence would replay the
   * entrance for every row, forever. See `seenRef` in ActivityRail.
   */
  entering: boolean;
}) {
  const [open, setOpen] = useState(false);
  const color = ACTOR_COLOR[event.actorType] ?? INK.muted;

  return (
    <div
      data-testid="activity-row"
      data-event-type={event.eventType}
      data-sequence={event.sequence}
      style={{
        display: 'flex',
        gap: 10,
        padding: '8px',
        borderRadius: 8,
        background: newest ? N.newest : 'transparent',
        // The approved entrance for a real lifecycle event. Bound to arrival,
        // never to a timer: the backend event IS the trigger.
        animation: entering ? 'vSlide .32s cubic-bezier(.2,.7,.2,1) both' : undefined,
      }}
    >
      <div style={{ flex: 'none', width: 3, borderRadius: 3, background: color }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
          <span style={{ font: `500 9.5px ${MONO}`, color: INK.faint }}>{event.clock}</span>
          <span
            style={{
              font: `700 9.5px ${MONO}`,
              letterSpacing: '.04em',
              color,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {event.actorDisplayName.toUpperCase()}
          </span>
        </div>
        <div style={{ font: `600 12px ${SANS}`, color: INK.primary, marginTop: 2 }}>
          {event.shortLabel}
        </div>
        {event.toolId && (
          <div style={{ font: `500 10px ${MONO}`, color: '#7C766A', marginTop: 2 }}>
            {event.toolId}
          </div>
        )}
        {event.resultSummary && (
          <div
            style={{
              font: `400 11px ${MONO}`,
              color: RESULT_COLOR[event.resultStatus ?? 'neutral'],
              marginTop: 2,
            }}
          >
            {event.resultSummary}
          </div>
        )}
        {event.expandable && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            style={{
              marginTop: 4,
              background: 'transparent',
              border: 'none',
              padding: 0,
              cursor: 'pointer',
              font: `500 9.5px ${MONO}`,
              color: INK.label,
            }}
          >
            {open ? '▾ less' : '▸ detail'}
          </button>
        )}
        {open &&
          event.detail?.map((d) => (
            <div
              key={d.label}
              style={{ display: 'flex', gap: 6, marginTop: 3, font: `400 10px ${MONO}` }}
            >
              <span style={{ color: INK.label }}>{d.label}</span>
              <span style={{ color: INK.dense }}>{d.value}</span>
            </div>
          ))}
      </div>
    </div>
  );
}

export function ActivityRail({
  events,
  live,
}: {
  events: ActivityEventVM[];
  live: boolean;
}) {
  /**
   * Every event id that has already been rendered once.
   *
   * The rail re-renders on every 900ms poll tick. Without this, `vSlide` would
   * be re-applied to every row on every tick and the whole rail would slide in
   * repeatedly for the length of the run. Recording ids in an effect (after
   * paint) means a row's FIRST render sees itself as new and animates, and its
   * every later render does not.
   *
   * A ref, not state: writing it must not itself schedule a render.
   */
  const seenRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const e of events) seenRef.current.add(e.eventId);
  }, [events]);

  return (
    <div
      style={{
        width: 320,
        flex: 'none',
        borderLeft: '1px solid rgba(0,0,0,.12)',
        background: N.recessed,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
      data-testid="activity-rail"
    >
      <div
        style={{
          flex: 'none',
          padding: '14px 18px',
          borderBottom: '1px solid rgba(0,0,0,.1)',
          display: 'flex',
          alignItems: 'center',
          gap: 9,
        }}
      >
        <span
          data-testid="rail-live-dot"
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: live ? '#3E6B54' : '#B7B0A2',
            flex: 'none',
            // The one place a pulse is approved: it means "a real evaluation is
            // running right now", and it stops when the backend stops.
            animation: live ? 'vp 1.6s ease-in-out infinite' : undefined,
          }}
        />
        <div style={{ font: `800 12px ${SANS}`, color: INK.primary }}>Activity</div>
        <div style={{ font: `400 10px ${MONO}`, color: INK.label }}>newest first</div>
        <div style={{ marginLeft: 'auto', font: `400 10px ${MONO}`, color: INK.label }}>
          {events.length}
        </div>
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '10px 12px' }}>
        {events.length === 0 ? (
          <div style={{ font: `400 11px ${MONO}`, color: INK.placeholder, padding: '8px' }}>
            {live ? 'Waiting for the first event…' : 'No activity yet.'}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {events.map((e, i) => (
              <EventRow
                key={e.eventId}
                event={e}
                newest={i === 0}
                entering={!seenRef.current.has(e.eventId)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
