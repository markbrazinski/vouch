export function IncomingStatusRail({
  arrived,
  needDecision,
  inProgress,
  completed,
}: {
  arrived: number;
  needDecision: number;
  inProgress: number;
  completed: number;
}) {
  const divider = (
    <div style={{ width: 1, height: 30, background: 'rgba(0,0,0,.12)', margin: '0 22px' }} />
  );
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        background: '#F6F3EC',
        border: '1px solid rgba(0,0,0,.1)',
        borderRadius: 12,
        padding: '14px 22px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 9 }}>
        <span
          style={{
            font: "800 30px 'Public Sans'",
            color: '#211F1B',
            letterSpacing: '-.02em',
            lineHeight: 1,
          }}
        >
          {arrived}
        </span>
        <span style={{ font: "500 12.5px 'Public Sans'", color: '#6B655B' }}>arrived today</span>
      </div>
      {divider}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 9 }}>
        <span
          style={{
            font: "800 30px 'Public Sans'",
            color: '#45508C',
            letterSpacing: '-.02em',
            lineHeight: 1,
          }}
        >
          {needDecision}
        </span>
        <span style={{ font: "700 12.5px 'Public Sans'", color: '#45508C' }}>
          need a Quality decision
        </span>
      </div>
      {divider}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ font: "700 17px 'Public Sans'", color: '#6E685C', lineHeight: 1 }}>
          {inProgress}
        </span>
        <span style={{ font: "400 12px 'Public Sans'", color: '#8A8478' }}>in progress</span>
      </div>
      {divider}
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ font: "700 17px 'Public Sans'", color: '#3E6B54', lineHeight: 1 }}>
          {completed}
        </span>
        <span style={{ font: "400 12px 'Public Sans'", color: '#8A8478' }}>completed by Vouch</span>
      </div>
      <div
        style={{
          marginLeft: 'auto',
          font: "400 11px 'IBM Plex Mono'",
          color: '#9A9384',
          display: 'flex',
          alignItems: 'center',
          gap: 7,
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 6,
            height: 6,
            borderRadius: '50%',
            background: '#7C776B',
            display: 'inline-block',
            animation: 'vp 1.6s ease-in-out infinite',
          }}
        />
        live
      </div>
    </div>
  );
}
