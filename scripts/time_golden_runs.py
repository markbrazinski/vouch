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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hold", type=float, default=1.5,
                    help="seconds to hold a human decision or a terminal frame")
    ap.add_argument("--write", action="store_true",
                    help="write timings back into each beats.json")
    args = ap.parse_args()

    lots = sorted(p.name for p in GOLDEN.iterdir() if p.is_dir())
    grand_measured = grand_film = 0.0

    for lot in lots:
        beats = measure(lot)
        for beat in beats:
            beat["film_s"] = film_time(beat, args.hold, lot)

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
