"""A2: DynamoDB is authoritative state, and survives separate sessions.

Requires live AWS. Skips (never silently passes) without it.
"""

from __future__ import annotations

import os
import uuid

import pytest


def _ddb_available() -> tuple[bool, str]:
    try:
        import boto3

        from vouch.config import load

        cfg = load()
        if not cfg.state_table:
            return False, "no state_table configured"
        boto3.client("dynamodb", region_name=cfg.region).describe_table(TableName=cfg.state_table)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:120]}"


AVAILABLE, REASON = _ddb_available()
requires_ddb = pytest.mark.skipif(not AVAILABLE, reason=f"DynamoDB unavailable — {REASON}")


@pytest.fixture
def store():
    from vouch.dynamo_store import DynamoStateStore
    from vouch.fixtures import build_store

    ns = f"test-{uuid.uuid4().hex[:8]}"
    s = DynamoStateStore(namespace=ns)
    s.seed_from(build_store())
    yield s
    s.wipe()


@requires_ddb
def test_state_survives_a_separate_session(store):
    """The core A2 requirement: a new store object sees committed truth."""
    from vouch.dynamo_store import DynamoStateStore
    from vouch.state import LotStatus, Usability
    from vouch.workflow import Vouch

    Vouch(store).evaluate_lot("PERSIST", "LOT-1001")

    fresh = DynamoStateStore(namespace=store.namespace)  # separate "invocation"
    assert fresh.get("lot", "LOT-1001").status is LotStatus.RELEASED
    assert fresh.get("inventory", "LOT-1001").usability is Usability.USABLE
    assert len(fresh.authority_log) == 1


@requires_ddb
def test_replay_is_idempotent_across_sessions(store):
    """Replay in a NEW session must not double-release inventory."""
    from vouch.dynamo_store import DynamoStateStore
    from vouch.workflow import Vouch

    first = Vouch(store)
    first.evaluate_lot("REPLAY", "LOT-1001")
    usable = first.read.get_usable_inventory("MAT-ALLOY-7")

    second = Vouch(DynamoStateStore(namespace=store.namespace))
    second.evaluate_lot("REPLAY", "LOT-1001")

    assert second.read.get_usable_inventory("MAT-ALLOY-7") == usable


@requires_ddb
def test_full_chain_on_dynamodb(store):
    """S1-S7 end to end against authoritative DynamoDB state."""
    from vouch.fixtures import add_qa_evidence
    from vouch.state import LotStatus, OrderStatus
    from vouch.workflow import Vouch

    gh = Vouch(store)

    assert gh.evaluate_lot("D1", "LOT-1001")["actor"]["disposition"] == "RELEASE"
    assert gh.evaluate_lot("D2", "LOT-1002")["actor"]["disposition"] == "QUARANTINE"

    readiness = gh.evaluate_production_readiness("D3", "C-417")
    assert readiness["readiness"]["authority_status"] == "HOLD"
    assert gh.read.get_production_order("C-417").status is OrderStatus.HOLD

    recovery = gh.evaluate_recovery("D5", "C-417")
    assert recovery["actor"]["action"] == "RESEQUENCE"
    assert recovery["gate"].allowed is True

    assert gh.evaluate_lot("D6", "LOT-1003")["actor"]["disposition"] == "INSUFFICIENT_EVIDENCE"
    assert gh.read.get_lot("LOT-1003").status is LotStatus.PENDING_QA

    add_qa_evidence(store, "LOT-1003")
    assert gh.evaluate_lot("D6", "LOT-1003")["actor"]["disposition"] == "RELEASE"
    assert gh.read.get_lot("LOT-1003").status is LotStatus.RELEASED

    assert len(store.authority_log) >= 6
