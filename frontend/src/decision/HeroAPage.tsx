/**
 * The Hero A entry surface.
 *
 * The arrival that has not been decided yet, above the decisions that have.
 *
 * `list_decisions` was blocked when this surface was first built, so it carried
 * a notice saying enumeration was unprovisioned. That notice outlived the
 * blocker: the `decisions-by-recency` GSI is ACTIVE and the endpoint returns
 * real rows, so the text had become a false statement about the product on the
 * first screen a reader sees. It is gone, and the live list renders beneath the
 * arrival — every row served by the backend, none fabricated here.
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
import { fetchAssetAsBase64 } from '../adapter/client';
import { useDecisionRun } from './useDecisionRun';
import { INK, MONO, N, Pill, HAIR } from './primitives';
import { IncomingSurface } from '../features/Surfaces';

export interface HeroAEntry {
  lotId: string;
  material?: string;
  receiptMeta?: string;
  /** Inline text evidence. Mutually exclusive with `documentUrl`. */
  document?: string;
  /**
   * A bundled binary source document (the canonical COA PDF). Fetched and
   * base64-encoded at click time and submitted through the same `evaluate_lot`
   * ingestion path text evidence uses.
   */
  documentUrl?: string;
  documentName?: string;
  contentType?: string;
}

export function HeroAPage({
  entry,
  onOpenRecord,
}: {
  entry: HeroAEntry;
  onOpenRecord?: (decisionRecordId: string) => void;
}) {
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
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflowY: 'auto' }}>
        <div style={{ margin: '18px 26px 0', maxWidth: 720 }}>
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
              void (async () => {
                // The bundled PDF is read here, at the moment the operator opens
                // the arrival — not at module load, so a document that cannot be
                // read fails the run that needed it rather than the whole app.
                const documentB64 = entry.documentUrl
                  ? await fetchAssetAsBase64(entry.documentUrl)
                  : undefined;
                await run.start({
                  lotId: entry.lotId,
                  document: entry.document,
                  documentB64,
                  contentType: entry.contentType,
                });
              })();
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

        {/* The decisions already on record. Real rows from `list_decisions`,
            with their own loading, empty, blocked and failure states driven by
            the backend envelope rather than by anything asserted here. */}
        <IncomingSurface onOpen={onOpenRecord} />
      </div>
    );
  }

  return <DecisionWorkspace vm={vm} />;
}
