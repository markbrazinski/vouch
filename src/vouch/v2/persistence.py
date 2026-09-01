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
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Protocol

from .contracts import FailureCategory, VouchFailure, content_hash
from .decision_record import ArchivedRun, DecisionRecord
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
    def append_all(self, events: Iterable[LifecycleEvent], start: int | None = None) -> int: ...
    def next_sequence(self, decision_record_id: str) -> int: ...
    def events_for(
        self, decision_record_id: str, after_sequence: int = 0, limit: int | None = None
    ) -> list[dict]: ...


def _event_identity(event: LifecycleEvent) -> tuple:
    """Stable identity of ONE emitted event, independent of its sequence.

    Change A writes each event twice: once live from the sink, once in the
    terminal `append_all`. `event_id` cannot dedupe that, because it is derived
    from the sequence — a re-append at the next free slot gets a new id and
    lands as a duplicate. Identity has to come from the event itself.

    `at` is included deliberately: it is set once at construction
    (`LifecycleEvent.at`), so the same emitted event always carries the same
    timestamp, while two genuinely separate emissions of the same type — three
    `TOOL_CALLED`s for the same tool, say — stay distinct.
    """
    return (
        event.decision_record_id,
        event.event_type.value,
        event.at,
        content_hash(event.payload),
    )


def _row_identity(row: dict) -> tuple:
    """The same identity, computed from a STORED row rather than a live event."""
    return (
        row.get("decision_record_id", ""),
        row.get("event", ""),
        row.get("at", ""),
        content_hash(row.get("payload") or {}),
    )


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
        # Idempotent on event identity, not on sequence: change A appends each
        # event live and then again in the terminal batch.
        if self._already_stored(event):
            return
        row = _event_row(event, sequence, event.decision_record_id)
        with self._lock:
            with self._events_path(event.decision_record_id).open("a") as handle:
                handle.write(json.dumps(row, default=str) + "\n")

    def _already_stored(self, event: LifecycleEvent) -> bool:
        identity = _event_identity(event)
        return any(
            _row_identity(row) == identity
            for row in self.events_for(event.decision_record_id)
        )

    def next_sequence(self, decision_record_id: str) -> int:
        existing = self.events_for(decision_record_id)
        return (existing[-1]["sequence"] + 1) if existing else 1

    def append_all(self, events: Iterable[LifecycleEvent], start: int | None = None) -> int:
        events = list(events)
        if not events:
            return 0
        index = (
            start if start is not None
            else self.next_sequence(events[0].decision_record_id)
        )
        for event in events:
            self.append(event, index)
            index += 1
        return len(events)

    def events_for(
        self,
        decision_record_id: str,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict]:
        path = self._events_path(decision_record_id)
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines() if line]
        rows = sorted(
            (r for r in rows if r["sequence"] > after_sequence),
            key=lambda r: r["sequence"],
        )
        return rows[:limit] if limit is not None else rows


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

    #: Decision-enumeration index. Provisioned by scripts/cloudshell_provision.sh,
    #: which is the only place the state table is defined.
    DECISION_INDEX = "decisions-by-recency"
    #: Constant partition value every DecisionRecord meta row carries.
    DECISION_ENTITY = "DECISION"

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
                # Constant partition key for the decision-enumeration index.
                # Records are keyed `RECORD#<id>`, so without one shared value
                # there is nothing to query "which decisions exist" against
                # short of a table scan.
                "entity": {"S": self.DECISION_ENTITY},
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

    def list_ids(self, limit: int = 50, cursor: dict | None = None) -> list[str]:
        """Record ids, newest first, via the decision index.

        This used to raise: the single-table layout gives no way to enumerate
        records without an index, and scanning the table to fake one would have
        read every corpus, capability and ledger row to find them.
        """
        return [row["record_id"] for row in self.list_decisions(limit, cursor)[0]]

    def list_decisions(
        self, limit: int = 50, cursor: dict | None = None
    ) -> tuple[list[dict], dict | None]:
        """One page of decision summaries, newest first, plus the next cursor.

        Returns the projected columns rather than whole records: an Incoming
        list renders a row per decision, and loading every full document to
        build it would be the expensive way to answer a cheap question.
        """
        request = {
            "TableName": self.table,
            "IndexName": self.DECISION_INDEX,
            "KeyConditionExpression": "entity = :entity",
            "ExpressionAttributeValues": {":entity": {"S": self.DECISION_ENTITY}},
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }
        if cursor:
            request["ExclusiveStartKey"] = cursor
        try:
            response = self.ddb.query(**request)
        except Exception as exc:  # noqa: BLE001
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                f"could not list decisions: {exc}",
            ) from exc
        rows = [
            {
                "record_id": item["record_id"]["S"],
                "lot_id": item.get("lot_id", {}).get("S", ""),
                "disposition": item.get("disposition", {}).get("S", ""),
                "failure_category": item.get("failure_category", {}).get("S", ""),
                "saved_at": item.get("saved_at", {}).get("S", ""),
            }
            for item in response.get("Items", [])
            if "record_id" in item
        ]
        return rows, response.get("LastEvaluatedKey")

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

    def next_sequence(self, decision_record_id: str) -> int:
        """One past the highest event sequence already stored (audit-2 F8).

        Numbering restarting at 1 on a new process was silently DISCARDING
        continuation events: `append` is conditional on the sort key being
        absent, so every event of run 2 collided with run 1 and was swallowed
        as a duplicate. A resumed case must extend history, never overwrite or
        vanish into it.

        A descending query limited to one item is O(1); it does not read the
        whole event history.
        """
        response = self.ddb.query(
            TableName=self.table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": {"S": f"RECORD#{decision_record_id}"},
                ":prefix": {"S": "EVENT#"},
            },
            ScanIndexForward=False,
            Limit=1,
        )
        items = response.get("Items", [])
        if not items:
            return 1
        return int(items[0]["sk"]["S"].split("#")[1]) + 1

    def append_all(self, events: Iterable[LifecycleEvent], start: int | None = None) -> int:
        events = list(events)
        if not events:
            return 0
        record_id = events[0].decision_record_id
        index = start if start is not None else self.next_sequence(record_id)
        count = 0
        for event in events:
            try:
                self.append(event, index)
                count += 1
            except Exception as exc:  # noqa: BLE001
                if "ConditionalCheckFailed" not in str(exc):
                    raise
            index += 1
        return count

    def events_for(
        self,
        decision_record_id: str,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict]:
        """Events for one record, ascending, optionally after a cursor.

        `after_sequence` is what makes a frontend able to poll: it asks only for
        what it has not seen, rather than re-reading the whole history each time.
        Because the sort key is `EVENT#%06d`, "after N" is a key range and costs
        nothing to express.

        Paginating matters more than it looks. A query returns at most 1MB, and
        the previous version ignored `LastEvaluatedKey` — so a long-running case
        silently returned a truncated history that looked complete, which is the
        worst shape for an audit read.
        """
        rows: list[dict] = []
        start_key = None
        while True:
            request = {
                "TableName": self.table,
                "KeyConditionExpression": "pk = :pk AND sk > :after",
                "ExpressionAttributeValues": {
                    ":pk": {"S": f"RECORD#{decision_record_id}"},
                    ":after": {"S": f"EVENT#{after_sequence:06d}"},
                },
            }
            if start_key:
                request["ExclusiveStartKey"] = start_key
            if limit is not None:
                request["Limit"] = max(0, limit - len(rows))
            response = self.ddb.query(**request)
            rows.extend(
                {
                    "event_id": i["event_id"]["S"],
                    "sequence": int(i["sk"]["S"].split("#")[1]),
                    "event": i["event"]["S"],
                    "decision_record_id": decision_record_id,
                    "at": i["at"]["S"],
                    "payload": json.loads(i["payload"]["S"]),
                }
                for i in response.get("Items", [])
                # `sk > EVENT#...` also admits any sort key that sorts after the
                # EVENT# range; keep only real event rows.
                if i["sk"]["S"].startswith("EVENT#")
            )
            start_key = response.get("LastEvaluatedKey")
            if not start_key or (limit is not None and len(rows) >= limit):
                break
        return rows[:limit] if limit is not None else rows


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
        rows = self.events.setdefault(event.decision_record_id, [])
        identity = _event_identity(event)
        if any(_row_identity(row) == identity for row in rows):
            return
        rows.append(_event_row(event, sequence, event.decision_record_id))

    def next_sequence(self, decision_record_id: str) -> int:
        existing = self.events.get(decision_record_id, [])
        return (max(r["sequence"] for r in existing) + 1) if existing else 1

    def append_all(self, events: Iterable[LifecycleEvent], start: int | None = None) -> int:
        events = list(events)
        if not events:
            return 0
        index = (
            start if start is not None
            else self.next_sequence(events[0].decision_record_id)
        )
        for event in events:
            self.append(event, index)
            index += 1
        return len(events)

    def events_for(
        self,
        decision_record_id: str,
        after_sequence: int = 0,
        limit: int | None = None,
    ) -> list[dict]:
        rows = sorted(
            (
                r for r in self.events.get(decision_record_id, [])
                if r["sequence"] > after_sequence
            ),
            key=lambda r: r["sequence"],
        )
        return rows[:limit] if limit is not None else rows


def hydrate_record(document: dict) -> DecisionRecord:
    """Rebuild a DecisionRecord from its stored document (audit-2 F8).

    Typed reconstruction, not a dict pretending to be a record: each segment is
    rebuilt as its dataclass, so a resumed case has the same object the first
    run had and every downstream `record.x.y` access keeps working.

    Unknown keys are DROPPED rather than raising: a record written by an older
    schema must still be resumable, and refusing to load history because a
    field was added later would be its own kind of data loss.
    """
    from dataclasses import fields as dataclass_fields

    def build(cls, payload):
        if not isinstance(payload, dict):
            return cls()
        known = {f.name for f in dataclass_fields(cls)}
        return cls(**{k: v for k, v in payload.items() if k in known})

    def build_run(payload):
        """One archived run, whose own segments are dataclasses too.

        A plain `build` would leave `investigator` and friends as dicts inside
        an otherwise typed object, so `run.investigator.brief_hash` would raise
        after a restart — the archive would survive storage but stop being
        readable, which is the failure it exists to prevent.
        """
        if not isinstance(payload, dict):
            return ArchivedRun()
        # Build the nested segments FIRST. `build` would otherwise assign the
        # raw dicts straight onto the run, and a type taken from the resulting
        # attribute is then `dict`, not the segment class — the check has to
        # come from a fresh default, which knows what each field really is.
        default = ArchivedRun()
        rebuilt = dict(payload)
        for field_name in (f.name for f in dataclass_fields(ArchivedRun)):
            nested = getattr(default, field_name)
            if is_dataclass(nested) and isinstance(payload.get(field_name), dict):
                rebuilt[field_name] = build(type(nested), payload[field_name])
        return build(ArchivedRun, rebuilt)

    record = DecisionRecord(record_id=document.get("record_id", ""))
    for name in (f.name for f in dataclass_fields(DecisionRecord)):
        value = document.get(name)
        if value is None:
            continue
        current = getattr(record, name)
        if is_dataclass(current):
            setattr(record, name, build(type(current), value))
        elif name == "archived_runs" and isinstance(value, list):
            setattr(record, name, [build_run(item) for item in value])
        else:
            setattr(record, name, value)
    return record


def hydrate_claims(document: dict) -> list:
    """Rebuild the canonical claims stored alongside a record (audit-2 F8).

    A claim that no longer validates is dropped rather than crashing the
    resume: the record still carries its hash and storage ref, so the loss is
    visible to an auditor instead of taking the whole case down.
    """
    from .contracts import CanonicalEvidenceClaim

    rebuilt = []
    for payload in (document.get("evidence") or {}).get("canonical_claims", []):
        try:
            rebuilt.append(CanonicalEvidenceClaim(**payload))
        except Exception:  # noqa: BLE001
            continue
    return rebuilt


__all__ = [
    "DynamoRecordStore",
    "EventStore",
    "InMemoryRecordStore",
    "JsonRecordStore",
    "RecordStore",
    "hydrate_claims",
    "hydrate_record",
]
