/**
 * `/incoming` — the current arrivals, and the one way a decision begins.
 *
 * This route means exactly "show what currently requires disposition". It never
 * means "show whichever lot was opened last time", which is what the previous
 * `openLot` state made it mean: that value lived inside the Incoming page, so
 * clicking Incoming while a decision was open changed nothing the shell could
 * see and the operator was stranded.
 *
 * Opening a row starts a real evaluation and then NAVIGATES. The record id is
 * minted here, before the POST, because the workspace is addressed by it —
 * `evaluate_lot` accepts a caller-supplied id and treats it as CONTINUED, which
 * is the same property that already let the client poll a decision it named
 * first. So the route changes immediately and the workspace watches the run;
 * nothing waits for the evaluation to finish.
 *
 * There is deliberately still no "Start Vouch" button, and no special LOT-1002
 * card. A decision begins because material arrived, and every arrival is opened
 * the same way.
 */

import { useNavigate } from 'react-router-dom';
import { fetchAssetAsBase64, newDecisionRecordId } from '../adapter/client';
import { IncomingSurface } from '../features/Surfaces';
import { pendingRun } from './pendingRun';
import { DEMO_AVAILABLE, demoEnabled } from '../demo/mode';
import type { ArrivalDocuments } from './entry';

export function IncomingRoute({ arrivals }: { arrivals: ArrivalDocuments }) {
  const navigate = useNavigate();
  /**
   * In Demo Mode a lot opens its ARCHIVED run instead of starting a live one.
   *
   * The mode rides on the EXISTING surface rather than a parallel "demo
   * gallery": the arrivals, the lots and the certificates are the real ones
   * either way, and only what a click opens changes. A second screen would
   * drift from the product it exists to show, and a cloned repo is supposed to
   * behave like Vouch, not like a video player.
   */
  // `DEMO_AVAILABLE &&` first so a judge build folds this to `false` and drops
  // the branch — and with it the `/demo/` route string — as dead code.
  const demo = DEMO_AVAILABLE && demoEnabled();

  return (
    // The same scroll wrapper Records uses. The extra `display: flex` this
    // once had made the page div a flex ITEM, so it shrank to its content
    // width (934px against Records' 1376px) and sat centred between two large
    // gutters. Incoming and Records render the same table; they now measure
    // the same too.
    <div style={{ flex: 1, overflowY: 'auto', minHeight: 0 }}>
      <IncomingSurface
        onEvaluate={(lotId) => {
          // Demo Mode opens the run this lot already made. Nothing is posted
          // and no authoritative state is mutated: the decision was committed
          // when it was captured, and this is that record playing.
          if (demo) {
            navigate(`/demo/${lotId}`);
            return;
          }

          const recordId = newDecisionRecordId();

          /**
           * The canonical evidence for THIS lot, and only this lot.
           *
           * Each certificate is attached to the lot its supplier issued it for.
           * Sending one with a different lot would assert that supplier
           * certified material they did not. A lot with no bundled document
           * starts from the evidence already on its record, which is what the
           * backend does when none is supplied.
           */
          const arrival = arrivals[lotId];

          /**
           * Hand the workspace the work, then route.
           *
           * The document has to be read before `evaluate` can be called, and
           * that read is async — but the operator clicked, so the route should
           * change now rather than after a fetch. The intent is parked for the
           * workspace to pick up on mount, keyed by the id we just minted, so
           * the POST is issued exactly once by whichever component owns it.
           */
          pendingRun.set(recordId, {
            lotId,
            decisionRecordId: recordId,
            document: arrival?.document,
            contentType: arrival?.contentType,
            loadDocumentB64: arrival?.documentUrl
              ? () => fetchAssetAsBase64(arrival.documentUrl!)
              : undefined,
          });

          navigate(`/decisions/${recordId}`);
        }}
      />
    </div>
  );
}
