import { useEffect, useRef } from 'react';
import type { Command, DecisionRow, ResumeStep } from '../../view-models/types';
import { StatusPill } from '../../components/StatusPill';

function Card({
  label,
  labelColor,
  children,
  bg,
  border,
}: {
  label: string;
  labelColor: string;
  children: React.ReactNode;
  bg: string;
  border: string;
}) {
  return (
    <div
      style={{
        background: bg,
        border: `1px solid ${border}`,
        borderRadius: 10,
        padding: '13px 15px',
      }}
    >
      <div style={{ font: "600 10px 'IBM Plex Mono'", letterSpacing: '.09em', color: labelColor }}>
        {label}
      </div>
      {children}
    </div>
  );
}

function BoundedAction({
  label,
  sub,
  primary,
  onClick,
}: {
  label: string;
  sub: string;
  primary?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        textAlign: 'left',
        padding: '13px 16px',
        background: primary ? '#211F1B' : '#F6F3EC',
        border: primary ? 'none' : '1px solid rgba(0,0,0,.14)',
        borderRadius: 10,
        cursor: 'pointer',
        width: '100%',
      }}
    >
      <div style={{ font: "700 13.5px 'Public Sans'", color: primary ? '#F6F3EC' : '#211F1B' }}>
        {label}
      </div>
      <div
        style={{
          font: "400 11.5px/1.4 'Public Sans'",
          color: primary ? 'rgba(246,243,236,.72)' : '#6B655B',
          marginTop: 3,
        }}
      >
        {sub}
      </div>
    </button>
  );
}

export function QualityDecisionDrawer({
  row,
  resolved,
  resumeSteps,
  dispatch,
}: {
  row: DecisionRow;
  resolved: boolean;
  resumeSteps: ResumeStep[];
  dispatch: (cmd: Command) => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  const close = () => dispatch({ type: 'CLOSE_DRAWER' });

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') dispatch({ type: 'CLOSE_DRAWER' });
    };
    document.addEventListener('keydown', onKey);
    panelRef.current?.focus();
    return () => document.removeEventListener('keydown', onKey);
  }, [dispatch]);

  return (
    <>
      <div
        onClick={close}
        style={{ position: 'absolute', inset: 0, background: 'rgba(33,31,27,.28)', zIndex: 50 }}
      />
      <aside
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={`Quality decision · ${row.lotId}`}
        tabIndex={-1}
        style={{
          position: 'absolute',
          top: 0,
          right: 0,
          bottom: 0,
          width: 494,
          maxWidth: '100%',
          background: '#F0EDE6',
          borderLeft: '1px solid rgba(0,0,0,.14)',
          boxShadow: '-14px 0 40px rgba(33,31,27,.16)',
          zIndex: 51,
          display: 'flex',
          flexDirection: 'column',
          animation: 'vDraw .34s cubic-bezier(.2,.7,.2,1) both',
          outline: 'none',
        }}
      >
        <div
          style={{
            flex: 'none',
            padding: '18px 22px',
            borderBottom: '1px solid rgba(0,0,0,.1)',
            display: 'flex',
            alignItems: 'flex-start',
            gap: 12,
          }}
        >
          <div style={{ flex: 1 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 11 }}>
              <span style={{ font: "700 19px 'IBM Plex Mono'", color: '#211F1B' }}>
                {row.lotId}
              </span>
              <span style={{ font: "400 13px 'IBM Plex Mono'", color: '#6B655B' }}>
                {row.material}
              </span>
            </div>
            <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 9 }}>
              {resolved ? (
                <span
                  style={{
                    display: 'inline-block',
                    font: "700 10px 'IBM Plex Mono'",
                    letterSpacing: '.05em',
                    color: '#fff',
                    background: '#3E6B54',
                    border: '1px solid #3E6B54',
                    borderRadius: 6,
                    padding: '3px 8px',
                  }}
                >
                  RELEASED
                </span>
              ) : (
                <StatusPill tone={row.tone} label={row.disposition} />
              )}
              {resolved && (
                <span style={{ font: "400 11px 'IBM Plex Mono'", color: '#33594E' }}>
                  Release verified
                </span>
              )}
            </div>
          </div>
          <button
            onClick={close}
            aria-label="Close"
            style={{
              flex: 'none',
              width: 30,
              height: 30,
              border: '1px solid rgba(0,0,0,.14)',
              background: '#F6F3EC',
              borderRadius: 8,
              font: "400 15px 'IBM Plex Mono'",
              color: '#6B655B',
              cursor: 'pointer',
            }}
          >
            ✕
          </button>
        </div>

        <div className="vh" style={{ flex: 1, overflowY: 'auto', padding: '20px 22px' }}>
          {!resolved && (
            <>
              <div
                style={{
                  background: '#EAEBF4',
                  border: '1px solid rgba(69,80,140,.28)',
                  borderRadius: 11,
                  padding: '15px 17px',
                }}
              >
                <div
                  style={{
                    font: "600 10px 'IBM Plex Mono'",
                    letterSpacing: '.1em',
                    color: '#45508C',
                  }}
                >
                  UNRESOLVED
                </div>
                <div
                  style={{ font: "600 16px/1.45 'Public Sans'", color: '#2D3563', marginTop: 7 }}
                >
                  {row.question}
                </div>
              </div>

              <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
                <Card
                  label="GOVERNING BASIS"
                  labelColor="#8A8478"
                  bg="#F6F3EC"
                  border="rgba(0,0,0,.1)"
                >
                  <div style={{ font: "700 13px 'Public Sans'", color: '#211F1B', marginTop: 5 }}>
                    {row.governingBasis.label}
                  </div>
                  <div
                    style={{ font: "400 12px/1.5 'Public Sans'", color: '#57534A', marginTop: 4 }}
                  >
                    {row.governingBasis.body}
                  </div>
                </Card>
                <Card
                  label="SUPPLIED EVIDENCE"
                  labelColor="#8A8478"
                  bg="#F6F3EC"
                  border="rgba(0,0,0,.1)"
                >
                  <div style={{ font: "700 13px 'Public Sans'", color: '#211F1B', marginTop: 5 }}>
                    {row.suppliedEvidence.label}
                  </div>
                  <div
                    style={{ font: "400 12px/1.5 'Public Sans'", color: '#57534A', marginTop: 4 }}
                  >
                    {row.suppliedEvidence.body}
                  </div>
                </Card>
                <Card
                  label="THE GAP"
                  labelColor="#45508C"
                  bg="#EFEAF0"
                  border="rgba(69,80,140,.24)"
                >
                  <div
                    style={{ font: "400 12.5px/1.5 'Public Sans'", color: '#3F4570', marginTop: 5 }}
                  >
                    {row.gap}
                  </div>
                </Card>
              </div>

              <div
                style={{
                  marginTop: 12,
                  background: '#FBF8EF',
                  border: '1px solid rgba(181,133,42,.3)',
                  borderRadius: 10,
                  padding: '12px 15px',
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                }}
              >
                <span
                  style={{
                    font: "700 10px 'IBM Plex Mono'",
                    letterSpacing: '.05em',
                    color: '#8a6318',
                    background: '#F5EED9',
                    border: '1px solid rgba(181,133,42,.36)',
                    borderRadius: 6,
                    padding: '4px 8px',
                  }}
                >
                  {row.consequence.tag}
                </span>
                <div style={{ font: "400 12px/1.45 'Public Sans'", color: '#5c4a20' }}>
                  {row.consequence.line}
                </div>
              </div>

              <h3
                style={{ font: "800 13px 'Public Sans'", color: '#211F1B', margin: '20px 0 10px' }}
              >
                What you can do
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 9 }}>
                {/* The human provides evidence and accountable authority. Vouch reassesses. */}
                <BoundedAction
                  primary
                  label={row.primaryAction.label}
                  sub={row.primaryAction.sub}
                  onClick={() =>
                    dispatch({
                      type: 'PROVIDE_EVIDENCE',
                      lotId: row.lotId,
                      authority: 'D. Karlsson · Quality manager',
                    })
                  }
                />
                <BoundedAction
                  label="Request the governing result"
                  sub="Ask the supplier for the required method. Lot stays held until it arrives."
                />
                <BoundedAction
                  label="Keep quarantined"
                  sub="Hold the lot as Quarantined until evidence changes. Reversible."
                />
              </div>
              <div style={{ marginTop: 14 }}>
                <button
                  onClick={() => dispatch({ type: 'NAVIGATE', screen: 'record' })}
                  style={{
                    font: "600 12px 'Public Sans'",
                    color: '#4A463E',
                    cursor: 'pointer',
                    background: 'none',
                    border: 'none',
                    padding: 0,
                    textDecoration: 'underline',
                    textUnderlineOffset: 2,
                  }}
                >
                  Open full decision record →
                </button>
              </div>
            </>
          )}

          {resolved && (
            <>
              <div
                style={{
                  background: '#EEF2ED',
                  border: '1px solid rgba(62,107,84,.3)',
                  borderRadius: 11,
                  padding: '16px 18px',
                  animation: 'vFade .3s ease-out both',
                }}
              >
                <span
                  style={{
                    font: "700 11px 'IBM Plex Mono'",
                    letterSpacing: '.06em',
                    color: '#fff',
                    background: '#3E6B54',
                    borderRadius: 6,
                    padding: '5px 12px',
                  }}
                >
                  RELEASED
                </span>
                <div
                  style={{ font: "400 12.5px/1.55 'Public Sans'", color: '#33594E', marginTop: 11 }}
                >
                  Approved equivalence evidence was attached to this record. Vouch reassessed on the
                  resolved basis and independent verification confirmed it.
                </div>
              </div>

              <div style={{ position: 'relative', paddingLeft: 32, marginTop: 18 }}>
                <div
                  aria-hidden="true"
                  style={{
                    position: 'absolute',
                    left: 10,
                    top: 6,
                    bottom: 6,
                    width: 2,
                    background: 'rgba(62,107,84,.28)',
                  }}
                />
                <ol
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    gap: 11,
                    margin: 0,
                    padding: 0,
                    listStyle: 'none',
                  }}
                >
                  {resumeSteps.map((r, i) => (
                    <li
                      key={r.head}
                      style={{
                        position: 'relative',
                        animation: `vFade .3s ease-out ${i * 140}ms both`,
                      }}
                    >
                      <div
                        aria-hidden="true"
                        style={{
                          position: 'absolute',
                          left: -32,
                          top: 11,
                          width: 22,
                          height: 22,
                          borderRadius: '50%',
                          background: '#3E6B54',
                          color: '#fff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          font: "700 10px 'IBM Plex Mono'",
                          boxShadow: '0 0 0 4px #F0EDE6',
                        }}
                      >
                        {i + 1}
                      </div>
                      <div
                        style={{
                          background: '#F6F3EC',
                          border: '1px solid rgba(0,0,0,.1)',
                          borderRadius: 10,
                          padding: '11px 14px',
                        }}
                      >
                        <div style={{ font: "700 13px 'Public Sans'", color: '#211F1B' }}>
                          {r.head}
                        </div>
                        <div
                          style={{
                            font: "400 12px/1.5 'Public Sans'",
                            color: '#413D35',
                            marginTop: 3,
                          }}
                        >
                          {r.body}
                        </div>
                      </div>
                    </li>
                  ))}
                </ol>
              </div>

              <div
                style={{
                  marginTop: 16,
                  background: '#EEF2ED',
                  border: '1px solid rgba(62,107,84,.3)',
                  borderRadius: 10,
                  padding: '13px 16px',
                }}
              >
                <div
                  style={{
                    font: "700 10px 'IBM Plex Mono'",
                    letterSpacing: '.05em',
                    color: '#33594E',
                  }}
                >
                  READINESS UPDATED IN PLACE
                </div>
                <div style={{ font: "600 13px 'Public Sans'", color: '#33594E', marginTop: 5 }}>
                  {row.order} — AT RISK → READY. Coverage restored.
                </div>
              </div>

              <button
                onClick={() => dispatch({ type: 'NAVIGATE', screen: 'today' })}
                style={{
                  marginTop: 14,
                  padding: '10px 16px',
                  background: '#211F1B',
                  border: 'none',
                  borderRadius: 9,
                  font: "700 12.5px 'Public Sans'",
                  color: '#F6F3EC',
                  cursor: 'pointer',
                }}
              >
                View in Today
              </button>
            </>
          )}
        </div>
      </aside>
    </>
  );
}
