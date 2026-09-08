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
import type { HeroAEntry } from './entry';

export function IncomingRoute({ entry }: { entry: HeroAEntry }) {
  const navigate = useNavigate();

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, overflowY: 'auto' }}>
      <IncomingSurface
        onEvaluate={(lotId) => {
          const recordId = newDecisionRecordId();

          /**
           * The canonical evidence, attached only to the lot it belongs to.
           *
           * The bundled PDF is Eastern Metals' certificate for the entry lot.
           * Sending it with a different lot would assert that they certified
           * material they did not. Every other lot starts from the evidence
           * already on its record, which is what the backend does when no
           * document is supplied.
           */
          const canonical = lotId === entry.lotId;

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
            document: canonical ? entry.document : undefined,
            contentType: canonical ? entry.contentType : undefined,
            loadDocumentB64:
              canonical && entry.documentUrl
                ? () => fetchAssetAsBase64(entry.documentUrl!)
                : undefined,
          });

          navigate(`/decisions/${recordId}`);
        }}
      />
    </div>
  );
}
