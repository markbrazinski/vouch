"""DynamoDB-backed authoritative state (A2).

Same interface as the in-memory StateStore, so the workflow is unchanged. Truth
lives in `gatehouse-dev-state` and survives separate runtime invocations and
sessions.

Key design: pk = "<namespace>#<kind>", sk = "<id>". A namespace scopes one
logical world (a demo run, an eval case), so concurrent cases cannot collide.

Idempotency is enforced in the database, not in process memory: a conditional
put on the applied-key item is what makes replay safe across sessions.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, fields, is_dataclass
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

from . import state as S
from .state import (
    AuthorityRecord,
    LOT_TRANSITIONS,
    ORDER_TRANSITIONS,
    LotStatus,
    OrderStatus,
    TransitionError,
    Usability,
)

# kind -> dataclass, for rehydration
_KINDS: dict[str, type] = {
    "material": S.Material,
    "spec": S.MaterialSpecification,
    "supplier_qualification": S.SupplierQualification,
    "lot": S.Lot,
    "evidence": S.Evidence,
    "inventory": S.InventoryRecord,
    "production_order": S.ProductionOrder,
    "substitution": S.ApprovedSubstitution,
    "qa_review": S.QAReview,
}

# nested tuple-of-dataclass fields that need rebuilding on read
_NESTED: dict[type, dict[str, type]] = {
    S.MaterialSpecification: {"characteristics": S.Characteristic},
    S.Evidence: {"measurements": S.EvidenceMeasurement},
    S.ProductionOrder: {"requirements": S.MaterialRequirement},
}

_ENUMS: dict[str, type] = {"status": None, "usability": Usability}


def _encode(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, (list, tuple)):
        return [_encode(v) for v in value]
    if isinstance(value, dict):
        return {k: _encode(v) for k, v in value.items()}
    if hasattr(value, "value"):  # Enum
        return value.value
    if is_dataclass(value):
        return {k: _encode(v) for k, v in asdict(value).items()}
    return value


def _decode(value: Any) -> Any:
    if isinstance(value, Decimal):
        f = float(value)
        return int(f) if f.is_integer() else f
    if isinstance(value, list):
        return [_decode(v) for v in value]
    if isinstance(value, dict):
        return {k: _decode(v) for k, v in value.items()}
    return value


def _rehydrate(kind: str, raw: dict) -> Any:
    cls = _KINDS[kind]
    data = {k: _decode(v) for k, v in raw.items() if k not in ("pk", "sk", "_kind")}

    for name, sub in _NESTED.get(cls, {}).items():
        if name in data and data[name] is not None:
            data[name] = tuple(sub(**item) for item in data[name])

    if cls is S.Lot and "status" in data:
        data["status"] = LotStatus(data["status"])
    if cls is S.ProductionOrder and "status" in data:
        data["status"] = OrderStatus(data["status"])
    if cls is S.InventoryRecord and "usability" in data:
        data["usability"] = Usability(data["usability"])
    if cls is S.QAReview and "evidence_refs" in data:
        data["evidence_refs"] = tuple(data["evidence_refs"])

    valid = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in valid})


class DynamoStateStore:
    """Authoritative state in DynamoDB. Drop-in for StateStore."""

    def __init__(self, table_name: str | None = None, namespace: str = "default") -> None:
        from .config import load

        cfg = load()
        self.table_name = table_name or cfg.state_table or os.environ["VOUCH_STATE_TABLE"]
        self.namespace = namespace
        self._ddb = boto3.resource("dynamodb", region_name=cfg.region)
        self._t = self._ddb.Table(self.table_name)

    # -- keys -------------------------------------------------------------
    def _pk(self, kind: str) -> str:
        return f"{self.namespace}#{kind}"

    # -- generic ----------------------------------------------------------
    def put(self, kind: str, key: str, value: Any) -> None:
        item = {"pk": self._pk(kind), "sk": key, "_kind": kind}
        item.update(_encode(value) if is_dataclass(value) else {"_raw": _encode(value)})
        self._t.put_item(Item=item)

    def get(self, kind: str, key: str) -> Any:
        resp = self._t.get_item(Key={"pk": self._pk(kind), "sk": key})
        item = resp.get("Item")
        if item is None:
            return None
        if "_raw" in item:
            return _decode(item["_raw"])
        return _rehydrate(kind, item)

    def all(self, kind: str) -> list[Any]:
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {"KeyConditionExpression": Key("pk").eq(self._pk(kind))}
        while True:
            resp = self._t.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return [_rehydrate(kind, i) for i in items if "_raw" not in i]

    # -- idempotency (enforced in the database) ---------------------------
    def already_applied(self, idempotency_key: str) -> str | None:
        resp = self._t.get_item(Key={"pk": self._pk("applied"), "sk": idempotency_key})
        item = resp.get("Item")
        return item.get("result") if item else None

    def mark_applied(self, idempotency_key: str, result: str) -> None:
        try:
            self._t.put_item(
                Item={"pk": self._pk("applied"), "sk": idempotency_key, "result": result},
                ConditionExpression="attribute_not_exists(sk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            # already applied by a concurrent/earlier invocation — that is the point

    # -- guarded transitions ---------------------------------------------
    def set_lot_status(self, lot_id: str, new: LotStatus):
        lot = self.get("lot", lot_id)
        if lot is None:
            raise KeyError(f"unknown lot {lot_id}")
        if new not in LOT_TRANSITIONS[lot.status]:
            raise TransitionError(f"lot {lot_id}: {lot.status.value} -> {new.value} not permitted")
        from dataclasses import replace

        updated = replace(lot, status=new)
        self.put("lot", lot_id, updated)
        return updated

    def set_order_status(self, order_id: str, new: OrderStatus):
        order = self.get("production_order", order_id)
        if order is None:
            raise KeyError(f"unknown production order {order_id}")
        if new not in ORDER_TRANSITIONS[order.status]:
            raise TransitionError(
                f"order {order_id}: {order.status.value} -> {new.value} not permitted"
            )
        from dataclasses import replace

        updated = replace(order, status=new)
        self.put("production_order", order_id, updated)
        return updated

    def set_inventory_usability(self, lot_id: str, usability: Usability) -> None:
        rec = self.get("inventory", lot_id)
        if rec is None:
            raise KeyError(f"unknown inventory for lot {lot_id}")
        from dataclasses import replace

        self.put("inventory", lot_id, replace(rec, usability=usability))

    # -- authority ledger --------------------------------------------------
    def record_authority(self, record: AuthorityRecord) -> None:
        sk = f"{record.timestamp}#{record.case_id}#{record.requested_tool}"
        item = {"pk": self._pk("authority"), "sk": sk, "_kind": "authority"}
        item.update(_encode(record))
        self._t.put_item(Item=item)

    @property
    def authority_log(self) -> list[AuthorityRecord]:
        from boto3.dynamodb.conditions import Key

        resp = self._t.query(KeyConditionExpression=Key("pk").eq(self._pk("authority")))
        out = []
        for i in sorted(resp.get("Items", []), key=lambda x: x["sk"]):
            data = {k: _decode(v) for k, v in i.items() if k not in ("pk", "sk", "_kind")}
            data["evidence_refs"] = tuple(data.get("evidence_refs", []))
            valid = {f.name for f in fields(AuthorityRecord)}
            out.append(AuthorityRecord(**{k: v for k, v in data.items() if k in valid}))
        return out

    # -- seeding -----------------------------------------------------------
    def seed_from(self, memory_store: S.StateStore) -> "DynamoStateStore":
        """Load a fixture world into this namespace."""
        for kind in _KINDS:
            for key, value in memory_store._t.get(kind, {}).items():
                self.put(kind, key, value)
        return self

    def wipe(self) -> None:
        """Delete every item in this namespace (test hygiene)."""
        from boto3.dynamodb.conditions import Key

        for kind in list(_KINDS) + ["applied", "authority"]:
            resp = self._t.query(KeyConditionExpression=Key("pk").eq(self._pk(kind)))
            with self._t.batch_writer() as batch:
                for item in resp.get("Items", []):
                    batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
