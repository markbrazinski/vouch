import type { SequenceCell, VouchViewModel } from '../../view-models/types';
import { ReadinessPill } from '../../components/StatusPill';

const BG = {
  READY: '#FCFBF7',
  AWAITING_QUALITY: '#EFF0F7',
  AT_RISK: '#FBF8EF',
  BLOCKED: '#FBF3F1',
} as const;
const BORDER = {
  READY: 'rgba(0,0,0,.12)',
  AWAITING_QUALITY: 'rgba(69,80,140,.34)',
  AT_RISK: 'rgba(181,133,42,.4)',
  BLOCKED: 'rgba(142,43,36,.4)',
} as const;

// Entrance motion per cell: C-418 slides into the vacated slot; C-417 pops in blocked.
const ANIM: Record<string, string> = {
  'C-418': 'vSlide .44s cubic-bezier(.2,.7,.2,1) both',
  'C-417': 'vFade .3s ease-out both, vPop .55s ease-out .28s both',
};

function seqAnim(id: string, i: number) {
  return ANIM[id] ?? `vFade .3s ease-out ${60 + i * 60}ms both`;
}

export function LineSequence({ cells }: { cells: SequenceCell[] }) {
  return (
    <div style={{ display: 'flex', alignItems: 'stretch', gap: 0, marginTop: 12 }}>
      {cells.map((o, i) => (
        <div key={o.id} style={{ flex: 1, display: 'flex', alignItems: 'stretch' }}>
          <div
            style={{
              flex: 1,
              background: BG[o.readiness],
              border: `1.5px solid ${BORDER[o.readiness]}`,
              borderRadius: 9,
              padding: '10px 12px',
              position: 'relative',
              animation: seqAnim(o.id, i),
            }}
          >
            {o.tag && (
              <span
                style={{
                  position: 'absolute',
                  top: -8,
                  left: 11,
                  font: "700 8px 'IBM Plex Mono'",
                  letterSpacing: '.06em',
                  color: '#EFEBE2',
                  background: '#3F3A32',
                  borderRadius: 4,
                  padding: '2px 6px',
                }}
              >
                {o.tag}
              </span>
            )}
            <div style={{ font: "400 10px 'IBM Plex Mono'", color: '#8A8478' }}>{o.time}</div>
            <div style={{ font: "700 15px 'IBM Plex Mono'", color: '#211F1B', marginTop: 1 }}>
              {o.id}
            </div>
            <div style={{ marginTop: 7 }}>
              <ReadinessPill readiness={o.readiness} />
            </div>
          </div>
          {i < cells.length - 1 && (
            <div
              aria-hidden="true"
              style={{
                display: 'flex',
                alignItems: 'center',
                padding: '0 4px',
                font: "600 15px 'IBM Plex Mono'",
                color: '#B7B0A2',
              }}
            >
              ›
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

export function ResequencePanel({
  resequence,
}: {
  resequence: NonNullable<NonNullable<VouchViewModel['today']>['disruption']>['resequence'];
}) {
  return (
    <div
      style={{
        marginTop: 12,
        background: '#EFEBE2',
        border: '1px solid rgba(0,0,0,.14)',
        borderRadius: 10,
        padding: '12px 16px',
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        flexWrap: 'wrap',
      }}
    >
      <span
        style={{
          font: "700 10px 'IBM Plex Mono'",
          letterSpacing: '.06em',
          color: '#EFEBE2',
          background: '#3F3A32',
          borderRadius: 6,
          padding: '4px 9px',
        }}
      >
        {resequence.badge}
      </span>
      <div style={{ font: "600 13px 'Public Sans'", color: '#211F1B' }}>{resequence.line}</div>
      <div style={{ textAlign: 'right', marginLeft: 'auto' }}>
        <div style={{ font: "700 11px 'IBM Plex Mono'", letterSpacing: '.05em', color: '#3E6B54' }}>
          {resequence.result}
        </div>
        {/* C-417 stays blocked. The UI never implies it ran. */}
        <div style={{ font: "400 10.5px 'IBM Plex Mono'", color: '#8A8478', marginTop: 2 }}>
          {resequence.caveat}
        </div>
      </div>
    </div>
  );
}
