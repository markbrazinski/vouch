/**
 * `/decisions/:recordId` — the operational workspace for ONE decision.
 *
 * The decision is identified by `decision_record_id`, never by lot. A lot can
 * be evaluated many times; the record is the evaluation being watched. That is
 * why the route carries the record id and why two runs of the same lot stay
 * independently addressable.
 *
 * Mounting does one of exactly two things, decided by whether an intent was
 * parked for this id:
 *
 *   a pending run  -> start it (the operator just clicked the arrival)
 *   no pending run -> observe it (a deep link, a refresh, a Back, a revisit)
 *
 * `observe` submits nothing. It reads the authoritative record and its events;
 * if the backend says the decision is still going, it watches with the same
 * poll loop a live run uses. So navigating away and back resumes observation of
 * the same execution, and the evaluation is never restarted — the intent is
 * claimed exactly once, and a remount finds it gone.
 *
 * Navigating away simply unmounts: the hook's own cleanup clears its interval,
 * and the backend run continues untouched. Nothing here cancels work.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import { DecisionWorkspace } from './DecisionWorkspace';
import { project } from './adapter';
import { useDecisionRun } from './useDecisionRun';
import { pendingRun } from './pendingRun';
import { BackBar } from '../app/RoutedShell';
import { SurfaceState } from '../components/SurfaceState';
import type { HeroAEntry } from './entry';

export function DecisionRoute({ entry }: { entry: HeroAEntry }) {
  const { recordId } = useParams();
  const run = useDecisionRun(recordId);

  /**
   * One start-or-observe per record id.
   *
   * StrictMode double-invokes effects in development, and a second call here
   * would either submit a duplicate evaluation or open a second poll loop. The
   * guard is the record id itself rather than a boolean, so navigating from one
   * decision to another still acts.
   */
  const actedFor = useRef<string | null>(null);

  /**
   * The lot this route is about, known before the record exists.
   *
   * The workspace renders as soon as the run starts, and the stored record does
   * not answer until the first poll returns — so for the opening seconds
   * `run.record` is undefined. Falling back to the ENTRY lot there meant
   * clicking LOT-1001 opened a workspace headed LOT-1002: the run underneath
   * was correct, the header was not, which is worse than being blank.
   *
   * The click already knew the lot. This keeps it.
   */
  const [intendedLotId, setIntendedLotId] = useState<string>('');

  useEffect(() => {
    if (!recordId || actedFor.current === recordId) return;
    actedFor.current = recordId;

    const intent = pendingRun.take(recordId);
    if (intent) setIntendedLotId(intent.lotId);
    if (!intent) {
      // Nobody parked work for this id: it is an existing decision.
      void run.observe(recordId);
      return;
    }

    void (async () => {
      // The bundled PDF is read HERE, at the moment the run starts, so a
      // document that cannot be read fails the run that needed it rather than
      // the whole app.
      const documentB64 = intent.loadDocumentB64 ? await intent.loadDocumentB64() : undefined;
      await run.start({
        lotId: intent.lotId,
        decisionRecordId: intent.decisionRecordId,
        document: intent.document,
        documentB64,
        contentType: intent.contentType,
      });
    })();
    // `run` is intentionally not a dependency: its identity changes on every
    // state update, and this must fire once per record id, not per render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recordId]);

  // The lot, most authoritative source first: the stored record, then what the
  // operator clicked, and only then the entry the app was opened with.
  const lotId = (run.record?.lot_id as string) || intendedLotId || entry.lotId;
  // Receipt identity from the entry applies only when this IS the entry lot.
  const isEntryLot = lotId === entry.lotId;

  const vm = useMemo(
    () =>
      project({
        decisionRecordId: run.decisionRecordId,
        lotId,
        // Receipt identity is the entry's only where the entry IS the lot.
        material: isEntryLot ? entry.material : undefined,
        receiptMeta: isEntryLot ? entry.receiptMeta : undefined,
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
      isEntryLot,
      lotId,
    ],
  );

  if (!recordId) {
    return (
      <SurfaceState
        kind="failure"
        headline="No decision was named in this address."
        detail="A decision is addressed by its DecisionRecord id."
      />
    );
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <BackBar label="Back to Incoming" to="/incoming" />
      <DecisionWorkspace
        vm={vm}
        onQualityDecision={(decision) =>
          run.decide({
            decision,
            // Who is acting, and under what authority. Hard-coded here only
            // because this build has no operator identity to read from; the
            // backend requires both and refuses an empty either way, so the
            // moment sign-in exists these become the signed-in operator.
            accountableActor: 'QA-LEAD',
            authoritySource: 'Plant Quality Authority',
            questionId: vm.qualityAuthorityPanel?.questionId,
          })
        }
      />
    </div>
  );
}
