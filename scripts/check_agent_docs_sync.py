#!/usr/bin/env python3
"""Verify AGENTS.md and CLAUDE.md are byte-for-byte identical.

AGENTS.md is canonical. Run with --fix to copy it over CLAUDE.md.
Exit 0 when in sync, 1 when they differ or a file is missing.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL = ROOT / "AGENTS.md"
MIRROR = ROOT / "CLAUDE.md"


def check(fix: bool = False) -> int:
    if not CANONICAL.exists():
        print(f"FAIL: canonical {CANONICAL.name} is missing")
        return 1

    canonical_bytes = CANONICAL.read_bytes()

    if fix:
        MIRROR.write_bytes(canonical_bytes)
        print(f"OK: wrote {CANONICAL.name} -> {MIRROR.name} ({len(canonical_bytes)} bytes)")
        return 0

    if not MIRROR.exists():
        print(f"FAIL: {MIRROR.name} is missing. Run with --fix.")
        return 1

    mirror_bytes = MIRROR.read_bytes()
    if canonical_bytes == mirror_bytes:
        print(f"OK: {CANONICAL.name} and {MIRROR.name} are identical ({len(canonical_bytes)} bytes)")
        return 0

    print(f"FAIL: {CANONICAL.name} and {MIRROR.name} differ.")
    print(f"  {CANONICAL.name}: {len(canonical_bytes)} bytes")
    print(f"  {MIRROR.name}: {len(mirror_bytes)} bytes")
    print("Run: python scripts/check_agent_docs_sync.py --fix")
    return 1


if __name__ == "__main__":
    sys.exit(check(fix="--fix" in sys.argv))
