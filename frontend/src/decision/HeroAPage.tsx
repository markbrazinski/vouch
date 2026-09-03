/**
 * The Hero A entry surface.
 *
 * §9 of the gate: the real `list_decisions` path is blocked pending the admin
 * GSI/IAM step, so full Incoming is NOT built here and no fake production rows
 * are fabricated. What exists instead is the minimum honest shell needed to
 * enter a Decision Workspace, and it says plainly why the list is empty rather
 * than inventing content to fill it.
 *
 * There is deliberately no "Start Vouch" button in the production frame. A
 * decision begins because material arrived, not because someone pressed a
 * button, and a control implying otherwise would misrepresent the product. The
 * dev harness (DEV-only, excluded from the production bundle) is where a lot id
 * can be injected during development.
 */

import { useMemo, useState } from 'react';
import { DecisionWorkspace } from './DecisionWorkspace';
import { project } from './adapter';
import { useDecisionRun } from './useDecisionRun';
import { INK, MONO, N, Pill, SANS, HAIR } from './primitives';

export interface HeroAEntry {
  lotId: string;
  material?: string;
  receiptMeta?: string;
  document?: string;
  contentType?: string;
}

/**
 * Incoming, in its honest blocked state.
 *
 * This is not a placeholder standing in for a finished list — it is the
 * truthful rendering of a surface whose live endpoint returns
 * PERSISTENCE_FAILURE today.
 */
export function IncomingBlockedNotice({ detail }: { detail?: string }) {
  return (
    <div
      data-testid="incoming-blocked"
      style={{
        margin: '18px 26px',
        background: N.fill,
        border: `1px solid ${HAIR}`,
        borderLeft: '5px solid #8A8478',
        borderRadius: 13,
        padding: '15px 22px',
        maxWidth: 720,
      }}
    >
      <div style={{ font: `600 9px ${MONO}`, letterSpacing: '.1em', color: INK.label }}>
        INCOMING
      </div>
      <div style={{ font: `800 17px ${SANS}`, color: INK.muted, marginTop: 3 }}>
        Decision enumeration is not available in this environment
      </div>
      <div style={{ font: `400 12.5px/1.5 ${SANS}`, color: INK.prose, marginTop: 6 }}>
        Listing decisions needs an index on the authoritative table that has not been provisioned
        yet. Decisions themselves are unaffected — each one is durable and can be opened directly.
      </div>
      {detail && (
        <div style={{ font: `400 10.5px ${MONO}`, color: INK.label, marginTop: 8 }}>{detail}</div>
      )}
    </div>
  );
}

export function HeroAPage({ entry }: { entry: HeroAEntry }) {
  const run = useDecisionRun();
  const [started, setStarted] = useState(false);

  const vm = useMemo(
    () =>
      project({
        decisionRecordId: run.decisionRecordId,
        lotId: entry.lotId,
        material: entry.material,
        receiptMeta: entry.receiptMeta,
        events: run.events,
        result: run.result,
        sources: run.sources,
        record: run.record,
        running: run.running,
        failure: run.failure,
        durable: run.durable,
      }),
    [
      run.decisionRecordId,
      run.events,
      run.result,
      run.sources,
      run.record,
      run.running,
      run.failure,
      run.durable,
      entry,
    ],
  );

  if (!started) {
    // The entry point is an INCOMING ROW, not a start button.
    //
    // §9 forbids a fake production "Start Vouch" control, and the distinction
    // is a product one rather than a cosmetic one: a decision exists because
    // material arrived, so the honest affordance is "open the arrival that is
    // already waiting". Opening it is what causes Vouch to evaluate — the same
    // causality the real Incoming list will have once its endpoint qualifies.
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <IncomingBlockedNotice />
        <div style={{ margin: '0 26px', maxWidth: 720 }}>
          <div
            style={{
              font: `600 9px ${MONO}`,
              letterSpacing: '.1em',
              color: INK.label,
              marginBottom: 8,
            }}
          >
            AWAITING A QUALITY DECISION
          </div>
          <button
            type="button"
            data-testid="incoming-row"
            onClick={() => {
              setStarted(true);
              void run.start({
                lotId: entry.lotId,
                document: entry.document,
                contentType: entry.contentType,
              });
            }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 14,
              width: '100%',
              textAlign: 'left',
              background: N.card,
              border: `1px solid ${HAIR}`,
              borderRadius: 10,
              padding: '14px 18px',
              cursor: 'pointer',
            }}
          >
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ font: `700 15px ${MONO}`, color: INK.primary }}>{entry.lotId}</div>
              <div style={{ font: `400 11.5px ${MONO}`, color: INK.label, marginTop: 3 }}>
                {entry.material} · {entry.receiptMeta}
              </div>
            </div>
            <Pill tone="progress">EVIDENCE RECEIVED</Pill>
            <span style={{ font: `400 14px ${MONO}`, color: INK.chevron }}>›</span>
          </button>
        </div>
      </div>
    );
  }

  return <DecisionWorkspace vm={vm} />;
}
