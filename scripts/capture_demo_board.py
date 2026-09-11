#!/usr/bin/env python3
"""Capture the canonical OPENING board for Demo Mode.

Demo Mode replays five archived golden runs with no backend. The runs carry
their own truth, but the boards they start from — Incoming's arrivals and
Today's production plan — are read models a live deployment serves from
DynamoDB. A clone has neither.

So the opening board is captured here rather than hand-written, from the SAME
`get_today` / `list_decisions` code path the deployed runtime answers with,
against the canonical seeded corpus (`VOUCH_MODE=local`). Hand-writing it would
create a second source of truth able to drift from the corpus the golden runs
were actually captured against.

What this captures is the state BEFORE any decision: five lots RECEIVED, three
orders AWAITING_QUALITY. Everything after that comes from the archived runs'
own recorded consequences, never from a second table of expected endings.

    .venv/bin/python scripts/capture_demo_board.py

Writes `frontend/src/demo/opening-board.json`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "app" / "Gatehouse"))

os.environ["VOUCH_MODE"] = "local"

import main as runtime  # noqa: E402  — the REAL action handler, not a copy

OUT = ROOT / "frontend" / "src" / "demo" / "opening-board.json"

# The lots Demo Mode exposes. LOT-1007 is a real corpus lot with no archived
# run, so Incoming must not offer it — a row that cannot be opened is worse
# than no row.
DEMO_LOTS = ("LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004", "LOT-1005")


def main() -> int:
    today = runtime.invoke({"action": "get_today"})
    decisions = runtime.invoke({"action": "list_decisions", "limit": 50})

    for name, body in (("get_today", today), ("list_decisions", decisions)):
        if not body.get("ok"):
            print(f"FAIL: {name} -> {body.get('error')}", file=sys.stderr)
            return 1

    rows = [r for r in decisions.get("rows", []) if r.get("lot_id") in DEMO_LOTS]
    missing = set(DEMO_LOTS) - {r.get("lot_id") for r in rows}
    if missing:
        print(f"FAIL: corpus has no row for {sorted(missing)}", file=sys.stderr)
        return 1

    decisions = {**decisions, "rows": rows, "counts": {"returned": len(rows)}}

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"today": today, "decisions": decisions}, indent=1, default=str) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)} — {len(rows)} lots, "
          f"{sum(len(l.get('orders', [])) for l in today.get('lines', []))} orders")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
