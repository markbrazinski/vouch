/**
 * The decision entry point.
 *
 * Incoming lists the lots that currently require disposition. Opening one runs
 * a FRESH evaluation of that lot and hands the workspace the live run.
 *
 * There was previously a second, privileged way in: a special LOT-1002 arrival
 * card pinned above the list, which owned the canonical PDF submission while
 * the rows beneath it opened historical DecisionRecords. That gave "click
 * LOT-1002" two different meanings depending on which element you hit — one a
 * live canonical run, the other whichever past execution that row represented,
 * including pre-fix ones. The card is gone and its exact behaviour moved into
 * the ordinary row action, so there is one interaction model and one meaning.
 *
 * There is deliberately still no "Start Vouch" button. A decision begins
 * because material arrived; opening the arrival is what causes Vouch to
 * evaluate it.
 */

import { useMemo, useState } from 'react';
import { DecisionWorkspace } from './DecisionWorkspace';
import { project } from './adapter';
import { fetchAssetAsBase64 } from '../adapter/client';
import { useDecisionRun } from './useDecisionRun';
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
  onOpenRecord: _onOpenRecord,
}: {
  entry: HeroAEntry;
  onOpenRecord?: (decisionRecordId: string) => void;
}) {
  const run = useDecisionRun();
  const [openLot, setOpenLot] = useState<string | null>(null);

  const vm = useMemo(
    () =>
      project({
        decisionRecordId: run.decisionRecordId,
        lotId: openLot ?? entry.lotId,
        material: openLot === entry.lotId ? entry.material : undefined,
        receiptMeta: openLot === entry.lotId ? entry.receiptMeta : undefined,
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
      openLot,
    ],
  );

  if (!openLot) {
    return (
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflowY: 'auto' }}>
        <IncomingSurface
          onEvaluate={(lotId) => {
            setOpenLot(lotId);
            void (async () => {
              /**
               * The canonical evidence, submitted the way the removed hero card
               * submitted it.
               *
               * The bundled PDF belongs to the entry lot, so it is attached only
               * to that lot's run. Sending it with a different lot would be
               * asserting that Eastern Metals certified material it did not.
               * Every other lot starts from the evidence already on its record,
               * which is what the backend does when no document is supplied.
               *
               * Read here, at the moment the operator opens the arrival, so a
               * document that cannot be read fails the run that needed it rather
               * than the whole app.
               */
              const canonical = lotId === entry.lotId;
              const documentB64 =
                canonical && entry.documentUrl
                  ? await fetchAssetAsBase64(entry.documentUrl)
                  : undefined;
              await run.start({
                lotId,
                document: canonical ? entry.document : undefined,
                documentB64,
                contentType: canonical ? entry.contentType : undefined,
              });
            })();
          }}
        />
      </div>
    );
  }

  return <DecisionWorkspace vm={vm} />;
}
