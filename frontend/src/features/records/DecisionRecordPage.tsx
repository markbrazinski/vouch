import type { BasisStep, Command, VouchViewModel } from '../../view-models/types';
import { SEM } from '../../components/tokens';

const INK = { fg: '#211F1B', bg: '#EFEBE2', br: 'rgba(0,0,0,.12)' };

function toneSpec(tone: BasisStep['tone']) {
  return tone === 'ink' ? INK : SEM[tone];
}

function BasisChain({ links }: { links: NonNullable<VouchViewModel['record']>['basisChain'] }) {
  return (
    <div
      style={{
        marginTop: 20,
        background: '#F6F3EC',
        border: '1px solid rgba(0,0,0,.1)',
        borderRadius: 12,
        padding: '16px 20px',
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        flexWrap: 'wrap',
      }}
    >
      {links.map((l, i) => (
        <div key={l.label} style={{ display: 'contents' }}>
          {i > 0 && (
            <span
              aria-hidden="true"
              style={{ font: "600 15px 'IBM Plex Mono'", color: '#B7B0A2', padding: '0 4px' }}
            >
              →
            </span>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <span
              style={{
                font: "500 10px 'IBM Plex Mono'",
                letterSpacing: '.08em',
                color: '#8A8478',
              }}
            >
              {l.label}
            </span>
            {l.tone && l.tone !== 'ink' ? (
              <span
                style={{
                  font: `700 ${l.tone === 'released' ? 11 : 11}px 'IBM Plex Mono'`,
                  letterSpacing: l.tone === 'quarantine' ? '.05em' : undefined,
                  color: SEM[l.tone].fg,
                  background: SEM[l.tone].bg,
                  border: l.tone === 'quarantine' ? `1px solid ${SEM[l.tone].br}` : undefined,
                  borderRadius: 5,
                  padding: '3px 8px',
                  alignSelf: 'flex-start',
                }}
              >
                {l.value}
              </span>
            ) : (
              <span
                style={{
                  font: `700 13px ${l.label === 'GOVERNING BASIS' ? "'Public Sans'" : "'IBM Plex Mono'"}`,
                  color: l.label === 'SUPPLIED RESULT' ? '#9A5A2A' : '#211F1B',
                }}
              >
                {l.value}
              </span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function BasisStepCard({ step }: { step: BasisStep }) {
  const t = toneSpec(step.tone);
  const big = !!step.loadBearing;
  const quar = step.tone === 'quarantine';
  const block = step.tone === 'blocked';
  return (
    <li style={{ position: 'relative', listStyle: 'none' }}>
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          left: -34,
          top: 14,
          width: 24,
          height: 24,
          borderRadius: '50%',
          background: quar ? '#9A5A2A' : block ? '#8E2B24' : '#211F1B',
          color: '#fff',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          font: "700 12px 'IBM Plex Mono'",
          boxShadow: '0 0 0 4px #F0EDE6',
        }}
      >
        {step.n}
      </div>
      <div
        style={{
          background: big ? (quar ? '#FCF6F0' : block ? '#FBF3F1' : '#EFEBE2') : '#F6F3EC',
          border: `1px solid ${
            big
              ? quar
                ? 'rgba(154,90,42,.34)'
                : block
                  ? 'rgba(142,43,36,.28)'
                  : 'rgba(0,0,0,.18)'
              : 'rgba(0,0,0,.1)'
          }`,
          borderRadius: 12,
          padding: '14px 18px',
        }}
      >
        <div style={{ font: "600 10px 'IBM Plex Mono'", letterSpacing: '.12em', color: '#8A8478' }}>
          {step.kind}
        </div>
        <div
          style={{
            font: "700 16px 'Public Sans'",
            color: big && quar ? '#9A5A2A' : '#211F1B',
            marginTop: 5,
            letterSpacing: '-.01em',
          }}
        >
          {step.head}
        </div>
        <div
          style={{
            font: "400 13px/1.55 'Public Sans'",
            color: '#413D35',
            margin: '6px 0 11px',
            maxWidth: 620,
          }}
        >
          {step.body}
        </div>
        <span
          style={{
            display: 'inline-block',
            font: `700 ${big ? 12 : 11}px 'IBM Plex Mono'`,
            letterSpacing: '.04em',
            color: t.fg,
            background: t.bg,
            border: `1px solid ${t.br}`,
            borderRadius: 7,
            padding: big ? '6px 13px' : '4px 10px',
          }}
        >
          {step.pill}
        </span>
      </div>
    </li>
  );
}

export function DecisionRecordPage({
  vm,
  dispatch,
}: {
  vm: NonNullable<VouchViewModel['record']>;
  dispatch: (cmd: Command) => void;
}) {
  return (
    <div style={{ padding: '24px 30px 70px', maxWidth: 940, margin: '0 auto' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          font: "400 12px 'IBM Plex Mono'",
          color: '#8A8478',
        }}
      >
        <button
          onClick={() => dispatch({ type: 'NAVIGATE', screen: 'records' })}
          style={{
            cursor: 'pointer',
            background: 'none',
            border: 'none',
            padding: 0,
            font: 'inherit',
            color: 'inherit',
          }}
        >
          Records
        </button>
        <span aria-hidden="true">›</span>
        <span style={{ color: '#4A463E' }}>{vm.lotId}</span>
      </div>

      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 20,
          marginTop: 12,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <span style={{ font: "700 24px 'IBM Plex Mono'", color: '#211F1B' }}>{vm.lotId}</span>
            <span style={{ font: "400 16px 'IBM Plex Mono'", color: '#6B655B' }}>
              {vm.material}
            </span>
          </div>
          <div style={{ font: "400 12px 'IBM Plex Mono'", color: '#8A8478', marginTop: 6 }}>
            {vm.meta}
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span
            style={{
              display: 'inline-block',
              font: "700 12px 'IBM Plex Mono'",
              letterSpacing: '.06em',
              color: '#9A5A2A',
              background: 'transparent',
              border: '1px solid #9A5A2A',
              borderRadius: 7,
              padding: '5px 13px',
            }}
          >
            {vm.disposition}
          </span>
          <div style={{ font: "400 11px 'IBM Plex Mono'", color: '#8A8478', marginTop: 7 }}>
            {vm.dispositionNote}
          </div>
        </div>
      </div>

      <BasisChain links={vm.basisChain} />

      <h3 style={{ font: "800 15px 'Public Sans'", color: '#211F1B', margin: '26px 0 16px' }}>
        Decision basis
      </h3>

      <div style={{ position: 'relative', paddingLeft: 34 }}>
        <div
          aria-hidden="true"
          style={{
            position: 'absolute',
            left: 11,
            top: 8,
            bottom: 8,
            width: 2,
            background: 'rgba(0,0,0,.12)',
          }}
        />
        <ol
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: 13,
            margin: 0,
            padding: 0,
            listStyle: 'none',
          }}
        >
          {vm.steps.map((s) => (
            <BasisStepCard key={s.n} step={s} />
          ))}
        </ol>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 24, flexWrap: 'wrap' }}>
        <button
          onClick={() => dispatch({ type: 'NAVIGATE', screen: 'today' })}
          style={{
            padding: '10px 17px',
            background: '#211F1B',
            border: 'none',
            borderRadius: 9,
            font: "700 13px 'Public Sans'",
            color: '#F6F3EC',
            cursor: 'pointer',
          }}
        >
          Open in Today
        </button>
        <button
          style={{
            padding: '10px 17px',
            background: '#F6F3EC',
            border: '1px solid rgba(0,0,0,.16)',
            borderRadius: 9,
            font: "600 13px 'Public Sans'",
            color: '#4A463E',
            cursor: 'pointer',
          }}
        >
          Request corrected evidence
        </button>
        <button
          style={{
            padding: '10px 17px',
            background: '#F6F3EC',
            border: '1px solid rgba(0,0,0,.16)',
            borderRadius: 9,
            font: "600 13px 'Public Sans'",
            color: '#4A463E',
            cursor: 'pointer',
          }}
        >
          Export record
        </button>
      </div>
    </div>
  );
}
