#!/usr/bin/env python3
"""Copy the golden packages into the frontend bundle input.

    python scripts/sync_golden_to_frontend.py

`golden-runs/` is the canonical capture output and stays the source of truth.
Vite can only bundle what lives under `frontend/`, and reaching outside the
project root needs `server.fs.allow` plus a tsconfig include — configuration
that exists solely to avoid a copy. The copy is cheaper and more obvious.

Only the three files playback reads are copied. `beats.json` is deliberately NOT
among them: the frontend's timing table is hard-coded in
`src/demo/timing.ts` so playback needs no second parameter, and
shipping a second copy of the boundaries would invite the two to disagree.

Verified by `tests/v2/test_golden_runs.py`, which fails if the copy drifts from
the capture.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "golden-runs"
DEST = ROOT / "frontend" / "src" / "demo" / "packages"

#: What the browser needs. The DecisionRecord and the terminal response are
#: both required: `project()` reads the disposition off the response and the
#: canonical claims off the record.
FILES = ("events.json", "result.json", "decision-record.json", "sources.json")


def main() -> int:
    if not GOLDEN.is_dir():
        print("no golden-runs/ to sync", file=sys.stderr)
        return 1

    DEST.mkdir(parents=True, exist_ok=True)
    copied = 0
    for lot in sorted(p.name for p in GOLDEN.iterdir() if p.is_dir()):
        target = DEST / lot
        target.mkdir(exist_ok=True)
        for name in FILES:
            source = GOLDEN / lot / name
            if not source.exists():
                print(f"  {lot}/{name} missing from the capture", file=sys.stderr)
                return 1
            # Re-serialized rather than byte-copied, so a stray trailing comma
            # or a non-JSON file fails here instead of at bundle time.
            target_path = target / name
            target_path.write_text(
                json.dumps(json.loads(source.read_text()), indent=1) + "\n"
            )
            copied += 1
        print(f"  {lot}: {len(FILES)} files")

    print(f"synced {copied} files -> {DEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
