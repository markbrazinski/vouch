import type { Command, VouchViewModel } from '../../view-models/types';
import { IncomingStatusRail } from './IncomingStatusRail';
import { NeedsQualityDecisionList } from './NeedsQualityDecisionList';

function SectionHead({
  dot,
  title,
  size,
  meta,
}: {
  dot: string;
  title: string;
  size: number;
  meta: string;
}) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
      <span
        aria-hidden="true"
        style={{ width: 7, height: 7, borderRadius: 2, background: dot, display: 'inline-block' }}
      />
      <h2
        style={{
          margin: 0,
          font: `800 ${size}px 'Public Sans'`,
          color: '#211F1B',
          letterSpacing: '-.01em',
        }}
      >
        {title}
      </h2>
      <div style={{ font: "400 12px 'IBM Plex Mono'", color: '#8A8478' }}>{meta}</div>
    </div>
  );
}

export function IncomingPage({
  vm,
  dispatch,
}: {
  vm: NonNullable<VouchViewModel['incoming']>;
  dispatch: (cmd: Command) => void;
}) {
  return (
    <div style={{ padding: '22px 30px 60px', maxWidth: 1180, margin: '0 auto' }}>
      <IncomingStatusRail {...vm.rail} />

      {vm.incident && (
        <div
          style={{
            marginTop: 14,
            background: '#F6EEE6',
            border: '1px solid rgba(154,90,42,.4)',
            borderLeft: '4px solid #9A5A2A',
            borderRadius: 11,
            padding: '13px 18px',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            flexWrap: 'wrap',
            animation: 'vFade .3s ease-out both',
          }}
        >
          <span
            style={{
              font: "700 10px 'IBM Plex Mono'",
              letterSpacing: '.08em',
              color: '#9A5A2A',
              background: '#EFE0D2',
              border: '1px solid rgba(154,90,42,.4)',
              borderRadius: 6,
              padding: '4px 9px',
            }}
          >
            {vm.incident.headline}
          </span>
          <div style={{ font: "400 13px/1.5 'Public Sans'", color: '#5C4326' }}>
            <b>Halden Chemical</b>
            {vm.incident.body}
          </div>
        </div>
      )}

      <div style={{ marginTop: 26 }}>
        <SectionHead
          dot="#45508C"
          title="Needs you"
          size={17}
          meta="ranked by production impact, then time to slot"
        />
      </div>
      <NeedsQualityDecisionList
        rows={vm.needsYou}
        onOpen={(lotId) => dispatch({ type: 'OPEN_LOT', lotId })}
      />

      <div style={{ marginTop: 26 }}>
        <SectionHead
          dot="#7C776B"
          title="In progress"
          size={15}
          meta={`Vouch is working · ${vm.rail.inProgress} lots`}
        />
      </div>
      <div
        style={{
          marginTop: 11,
          background: '#F6F3EC',
          border: '1px solid rgba(0,0,0,.1)',
          borderRadius: 11,
          padding: '12px 18px',
          display: 'flex',
          alignItems: 'center',
          gap: 20,
          flexWrap: 'wrap',
        }}
      >
        {vm.inProgress.map((p) => (
          <div key={p.label} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ font: "700 14px 'IBM Plex Mono'", color: '#57534A' }}>{p.n}</span>
            <span style={{ font: "400 12px 'Public Sans'", color: '#6B655B' }}>{p.label}</span>
          </div>
        ))}
      </div>

      <div style={{ marginTop: 24 }}>
        <SectionHead
          dot="#3E6B54"
          title="Completed by Vouch"
          size={15}
          meta={`${vm.rail.completed} lots · fully auditable`}
        />
      </div>
      <div
        style={{
          marginTop: 11,
          background: '#EEF2ED',
          border: '1px solid rgba(62,107,84,.26)',
          borderRadius: 11,
          padding: '12px 18px',
          display: 'flex',
          alignItems: 'center',
          gap: 24,
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
          <div>
            <span style={{ font: "700 14px 'IBM Plex Mono'", color: '#3E6B54' }}>
              {vm.completed.released}
            </span>{' '}
            <span style={{ font: "400 11.5px 'Public Sans'", color: '#6B655B' }}>released</span>
          </div>
          <div>
            <span style={{ font: "700 14px 'IBM Plex Mono'", color: '#9A5A2A' }}>
              {vm.completed.quarantined}
            </span>{' '}
            <span style={{ font: "400 11.5px 'Public Sans'", color: '#6B655B' }}>quarantined</span>
          </div>
          <div>
            <span style={{ font: "700 14px 'IBM Plex Mono'", color: '#57534A' }}>
              {vm.completed.reopened}
            </span>{' '}
            <span style={{ font: "400 11.5px 'Public Sans'", color: '#6B655B' }}>reopened</span>
          </div>
        </div>
        <button
          onClick={() => dispatch({ type: 'NAVIGATE', screen: 'records' })}
          style={{
            marginLeft: 'auto',
            padding: '7px 14px',
            background: '#F6F3EC',
            border: '1px solid rgba(62,107,84,.36)',
            borderRadius: 8,
            font: "600 12px 'Public Sans'",
            color: '#33594E',
            cursor: 'pointer',
          }}
        >
          View records →
        </button>
      </div>
    </div>
  );
}
