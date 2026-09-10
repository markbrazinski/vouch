"""Demo state reset, at LOT granularity. Dev/film use only.

Filming a live LOT-1003 run means running it repeatedly: model inference is
non-deterministic, so a take that lands on MATERIAL_DISAGREEMENT may need
several attempts. Re-seeding the whole corpus between takes would roll back
LOT-1001, LOT-1002 and the C-417/C-418 recovery story too, which is both wrong
and slow.

This restores exactly the rows one scenario owns, and nothing else.

Three properties make it safe to expose to a dev-only route:

  * **Whitelisted.** Only lots named in `RESETTABLE` can be reset, and each
    one declares precisely which corpus rows it owns. A caller cannot name an
    arbitrary object, so this is not a general-purpose corpus mutation.

  * **History-preserving.** DecisionRecords are never read, rewritten or
    deleted. A reset rolls back OPERATING STATE — what is true of the plant
    now — and says nothing about what Vouch decided in the past. Previous runs
    stay in Records as truthful history, which is the whole point of an audit
    ledger that a demo cannot launder.

  * **Version-advancing, not version-rewinding.** The canonical rows are
    rebuilt from `build_corpus()` but their `state_version` is set ABOVE the
    version currently in the store, never back to 1. Capabilities bind to an
    observed state_version and refuse when it moves (`authority.py`), so
    rewinding would let a capability issued before the reset replay against
    the restored lot. Advancing keeps that protection intact: every
    outstanding capability is stale, exactly as it should be.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .fixtures import build_corpus

#: The lots a reset may touch, and the rows each one owns.
#:
#: Stated per lot rather than derived, because "which rows does this scenario
#: own" is a claim that must be reviewable. A derived version would quietly
#: widen when the fixture grows.
RESETTABLE: dict[str, tuple[tuple[str, str], ...]] = {
    "LOT-1003": (
        ("lot", "LOT-1003"),
        ("inventory", "LOT-1003"),
        # C-419 is LOT-1003's consequence and nothing else's: it is short by
        # exactly LOT-1003's 200 kg. C-417 / C-418 belong to the alloy story
        # and are deliberately absent.
        ("production_order", "C-419"),
        # The queued coverage that makes C-419 read AT_RISK rather than
        # BLOCKED before the applicability question is settled.
        ("planned_coverage", "PC-2"),
    ),
}


class NotResettable(ValueError):
    """The caller named a lot that is not on the whitelist."""


def reset_lot(corpus: Any, lot_id: str) -> dict:
    """Restore one scenario's canonical pre-decision state.

    Returns what was restored, so a caller can show the operator the state it
    is now in rather than asserting success blindly.
    """
    rows = RESETTABLE.get(lot_id)
    if rows is None:
        raise NotResettable(
            f"{lot_id} is not a resettable demo lot; "
            f"allowed: {sorted(RESETTABLE)}"
        )

    canonical = build_corpus()
    restored: list[str] = []

    for kind, key in rows:
        pristine = canonical.get(kind, key)
        if pristine is None:  # pragma: no cover - fixture drift
            continue
        current = corpus.get(kind, key)
        # Advance past whatever the store holds. See the module docstring:
        # rewinding a state_version would re-validate stale capabilities.
        if hasattr(pristine, "state_version"):
            current_version = getattr(current, "state_version", 0) or 0
            pristine = replace(
                pristine,
                state_version=max(current_version + 1, pristine.state_version),
            )
        corpus.put(kind, key, pristine)
        restored.append(f"{kind}/{key}")

    lot = corpus.get("lot", lot_id)
    inventory = corpus.get("inventory", lot_id)
    return {
        "lot_id": lot_id,
        "restored": restored,
        "lot_status": getattr(lot, "status", ""),
        "lot_state_version": getattr(lot, "state_version", 0),
        "inventory_usable": bool(getattr(inventory, "usable", False)),
        "readiness": {
            key: getattr(corpus.get(kind, key), "status", "")
            for kind, key in rows
            if kind == "production_order"
        },
    }


__all__ = ["RESETTABLE", "NotResettable", "reset_lot"]
