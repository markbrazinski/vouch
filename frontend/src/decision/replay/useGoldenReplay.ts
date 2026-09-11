/**
 * Play back a real recorded run at a speed a camera can use.
 *
 * These are not simulations. Every event replayed here was produced by the
 * deployed runtime against the real reasoners and the real authoritative
 * stores, and each one carries the timestamp and audit record it was written
 * with. What this changes is WHEN each already-real event appears, so a 44.7s
 * decision fits a five-minute film.
 *
 * It returns the SAME `DecisionRunState` that `useDecisionRun` returns, so the
 * workspace cannot tell the two apart and nothing downstream branches on which
 * one it got. The footage is of the product, not of a mock of it.
 *
 * THE HUMAN GATE REALLY WAITS. On LOT-1003 and LOT-1004 playback stops at the
 * quality question and does not resume until the operator presses the button,
 * however long that takes — the pause belongs to the person being filmed, not
 * to a timer. `advance()` is what the button calls. Without this the take would
 * be mimed: the decision would arrive on its own while an operator pretended to
 * make it.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import type { DecisionRunState } from '../useDecisionRun';
import { normalizeEvent } from '../useDecisionRun';
import type { EvaluateDTO, LifecycleEventDTO, SourceArtifactDTO } from '../dto';
import { BEAT_TIMINGS, type BeatTiming } from './timing';

/** One recorded run, as the files playback needs. */
interface GoldenPackage {
  events: LifecycleEventDTO[];
  result: EvaluateDTO;
  record: Record<string, unknown>;
  sources: SourceArtifactDTO[];
}

const LOADERS: Record<string, () => Promise<GoldenPackage>> = {
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
    // Stored rows nest their payload; the adapter reads flat. The same
    // normalization the live poll applies, so replay and live hand `project()`
    // identical input.
    events: (events.default as LifecycleEventDTO[]).map(normalizeEvent),
    result: result.default as EvaluateDTO,
    record: record.default as Record<string, unknown>,
    sources: [],
  };
}

export interface GoldenReplayState extends DecisionRunState {
  loading: boolean;
  /** The lot being played, or '' when this is not a replay. */
  replayingLot: string;
  beat: BeatTiming | null;
  beatIndex: number;
  beatCount: number;
  finished: boolean;
  /**
   * Playback is parked on the human question and will not move on its own.
   *
   * The workspace's authority buttons are live in this state: pressing one
   * calls `advance()`. Nothing else resumes it.
   */
  awaitingOperator: boolean;
  /** Resume from a human gate. What the authority buttons call. */
  advance: () => void;
}

const IDLE: Omit<GoldenReplayState, 'advance'> = {
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
  awaitingOperator: false,
};

/**
 * A beat that stops for a person.
 *
 * `human_gate` is where the question is put. It is the beat whose duration is
 * the operator's, and the only one playback will not leave on a timer — but
 * ONLY when a question was genuinely asked. LOT-1005's security halt emits the
 * same escalation event with no question and no options, so there is nothing to
 * press and nothing to wait for; it plays straight through.
 */
const pausesForOperator = (beat: BeatTiming): boolean =>
  beat.beatId === 'human_gate' && beat.awaitsOperator === true;

/**
 * The record AS IT STOOD when the question was put, rebuilt from the stored one.
 *
 * The captured record is the finished audit document, so its question reads
 * `RESOLVED` with the operator's decision beside it. That is correct history and
 * wrong for this moment: the workspace only renders the authority panel for an
 * OPEN question with no decision recorded, so replaying the final record at the
 * gate shows the disagreement with no button to answer it.
 *
 * Nothing is invented here. The question, its two options, the measurements and
 * the thresholds are the stored ones, unmodified; only the two fields that say
 * "this has since been answered" are wound back — which is exactly what was
 * true at the instant the run stopped to ask. The operator's actual decision is
 * still in the event stream and still in the record that lands at the terminal
 * beat, so the audit trail the film shows is complete.
 */
function recordAtTheGate(record: Record<string, unknown>): Record<string, unknown> {
  const authority = record.quality_authority as
    | { question?: Record<string, unknown>; decisions?: unknown[] }
    | undefined;
  if (!authority?.question) return record;
  return {
    ...record,
    // The second run has not started: the operator is the thing that starts it.
    // The stored `run_count` is 2 because the record was written after the
    // decision, and the header reads it directly — so the gate frame announced
    // "Run 2 · resumed" while still asking the question that causes run 2.
    run_count: 1,
    quality_authority: {
      ...authority,
      question: { ...authority.question, status: 'OPEN' },
      decisions: [],
    },
  };
}

export function useGoldenReplay(lotId: string | null): GoldenReplayState {
  const [state, setState] = useState<Omit<GoldenReplayState, 'advance'>>(IDLE);

  const pkg = useRef<GoldenPackage | null>(null);
  const timers = useRef<number[]>([]);
  /** The beat index playback should resume from when the operator acts. */
  const resumeAt = useRef<number>(-1);
  const cancelled = useRef(false);

  const clearTimers = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  /**
   * Schedule every beat from `startIndex` onward.
   *
   * Called once when the package loads, and again from `advance()` after a
   * human gate. Scheduling forward from a point rather than replaying from zero
   * is what lets the pause be any length: the beats after it are laid out
   * relative to the moment the operator acted.
   */
  const schedule = useCallback((startIndex: number, lot: string) => {
    const loaded = pkg.current;
    if (!loaded) return;
    const beats = BEAT_TIMINGS[lot] ?? [];
    clearTimers();

    let elapsed = 0;
    for (let index = startIndex; index < beats.length; index += 1) {
      const beat = beats[index];
      const at = elapsed;
      const last = index === beats.length - 1;
      const pause = pausesForOperator(beat);

      timers.current.push(
        window.setTimeout(() => {
          if (cancelled.current) return;
          setState((prev) => ({
            ...prev,
            events: loaded.events.filter((e) => Number(e.sequence ?? 0) <= beat.to),
            // The authoritative response lands only at the terminal beat: it
            // states the disposition outright, and revealing it earlier would
            // put the outcome on screen before its cause.
            result: last ? loaded.result : null,
            // The record is needed at a human gate too, not only at the end:
            // the authority panel — the button the operator presses — is
            // rendered from it. Wound back to its open state there, whole at
            // the terminal beat.
            record: last
              ? loaded.record
              : pause
                ? recordAtTheGate(loaded.record)
                : null,
            sources: last ? loaded.sources : [],
            running: !last && !pause,
            beat,
            beatIndex: index,
            finished: last,
            awaitingOperator: pause,
          }));
        }, at),
      );

      if (pause) {
        // Stop laying out the future. The rest is scheduled by `advance()`,
        // whenever the operator gets to it.
        resumeAt.current = index + 1;
        break;
      }
      elapsed += beat.seconds * 1000;
    }
  }, []);

  const advance = useCallback(() => {
    if (resumeAt.current < 0 || !state.replayingLot) return;
    const from = resumeAt.current;
    resumeAt.current = -1;
    setState((prev) => ({ ...prev, awaitingOperator: false, running: true }));
    schedule(from, state.replayingLot);
  }, [schedule, state.replayingLot]);

  useEffect(() => {
    cancelled.current = false;
    clearTimers();
    resumeAt.current = -1;
    pkg.current = null;

    if (!lotId || !LOADERS[lotId]) {
      setState(IDLE);
      return;
    }

    setState({ ...IDLE, loading: true, replayingLot: lotId, running: true });

    void LOADERS[lotId]().then((loaded) => {
      if (cancelled.current) return;
      pkg.current = loaded;
      setState({
        ...IDLE,
        replayingLot: lotId,
        decisionRecordId: (loaded.result.decision_record_id as string) || '',
        running: true,
        beatCount: (BEAT_TIMINGS[lotId] ?? []).length,
      });
      schedule(0, lotId);
    });

    return () => {
      cancelled.current = true;
      clearTimers();
    };
  }, [lotId, schedule]);

  return { ...state, advance };
}
