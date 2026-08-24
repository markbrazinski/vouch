import type { RecoveryVerdictVM } from '../../view-models/types';
import { SEM } from '../../components/tokens';

export function RecoveryVerdict({ v, delay }: { v: RecoveryVerdictVM; delay: number }) {
  const t = SEM[v.tone];
  return (
    <div
      style={{
        background: '#F6F3EC',
        border: '1px solid rgba(0,0,0,.1)',
        borderRadius: 9,
        padding: '11px 13px',
        animation: `vFade .3s ease-out ${delay}ms both`,
      }}
    >
      <div style={{ font: "400 10px 'IBM Plex Mono'", color: '#8A8478' }}>{v.kind}</div>
      <div style={{ font: "600 13px 'Public Sans'", color: '#211F1B', marginTop: 3 }}>
        {v.title}
      </div>
      <div
        style={{
          font: "400 11px/1.45 'Public Sans'",
          color: '#57534A',
          margin: '6px 0 10px',
          minHeight: 30,
        }}
      >
        {v.detail}
      </div>
      <span
        style={{
          display: 'inline-block',
          font: "700 11px 'IBM Plex Mono'",
          letterSpacing: '.05em',
          color: t.fg,
          background: t.bg,
          border: `1px solid ${t.br}`,
          borderRadius: 7,
          padding: '5px 11px',
        }}
      >
        {v.verdict}
      </span>
    </div>
  );
}

/** Recovery is evaluated before the plan moves. Stagger 0 / 160 / 320ms. */
export function RecoveryEvaluation({ verdicts }: { verdicts: RecoveryVerdictVM[] }) {
  return (
    <>
      <div
        style={{
          font: "700 11px 'IBM Plex Mono'",
          letterSpacing: '.06em',
          color: '#8A8478',
          margin: '16px 0 9px',
        }}
      >
        RECOVERY EVALUATED BEFORE THE PLAN MOVED
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 10 }}>
        {verdicts.map((v, i) => (
          <RecoveryVerdict key={v.kind} v={v} delay={i * 160} />
        ))}
      </div>
    </>
  );
}
