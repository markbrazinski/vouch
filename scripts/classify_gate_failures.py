#!/usr/bin/env python3
"""Classify each Hero acceptance failure by its actual cause.

    AWS_PROFILE=gatehouse python scripts/classify_gate_failures.py DR-... DR-...

The distinction the freeze audit turns on:

  BRIEF_CONTRACT_VIOLATION  a brief contradicted the authoritative corpus and
                            still did after its bounded retry. A defect in the
                            brief, and repairable.
  MATERIAL_DISAGREEMENT     two contract-valid briefs reached different
                            defensible judgments. The agentic seam doing its
                            job; not repairable without choosing a winner,
                            which the commission forbids.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vouch.config import load  # noqa: E402
from vouch.v2.persistence import DynamoRecordStore  # noqa: E402


def classify(record: dict) -> tuple[str, str]:
    for role in ("investigator", "verifier"):
        segment = record.get(role) or {}
        if segment.get("failure_category") == "BRIEF_CONTRACT_VIOLATION":
            return "BRIEF_CONTRACT_VIOLATION", f"{role}: {segment.get('failure', '')[:160]}"
        if segment.get("failure_category"):
            return segment["failure_category"], f"{role}: {segment.get('failure', '')[:160]}"

    reconciliation = record.get("reconciliation") or {}
    if reconciliation.get("outcome") == "MATERIAL_DISAGREEMENT":
        return (
            "MATERIAL_DISAGREEMENT",
            f"contract-valid briefs differ on {reconciliation.get('differing_fields')}: "
            f"{reconciliation.get('investigator_values')} vs "
            f"{reconciliation.get('verifier_values')}",
        )

    disposition = (record.get("disposition") or {}).get("disposition")
    return "COMPLETED", f"disposition={disposition}"


def main() -> int:
    store = DynamoRecordStore(load().state_table)
    counts: Counter[str] = Counter()

    for record_id in sys.argv[1:]:
        try:
            record = store.load(record_id)
        except Exception as exc:  # noqa: BLE001
            print(f"{record_id}: LOAD FAILED {exc}")
            continue
        kind, detail = classify(record)
        counts[kind] += 1
        print(f"{record_id}: {kind}\n    {detail}")

    print("\n--- totals ---")
    for kind, n in counts.most_common():
        print(f"  {kind}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
