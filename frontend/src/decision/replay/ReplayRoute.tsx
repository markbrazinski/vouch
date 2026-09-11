/**
 * `/demo/:lotId` — one golden run, replayed at film pace.
 *
 * Renders the SAME `DecisionWorkspace` the live route renders, from the same
 * `project()` projection. The only difference is where the events come from and
 * what reveals them: a captured package and a hard-coded per-beat clock,
 * instead of a live invocation and a poll loop.
 *
 * A REPLAY BANNER IS NOT OPTIONAL. Saved data rendering in the live app is
 * exactly the surface where a viewer could mistake a recording for a live
 * decision, so the frame says what it is, permanently and unmissably. Nothing
 * here is hidden behind a dev flag — this route is meant to work in a deployed
 * build — which makes the labelling the thing that keeps it honest.
 */

import { useMemo } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { DecisionWorkspace } from '../DecisionWorkspace';
import { project } from '../adapter';
import { useGoldenReplay } from './useGoldenReplay';
import { MACHINE_SECONDS, filmSeconds, GOLDEN_LOTS } from './timing';
import { BackBar } from '../../app/RoutedShell';
import { SurfaceState } from '../../components/SurfaceState';
import { INK, MONO, HAIR } from '../primitives';

/** The banner. Always on screen for the whole replay. */
function ReplayBanner({
  lotId,
  beatId,
  beatIndex,
  beatCount,
  machine,
}: {
  lotId: string;
  beatId: string;
  beatIndex: number;
  beatCount: number;
  machine: number;
}) {
  return (
    <div
      data-testid="replay-banner"
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 14,
        padding: '7px 30px',
        background: '#3A3126',
        color: '#F1ECE1',
        font: `600 11px ${MONO}`,
        letterSpacing: '.06em',
        borderBottom: `1px solid ${HAIR}`,
      }}
    >
      <span
        style={{
          background: '#C9A227',
          color: '#241D14',
          padding: '2px 8px',
          borderRadius: 4,
          fontWeight: 700,
        }}
      >
        REPLAY
      </span>
      {/* The claim this banner has to make: real decision, recorded earlier,
          nothing live is happening. Stating the machine time keeps the
          compression honest rather than implying the pipeline is this fast. */}
      <span>
        Recorded run · {lotId} · took {machine.toFixed(1)}s in real time
      </span>
      <span style={{ marginLeft: 'auto', color: '#A79B85' }}>
        {beatId} · {beatIndex + 1}/{beatCount}
      </span>
    </div>
  );
}

export function ReplayRoute() {
  const { lotId = '' } = useParams();
  const navigate = useNavigate();
  const known = GOLDEN_LOTS.includes(lotId);
  const replay = useGoldenReplay(known ? lotId : null);

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
    return <SurfaceState kind="loading" headline="Loading the recorded run…" />;
  }

  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <ReplayBanner
        lotId={lotId}
        beatId={replay.beat?.beatId ?? 'startup'}
        beatIndex={Math.max(replay.beatIndex, 0)}
        beatCount={replay.beatCount}
        machine={MACHINE_SECONDS[lotId] ?? 0}
      />
      <BackBar label="Back to the demo list" to="/incoming?demo=true" />
      <DecisionWorkspace
        vm={vm}
        /* A replay is a recording. The authority controls are inert by
           construction: the human decision ALREADY happened and is in the
           event stream, and offering a button that appears to make it again
           would be the one thing playback must never do — let a viewer think
           they changed a recorded outcome. */
        onEstablishEvidence={() => {}}
        onKeepHeld={() => {}}
        onConfirmBinding={() => {}}
        onKeepUnbound={() => {}}
      />
      {replay.finished && (
        <div
          data-testid="replay-finished"
          style={{
            padding: '10px 30px',
            borderTop: `1px solid ${HAIR}`,
            font: `600 11.5px ${MONO}`,
            color: INK.label,
            display: 'flex',
            gap: 16,
            alignItems: 'center',
          }}
        >
          <span>
            Replay complete · {filmSeconds(lotId).toFixed(1)}s of playback ·{' '}
            {(MACHINE_SECONDS[lotId] ?? 0).toFixed(1)}s of real machine time
          </span>
          <button
            type="button"
            onClick={() => navigate('/incoming?demo=true')}
            style={{
              marginLeft: 'auto',
              background: 'transparent',
              border: `1px solid ${HAIR}`,
              borderRadius: 7,
              padding: '5px 11px',
              font: `600 11.5px ${MONO}`,
              color: INK.prose,
              cursor: 'pointer',
            }}
          >
            Choose another run
          </button>
        </div>
      )}
    </div>
  );
}
