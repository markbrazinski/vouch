#!/usr/bin/env python3
"""Stage src/gatehouse into the AgentCore runtime bundle before packaging.

`agentcore package` zips app/Gatehouse/, so the workflow package has to live
there at build time. Keeping the source of truth in src/ and staging on demand
avoids a second copy drifting out of sync.

Usage:
    python scripts/stage_runtime.py          # stage
    python scripts/stage_runtime.py --clean  # remove staged copy
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "src" / "gatehouse"
STAGED = ROOT / "app" / "Gatehouse" / "src" / "gatehouse"


def clean() -> None:
    if STAGED.parent.exists():
        shutil.rmtree(STAGED.parent)
        print(f"removed {STAGED.parent.relative_to(ROOT)}")


def stage() -> None:
    if not SOURCE.exists():
        raise SystemExit(f"missing source package: {SOURCE}")
    clean()
    shutil.copytree(
        SOURCE, STAGED, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
    )
    print(f"staged {SOURCE.relative_to(ROOT)} -> {STAGED.relative_to(ROOT)}")


if __name__ == "__main__":
    clean() if "--clean" in sys.argv else stage()
