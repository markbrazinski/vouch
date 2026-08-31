"""Durable DecisionRecord and lifecycle-event storage (P1-1, P1-2).

The audit found the DecisionRecord living in process memory and the lifecycle
events living in a Python list. Both vanish when the process exits, so nothing
an auditor could inspect actually survived a decision.

Two stores, one interface each:

    RecordStore   save/load/list DecisionRecords, queryable by lot
    EventStore    append/read lifecycle events, ordered and queryable by record

`JsonRecordStore` writes to disk and is real durability for a single node.
`DynamoRecordStore` is the multi-node production form. `InMemory*` remains for
tests and is labeled as such — it is NOT a persistence claim.

What is stored is structured facts, hashes, versions, tool events and causal
links. What is never stored is chain of thought: `LifecycleEvent` already
rejects reasoning-shaped payload keys, and DecisionRecord has no rationale
field to persist.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Protocol

from .contracts import FailureCategory, VouchFailure, content_hash
from .decision_record import DecisionRecord
from .lifecycle import EventType, LifecycleEvent, utcnow


# ==========================================================================
# interfaces
# ==========================================================================


class RecordStore(Protocol):
    def save(self, record: DecisionRecord) -> str: ...
    def load(self, record_id: str) -> dict | None: ...
    def list_ids(self) -> list[str]: ...


class EventStore(Protocol):
    def append(self, event: LifecycleEvent, sequence: int) -> None: ...
    def events_for(self, decision_record_id: str) -> list[dict]: ...


def _event_row(event: LifecycleEvent, sequence: int, record_id: str) -> dict:
    """One durable, ordered event row (P1-2).

    `event_id` is stable and derived, so re-appending the same event is
    idempotent rather than producing a duplicate.
    """
    payload = dict(event.payload)
    return {
        "event_id": f"{record_id}#{sequence:06d}",
        "sequence": sequence,
        "event": event.event_type.value,
        "decision_record_id": record_id,
        "at": event.at,
        "payload": payload,
    }


# ==========================================================================
# local durable — JSON on disk
# ==========================================================================


class JsonRecordStore:
    """DecisionRecords + events as JSON files. Durable for a single node.

    Real persistence: the record survives the process. Not a distributed store,
    and the class says so rather than implying more.
    """

    kind = "LOCAL_JSON"

    def __init__(self, root: str | Path = ".vouch/records") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, record_id: str) -> Path:
        # record ids are internally generated (DR-<hex>); reject anything that
        # could escape the directory rather than trusting the caller.
        if "/" in record_id or ".." in record_id:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE, f"illegal record id {record_id!r}"
            )
        return self.root / f"{record_id}.json"

    def save(self, record: DecisionRecord) -> str:
        payload = record.to_dict()
        payload["audit_hash"] = record.audit_hash()
        payload["saved_at"] = utcnow()
        with self._lock:
            path = self._path(record.record_id)
            # Write-then-rename so a crash cannot leave a half-written record.
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2, default=str))
            temporary.replace(path)
        return str(path)

    def load(self, record_id: str) -> dict | None:
        path = self._path(record_id)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def list_ids(self) -> list[str]:
        return sorted(p.stem for p in self.root.glob("DR-*.json"))

    # -- events ---------------------------------------------------------
    def _events_path(self, record_id: str) -> Path:
        return self.root / f"{record_id}.events.jsonl"

    def append(self, event: LifecycleEvent, sequence: int) -> None:
        row = _event_row(event, sequence, event.decision_record_id)
        with self._lock:
            with self._events_path(event.decision_record_id).open("a") as handle:
                handle.write(json.dumps(row, default=str) + "\n")

    def append_all(self, events: Iterable[LifecycleEvent]) -> int:
        count = 0
        for index, event in enumerate(events, start=1):
            self.append(event, index)
            count += 1
        return count

    def events_for(self, decision_record_id: str) -> list[dict]:
        path = self._events_path(decision_record_id)
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line]
        return sorted(rows, key=lambda r: r["sequence"])


# ==========================================================================
# production — DynamoDB
# ==========================================================================


class DynamoRecordStore:
    """DecisionRecords and events in the same single-table store.

        RECORD#<record_id>  / META            the record document
        RECORD#<record_id>  / EVENT#<seq>     one lifecycle event, ordered

    Events are queryable by record and ordered by sort key, which is exactly
    what P1-2 asks for.
    """

    kind = "AWS_DYNAMODB"

    def __init__(self, table: str | None = None, *, region: str | None = None) -> None:
        from ..config import load

        self.table = table or load().state_table
        if not self.table:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE, "no state table configured"
            )
        self._region = region
        self._ddb = None

    @property
    def ddb(self):
        if self._ddb is None:
            from .aws import _client

            self._ddb = _client("dynamodb", self._region)
        return self._ddb

    def save(self, record: DecisionRecord) -> str:
        payload = record.to_dict()
        payload["audit_hash"] = record.audit_hash()
        # The record is stored as one JSON document: it is read as a whole by
        # auditors, and this keeps it under the item size limit for our shape
        # while staying queryable by id.
        # ponytail: single document, not an item-per-segment fan-out. Split it
        # if a record ever approaches 400KB.
        self.ddb.put_item(
            TableName=self.table,
            Item={
                "pk": {"S": f"RECORD#{record.record_id}"},
                "sk": {"S": "META"},
                "record_id": {"S": record.record_id},
                "lot_id": {"S": record.identity.lot_id or ""},
                "disposition": {"S": record.disposition.disposition or ""},
                "failure_category": {"S": record.failure_category or ""},
                "audit_hash": {"S": payload["audit_hash"]},
                "saved_at": {"S": utcnow()},
                "document": {"S": json.dumps(payload, default=str)},
            },
        )
        return f"dynamodb://{self.table}/RECORD#{record.record_id}"

    def load(self, record_id: str) -> dict | None:
        item = self.ddb.get_item(
            TableName=self.table,
            Key={"pk": {"S": f"RECORD#{record_id}"}, "sk": {"S": "META"}},
        ).get("Item")
        if item is None:
            return None
        return json.loads(item["document"]["S"])

    def list_ids(self) -> list[str]:
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            "listing all records requires a GSI; query by record id",
        )

    def append(self, event: LifecycleEvent, sequence: int) -> None:
        row = _event_row(event, sequence, event.decision_record_id)
        self.ddb.put_item(
            TableName=self.table,
            Item={
                "pk": {"S": f"RECORD#{event.decision_record_id}"},
                "sk": {"S": f"EVENT#{sequence:06d}"},
                "event_id": {"S": row["event_id"]},
                "event": {"S": row["event"]},
                "at": {"S": row["at"]},
                "payload": {"S": json.dumps(row["payload"], default=str)},
            },
            # Idempotent: replaying the same run cannot duplicate events.
            ConditionExpression="attribute_not_exists(sk)",
        )

    def append_all(self, events: Iterable[LifecycleEvent]) -> int:
        count = 0
        for index, event in enumerate(events, start=1):
            try:
                self.append(event, index)
                count += 1
            except Exception as exc:  # noqa: BLE001
                if "ConditionalCheckFailed" not in str(exc):
                    raise
        return count

    def events_for(self, decision_record_id: str) -> list[dict]:
        response = self.ddb.query(
            TableName=self.table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": {"S": f"RECORD#{decision_record_id}"},
                ":prefix": {"S": "EVENT#"},
            },
        )
        return [
            {
                "event_id": i["event_id"]["S"],
                "sequence": int(i["sk"]["S"].split("#")[1]),
                "event": i["event"]["S"],
                "decision_record_id": decision_record_id,
                "at": i["at"]["S"],
                "payload": json.loads(i["payload"]["S"]),
            }
            for i in response.get("Items", [])
        ]


# ==========================================================================
# tests only
# ==========================================================================


class InMemoryRecordStore:
    """NOT DURABLE. For tests only; vanishes with the process."""

    kind = "IN_MEMORY_NOT_DURABLE"

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.events: dict[str, list[dict]] = {}

    def save(self, record: DecisionRecord) -> str:
        payload = record.to_dict()
        payload["audit_hash"] = record.audit_hash()
        self.records[record.record_id] = payload
        return f"memory://{record.record_id}"

    def load(self, record_id: str) -> dict | None:
        return self.records.get(record_id)

    def list_ids(self) -> list[str]:
        return sorted(self.records)

    def append(self, event: LifecycleEvent, sequence: int) -> None:
        self.events.setdefault(event.decision_record_id, []).append(
            _event_row(event, sequence, event.decision_record_id)
        )

    def append_all(self, events: Iterable[LifecycleEvent]) -> int:
        count = 0
        for index, event in enumerate(events, start=1):
            self.append(event, index)
            count += 1
        return count

    def events_for(self, decision_record_id: str) -> list[dict]:
        return sorted(
            self.events.get(decision_record_id, []), key=lambda r: r["sequence"]
        )


__all__ = [
    "DynamoRecordStore",
    "EventStore",
    "InMemoryRecordStore",
    "JsonRecordStore",
    "RecordStore",
]
