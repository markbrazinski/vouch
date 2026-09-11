/**
 * `/demo/:lotId` — one archived run, replayed in the real workspace.
 *
 * This renders the product. Not a preview of it and not a mock of it: the same
 * `DecisionWorkspace`, from the same `project()` projection, over events the
 * deployed runtime actually produced against the real reasoners and the real
 * authoritative stores. The only thing Demo Mode changes is WHEN each
 * already-real event appears — a 44.7s decision is slower than anyone exploring
 * a cloned repo will sit through.
 *
 * THE AUTHORITY BUTTONS WORK, AND THE RUN REALLY WAITS. On LOT-1003 and
 * LOT-1004 playback parks on the human question and does not resume until the
 * button is pressed, however long that takes. Pressing it continues the run
 * from the next beat.
 *
 * What the button CANNOT do is pick a different outcome. Which option the
 * operator took was decided when the run was captured — it is in the event
 * stream with the evidence they established — so the archive holds exactly one
 * downstream continuation. A demo that let a button select a branch would be
 * the one genuinely dishonest thing here: it would show a decision the factory
 * never made. See `Stages`/`DecisionWorkspace` for how the unrecorded option is
 * presented.
 */

import { useCallback, useEffect, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { DecisionWorkspace } from '../decision/DecisionWorkspace';
import { project } from '../decision/adapter';
import { useGoldenReplay } from './useGoldenReplay';
import { GOLDEN_LOTS } from './timing';
import { markDecided } from './decided';
import { BackBar } from '../app/RoutedShell';
import { SurfaceState } from '../components/SurfaceState';

export function DemoRoute() {
  const { lotId = '' } = useParams();
  const known = GOLDEN_LOTS.includes(lotId);
  const replay = useGoldenReplay(known ? lotId : null);

  /**
   * Every authority control resumes playback, deliberately mapping to one thing.
   *
   * The click reveals the recorded decision at the moment a person asks for it;
   * it does not choose it.
   */
  const resume = useCallback(() => replay.advance(), [replay]);

  /**
   * Record what this run decided, so Incoming and Today reflect it afterwards.
   *
   * Written only at the END: a lot is not decided until its run finishes, and
   * marking it earlier would settle a row while the decision it describes was
   * still on screen.
   */
  useEffect(() => {
    if (!replay.finished || !replay.result) return;
    const consequences = (replay.result.consequences ?? {}) as {
      readiness_changes?: { order_id?: string; to?: string }[];
    };
    markDecided({
      lotId,
      decisionRecordId: replay.decisionRecordId,
      disposition: String(replay.result.disposition ?? ''),
      failureCategory: String(replay.result.failure_category ?? ''),
      // What this run did to the plan, from its own recorded consequence.
      readinessChanges: consequences.readiness_changes,
    });
  }, [replay.finished, replay.result, replay.decisionRecordId, lotId]);

  const vm = useMemo(
    () =>
      project({
        decisionRecordId: replay.decisionRecordId,
        lotId,
        events: replay.events,
        result: replay.result,
        sources: replay.sources,
        record: replay.record,
        running: replay.running,
        durable: true,
      }),
    [
      replay.decisionRecordId,
      replay.events,
      replay.result,
      replay.sources,
      replay.record,
      replay.running,
      lotId,
    ],
  );

  if (!known) {
    return (
      <SurfaceState
        kind="failure"
        headline={`No archived run for ${lotId || 'this lot'}.`}
        detail={`Demo Mode replays ${GOLDEN_LOTS.join(', ')}.`}
      />
    );
  }

  if (replay.loading) {
    return <SurfaceState kind="loading" headline="Opening the decision…" />;
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <BackBar label="Back to Incoming" to="/incoming" />
      <DecisionWorkspace
        vm={vm}
        onEstablishEvidence={resume}
        onKeepHeld={resume}
        onConfirmBinding={resume}
        onKeepUnbound={resume}
      />
    </div>
  );
}
