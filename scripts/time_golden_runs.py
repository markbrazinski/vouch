#!/usr/bin/env python3
"""Measure real elapsed time per beat, and derive film durations.

    python scripts/time_golden_runs.py [--hold 1.5] [--write]

Every captured event carries a real `at`, so beat duration is MEASURED from the
golden runs rather than estimated. Two numbers per beat:

  measured_s   what the machine actually took (wall clock, from the capture)
  film_s       what playback should hold that beat for

They are deliberately different. `measured_s` is truth and never changes.
`film_s` is presentation, and this script is the first place a duration has been
allowed to exist at all — the capture itself stores only boundaries.

TWO MEASUREMENT RULES, both of which matter:

  * A beat's span is from the previous beat's last event to its OWN last event.
    An event's timestamp is when that step FINISHED, so the work it represents
    happened in the interval before it. Measuring first-to-last inside a beat
    would report the verifier as taking 0.0s whenever it emitted one event.

  * Operator latency is NOT machine time. On a human-gated lot the wall clock
    between the question and the answer is however long the person (here, the
    capture harness) took to respond — 61s on LOT-1003. That is excluded and
    replaced by the film hold, because the film is showing a decision being
    made, not a terminal being typed at.

The hold applies to a human decision and to the terminal frame: the two places
a viewer must be given time to read rather than watch.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden-runs"

#: Beats whose duration is a PERSON, not the machine. Their measured span is
#: operator latency and is replaced by the hold.
HUMAN_BEATS = {"human_gate", "human_authority"}

#: Never let a real beat flash past unreadably, even when the machine was
#: instant. Binding on LOT-1004 genuinely took 16ms; a frame that shows a
#: refusal for 16ms has not communicated it.
FLOOR_S = 0.6

#: A beat marked `safe_to_compress` may run at this fraction of measured time.
#: Extraction and mutation are mechanical: the viewer needs to see that they
#: happened, not to watch them happen.
COMPRESS = 0.35

#: Agent reasoning is the longest real work in every run and the least
#: interesting to watch second-by-second. It is compressed hard but never below
#: the floor that keeps it legible as thinking.
AGENT_CEILING_S = 3.5

#: Total seconds each lot must occupy on screen, set by the edit.
#:
#: LOT-1003 and LOT-1004 pause indefinitely for the operator, so their target
#: is the SHOT length minus a nominal 3s press: 49 -> 46 and 23 -> 20. Hold the
#: button longer on a take and that take runs longer; nothing here can fix
#: that, and it should not try.
FILM_TARGET_S: dict[str, float] = {
    "LOT-1001": 52.0,
    "LOT-1002": 48.0,
    "LOT-1003": 46.0,
    "LOT-1004": 20.0,
    "LOT-1005": 7.0,
}

#: How eagerly each beat absorbs the slack between raw pacing and the target.
#:
#: Every target is LONGER than both the raw pacing and the real machine time,
#: so this distributes added time rather than removing it. Weighting matters
#: more than the totals: spreading it evenly would hold `mutation` — a version
#: bump — as long as an agent reasoning, which inverts what the viewer is meant
#: to be looking at.
#:
#: Agents and the terminal frame take the most because they carry the content;
#: mechanical steps take the least because watching them longer reveals nothing.
STRETCH_WEIGHT: dict[str, float] = {
    "investigator": 3.0,
    "verifier": 3.0,
    "terminal": 2.5,
    "consequence": 2.0,
    "reconciliation": 1.5,
    "disposition": 1.5,
    "security": 1.2,
    "binding": 1.2,
    "evidence_received": 1.0,
    "run_2_start": 1.0,
    "extraction": 0.6,
    "mutation": 0.5,
    "startup": 0.4,
}

#: Beats whose length is the OPERATOR's, not the edit's. Excluded from
#: fitting: stretching a beat that waits for a button press is meaningless.
OPERATOR_BEATS = {"human_gate", "human_authority"}


def parse(at: str) -> datetime:
    return datetime.fromisoformat(at)


def measure(lot: str) -> list[dict]:
    events = {int(e["sequence"]): e for e in json.load(open(GOLDEN / lot / "events.json"))}
    beats = json.load(open(GOLDEN / lot / "beats.json"))
    out: list[dict] = []

    for beat in beats:
        start, end = beat["sequence_start"], beat["sequence_end"]
        # Span = previous beat's last event -> this beat's last event. An event
        # timestamp marks COMPLETION, so the work sits in the interval before it.
        prior = events.get(start - 1) or events.get(start)
        final = events.get(end)
        if prior is None or final is None:
            measured = 0.0
        else:
            measured = max(0.0, (parse(final["at"]) - parse(prior["at"])).total_seconds())

        human = beat["beat_id"] in HUMAN_BEATS
        row = dict(beat)
        row["measured_s"] = round(measured, 3)
        # Recorded so a reader can see WHY a human beat's film time ignores its
        # measurement, rather than finding an unexplained substitution.
        row["measured_is_operator_latency"] = human
        out.append(row)
    return out


def terminal_hold(lot: str, hold: float) -> float:
    """How long the closing frame stays up.

    The hold is the FLOOR, not the answer. Every terminal frame states an
    Outcome, a Why and a Next Action, but they are not the same size: LOT-1001
    says "released, 500 kg usable" while LOT-1002 says "quarantined, 462 < 480,
    C-417 blocked, C-418 started" — four facts and a causal chain between two
    production orders.

    Scaled by what the frame actually has to carry, measured from the run: each
    readiness transition and each executed recovery is another thing the viewer
    must read before the cut.
    """
    manifest = json.load(open(GOLDEN / lot / "manifest.json"))
    consequence = manifest.get("production_consequence") or {}
    facts = len(consequence.get("readiness_changes") or [])
    recovery = consequence.get("recovery") or {}
    if recovery.get("executed") or recovery.get("blocked_order_id"):
        facts += 1
    return round(hold + 0.5 * facts, 2)


def film_time(beat: dict, hold: float, lot: str) -> float:
    """What playback should hold this beat for."""
    beat_id = beat["beat_id"]
    if beat_id == "terminal":
        return terminal_hold(lot, hold)

    # A person deciding, and the frame that states the result. Both are read,
    # not watched, so both get the hold outright.
    #
    # `interaction_required` rather than the beat id: LOT-1005's security halt
    # emits QUALITY_DECISION_REQUIRED with no question and no options, so its
    # human_gate beat is an escalation nobody answers. Holding it as a decision
    # would stage a deliberation that never happened.
    if beat_id == "human_gate":
        return hold if beat["interaction_required"] else round(FLOOR_S, 2)
    if beat_id == "human_authority":
        return hold
    if beat_id == "startup":
        return round(FLOOR_S, 2)

    measured = beat["measured_s"]
    if beat["safe_to_compress"]:
        scaled = measured * COMPRESS
    elif beat_id in ("investigator", "verifier"):
        # Real reasoning, compressed to a watchable length. The proportion
        # between the two agents is preserved by the min(): a verifier that
        # genuinely ran longer still reads as longer, up to the ceiling.
        scaled = min(measured, AGENT_CEILING_S)
    else:
        scaled = measured

    return round(max(scaled, FLOOR_S), 2)


def fit_to_target(beats: list[dict], target: float) -> list[dict]:
    """Stretch the auto-playing beats so the run occupies exactly `target`.

    Time is added in proportion to STRETCH_WEIGHT, so the beats a viewer is
    actually reading grow and the mechanical ones stay brisk. An operator beat
    is left alone — its length belongs to the person pressing the button, and it
    is excluded from the arithmetic on a gated lot rather than being padded.

    Returns the beats with `film_s` replaced. Never shortens below the existing
    value: every target here is longer than the raw pacing, and a target that
    was not would need a different rule than "spread the slack".
    """
    auto = [b for b in beats if b["beat_id"] not in OPERATOR_BEATS]
    # A gate that WAITS contributes nothing to the automated length: the clock
    # is stopped until the button is pressed, and the 3s already subtracted from
    # the shot length is what covers it. Counting its placeholder hold as well
    # would charge the press twice. A gate nobody answers (LOT-1005's security
    # halt) still plays on a timer, so it still counts.
    fixed = sum(
        b["film_s"]
        for b in beats
        if b["beat_id"] in OPERATOR_BEATS and not b.get("interaction_required")
    )
    current = sum(b["film_s"] for b in auto)
    slack = target - fixed - current

    if slack <= 0:
        # Nothing to distribute. Left unchanged rather than compressed, so a
        # shorter target shows up as an overrun in the report instead of
        # silently squeezing beats below their readable floor.
        return beats

    weights = [STRETCH_WEIGHT.get(b["beat_id"], 1.0) for b in auto]
    total_weight = sum(weights) or 1.0
    for beat, weight in zip(auto, weights):
        beat["film_s"] = round(beat["film_s"] + slack * (weight / total_weight), 2)

    # Absorb rounding drift into the terminal frame, which is the one beat whose
    # exact length is a matter of taste rather than legibility.
    drift = target - sum(b["film_s"] for b in beats)
    terminal = next((b for b in reversed(beats) if b["beat_id"] == "terminal"), None)
    if terminal is not None:
        terminal["film_s"] = round(max(terminal["film_s"] + drift, FLOOR_S), 2)
    return beats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=1.5,
                    help="seconds to hold a human decision or a terminal frame")
    ap.add_argument("--write", action="store_true",
                    help="write timings back into each beats.json")
    ap.add_argument("--raw", action="store_true",
                    help="show the unfitted pacing, ignoring FILM_TARGET_S")
    args = ap.parse_args()

    lots = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
    grand_measured = grand_film = 0.0

    for lot in lots:
        beats = measure(lot)
        for beat in beats:
            beat["film_s"] = film_time(beat, args.hold, lot)
        target = FILM_TARGET_S.get(lot)
        if target and not args.raw:
            beats = fit_to_target(beats, target)

        # Machine time excludes operator latency: it is not something the
        # factory did.
        machine = sum(b["measured_s"] for b in beats if not b["measured_is_operator_latency"])
        film = sum(b["film_s"] for b in beats)
        grand_measured += machine
        grand_film += film

        print(f"\n{lot}  —  machine {machine:6.2f}s   film {film:6.2f}s   ({len(beats)} beats)")
        print(f"  {'beat':18} {'run':>3} {'seq':>9} {'measured':>9} {'film':>7}")
        for b in beats:
            span = f"{b['sequence_start']}-{b['sequence_end']}"
            note = ""
            if b["measured_is_operator_latency"]:
                note = "  <- operator latency, replaced by hold"
            elif b["beat_id"] == "terminal":
                note = "  <- hold"
            print(f"  {b['beat_id']:18} {b['run']:>3} {span:>9} "
                  f"{b['measured_s']:>8.2f}s {b['film_s']:>6.2f}s{note}")

        if args.write:
            path = GOLDEN / lot / "beats.json"
            path.write_text(json.dumps(beats, indent=1) + "\n")

    print(f"\n{'':18} TOTAL machine {grand_measured:6.2f}s   film {grand_film:6.2f}s")
    if args.write:
        print("wrote film_s and measured_s into every beats.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
