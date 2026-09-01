#!/usr/bin/env python3
"""Seed the demo scenario corpus into the authoritative DynamoDB table.

Provisioning, not runtime. `DynamoCorpus.seed` is deliberately unreachable from
the decision path, so populating authoritative state is an explicit, auditable
act rather than something a workflow can do to itself.

This exists so the Hero flows can run against the fully durable stack — real
DynamoDB corpus, real S3 evidence, real capability transactions — with no
fixture objects anywhere on the path.

    AWS_PROFILE=gatehouse python scripts/seed_demo_corpus.py

Seeding writes every scenario object at its declared initial state, overwriting
whatever a previous demo run left behind. That is what makes a Hero run
repeatable: re-seed, and LOT-1002 is RECEIVED and C-417 is READY again.

There is deliberately no delete: `DynamoCorpus` exposes no way to remove an
authoritative row, and this script is not the place to introduce one.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from vouch.config import assert_vouch_identity, load  # noqa: E402
from vouch.v2.fixtures import build_corpus  # noqa: E402
from vouch.v2.state import DynamoCorpus  # noqa: E402


def main() -> int:
    identity = assert_vouch_identity()
    config = load()
    print(f"identity: {identity}")
    print(f"table:    {config.state_table}")

    corpus = DynamoCorpus(config.state_table)
    written = corpus.seed(build_corpus())
    print(f"seeded:   {written} rows")

    for kind in ("lot", "production_order", "inventory", "material_spec_revision"):
        print(f"  {kind}: {len(corpus.all(kind))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
