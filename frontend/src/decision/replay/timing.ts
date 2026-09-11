/**
 * Beat timing for golden replay. One hard-coded table, per lot, per beat.
 *
 * These numbers are DERIVED, not invented: `scripts/time_golden_runs.py`
 * measures each beat from the captured event timestamps and applies the
 * presentation rules (a 1.5s hold at a human decision and at the terminal
 * frame, a 0.6s floor so nothing flashes past, a 3.5s ceiling on agent
 * reasoning, mechanical beats compressed). This file is that script's output,
 * frozen so playback needs no second parameter.
 *
 * Truth and presentation stay separate. `golden-runs/<LOT>/events.json` is what
 * happened and never changes; this is only how long each already-real beat is
 * held on screen. Regenerate with:
 *
 *     python scripts/time_golden_runs.py --write
 *
 * and copy the `film_s` column here.
 */

/** One beat of one lot: which events it covers, and how long it holds. */
export interface BeatTiming {
  beatId: string;
  run: number;
  /** Inclusive event-sequence span this beat reveals. */
  from: number;
  to: number;
  /** Seconds to hold before revealing the next beat. */
  seconds: number;
  /**
   * Playback STOPS here until the operator presses the authority button.
   *
   * Only true where a question was genuinely asked. `seconds` is ignored on
   * such a beat: the pause is however long the person takes, which is the
   * point — the decision is being filmed being made, not waited out.
   *
   * LOT-1005 deliberately does NOT set it. Its security halt emits the same
   * escalation event with no question and no options, so there is no button to
   * press; pausing there would stage a deliberation that never happened.
   */
  awaitsOperator?: boolean;
}

/**
 * Measured machine time per lot, for the caption the replay surface shows.
 *
 * Kept beside the film timings deliberately: a viewer being told "this took
 * 17.4s" while watching 15.8s of playback is the honest framing, and the number
 * is not derivable from the timings themselves once they have been compressed.
 */
export const MACHINE_SECONDS: Record<string, number> = {
  'LOT-1001': 17.4,
  'LOT-1002': 26.4,
  'LOT-1003': 44.7,
  'LOT-1004': 16.38,
  'LOT-1005': 0.69,
};

export const BEAT_TIMINGS: Record<string, BeatTiming[]> = {
  'LOT-1001': [
    { beatId: 'startup', run: 1, from: 0, to: 0, seconds: 1.31 },
    { beatId: 'evidence_received', run: 1, from: 1, to: 1, seconds: 2.37 },
    { beatId: 'security', run: 1, from: 2, to: 2, seconds: 2.97 },
    { beatId: 'binding', run: 1, from: 3, to: 3, seconds: 2.73 },
    { beatId: 'extraction', run: 1, from: 4, to: 5, seconds: 1.66 },
    { beatId: 'investigator', run: 1, from: 6, to: 13, seconds: 8.82 },
    { beatId: 'verifier', run: 1, from: 14, to: 21, seconds: 8.82 },
    { beatId: 'reconciliation', run: 1, from: 22, to: 22, seconds: 3.26 },
    { beatId: 'disposition', run: 1, from: 23, to: 24, seconds: 3.26 },
    { beatId: 'mutation', run: 1, from: 25, to: 26, seconds: 1.49 },
    { beatId: 'disposition', run: 1, from: 27, to: 27, seconds: 3.26 },
    { beatId: 'mutation', run: 1, from: 28, to: 29, seconds: 1.49 },
    { beatId: 'consequence', run: 1, from: 30, to: 32, seconds: 4.15 },
    { beatId: 'terminal', run: 1, from: 32, to: 32, seconds: 6.41 },
  ],
  'LOT-1002': [
    { beatId: 'startup', run: 1, from: 0, to: 0, seconds: 1.09 },
    { beatId: 'evidence_received', run: 1, from: 1, to: 1, seconds: 1.82 },
    { beatId: 'security', run: 1, from: 2, to: 2, seconds: 2.46 },
    { beatId: 'binding', run: 1, from: 3, to: 3, seconds: 2.06 },
    { beatId: 'extraction', run: 1, from: 4, to: 5, seconds: 1.33 },
    { beatId: 'investigator', run: 1, from: 6, to: 24, seconds: 7.15 },
    { beatId: 'verifier', run: 1, from: 25, to: 32, seconds: 7.15 },
    { beatId: 'reconciliation', run: 1, from: 33, to: 33, seconds: 2.43 },
    { beatId: 'disposition', run: 1, from: 34, to: 35, seconds: 2.43 },
    { beatId: 'mutation', run: 1, from: 36, to: 37, seconds: 1.21 },
    { beatId: 'disposition', run: 1, from: 38, to: 38, seconds: 2.43 },
    { beatId: 'mutation', run: 1, from: 39, to: 40, seconds: 1.21 },
    { beatId: 'consequence', run: 1, from: 41, to: 44, seconds: 3.03 },
    { beatId: 'disposition', run: 1, from: 45, to: 45, seconds: 2.43 },
    { beatId: 'mutation', run: 1, from: 46, to: 47, seconds: 1.21 },
    { beatId: 'consequence', run: 1, from: 48, to: 48, seconds: 3.03 },
    { beatId: 'terminal', run: 1, from: 48, to: 48, seconds: 5.53 },
  ],
  'LOT-1003': [
    { beatId: 'startup', run: 1, from: 0, to: 0, seconds: 0.87 },
    { beatId: 'evidence_received', run: 1, from: 1, to: 1, seconds: 1.27 },
    { beatId: 'security', run: 1, from: 2, to: 2, seconds: 1.66 },
    { beatId: 'binding', run: 1, from: 3, to: 3, seconds: 1.41 },
    { beatId: 'extraction', run: 1, from: 4, to: 5, seconds: 1.0 },
    { beatId: 'investigator', run: 1, from: 6, to: 15, seconds: 5.52 },
    { beatId: 'verifier', run: 1, from: 16, to: 27, seconds: 5.52 },
    { beatId: 'reconciliation', run: 1, from: 28, to: 28, seconds: 1.61 },
    { beatId: 'human_gate', run: 1, from: 29, to: 30, seconds: 1.5, awaitsOperator: true },
    { beatId: 'human_authority', run: 2, from: 31, to: 31, seconds: 1.5 },
    { beatId: 'run_2_start', run: 2, from: 32, to: 32, seconds: 1.27 },
    { beatId: 'extraction', run: 2, from: 33, to: 33, seconds: 1.0 },
    { beatId: 'investigator', run: 2, from: 34, to: 45, seconds: 5.52 },
    { beatId: 'verifier', run: 2, from: 46, to: 64, seconds: 5.52 },
    { beatId: 'reconciliation', run: 2, from: 65, to: 65, seconds: 1.61 },
    { beatId: 'disposition', run: 2, from: 66, to: 67, seconds: 1.61 },
    { beatId: 'mutation', run: 2, from: 68, to: 69, seconds: 0.94 },
    { beatId: 'disposition', run: 2, from: 70, to: 70, seconds: 1.61 },
    { beatId: 'mutation', run: 2, from: 71, to: 72, seconds: 0.94 },
    { beatId: 'consequence', run: 2, from: 73, to: 74, seconds: 1.95 },
    { beatId: 'terminal', run: 2, from: 74, to: 74, seconds: 2.17 },
  ],
  'LOT-1004': [
    { beatId: 'startup', run: 1, from: 0, to: 0, seconds: 0.61 },
    { beatId: 'evidence_received', run: 1, from: 1, to: 1, seconds: 0.64 },
    { beatId: 'security', run: 1, from: 2, to: 2, seconds: 0.89 },
    { beatId: 'binding', run: 1, from: 3, to: 3, seconds: 0.64 },
    { beatId: 'extraction', run: 1, from: 4, to: 4, seconds: 0.62 },
    { beatId: 'human_gate', run: 1, from: 5, to: 6, seconds: 1.5, awaitsOperator: true },
    { beatId: 'human_authority', run: 2, from: 7, to: 7, seconds: 1.5 },
    { beatId: 'binding', run: 2, from: 8, to: 8, seconds: 0.64 },
    { beatId: 'run_2_start', run: 2, from: 9, to: 9, seconds: 0.64 },
    { beatId: 'extraction', run: 2, from: 10, to: 10, seconds: 0.62 },
    { beatId: 'investigator', run: 2, from: 11, to: 18, seconds: 3.61 },
    { beatId: 'verifier', run: 2, from: 19, to: 26, seconds: 3.61 },
    { beatId: 'reconciliation', run: 2, from: 27, to: 27, seconds: 0.65 },
    { beatId: 'disposition', run: 2, from: 28, to: 29, seconds: 0.65 },
    { beatId: 'mutation', run: 2, from: 30, to: 31, seconds: 0.62 },
    { beatId: 'disposition', run: 2, from: 32, to: 32, seconds: 0.65 },
    { beatId: 'mutation', run: 2, from: 33, to: 34, seconds: 0.62 },
    { beatId: 'consequence', run: 2, from: 35, to: 37, seconds: 0.67 },
    { beatId: 'terminal', run: 2, from: 37, to: 37, seconds: 0.62 },
  ],
  'LOT-1005': [
    { beatId: 'startup', run: 1, from: 0, to: 0, seconds: 0.75 },
    { beatId: 'evidence_received', run: 1, from: 1, to: 1, seconds: 0.99 },
    { beatId: 'security', run: 1, from: 2, to: 2, seconds: 1.12 },
    { beatId: 'binding', run: 1, from: 3, to: 3, seconds: 1.06 },
    { beatId: 'human_gate', run: 1, from: 4, to: 4, seconds: 0.6 },
    { beatId: 'terminal', run: 1, from: 4, to: 4, seconds: 2.48 },
  ],
};

/** Total playback length of one lot, in seconds. */
export const filmSeconds = (lotId: string): number =>
  (BEAT_TIMINGS[lotId] ?? []).reduce((total, beat) => total + beat.seconds, 0);

/**
 * What each lot must occupy on screen, set by the edit.
 *
 * LOT-1003 and LOT-1004 pause indefinitely for the operator, so their number is
 * the shot length MINUS a nominal 3s press: 49 -> 46 and 23 -> 20. Holding the
 * button longer makes that take longer, which is the intended trade — the pause
 * belongs to the person being filmed.
 *
 * Every target is longer than both the raw pacing and the real machine time, so
 * fitting ADDS time rather than compressing it. `scripts/time_golden_runs.py`
 * distributes the slack by weight: agents and the terminal frame grow, mutation
 * and extraction stay brisk.
 */
export const FILM_TARGET_S: Record<string, number> = {
  'LOT-1001': 52,
  'LOT-1002': 48,
  'LOT-1003': 46,
  'LOT-1004': 20,
  'LOT-1005': 7,
};

export const GOLDEN_LOTS = Object.keys(BEAT_TIMINGS);
