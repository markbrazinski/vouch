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



#: The lots the judge demo is made of, in the order Incoming lists them.
#:
#: Named explicitly so the reset RESULT can be checked against the scenarios the
#: demo actually claims, rather than against whatever the fixture happens to
#: contain. A fixture that grew a sixth lot would otherwise silently widen what
#: "the canonical demo" means.
CANONICAL_LOTS: tuple[str, ...] = (
    "LOT-1001", "LOT-1002", "LOT-1003", "LOT-1004", "LOT-1005",
)

#: The production orders whose readiness tells the Today story.
CANONICAL_ORDERS: tuple[str, ...] = ("C-417", "C-418", "C-419")


def reset_demo(corpus: Any) -> dict:
    """Restore the WHOLE canonical demo to its opening state.

    This is `reset_lot`'s sibling, not its generalisation. `reset_lot` rolls
    back one scenario so a take can be re-filmed without disturbing the others;
    this rolls back every scenario, which is what a judge needs between passes.

    It takes NO arguments beyond the corpus. That is the security property: the
    only thing a caller can ask for is "the canonical demo, as seeded", so
    reaching this action can never become a way to write a chosen value into
    authoritative state. Compare `reset_lot`, which needs a whitelist precisely
    because it does accept a name.

    The mechanism is `DynamoCorpus.seed(build_corpus())` — the same call
    `scripts/seed_demo_corpus.py` has always made, and the same one the film
    reset path relies on. Nothing new decides anything here:

      * **History-preserving.** DecisionRecords are neither read nor written.
        A reset restores OPERATING STATE — what is true of the plant now — and
        says nothing about what Vouch decided before. Records keeps every prior
        judge run as truthful history, which is the whole point of a ledger a
        demo cannot launder.

      * **Version-advancing.** `seed` advances each row's `state_version` past
        whatever the table holds rather than rewinding it to 1, so every
        capability issued before the reset is stale and refuses. Rewinding
        would re-validate them.

    Returns the restored state rather than a bare acknowledgement, so a caller
    can show what is now true instead of asserting success blindly.
    """
    written = corpus.seed(build_corpus())

    lots = {
        lot_id: getattr(corpus.get("lot", lot_id), "status", "")
        for lot_id in CANONICAL_LOTS
    }
    # Readiness is DERIVED from live inventory, never stored, so it is computed
    # here the same way Today computes it. Reporting the stored `status` field
    # instead would let this claim a readiness the product does not show.
    from .consequences import compute_readiness

    orders = {}
    for order_id in CANONICAL_ORDERS:
        if corpus.get("production_order", order_id) is None:  # pragma: no cover
            continue
        orders[order_id] = compute_readiness(corpus, order_id).readiness.value

    return {
        "scope": "CANONICAL_DEMO",
        "rows_restored": written,
        "lots": lots,
        "readiness": orders,
    }


__all__ = [
    "CANONICAL_LOTS",
    "CANONICAL_ORDERS",
    "RESETTABLE",
    "NotResettable",
    "reset_demo",
    "reset_lot",
]
