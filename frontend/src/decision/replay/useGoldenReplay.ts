/**
 * Replay a captured golden run at film pace.
 *
 * Returns the SAME `DecisionRunState` shape `useDecisionRun` returns, so the
 * workspace cannot tell the two apart and no rendering code branches on which
 * one it got. What changes is only the source of the events and the clock that
 * reveals them.
 *
 * What playback may change: WHEN an already-real event becomes visible.
 * What playback may not change: what happened, who selected what, the event
 * order, the human decision, the disposition, the mutation, the consequence.
 * Every one of those is read from `golden-runs/<LOT>/`, unaltered.
 *
 * The terminal `result` and `record` are withheld until the last beat, for the
 * same reason the live path withholds them: they carry the outcome directly, so
 * revealing them early would announce a disposition before the events that
 * produce it. That is the causal invariant the whole capture exists to protect.
 */

import { useEffect, useRef, useState } from 'react';
import type { DecisionRunState } from '../useDecisionRun';
import { normalizeEvent } from '../useDecisionRun';
import type { EvaluateDTO, LifecycleEventDTO, SourceArtifactDTO } from '../dto';
import { BEAT_TIMINGS, type BeatTiming } from './timing';

/** One golden package, as the three files playback needs. */
interface GoldenPackage {
  events: LifecycleEventDTO[];
  result: EvaluateDTO;
  record: Record<string, unknown>;
  sources: SourceArtifactDTO[];
}

/**
 * Packages are imported dynamically and only on the replay path.
 *
 * Vite splits each into its own chunk, so the live app never downloads a
 * captured run — the demo costs nothing to anyone not asking for it.
 */
const PACKAGES: Record<string, () => Promise<GoldenPackage>> = {
  'LOT-1001': () => loadPackage('LOT-1001'),
  'LOT-1002': () => loadPackage('LOT-1002'),
  'LOT-1003': () => loadPackage('LOT-1003'),
  'LOT-1004': () => loadPackage('LOT-1004'),
  'LOT-1005': () => loadPackage('LOT-1005'),
};

async function loadPackage(lotId: string): Promise<GoldenPackage> {
  // `packages/` is a copy of `golden-runs/`, synced by
  // `scripts/sync_golden_to_frontend.py`. Vite bundles only what lives under
  // the project root, and a test fails if the copy drifts from the capture.
  const [events, result, record] = await Promise.all([
    import(`./packages/${lotId}/events.json`),
    import(`./packages/${lotId}/result.json`),
    import(`./packages/${lotId}/decision-record.json`),
  ]);
  return {
    // Stored rows nest their payload; the adapter reads flat. Same
    // normalization the live poll path applies, so replay and live produce
    // identical input to `project()`.
    events: (events.default as LifecycleEventDTO[]).map(normalizeEvent),
    result: result.default as EvaluateDTO,
    record: record.default as Record<string, unknown>,
    sources: [],
  };
}

export interface GoldenReplayState extends DecisionRunState {
  /** True until the package has loaded. */
  loading: boolean;
  /** The lot being replayed, or '' when this is not a replay. */
  replayingLot: string;
  /** Which beat is on screen, for the replay caption. */
  beat: BeatTiming | null;
  beatIndex: number;
  beatCount: number;
  /** True once the final beat has been reached. */
  finished: boolean;
}

const IDLE: GoldenReplayState = {
  decisionRecordId: '',
  events: [],
  result: null,
  sources: [],
  record: null,
  running: false,
  failure: null,
  durable: true,
  loading: false,
  replayingLot: '',
  beat: null,
  beatIndex: -1,
  beatCount: 0,
  finished: false,
};

export function useGoldenReplay(lotId: string | null): GoldenReplayState {
  const [state, setState] = useState<GoldenReplayState>(IDLE);
  // Every pending reveal, so an unmount or a lot change cancels the whole
  // schedule rather than leaving timers writing into a dead component.
  const timers = useRef<number[]>([]);

  useEffect(() => {
    timers.current.forEach(clearTimeout);
    timers.current = [];

    if (!lotId || !PACKAGES[lotId]) {
      setState(IDLE);
      return;
    }

    let cancelled = false;
    setState({ ...IDLE, loading: true, replayingLot: lotId, running: true });

    void PACKAGES[lotId]().then((pkg) => {
      if (cancelled) return;
      const beats = BEAT_TIMINGS[lotId] ?? [];
      const recordId = (pkg.result.decision_record_id as string) || '';

      setState({
        ...IDLE,
        replayingLot: lotId,
        decisionRecordId: recordId,
        running: true,
        beatCount: beats.length,
      });

      // Each beat is revealed at the sum of every prior beat's hold, so a beat
      // is on screen for exactly the time this lot's timing table gives it.
      let elapsed = 0;
      beats.forEach((beat, index) => {
        const at = elapsed;
        elapsed += beat.seconds * 1000;
        const last = index === beats.length - 1;

        timers.current.push(
          window.setTimeout(() => {
            if (cancelled) return;
            setState((prev) => ({
              ...prev,
              // Every event up to and including this beat's last.
              events: pkg.events.filter((e) => Number(e.sequence ?? 0) <= beat.to),
              // The authoritative response lands ONLY at the terminal beat. It
              // states the disposition outright, so revealing it earlier would
              // put an outcome on screen before its cause.
              result: last ? pkg.result : null,
              record: last ? pkg.record : null,
              sources: last ? pkg.sources : [],
              running: !last,
              beat,
              beatIndex: index,
              finished: last,
            }));
          }, at),
        );
      });
    });

    return () => {
      cancelled = true;
      timers.current.forEach(clearTimeout);
      timers.current = [];
    };
  }, [lotId]);

  return state;
}
