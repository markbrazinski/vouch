"""DynamoDB-backed authoritative corpus (audit-2 F5).

The audit found the AgentCore entrypoint building `build_corpus()` — the
fixture world — holding lots, orders and inventory in process memory, while
only DecisionRecords went to DynamoDB. A runtime whose *manufacturing truth*
lives in a Python dict is not a control plane; it is a demo that survives
restarts only in its paperwork.

`DynamoCorpus` implements the SAME `Corpus` read surface the pipeline, tools
and deterministic checks already consume, so nothing above it changes. What
changes is where the objects come from and where mutations land:

    put(kind, key, value)   ->  PutItem, write-through
    get(kind, key)          ->  GetItem, read-through (cached per instance run)
    bump(kind, key, **)     ->  read-modify-PutItem with the new state_version
    all(kind)               ->  Query on the kind partition

## Why read-through with a per-instance cache

A single decision reads the same lot and spec repeatedly (tools, basis checks,
policy, consume). Re-fetching each time would multiply latency for no
correctness gain, because the ONE place staleness could cause harm — the moment
of mutation — is protected by the capability's `state_version` binding and the
transaction's `ConditionExpression`. If the cached version is stale, the
transaction refuses; it cannot silently apply.

`refresh()` drops the cache, which is what the resume path uses so a rehydrated
case reads the CURRENT lot version rather than the one it saw last run
(audit-2 F8).

## Fail closed

Every operation raises `VouchFailure(PERSISTENCE_FAILURE)` when DynamoDB is
unreachable. There is deliberately NO fallback to memory: a silent downgrade
would mean the runtime reporting authorized mutations against state that
evaporates, which is exactly the condition F5 exists to remove.

ponytail: JSON-document-per-item, not an attribute-per-field mapping. The
corpus objects are frozen dataclasses with nested tuples; a field mapping would
be a schema migration surface for no gain, and these items are far below the
400KB limit.
"""

from __future__ import annotations

import json
from dataclasses import asdict, fields, is_dataclass, replace
from typing import Any

from .contracts import FailureCategory, VouchFailure
from .corpus import (
    ApprovedDeviation,
    ApprovedSubstitution,
    Corpus,
    CustomerOverlay,
    InventoryRecord,
    Lot,
    Material,
    MaterialRequirementLine,
    MethodEquivalence,
    PlannedCoverage,
    ProductionOrder,
    Requirement,
    SpecificationRevision,
    Supplier,
    SupplierQualification,
    SupplierSite,
)

#: kind -> dataclass. The corpus is typed, so rehydration is typed: an item
#: whose kind has no class here is a bug, not a dict to pass through.
KINDS: dict[str, type] = {
    "material": Material,
    "supplier": Supplier,
    "supplier_site": SupplierSite,
    "supplier_qualification": SupplierQualification,
    "spec_revision": SpecificationRevision,
    "customer_overlay": CustomerOverlay,
    "deviation": ApprovedDeviation,
    "equivalence": MethodEquivalence,
    "production_order": ProductionOrder,
    "lot": Lot,
    "inventory": InventoryRecord,
    "substitution": ApprovedSubstitution,
    "planned_coverage": PlannedCoverage,
}

#: Fields that are tuples of nested dataclasses, so rehydration rebuilds them
#: rather than handing the pipeline a list of dicts that looks almost right.
NESTED: dict[tuple[str, str], type] = {
    ("spec_revision", "requirements"): Requirement,
    ("customer_overlay", "requirements"): Requirement,
    ("production_order", "requirements"): MaterialRequirementLine,
}

#: Kinds that are plain dicts rather than dataclasses (QA reviews).
DICT_KINDS = frozenset({"qa_review"})

#: Fields the capability-consume transaction updates as TOP-LEVEL DynamoDB
#: attributes rather than inside the JSON document (audit-2 F5/F6).
#:
#: There is exactly one authoritative representation of these values: the
#: top-level attribute. It has to be top-level because a conditional update
#: cannot condition on or patch a field buried in a JSON blob, and the whole
#: authority model rests on `ConditionExpression`. `_decode` overlays them back
#: onto the rehydrated object, so a reader never sees a stale document value.
LIVE_ATTRIBUTES: dict[str, tuple[str, ...]] = {
    "lot": ("status", "state_version"),
    "production_order": ("status", "planned_slot", "state_version"),
    "inventory": ("usable", "state_version"),
}


def _encode(kind: str, value: Any) -> str:
    if is_dataclass(value):
        return json.dumps(asdict(value), sort_keys=True, default=str)
    return json.dumps(value, sort_keys=True, default=str)


def _decode(kind: str, document: str, item: dict | None = None) -> Any:
    """Rebuild a corpus object, overlaying the live top-level attributes.

    The document is the object as last written whole; the top-level attributes
    are what the authority transaction has since changed. The attributes win —
    that is what makes them authoritative.
    """
    payload = json.loads(document)
    for name in LIVE_ATTRIBUTES.get(kind, ()):
        live = (item or {}).get(name)
        if live is None:
            continue
        if "N" in live:
            payload[name] = int(float(live["N"]))
        elif "BOOL" in live:
            payload[name] = live["BOOL"]
        else:
            payload[name] = live["S"]
    if kind in DICT_KINDS:
        return payload
    cls = KINDS.get(kind)
    if cls is None:
        return payload
    known = {f.name for f in fields(cls)}
    kwargs = {k: v for k, v in payload.items() if k in known}
    for name, value in list(kwargs.items()):
        nested = NESTED.get((kind, name))
        if nested is not None and isinstance(value, list):
            kwargs[name] = tuple(
                nested(**{k: v for k, v in item.items()
                          if k in {f.name for f in fields(nested)}})
                for item in value
            )
        elif isinstance(value, list):
            kwargs[name] = tuple(value)
    return cls(**kwargs)


def corpus_pk(kind: str) -> str:
    return f"CORPUS#{kind}"


def corpus_item(kind: str, key: str, value: Any) -> dict:
    """One corpus item: the whole object, plus its live authoritative fields.

    Shared by `DynamoCorpus.put` and the seeding path so there is a single
    definition of the item shape the authority transaction conditions on.
    """
    item = {
        "pk": {"S": corpus_pk(kind)},
        "sk": {"S": key},
        "kind": {"S": kind},
        "document": {"S": _encode(kind, value)},
    }
    for name in LIVE_ATTRIBUTES.get(kind, ()):
        live = getattr(value, name, None)
        if live is None:
            continue
        if isinstance(live, bool):
            item[name] = {"BOOL": live}
        elif isinstance(live, (int, float)):
            item[name] = {"N": str(live)}
        else:
            item[name] = {"S": str(live)}
    # Inventory has no state_version of its own on the dataclass; it tracks the
    # lot's, so a replay cannot re-apply a delta.
    if kind == "inventory" and "state_version" not in item:
        item["state_version"] = {"N": "1"}
    return item


class DynamoCorpus(Corpus):
    """The authoritative corpus, in DynamoDB.

    Same interface as `Corpus`; different durability. Reads go through the
    table, writes land in the table, and an unreachable table is a typed
    failure rather than a quiet in-memory success.
    """

    kind = "AWS_DYNAMODB"

    def __init__(self, table: str | None = None, *, region: str | None = None) -> None:
        super().__init__()
        from ..config import load

        self.table = table or load().state_table
        if not self.table:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                "no state table configured (VOUCH_STATE_TABLE)",
            )
        self._region = region
        self._ddb = None
        #: Kinds whose full partition has been fetched, so `all()` is not a
        #: repeated scan within one decision.
        self._loaded: set[str] = set()

    @property
    def ddb(self):
        if self._ddb is None:
            from .aws import _client

            self._ddb = _client("dynamodb", self._region)
        return self._ddb

    def refresh(self) -> None:
        """Drop every cached object. Used when resuming a case (F8)."""
        self._t.clear()
        self._loaded.clear()

    # -- generic surface ---------------------------------------------------
    def put(self, kind: str, key: str, value: Any) -> None:
        try:
            self.ddb.put_item(
                TableName=self.table,
                Item=corpus_item(kind, key, value),
            )
        except VouchFailure:
            raise
        except Exception as exc:  # noqa: BLE001
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                f"could not write {kind} {key}: {exc}",
            ) from exc
        super().put(kind, key, value)

    def get(self, kind: str, key: str) -> Any:
        cached = super().get(kind, key)
        if cached is not None or kind in self._loaded:
            return cached
        try:
            item = self.ddb.get_item(
                TableName=self.table,
                Key={"pk": {"S": f"CORPUS#{kind}"}, "sk": {"S": key}},
            ).get("Item")
        except Exception as exc:  # noqa: BLE001
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                f"could not read {kind} {key}: {exc}",
            ) from exc
        if item is None:
            return None
        value = _decode(kind, item["document"]["S"], item)
        super().put(kind, key, value)
        return value

    def all(self, kind: str) -> list[Any]:
        if kind not in self._loaded:
            try:
                response = self.ddb.query(
                    TableName=self.table,
                    KeyConditionExpression="pk = :pk",
                    ExpressionAttributeValues={":pk": {"S": f"CORPUS#{kind}"}},
                )
            except Exception as exc:  # noqa: BLE001
                raise VouchFailure(
                    FailureCategory.PERSISTENCE_FAILURE,
                    f"could not list {kind}: {exc}",
                ) from exc
            for item in response.get("Items", []):
                super().put(
                    kind, item["sk"]["S"], _decode(kind, item["document"]["S"], item)
                )
            self._loaded.add(kind)
        return super().all(kind)

    def bump(self, kind: str, key: str, **changes: Any) -> Any:
        """Apply changes and increment state_version, writing through.

        The version check that makes this safe lives in the capability consume
        path, exactly as it does for the in-memory corpus. This method is only
        reachable from a mutation the gate already authorized.
        """
        current = self.get(kind, key)
        if current is None:
            raise KeyError(f"unknown {kind} {key}")
        updated = replace(current, state_version=current.state_version + 1, **changes)
        self.put(kind, key, updated)
        return updated

    def seed(self, source: Corpus) -> int:
        """Write an entire corpus into the table. Provisioning, not runtime.

        Used once to populate authoritative state. Deliberately explicit and
        never called from the decision path, so production can never
        accidentally re-seed itself with fixtures.
        """
        written = 0
        for kind, rows in source._t.items():
            for key, value in rows.items():
                self.put(kind, key, value)
                written += 1
        return written


__all__ = ["DynamoCorpus", "KINDS", "LIVE_ATTRIBUTES", "corpus_item", "corpus_pk"]
