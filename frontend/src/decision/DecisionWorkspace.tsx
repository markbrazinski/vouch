/**
 * One incoming-material decision, end to end.
 *
 * Layout, per the frozen two-column design:
 *
 *   identity row          full inner width
 *   decision spine        full inner width
 *   outcome summary       full inner width, only once it genuinely exists
 *   ┌─────────────┬────────────────────┐   ← 34% / 1fr, left column sticky
 *   │ case context│ active stage       │
 *   │ (source +   │ completed stack    │
 *   │  durable    │                    │
 *   │  facts)     │                    │
 *   └─────────────┴────────────────────┘
 *
 * Reconciliation and Consequence drop the left column entirely and take the
 * full inner width — they carry wide tabular content, and the context column
 * has nothing to add while the two independent reads are being compared.
 */

import { useState } from 'react';
import { ActivityRail } from './ActivityRail';
import { CaseContextColumn } from './CaseContextColumn';
import { DecisionSpine } from './DecisionSpine';
import { SourceDocumentViewer } from './SourceDocumentViewer';
import {
  AgentStage,
  CompletedStageStack,
  ConsequenceStage,
  DispositionStage,
  EvidenceStage,
  ReconciliationStage,
  StageCard,
} from './Stages';
import { INK, MONO, N, Pill, SANS, HAIR } from './primitives';
import type { DecisionWorkspaceVM, StageKey } from './model';
import { SEM } from '../components/tokens';

/** The disposition-tinted container for an active Disposition card. */
const DISPOSITION_ACCENT: Record<string, { bg: string; border: string }> = {
  RELEASE: { bg: '#EEF2ED', border: 'rgba(62,107,84,.28)' },
  QUARANTINE: { bg: '#FCF6F0', border: 'rgba(154,90,42,.26)' },
  INSUFFICIENT_EVIDENCE: { bg: '#F3F4F9', border: 'rgba(69,80,140,.24)' },
};

function OutcomeSummary({ vm }: { vm: DecisionWorkspaceVM['outcome'] }) {
  if (!vm.visible) return null;
  const tone = SEM[vm.tone];
  const accent = vm.tone === 'released' ? '#3E6B54' : vm.tone === 'decision' ? '#45508C' : '#9A5A2A';

  return (
    <div
      data-testid="outcome-summary"
      style={{
        // The reveal of a real outcome. `OutcomeSummary` returns null until the
        // backend has actually produced one, so mounting IS the trigger.
        animation: 'vFade .4s ease-out both',
        marginTop: 14,
        background: vm.tone === 'released' ? '#EEF2ED' : vm.tone === 'decision' ? '#EAEBF4' : '#FCF6F0',
        border: `1px solid ${tone.br}`,
        borderLeft: `5px solid ${accent}`,
        borderRadius: 13,
        padding: '15px 22px',
        display: 'flex',
        alignItems: 'center',
        gap: 20,
      }}
    >
      <div style={{ flex: 'none', maxWidth: 320 }}>
        <div style={{ font: `600 9px ${MONO}`, letterSpacing: '.1em', color: INK.label }}>
          OUTCOME
        </div>
        <div
          style={{
            font: `800 23px ${SANS}`,
            letterSpacing: '-.02em',
            color: accent,
            marginTop: 3,
          }}
        >
          {vm.headline}
        </div>
      </div>
      <div style={{ width: 1, height: 38, background: 'rgba(0,0,0,.14)', flex: 'none' }} />
      <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 3 }}>
        {vm.lines.map((line, i) => (
          <div key={i} style={{ font: `500 13px ${SANS}`, color: INK.dense }}>
            {line}
          </div>
        ))}
        {/* Secondary, and it must LOOK secondary: the deterministic reason
            above is the answer to "why", this only explains why a document
            that reads as acceptable still failed. */}
        {vm.context && (
          <div
            data-testid="outcome-context"
            style={{ font: `400 11.5px ${SANS}`, color: INK.label, marginTop: 2 }}
          >
            {vm.context}
          </div>
        )}
      </div>
      {vm.chip && (
        <Pill tone={vm.chip.tone} big style={{ flex: 'none' }}>
          {vm.chip.label}
        </Pill>
      )}
    </div>
  );
}

/**
 * The third question the terminal frame must answer: what does the operator do
 * now?
 *
 * Deliberately text-only. There is no backend action that closes a material
 * gap — the material either exists or it does not — so a button here would be
 * an affordance leading nowhere. It renders only when `nextAction` is set,
 * which happens only when an order is genuinely still blocked.
 */
function NextAction({ text }: { text: string }) {
  return (
    <div
      data-testid="next-action"
      style={{
        animation: 'vFade .4s ease-out both',
        marginTop: 10,
        background: N.card,
        border: `1px solid ${HAIR}`,
        borderLeft: '5px solid #8A8478',
        borderRadius: 13,
        padding: '12px 22px',
        display: 'flex',
        alignItems: 'baseline',
        gap: 16,
      }}
    >
      <div
        style={{
          font: `600 9px ${MONO}`,
          letterSpacing: '.1em',
          color: INK.label,
          flex: 'none',
        }}
      >
        NEXT ACTION
      </div>
      <div style={{ font: `500 13px ${SANS}`, color: INK.dense }}>{text}</div>
    </div>
  );
}

/**
 * A technical failure. Deliberately NOT a red error banner and deliberately
 * not a disposition: nothing about the material was decided, and the UI must
 * say exactly that much and no more.
 */
function FailureNotice({ vm }: { vm: NonNullable<DecisionWorkspaceVM['failure']> }) {
  const technical = vm.kind === 'TECHNICAL_FAILURE' || vm.kind === 'CONFLICT_STALE';
  return (
    <div
      data-testid="failure-notice"
      data-failure-kind={vm.kind}
      style={{
        animation: 'vFade .4s ease-out both',
        marginTop: 14,
        background: technical ? N.fill : '#F3F4F9',
        border: `1px solid ${technical ? 'rgba(0,0,0,.14)' : 'rgba(69,80,140,.24)'}`,
        borderLeft: `5px solid ${technical ? '#8A8478' : '#45508C'}`,
        borderRadius: 13,
        padding: '15px 22px',
      }}
    >
      <div style={{ font: `600 9px ${MONO}`, letterSpacing: '.1em', color: INK.label }}>
        {technical ? 'SERVICE' : 'OUTCOME'}
      </div>
      <div
        style={{
          font: `800 19px ${SANS}`,
          letterSpacing: '-.01em',
          color: technical ? INK.muted : '#2D3563',
          marginTop: 3,
        }}
      >
        {vm.headline}
      </div>
      <div style={{ font: `400 13px/1.5 ${SANS}`, color: INK.prose, marginTop: 6, maxWidth: 720 }}>
        {vm.detail}
      </div>
    </div>
  );
}

export function DecisionWorkspace({ vm }: { vm: DecisionWorkspaceVM }) {
  const [viewing, setViewing] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const selectedId = selected ?? vm.selectedArtifactId ?? vm.sources[0]?.artifactId ?? null;
  const viewingArtifact = vm.sources.find((s) => s.artifactId === viewing) ?? null;

  // The reported count, not the itemized length — see SourceArtifactVM.claimCount.
  const claimCount = vm.sources.reduce((n, s) => n + s.claimCount, 0);

  /**
   * The document the header offers while the frame is full-bleed.
   *
   * The same artifact the column would have shown, and only when it can
   * actually be opened — an affordance that leads to "source unavailable" is
   * worse than none. A quarantined artifact is excluded for the same reason the
   * column never previews one: its bytes were excluded from the decision.
   */
  const headerSource =
    vm.sources.find((s) => s.artifactId === selectedId && s.openable) ??
    vm.sources.find((s) => s.openable && s.securityState !== 'quarantined') ??
    null;

  const renderStage = (key: StageKey) => {
    switch (key) {
      case 'evidence':
        return (
          <EvidenceStage
            sources={vm.sources}
            claimCount={claimCount}
            onOpenSource={setViewing}
          />
        );
      case 'investigator':
        return vm.investigator ? <AgentStage vm={vm.investigator} /> : null;
      case 'verifier':
        return vm.verifier ? <AgentStage vm={vm.verifier} /> : null;
      case 'reconciliation':
        return vm.reconciliation ? <ReconciliationStage vm={vm.reconciliation} /> : null;
      case 'disposition':
        return vm.disposition ? <DispositionStage vm={vm.disposition} /> : null;
      case 'consequence':
        return vm.consequence ? <ConsequenceStage vm={vm.consequence} /> : null;
      default:
        return null;
    }
  };

  // A stage whose body is null gets no card. `renderStage` already refuses to
  // invent content it does not have, but the StageCard chrome around it does
  // not know that — so a security halt rendered an empty "Disposition —
  // deterministic, computed from established truth" panel over nothing. That is
  // the placeholder integration-contract invariant 6 forbids.
  const active = vm.activeStage && renderStage(vm.activeStage) ? vm.activeStage : null;
  const accent =
    active === 'disposition' && vm.disposition
      ? DISPOSITION_ACCENT[vm.disposition.disposition]
      : active === 'reconciliation' && vm.reconciliation
        ? vm.reconciliation.state === 'MATERIAL_DISAGREEMENT'
          ? { bg: '#EFF0F6', border: 'rgba(69,80,140,.26)' }
          : { bg: '#EEF2ED', border: 'rgba(62,107,84,.3)' }
        : undefined;

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      <div style={{ flex: 1, minWidth: 0, overflowY: 'auto' }}>
        <div style={{ padding: '18px 26px 50px' }}>
          {/* identity row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span
              style={{
                font: `700 25px ${MONO}`,
                color: INK.primary,
                letterSpacing: '-.01em',
              }}
            >
              {vm.lotId}
            </span>
            {vm.material && (
              <span style={{ font: `400 15px ${MONO}`, color: INK.muted }}>{vm.material}</span>
            )}
            {/* No disposition pill at all while a technical failure stands. */}
            {vm.dispositionLabel ? (
              <Pill tone={vm.dispositionTone} big>
                {vm.dispositionLabel}
              </Pill>
            ) : vm.running ? (
              <Pill tone="progress" big>
                EVALUATING
              </Pill>
            ) : null}
            <div style={{ flex: 1 }} />
            {/* The way back to the evidence when the frame belongs to the
                consequence.
                
                The source column is deliberately absent on the full-bleed
                consequence — what changed for the factory owns that frame — but
                a settled decision must still let an auditor reach the document
                it was decided from. This is that route, and it opens the SAME
                viewer the column's "Open source" opens. It appears only when
                the column is not already offering one, so there are never two
                controls for one job. */}
            {vm.fullBleed && headerSource && (
              <button
                type="button"
                data-testid="header-open-source"
                onClick={() => setViewing(headerSource.artifactId)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  background: N.card,
                  border: `1px solid ${HAIR}`,
                  borderRadius: 7,
                  padding: '5px 10px',
                  cursor: 'pointer',
                  font: `600 10.5px ${MONO}`,
                  color: INK.button,
                }}
              >
                <span aria-hidden>▤</span>
                View {headerSource.documentType?.toUpperCase() || 'source'}
              </button>
            )}
            {!vm.durable && (
              <Pill tone="atrisk">NON-DURABLE BACKEND</Pill>
            )}
            <div
              style={{
                font: `400 11px ${MONO}`,
                color: INK.label,
                textAlign: 'right',
              }}
            >
              {vm.receiptMeta}
            </div>
          </div>

          <DecisionSpine nodes={vm.spine} />

          {vm.failure && vm.failure.suppressesDisposition ? (
            <FailureNotice vm={vm.failure} />
          ) : (
            <>
              <OutcomeSummary vm={vm.outcome} />
              {vm.outcome.visible && vm.outcome.nextAction && (
                <NextAction text={vm.outcome.nextAction} />
              )}
            </>
          )}

          {vm.fullBleed ? (
            <div style={{ marginTop: 14 }}>
              {active && (
                <StageCard
                  stageKey={active}
                  active
                  accentBg={accent?.bg}
                  accentBorder={accent?.border}
                >
                  {renderStage(active)}
                </StageCard>
              )}
              <CompletedStageStack stages={vm.completed} renderDetail={renderStage} />
            </div>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '34% 1fr',
                gap: 20,
                marginTop: 14,
                alignItems: 'start',
              }}
            >
              <CaseContextColumn
                sources={vm.sources}
                selectedId={selectedId}
                decisionRecordId={vm.decisionRecordId}
                truth={vm.truth}
                pending={vm.sourcesPending}
                onSelect={setSelected}
                onOpenSource={setViewing}
              />
              <div style={{ minWidth: 0 }}>
                {active ? (
                  <StageCard
                    stageKey={active}
                    active
                    accentBg={accent?.bg}
                    accentBorder={accent?.border}
                    runNumber={
                      active === 'investigator'
                        ? vm.investigator?.runNumber
                        : active === 'verifier'
                          ? vm.verifier?.runNumber
                          : undefined
                    }
                  >
                    {renderStage(active)}
                  </StageCard>
                ) : (
                  <div
                    style={{
                      marginTop: 12,
                      border: `1px solid ${HAIR}`,
                      borderRadius: 13,
                      background: N.card,
                      padding: '22px 20px',
                      font: `400 12px ${MONO}`,
                      color: INK.placeholder,
                    }}
                  >
                    {vm.running
                      ? 'Waiting for the first lifecycle event…'
                      : vm.failure?.kind === 'SECURITY_HOLD' ||
                          vm.spine.some((n) => n.state === 'halted')
                        ? 'No stage ran. The document was withheld before the agents started.'
                        : 'No stage yet.'}
                  </div>
                )}
                <CompletedStageStack stages={vm.completed} renderDetail={renderStage} />
              </div>
            </div>
          )}
        </div>
      </div>

      <ActivityRail events={vm.activity} live={vm.running} />

      {viewingArtifact && (
        <SourceDocumentViewer
          artifact={viewingArtifact}
          decisionRecordId={vm.decisionRecordId}
          onClose={() => setViewing(null)}
        />
      )}
    </div>
  );
}
