/**
 * The stage cards for the active work column.
 *
 * One stage owns the slot at a time. Completed stages collapse into reopenable
 * summary rows below it. The card chrome carries the state: an active card is
 * lighter, bordered darker and lifted; a collapsed card recedes to the rail's
 * own tone so the eye goes to the live one.
 */

import { useState, type ReactNode } from 'react';
import { Dot, Eyebrow, INK, MONO, N, Pill, SANS, HAIR, STAGE_DOT } from './primitives';
import type {
  AgentStageVM,
  CompletedStageVM,
  ConsequenceVM,
  DispositionVM,
  IdentityBindingPanelVM,
  QualityAuthorityPanelVM,
  QualityAuthorityRecordVM,
  ReconciliationVM,
  SourceArtifactVM,
  StageKey,
} from './model';

const SUBTITLE: Record<StageKey, string> = {
  evidence: 'what entered — is it safe to reason from?',
  investigator: 'determining what governs & applies',
  verifier: 'independent reconstruction',
  reconciliation: 'do the two independent results agree?',
  disposition: 'deterministic — computed from established truth',
  consequence: 'what changed for the factory',
};

const TITLE: Record<StageKey, string> = {
  evidence: 'Evidence',
  investigator: 'Applicability Investigator',
  verifier: 'Independent Verifier',
  reconciliation: 'Reconciliation',
  disposition: 'Disposition',
  consequence: 'Consequence',
};

export function StageCard({
  stageKey,
  active,
  children,
  accentBg,
  accentBorder,
  runNumber,
}: {
  stageKey: StageKey;
  active: boolean;
  children: ReactNode;
  accentBg?: string;
  accentBorder?: string;
  runNumber?: number;
}) {
  return (
    <div style={{ marginTop: 12 }}>
      {runNumber && runNumber > 1 && (
        <div
          style={{
            font: `700 9px ${MONO}`,
            letterSpacing: '.12em',
            color: INK.label,
            margin: '8px 0 6px',
            paddingLeft: 3,
          }}
        >
          RUN {runNumber}
        </div>
      )}
      <div
        // Keyed on the stage so React REMOUNTS when the active stage changes.
        // That remount is what re-runs `vFade` — the animation therefore fires
        // on a real projection change and not on the 900ms poll that leaves the
        // stage where it was.
        key={stageKey}
        data-testid={`stage-${stageKey}`}
        data-active={active}
        style={{
          border: `1px solid ${active ? accentBorder ?? 'rgba(0,0,0,.16)' : 'rgba(0,0,0,.08)'}`,
          borderRadius: 13,
          background: active ? accentBg ?? N.card : N.recessed,
          overflow: 'hidden',
          boxShadow: active ? '0 1px 6px rgba(33,31,27,.05)' : undefined,
          animation: active ? 'vFade .34s ease-out both' : undefined,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 11,
            padding: active ? '15px 20px' : '11px 18px',
          }}
        >
          <Dot color={STAGE_DOT[stageKey]} />
          <div style={{ font: `800 ${active ? 15 : 13}px ${SANS}`, color: INK.primary }}>
            {TITLE[stageKey]}
          </div>
          {active && (
            <div style={{ font: `400 11px ${MONO}`, color: INK.label }}>{SUBTITLE[stageKey]}</div>
          )}
          <div style={{ flex: 1 }} />
        </div>
        <div style={{ padding: '0 20px 18px' }}>{children}</div>
      </div>
    </div>
  );
}

function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div style={{ font: `600 9.5px ${MONO}`, letterSpacing: '.08em', color: INK.label }}>
      {children}
    </div>
  );
}

function TrustRow({ k, v, color }: { k: string; v: string; color: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
      <Dot color={color} round />
      <span style={{ font: `500 11.5px ${SANS}`, color: INK.dense, flex: 1 }}>{k}</span>
      <span style={{ font: `600 10.5px ${MONO}`, color }}>{v}</span>
    </div>
  );
}

export function EvidenceStage({
  sources,
  claimCount,
  onOpenSource,
}: {
  sources: SourceArtifactVM[];
  claimCount: number;
  onOpenSource: (id: string) => void;
}) {
  const quarantined = sources.some((s) => s.securityState === 'quarantined');
  // Sponsor depth §6. A document can be readable enough to yield measurements
  // and still not readable enough to bind a lot id. That is a security state,
  // not a quality one, and it is the reason the Identity row below is read from
  // the artifact rather than asserted.
  const identityUntrusted = sources.some((s) => s.extraction?.identityTrusted === false);
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
      <div>
        <SectionLabel>ARTIFACTS</SectionLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginTop: 9 }}>
          {sources.length === 0 && (
            <div style={{ font: `400 11px ${MONO}`, color: INK.placeholder }}>
              Awaiting the first artifact.
            </div>
          )}
          {sources.map((s) => {
            const hostile = s.securityState === 'quarantined';
            return (
              <div
                key={s.artifactId}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 13,
                  background: N.nested,
                  border: `1px solid ${hostile ? 'rgba(154,90,42,.4)' : HAIR}`,
                  borderRadius: 9,
                  padding: '12px 15px',
                }}
              >
                <span style={{ font: `400 16px ${MONO}`, color: hostile ? '#9A5A2A' : INK.placeholder }}>
                  {hostile ? '⚠' : '▤'}
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ font: `600 13px ${SANS}`, color: INK.primary }}>{s.displayName}</div>
                  <div style={{ font: `400 10.5px ${MONO}`, color: INK.label }}>
                    {[s.documentType, s.hashSummary && `hash ${s.hashSummary}`]
                      .filter(Boolean)
                      .join(' · ')}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onOpenSource(s.artifactId)}
                  disabled={!s.openable}
                  style={{
                    font: `600 10px ${MONO}`,
                    color: s.openable ? INK.button : INK.placeholder,
                    background: N.chip,
                    border: '1px solid rgba(0,0,0,.14)',
                    borderRadius: 7,
                    padding: '5px 10px',
                    cursor: s.openable ? 'pointer' : 'not-allowed',
                    whiteSpace: 'nowrap',
                  }}
                >
                  View source
                </button>
                <Pill tone={hostile ? 'quarantine' : 'released'}>
                  {hostile ? '⊘ QUARANTINED' : 'CLEARED'}
                </Pill>
              </div>
            );
          })}
        </div>
      </div>

      <div>
        <SectionLabel>TRUST &amp; PROVENANCE</SectionLabel>
        <div
          style={{
            background: N.nested,
            border: `1px solid ${HAIR}`,
            borderRadius: 9,
            padding: '12px 15px',
            display: 'flex',
            flexDirection: 'column',
            gap: 9,
            marginTop: 9,
          }}
        >
          <TrustRow k="Supplier evidence" v="Untrusted" color="#9A5A2A" />
          <TrustRow k="Integrity" v="Versioned · hash-bound" color={INK.muted} />
          {/* Read, never asserted. Hard-coding "Bound to lot" would claim the
              evidence was tied to this lot even when the reading was too poor
              to establish an identity at all. */}
          <TrustRow
            k="Identity"
            v={identityUntrusted ? 'Not established' : 'Bound to lot'}
            color={identityUntrusted ? '#9A5A2A' : INK.muted}
          />
          <TrustRow
            k="Security inspection"
            v={quarantined ? 'Quarantined' : 'Passed'}
            color={quarantined ? '#9A5A2A' : '#3E6B54'}
          />
          <div
            style={{
              borderTop: `1px solid rgba(0,0,0,.08)`,
              paddingTop: 9,
              font: `400 10.5px ${MONO}`,
              color: INK.label,
            }}
          >
            {claimCount} claim{claimCount === 1 ? '' : 's'} frozen into the snapshot
          </div>
        </div>

        {/* The one genuinely new sponsor-depth state. The document is readable,
            the measurements may be real, but nothing ties them to this lot — so
            they bind to nothing and the case routes to a human. This is a valid
            evidence outcome, not a crash, and it deliberately does NOT claim a
            disposition or imply the agents consumed the unbound values. */}
        {identityUntrusted && (
          <div
            data-testid="identity-untrusted"
            style={{
              marginTop: 10,
              background: '#F6EEE6',
              border: '1px solid rgba(154,90,42,.4)',
              borderLeft: '4px solid #9A5A2A',
              borderRadius: 9,
              padding: '12px 15px',
            }}
          >
            <div style={{ font: `700 10px ${MONO}`, letterSpacing: '.06em', color: '#9A5A2A' }}>
              IDENTITY NOT ESTABLISHED
            </div>
            <div style={{ font: `400 12px/1.5 ${SANS}`, color: '#5C4326', marginTop: 5 }}>
              This document was readable enough to recover measurements, but not readable enough to
              establish which lot they belong to. The values are held unbound — no lot was decided
              from them, and nothing was changed.
            </div>
            <div style={{ font: `400 10.5px ${MONO}`, color: '#7A5B39', marginTop: 6 }}>
              Routed to Quality for identification.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function AgentStage({ vm }: { vm: AgentStageVM }) {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '1.15fr 1fr',
        gap: 18,
        position: 'relative',
      }}
    >
      {/* The independence rail. Structural, not decorative: the Verifier is a
          separate invocation that never receives the Investigator's output. */}
      {vm.isIndependent && (
        <div
          aria-hidden
          style={{
            position: 'absolute',
            left: -14,
            top: 2,
            bottom: 2,
            width: 3,
            background: INK.primary,
            borderRadius: 3,
          }}
        />
      )}
      <div>
        <SectionLabel>
          {vm.isIndependent ? 'RECONSTRUCTED FROM' : 'RECORDS CONSULTED'}
        </SectionLabel>
        <div style={{ marginTop: 6 }}>
          {vm.recordsConsulted.length === 0 && (
            <div style={{ font: `400 11px ${MONO}`, color: INK.placeholder, paddingTop: 6 }}>
              Consulting authoritative records…
            </div>
          )}
          {vm.recordsConsulted.map((r, i) => (
            <div
              key={`${r.label}-${i}`}
              style={{
                display: 'flex',
                alignItems: 'baseline',
                gap: 10,
                padding: '8px 0',
                borderBottom: `1px solid rgba(0,0,0,.06)`,
              }}
            >
              <span style={{ font: `700 11px ${MONO}`, color: '#3E6B54', flex: 'none' }}>✓</span>
              <div style={{ font: `400 12px ${SANS}`, color: INK.dense, flex: 1 }}>{r.label}</div>
              <div style={{ font: `600 11px ${MONO}`, color: INK.muted }}>{r.value}</div>
            </div>
          ))}
        </div>
        {vm.isIndependent && (
          <div style={{ font: `400 10.5px/1.45 ${SANS}`, color: INK.label, marginTop: 10 }}>
            The Investigator's output was not provided to this agent.
          </div>
        )}
      </div>

      <div>
        <SectionLabel>{vm.isIndependent ? 'INDEPENDENT RESULT' : 'APPLICABILITY'}</SectionLabel>
        <div
          style={{
            background: N.nested,
            border: `1px solid ${HAIR}`,
            borderRadius: 11,
            padding: '13px 15px',
            marginTop: 6,
          }}
        >
          <div style={{ font: `800 15px ${SANS}`, color: INK.primary }}>{vm.resultTitle}</div>
          <div style={{ font: `400 12px/1.5 ${SANS}`, color: INK.prose, marginTop: 6 }}>
            {vm.resultBody}
          </div>
          {vm.modelId && (
            <div style={{ font: `400 9.5px ${MONO}`, color: INK.label, marginTop: 8 }}>
              {vm.modelId}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export function ReconciliationStage({ vm }: { vm: ReconciliationVM }) {
  const match = vm.state === 'MATCH' || vm.state === 'NON_MATERIAL_DIFFERENCE';
  return (
    <div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1.4fr 1fr 1fr 26px',
          gap: 12,
          padding: '0 4px 9px',
          borderBottom: '1px solid rgba(0,0,0,.12)',
        }}
      >
        {['DIMENSION', 'INVESTIGATOR', 'VERIFIER', ''].map((h) => (
          <div key={h} style={{ font: `600 9.5px ${MONO}`, letterSpacing: '.06em', color: INK.label }}>
            {h}
          </div>
        ))}
      </div>
      {vm.dimensions.map((d) => (
        <div
          key={d.dimension}
          style={{
            display: 'grid',
            gridTemplateColumns: '1.4fr 1fr 1fr 26px',
            gap: 12,
            padding: '11px 4px',
            borderBottom: '1px solid rgba(0,0,0,.06)',
            alignItems: 'center',
            background: d.agrees ? 'transparent' : '#EAEBF4',
          }}
        >
          <div style={{ font: `400 12.5px ${SANS}`, color: INK.dense }}>{d.dimension}</div>
          <div style={{ font: `600 12px ${MONO}`, color: INK.muted }}>{d.investigatorValue}</div>
          <div style={{ font: `600 12px ${MONO}`, color: d.agrees ? INK.muted : '#45508C' }}>
            {d.verifierValue}
          </div>
          <div style={{ font: `700 13px ${MONO}`, color: d.agrees ? '#3E6B54' : '#45508C' }}>
            {d.agrees ? '=' : '≠'}
          </div>
        </div>
      ))}
      <div style={{ marginTop: 13, display: 'flex', alignItems: 'center', gap: 12 }}>
        <span
          style={{
            font: `700 11px ${MONO}`,
            letterSpacing: '.04em',
            color: '#fff',
            background: match ? '#3E6B54' : '#45508C',
            borderRadius: 6,
            padding: '5px 13px',
          }}
        >
          {match ? '✓ INDEPENDENT MATCH' : '✕ MATERIAL DISAGREEMENT'}
        </span>
      </div>
      <div
        style={{ font: `400 12px/1.5 ${SANS}`, color: INK.prose, marginTop: 11, maxWidth: 780 }}
      >
        {vm.note}
      </div>
    </div>
  );
}

export function DispositionStage({ vm }: { vm: DispositionVM }) {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1.25fr 1fr', gap: 18 }}>
      <div>
        <SectionLabel>BASIS</SectionLabel>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexWrap: 'wrap',
            marginTop: 9,
          }}
        >
          {vm.basisChain.map((link, i) => (
            <div key={link.label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div>
                <div
                  style={{ font: `500 9px ${MONO}`, letterSpacing: '.07em', color: INK.label }}
                >
                  {link.label.toUpperCase()}
                </div>
                <div style={{ font: `700 12px ${MONO}`, color: INK.primary, marginTop: 2 }}>
                  {link.value}
                </div>
              </div>
              {i < vm.basisChain.length - 1 && (
                <span style={{ font: `600 13px ${MONO}`, color: INK.chevron }}>→</span>
              )}
            </div>
          ))}
        </div>

        {vm.qualityDecisionRequired && (
          <div style={{ marginTop: 16 }}>
            <div style={{ font: `600 10px ${MONO}`, letterSpacing: '.1em', color: '#45508C' }}>
              UNRESOLVED
            </div>
            <div style={{ font: `600 16px/1.45 ${SANS}`, color: '#2D3563', marginTop: 8 }}>
              {vm.qdrQuestion || 'Vouch could not establish an answer from this evidence.'}
            </div>
            {vm.materialDifferences.map((d) => (
              <div key={d} style={{ display: 'flex', gap: 8, marginTop: 6 }}>
                <span style={{ font: `700 11px ${MONO}`, color: '#45508C' }}>·</span>
                <span style={{ font: `400 12px ${SANS}`, color: '#3F4570' }}>{d}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <SectionLabel>STATE CHANGE</SectionLabel>
        <div style={{ marginTop: 9, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {vm.stateMutation.length === 0 && (
            <div style={{ font: `400 11px ${MONO}`, color: INK.placeholder }}>
              No state was changed.
            </div>
          )}
          {vm.stateMutation.map((m, i) => (
            <div key={`${m}-${i}`} style={{ font: `500 10.5px ${MONO}`, color: INK.dense }}>
              {m}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export function ConsequenceStage({
  vm,
  onOpenSource: _onOpenSource,
}: {
  vm: ConsequenceVM;
  onOpenSource?: (id: string) => void;
}) {
  return (
    <div>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        {vm.readinessChanges.map((c, i) => (

          <div
            key={c.orderId}
            style={{
              flex: 1,
              minWidth: 210,
              background: c.to === 'BLOCKED' ? '#FBF3F1' : '#EEF2ED',
              border: `1px solid ${c.to === 'BLOCKED' ? 'rgba(142,43,36,.28)' : 'rgba(62,107,84,.28)'}`,
              borderRadius: 10,
              padding: '13px 16px',
              // Authoritative consequence arriving. Staggered so READY→BLOCKED
              // reads as a consequence of the disposition above it, not as a
              // panel that was always there.
              animation: `vFade .34s ease-out ${i * 90}ms both`,
            }}
          >
            <div style={{ font: `600 9.5px ${MONO}`, letterSpacing: '.07em', color: INK.label }}>
              PRODUCTION READINESS
            </div>
            <div
              style={{
                font: `700 14.5px ${SANS}`,
                color: c.to === 'BLOCKED' ? '#8E2B24' : '#3E6B54',
                marginTop: 6,
              }}
            >
              {c.orderId} · {c.from} → {c.to}
            </div>
          </div>
        ))}
        {vm.metrics.map((m) => (
          <div
            key={m.label}
            style={{
              flex: 1,
              minWidth: 210,
              background: '#FCF6F0',
              border: '1px solid rgba(154,90,42,.24)',
              borderRadius: 10,
              padding: '13px 16px',
            }}
          >
            <div style={{ font: `600 9.5px ${MONO}`, letterSpacing: '.07em', color: INK.label }}>
              {m.label}
            </div>
            <div style={{ font: `700 14.5px ${SANS}`, color: '#9A5A2A', marginTop: 6 }}>
              {m.value}
            </div>
            {m.note && (
              <div style={{ font: `400 11px ${SANS}`, color: INK.label, marginTop: 2 }}>
                {m.note}
              </div>
            )}
          </div>
        ))}
      </div>

      {vm.candidates.length > 0 && (
        <>
          <div
            style={{
              font: `700 10px ${MONO}`,
              letterSpacing: '.08em',
              color: INK.label,
              margin: '18px 0 10px',
            }}
          >
            RECOVERY EVALUATED BEFORE THE PLAN MOVED
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
            {vm.candidates.map((c, i) => (
              <div
                key={c.candidateId}
                data-testid={`recovery-${c.candidateId}`}
                data-selected={c.selected ? 'true' : undefined}
                style={{
                  // Each candidate appears in the order it was evaluated. The
                  // REFUSED one additionally gets the approved single-shot
                  // emphasis: a refusal is the point of the stage, and `vPop`
                  // runs once rather than looping.
                  animation:
                    c.verdict === 'REFUSED'
                      ? `vFade .34s ease-out ${140 + i * 90}ms both, vPop .5s ease-out ${420 + i * 90}ms both`
                      : `vFade .34s ease-out ${140 + i * 90}ms both`,
                  background:
                    c.verdict === 'ELIGIBLE'
                      ? '#EEF2ED'
                      : c.verdict === 'REFUSED'
                        ? '#EFE7E4'
                        : '#FBF3F1',
                  // The selected candidate is the one that MOVED the factory.
                  // It gets a heavier border and a lift; the rejected ones stay
                  // flat, so "which one won" survives a glance at 5 metres.
                  border: c.selected
                    ? '2px solid #3E6B54'
                    : `1px solid ${
                        c.verdict === 'ELIGIBLE'
                          ? 'rgba(62,107,84,.26)'
                          : c.verdict === 'REFUSED'
                            ? 'rgba(74,32,24,.2)'
                            : 'rgba(142,43,36,.22)'
                      }`,
                  boxShadow: c.selected ? '0 3px 12px rgba(62,107,84,.22)' : undefined,
                  borderRadius: 10,
                  padding: c.selected ? '12px 14px' : '13px 15px',
                  opacity: c.selected || c.verdict === 'REFUSED' ? 1 : 0.72,
                }}
              >
                <div
                  style={{
                    font: `400 10px ${MONO}`,
                    color: INK.label,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                  }}
                >
                  {c.kind.toUpperCase()}
                  {c.selected && (
                    <span
                      style={{
                        font: `700 8.5px ${MONO}`,
                        letterSpacing: '.07em',
                        color: '#FFF',
                        background: '#3E6B54',
                        borderRadius: 4,
                        padding: '2px 6px',
                      }}
                    >
                      SELECTED
                    </span>
                  )}
                </div>
                <div style={{ font: `600 13px ${SANS}`, color: INK.primary, marginTop: 3 }}>
                  {c.title}
                </div>
                <div
                  style={{
                    font: `400 11px/1.45 ${SANS}`,
                    color: INK.prose,
                    margin: '6px 0 11px',
                    minHeight: 32,
                  }}
                >
                  {c.detail}
                </div>
                <Pill tone={c.tone} big>
                  {c.verdict === 'REFUSED' ? '✕ REFUSED' : c.verdict.replace('_', ' ')}
                </Pill>
              </div>
            ))}
          </div>
        </>
      )}

      {vm.executed && (
        <div
          style={{
            marginTop: 13,
            background: N.chip,
            border: '1px solid rgba(0,0,0,.14)',
            borderRadius: 10,
            padding: '13px 17px',
            display: 'flex',
            alignItems: 'center',
            gap: 14,
            flexWrap: 'wrap',
          }}
        >
          <span
            style={{
              font: `700 10px ${MONO}`,
              letterSpacing: '.06em',
              color: N.chip,
              background: '#3F3A32',
              borderRadius: 6,
              padding: '4px 10px',
            }}
          >
            RESEQUENCED
          </span>
          <div style={{ font: `600 13px ${SANS}`, color: INK.primary }}>
            {vm.executed.tag} — {vm.executed.line}
          </div>
        </div>
      )}
    </div>
  );
}

export function CompletedStageStack({
  stages,
  renderDetail,
}: {
  stages: CompletedStageVM[];
  renderDetail: (stageKey: StageKey) => ReactNode;
}) {
  const [open, setOpen] = useState<StageKey | null>(null);
  if (!stages.length) return null;

  return (
    <div style={{ marginTop: 14 }}>
      <Eyebrow>COMPLETED</Eyebrow>
      {stages.map((s) => {
        const isOpen = open === s.stageKey;
        return (
          <div
            key={`${s.stageKey}-${s.runNumber ?? 1}`}
            style={{
              marginTop: 8,
              border: '1px solid rgba(0,0,0,.08)',
              borderRadius: 13,
              background: N.recessed,
              overflow: 'hidden',
              // Fires when a stage first joins the completed stack — a real
              // lifecycle transition. Existing rows keep their identity through
              // the stable key, so they do not replay it.
              animation: 'vFade .3s ease-out both',
            }}
          >
            <button
              type="button"
              onClick={() => setOpen(isOpen ? null : s.stageKey)}
              data-testid={`completed-${s.stageKey}`}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 11,
                padding: '11px 18px',
                width: '100%',
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
              }}
            >
              <Dot color={STAGE_DOT[s.stageKey]} />
              <div style={{ font: `800 13px ${SANS}`, color: INK.primary }}>{s.title}</div>
              {/* A resumed decision otherwise reads as a plain release: the
                  terminal frame showed no sign a human had ever been asked.
                  Only run 2+ is marked — labelling run 1 on every ordinary
                  decision would be noise. */}
              {s.runNumber !== undefined && s.runNumber > 1 && (
                <span
                  data-testid={`completed-run-${s.stageKey}`}
                  style={{
                    font: `700 9px ${MONO}`,
                    letterSpacing: '.08em',
                    color: INK.label,
                    border: '1px solid rgba(0,0,0,.14)',
                    borderRadius: 5,
                    padding: '2px 6px',
                    whiteSpace: 'nowrap',
                  }}
                >
                  RUN {s.runNumber}
                </span>
              )}
              <div
                style={{
                  font: `400 11px ${MONO}`,
                  color: INK.label,
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {s.oneLine}
              </div>
              <Pill tone={s.pill.tone}>{s.pill.label}</Pill>
              <span
                style={{
                  font: `400 12px ${MONO}`,
                  color: INK.label,
                  width: 18,
                  textAlign: 'center',
                }}
              >
                {isOpen ? '▾' : '▸'}
              </span>
            </button>
            {isOpen && <div style={{ padding: '0 20px 18px' }}>{renderDetail(s.stageKey)}</div>}
          </div>
        );
      })}
    </div>
  );
}

/**
 * §8. The one open applicability question, and the two things a human may do
 * about it.
 *
 * Deliberately narrow. The verbs are "Authorize applicability" and "Keep held"
 * — never Approve, Deny, Release or Override — because the human is
 * establishing a missing authoritative fact, not deciding the lot. What the
 * evidence then means is still computed downstream, and the copy must not
 * suggest otherwise.
 *
 * Rendered only while the question is genuinely unanswered: the projection
 * returns null once an authority exists, so this component disappears rather
 * than going disabled.
 */
export function QualityAuthorityPanel({
  vm,
  onEstablish,
  onHold,
  submitting = false,
}: {
  vm: QualityAuthorityPanelVM;
  /** Establish ONE named measurement as controlling for this decision. */
  onEstablish?: (claimId: string) => void;
  onHold?: () => void;
  submitting?: boolean;
}) {
  return (
    <div
      data-testid="quality-authority-panel"
      style={{
        animation: 'vFade .4s ease-out both',
        marginTop: 14,
        background: '#F3F4F9',
        border: '1px solid rgba(69,80,140,.24)',
        borderRadius: 12,
        padding: '18px 20px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Dot color="#45508C" />
        <Eyebrow>Quality decision required</Eyebrow>
      </div>

      <div
        data-testid="quality-authority-question"
        style={{ font: `600 15px/1.45 ${SANS}`, color: INK.primary, marginBottom: 3 }}
      >
        {vm.question}
      </div>
      <div style={{ font: `400 12px/1.5 ${SANS}`, color: INK.prose, marginBottom: 14 }}>
        {vm.disputed}
      </div>

      {/* Side by side and equal weight. The choice is between the two
          measurements, so neither may read as the default — a single button,
          or one visually heavier than the other, decides the lot on the
          operator's behalf where the paths diverge. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
          gap: 12,
          marginBottom: 14,
        }}
      >
        {vm.options.map((o) => (
          <div
            key={o.claimId}
            data-testid={`quality-option-${o.selectedBy.toLowerCase()}`}
            style={{
              display: 'flex',
              flexDirection: 'column',
              background: N.nested,
              border: `1px solid ${HAIR}`,
              borderRadius: 9,
              padding: '13px 14px',
            }}
          >
            <div
              style={{
                font: `600 9px ${MONO}`,
                color: INK.label,
                letterSpacing: '.07em',
                marginBottom: 8,
              }}
            >
              SELECTED BY {o.agentLabel.toUpperCase()}
            </div>

            <div style={{ font: `700 20px/1.15 ${SANS}`, color: INK.primary }}>
              {o.value}
            </div>
            <div style={{ font: `400 11px ${MONO}`, color: INK.muted, marginTop: 3 }}>
              {o.methodLine}
            </div>

            <div style={{ marginTop: 8 }}>
              <span
                style={{
                  display: 'inline-block',
                  font: `600 9px ${MONO}`,
                  letterSpacing: '.06em',
                  color: INK.dense,
                  background: N.chip,
                  border: `1px solid ${HAIR}`,
                  borderRadius: 5,
                  padding: '3px 7px',
                }}
              >
                {o.routeLabel}
              </span>
            </div>

            <div
              data-testid={`quality-consequence-${o.selectedBy.toLowerCase()}`}
              style={{
                font: `400 10px/1.5 ${MONO}`,
                color: o.passes ? '#3E6B54' : '#9A5A2A',
                margin: '10px 0 12px',
              }}
            >
              {o.consequence}
            </div>

            <button
              type="button"
              data-testid={`quality-establish-${o.selectedBy.toLowerCase()}`}
              disabled={submitting}
              onClick={() => onEstablish?.(o.claimId)}
              style={{
                marginTop: 'auto',
                font: `600 11px ${MONO}`,
                color: '#FFFFFF',
                background: submitting ? '#8189B5' : '#45508C',
                border: '1px solid rgba(69,80,140,.4)',
                borderRadius: 8,
                padding: '9px 12px',
                width: '100%',
                cursor: submitting ? 'progress' : 'pointer',
              }}
            >
              {o.actionLabel}
            </button>
          </div>
        ))}
      </div>

      {/* Tertiary. Holding the lot is a legitimate answer, but it is not the
          decision being asked, so it must not compete with the two cards. */}
      <button
        type="button"
        data-testid="quality-keep-held"
        disabled={submitting}
        onClick={() => onHold?.()}
        style={{
          font: `500 10px ${MONO}`,
          color: INK.muted,
          background: 'transparent',
          border: 'none',
          borderBottom: `1px solid ${HAIR}`,
          borderRadius: 0,
          padding: '2px 0',
          cursor: submitting ? 'progress' : 'pointer',
        }}
      >
        {vm.holdActionLabel}
      </button>
    </div>
  );
}


/**
 * The identity question, as a control an operator can answer.
 *
 * The failure mode this layout exists to prevent is being read as an OCR
 * failure. So it leads with what DID work — parsed, extracted, security
 * passed — and only then shows the two identifiers side by side with nothing
 * between them. The unresolved thing is a correspondence, and the screen
 * should look like a correspondence is missing, not like a document is broken.
 */
export function IdentityBindingPanel({
  vm,
  onConfirm,
  onKeepUnbound,
  submitting = false,
}: {
  vm: IdentityBindingPanelVM;
  onConfirm?: () => void;
  onKeepUnbound?: () => void;
  submitting?: boolean;
}) {
  return (
    <div
      data-testid="identity-binding-panel"
      style={{
        animation: 'vFade .4s ease-out both',
        marginTop: 14,
        background: '#F3F4F9',
        border: '1px solid rgba(69,80,140,.24)',
        borderRadius: 12,
        padding: '18px 20px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <Dot color="#45508C" />
        <Eyebrow>Identity confirmation required</Eyebrow>
      </div>

      <div
        data-testid="identity-binding-question"
        style={{ font: `600 15px/1.45 ${SANS}`, color: INK.primary, marginBottom: 3 }}
      >
        {vm.question}
      </div>
      <div style={{ font: `400 12px/1.5 ${SANS}`, color: INK.prose, marginBottom: 14 }}>
        {vm.reason}
      </div>

      {/* What Vouch DID do. Stated, not implied — an operator must never have
          to infer "the document was readable" from the absence of an error. */}
      <div
        data-testid="identity-verified-facts"
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 8,
          marginBottom: 14,
        }}
      >
        {vm.verified.map((f) => (
          <span
            key={f.label}
            style={{
              font: `500 10px ${MONO}`,
              color: '#3E6B54',
              background: 'rgba(62,107,84,.08)',
              border: '1px solid rgba(62,107,84,.22)',
              borderRadius: 5,
              padding: '4px 8px',
            }}
          >
            {f.label}: {f.value}
          </span>
        ))}
      </div>

      {/* The unresolved pair. Equal weight, and deliberately NOT joined by an
          arrow: an arrow would draw the very correspondence the system is
          refusing to assert. */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: 12,
          marginBottom: 10,
        }}
      >
        {[
          { key: 'supplier', side: vm.supplierSide },
          { key: 'vouch', side: vm.vouchSide },
        ].map(({ key, side }) => (
          <div
            key={key}
            data-testid={`identity-side-${key}`}
            style={{
              background: N.nested,
              border: `1px solid ${HAIR}`,
              borderRadius: 9,
              padding: '13px 14px',
            }}
          >
            <div
              style={{
                font: `600 9px ${MONO}`,
                color: INK.label,
                letterSpacing: '.07em',
                marginBottom: 8,
              }}
            >
              {side.heading}
            </div>
            <div style={{ font: `700 18px/1.2 ${SANS}`, color: INK.primary }}>
              {side.identifier}
            </div>
            <div style={{ font: `400 11px ${MONO}`, color: INK.muted, marginTop: 4 }}>
              {side.detail}
            </div>
          </div>
        ))}
      </div>

      <div
        data-testid="identity-mapping-status"
        style={{
          font: `600 10px ${MONO}`,
          letterSpacing: '.06em',
          color: '#9A5A2A',
          marginBottom: 14,
        }}
      >
        {vm.mappingStatus.toUpperCase()}
      </div>

      <button
        type="button"
        data-testid="identity-confirm-binding"
        disabled={submitting}
        onClick={() => onConfirm?.()}
        style={{
          font: `600 11px ${MONO}`,
          color: '#FFFFFF',
          background: submitting ? '#8189B5' : '#45508C',
          border: '1px solid rgba(69,80,140,.4)',
          borderRadius: 8,
          padding: '10px 16px',
          cursor: submitting ? 'progress' : 'pointer',
        }}
      >
        {vm.confirmLabel}
      </button>
      <div
        style={{
          font: `400 10px/1.5 ${MONO}`,
          color: INK.muted,
          margin: '7px 0 14px',
        }}
      >
        {vm.confirmDetail}
      </div>

      {/* Tertiary. Keeping the evidence unbound is a legitimate answer, but it
          is not the one being asked for, so it must not compete. */}
      <button
        type="button"
        data-testid="identity-keep-unbound"
        disabled={submitting}
        onClick={() => onKeepUnbound?.()}
        style={{
          font: `500 10px ${MONO}`,
          color: INK.muted,
          background: 'transparent',
          border: 'none',
          borderBottom: `1px solid ${HAIR}`,
          borderRadius: 0,
          padding: '2px 0',
          cursor: submitting ? 'progress' : 'pointer',
        }}
      >
        {vm.keepUnboundLabel}
      </button>
    </div>
  );
}


/**
 * §8. The durable record of an answered question.
 *
 * This is what the action panel becomes. It never disappears again: the
 * accountable actor, the authority they acted under and what they settled are
 * part of the audit surface for the life of the record.
 */
export function QualityAuthorityStage({ vm }: { vm: QualityAuthorityRecordVM }) {
  return (
    <div
      data-testid="quality-authority-stage"
      style={{
        marginTop: 14,
        background: N.card,
        border: `1px solid ${HAIR}`,
        borderRadius: 12,
        padding: '16px 20px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          marginBottom: 10,
        }}
      >
        <Eyebrow>{vm.stageLabel}</Eyebrow>
        <Pill tone={vm.tone}>{vm.headline}</Pill>
      </div>

      <div style={{ font: `400 12px/1.55 ${SANS}`, color: INK.prose, marginBottom: 12 }}>
        {vm.question}
      </div>

      <div style={{ display: 'grid', gap: 7 }}>
        {[
          [vm.answerLabel, vm.answer],
          ['Accountable', vm.accountableActor],
          ['Authority', vm.authoritySource],
          ['Recorded', vm.clock],
          [vm.bindingLabel, vm.snapshotBinding],
        ].map(([label, value]) => (
          <div
            key={label}
            style={{ display: 'grid', gridTemplateColumns: '130px 1fr', gap: 10 }}
          >
            <span style={{ font: `400 10px ${MONO}`, color: INK.label }}>{label}</span>
            <span style={{ font: `400 12px ${SANS}`, color: INK.dense }}>{value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
