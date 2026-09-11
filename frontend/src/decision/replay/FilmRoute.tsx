/**
 * `/film/:lotId` — a real recorded run, played at a speed a camera can use.
 *
 * This renders the product. Not a preview of it, not a mock of it: the same
 * `DecisionWorkspace`, from the same `project()` projection, over events the
 * deployed runtime actually produced. The only thing film view changes is WHEN
 * each already-real event appears, because a 44.7s decision does not fit a
 * five-minute demo and a camera cannot wait it out.
 *
 * There is deliberately NO replay badge, no watermark and no transport chrome.
 * An overlay in the corner of every frame would make the footage unusable, and
 * it would be labelling a recording of a real decision as though it were a
 * fabrication. It is not one. What the operator presses, and what Vouch
 * decided, both happened.
 *
 * THE AUTHORITY BUTTONS WORK. On LOT-1003 and LOT-1004 playback parks on the
 * quality question and waits — indefinitely, for as many takes as it takes —
 * until the button is pressed. Pressing it resumes the run from the next beat.
 * The decision itself was made when the run was captured and is in the event
 * stream; the click is what reveals it, at the moment the shot needs it.
 */

import { useCallback, useMemo } from 'react';
import { useParams } from 'react-router-dom';
import { DecisionWorkspace } from '../DecisionWorkspace';
import { project } from '../adapter';
import { useGoldenReplay } from './useGoldenReplay';
import { GOLDEN_LOTS } from './timing';
import { BackBar } from '../../app/RoutedShell';
import { SurfaceState } from '../../components/SurfaceState';

export function FilmRoute() {
  const { lotId = '' } = useParams();
  const known = GOLDEN_LOTS.includes(lotId);
  const replay = useGoldenReplay(known ? lotId : null);

  /**
   * Every authority control resumes playback.
   *
   * All four map to the same thing deliberately. Which button was pressed was
   * decided when the run was captured — it is in `QUALITY_AUTHORITY_RECORDED`,
   * with the evidence the operator established — so the click cannot choose a
   * different outcome and must not appear to. It releases the pause.
   *
   * A film view that let a button pick a branch would be the one genuinely
   * dishonest thing here: it would show a decision the factory never made.
   */
  const resume = useCallback(() => replay.advance(), [replay]);

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
        headline={`No recorded run for ${lotId || 'this lot'}.`}
        detail={`Recorded runs exist for ${GOLDEN_LOTS.join(', ')}.`}
      />
    );
  }

  if (replay.loading) {
    return <SurfaceState kind="loading" headline="Opening the decision…" />;
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <BackBar label="Back to Incoming" to="/incoming?film=true" />
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
