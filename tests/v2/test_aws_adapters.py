"""Production AWS adapters (P0-3, P0-5, P0-6).

Two tiers, deliberately separated so an auditor can tell them apart:

  * **Structural tests** always run. They prove the adapters exist, satisfy the
    same interfaces as the local ones, and construct the exact DynamoDB
    transaction the contract requires — without needing credentials.

  * **Live tests** run only with VOUCH_LIVE_AWS=1 and real credentials. They are
    the evidence behind IMPLEMENTED_AND_LIVE_VERIFIED; without the flag they
    SKIP rather than silently passing, because a green test that never touched
    AWS would be exactly the kind of fictional evidence this iteration exists to
    remove.
"""

from __future__ import annotations

import os
import threading
import uuid

import pytest

from vouch.v2.authority import (
    Action,
    CapabilityStore,
    Issuer,
    IssuerViolation,
    PolicyEngine,
    TargetType,
)
from vouch.v2.contracts import FailureCategory, VouchFailure
from vouch.v2.evidence import LocalEvidenceStore

LIVE = os.environ.get("VOUCH_LIVE_AWS") == "1"
live_only = pytest.mark.skipif(
    not LIVE, reason="live AWS test; set VOUCH_LIVE_AWS=1 with gatehouse credentials"
)


# ==========================================================================
# structural — always run
# ==========================================================================


def test_adapters_are_importable():
    from vouch.v2.aws import (
        BedrockGuardrailDetector,
        ClamAVScanner,
        DynamoCapabilityStore,
        S3EvidenceStore,
    )

    assert DynamoCapabilityStore.kind == "AWS_DYNAMODB"
    assert S3EvidenceStore.kind == "AWS_S3"


def test_local_store_is_labeled_a_simulation():
    """The local store must not be describable as immutable or WORM."""
    assert LocalEvidenceStore.kind == "LOCAL_SIMULATION"
    assert "SIMULATION" in LocalEvidenceStore.__doc__.upper()


def test_local_store_returns_an_object_version():
    """Same 3-tuple interface as S3, so callers are adapter-agnostic."""
    store = LocalEvidenceStore()
    uri, digest, version = store.put_original("LOT-1/ART-1", b"bytes")
    assert uri.startswith("local://")
    assert len(digest) == 64
    assert version


def test_dynamo_store_implements_the_capability_interface():
    """Same surface as the in-process store: issue(issuer, ...) / consume(id)."""
    import inspect

    from vouch.v2.aws import DynamoCapabilityStore

    for name in ("issue", "consume", "get", "_mint_issuer"):
        assert hasattr(DynamoCapabilityStore, name)

    issue = inspect.signature(DynamoCapabilityStore.issue)
    assert list(issue.parameters)[1] == "issuer"  # issuer is positional, P0-1

    consume = inspect.signature(DynamoCapabilityStore.consume)
    # P0-2: no parameter through which a caller can pass executable logic.
    assert "params" in consume.parameters
    assert consume.parameters["params"].kind is inspect.Parameter.KEYWORD_ONLY


def test_dynamo_consume_builds_one_transaction_with_all_three_conditions():
    """P0-3: atomicity must come from ONE TransactWriteItems, not N writes.

    Captures the call rather than mocking away the logic, so the assertions are
    about the real expression the adapter would send.
    """
    from vouch.v2.aws import DynamoCapabilityStore

    captured: dict = {}

    class FakeDDB:
        def get_item(self, **kwargs):
            return {
                "Item": {
                    "pk": {"S": "CAP#CAP-1"},
                    "capability_id": {"S": "CAP-1"},
                    "decision_record_id": {"S": "DR-1"},
                    "target_type": {"S": "lot"},
                    "target_id": {"S": "LOT-1"},
                    "action": {"S": "release_lot"},
                    "observed_state_version": {"N": "3"},
                    "issuer_identity": {"S": "vouch.policy-engine"},
                    "used": {"BOOL": False},
                }
            }

        def transact_write_items(self, **kwargs):
            captured.update(kwargs)
            return {}

    store = DynamoCapabilityStore(table="t")
    store._ddb = FakeDDB()
    entry = store.consume("CAP-1")

    items = captured["TransactItems"]
    assert len(items) == 3, "consume must be a single 3-item transaction"

    capability_condition = items[0]["Update"]["ConditionExpression"]
    for clause in ("attribute_exists(pk)", "used = :false", "expires_at > :now",
                   "target_id = :target", "#a = :action",
                   "decision_record_id = :record",
                   "observed_state_version = :bound"):
        assert clause in capability_condition

    assert items[1]["Update"]["ConditionExpression"] == "state_version = :bound"
    assert items[2]["Put"]["ConditionExpression"] == "attribute_not_exists(pk)"

    assert entry["before_version"] == 3
    assert entry["after_version"] == 4


def test_dynamo_consume_refuses_action_with_no_dispatch_entry(monkeypatch):
    """Fails closed exactly like the local store (P0-2)."""
    import vouch.v2.aws as aws

    class FakeDDB:
        def get_item(self, **kwargs):
            return {
                "Item": {
                    "capability_id": {"S": "CAP-1"},
                    "decision_record_id": {"S": "DR-1"},
                    "target_type": {"S": "lot"},
                    "target_id": {"S": "LOT-1"},
                    "action": {"S": "release_lot"},
                    "observed_state_version": {"N": "1"},
                    "used": {"BOOL": False},
                }
            }

    monkeypatch.setattr(aws, "MUTATIONS", {})
    store = aws.DynamoCapabilityStore(table="t")
    store._ddb = FakeDDB()
    with pytest.raises(VouchFailure) as exc:
        store.consume("CAP-1")
    assert exc.value.category is FailureCategory.POLICY_REFUSAL


def test_dynamo_unauthorized_issuer_is_refused():
    """P0-1 holds in the production adapter too, not only locally."""
    from vouch.v2.aws import DynamoCapabilityStore

    store = DynamoCapabilityStore(table="t")
    with pytest.raises(IssuerViolation):
        store.issue(
            Issuer(identity="investigator"),
            decision_record_id="DR-1", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )
    with pytest.raises(TypeError):
        store.issue(  # type: ignore[call-arg]
            decision_record_id="DR-1", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )


def test_replay_and_stale_state_are_distinct_categories():
    """P1-3: a replay must not be mislabeled a state conflict.

    Both conditions fail together in a real transaction (a consumed capability
    usually also means the version moved), so the mapping order is load-bearing.
    """
    from vouch.v2.aws import DynamoCapabilityStore

    class Cancelled(Exception):
        response = {
            "CancellationReasons": [
                {"Code": "ConditionalCheckFailed"},  # capability
                {"Code": "ConditionalCheckFailed"},  # target version
                {"Code": "None"},
            ]
        }

    failure = DynamoCapabilityStore._explain(Cancelled(), "CAP-1", "LOT-1", 1)
    assert failure.category is FailureCategory.POLICY_REFUSAL

    class StaleOnly(Exception):
        response = {
            "CancellationReasons": [
                {"Code": "None"},
                {"Code": "ConditionalCheckFailed"},
                {"Code": "None"},
            ]
        }

    failure = DynamoCapabilityStore._explain(StaleOnly(), "CAP-1", "LOT-1", 1)
    assert failure.category is FailureCategory.STATE_CONFLICT


def test_guardrail_detector_raises_when_unconfigured():
    """A guardrail that cannot run must never read as 'found nothing' (P0-6)."""
    from vouch.v2.aws import BedrockGuardrailDetector

    detector = BedrockGuardrailDetector(guardrail_id="")
    with pytest.raises(VouchFailure) as exc:
        detector("some text")
    assert exc.value.category is FailureCategory.TOOL_FAILURE


def test_detector_error_fails_closed_and_is_recorded_as_error():
    """P0-6: inspection that errored is not inspection that passed."""
    from vouch.v2.contracts import GuardrailOutcome
    from vouch.v2.evidence import inspect

    def broken(text: str):
        raise RuntimeError("guardrail unreachable")

    inspection = inspect(b"payload", "text/plain", "payload", broken)
    assert inspection.guardrail_outcome is GuardrailOutcome.ERROR
    assert inspection.prompt_attack_detected is True  # fail closed
    assert inspection.blocked


def test_scanner_absent_reports_not_run_not_a_pass():
    """P0-7: no fictional security evidence."""
    from vouch.v2.contracts import ScanStatus
    from vouch.v2.evidence import inspect

    inspection = inspect(b"payload", "text/plain", "payload")
    assert inspection.malware_scan is ScanStatus.NOT_RUN
    assert inspection.malware_found is False
    assert "no AV engine" in inspection.malware_detail


def test_scanner_failure_reports_failed():
    from vouch.v2.contracts import ScanStatus
    from vouch.v2.evidence import inspect

    def broken(raw: bytes):
        raise OSError("clamd down")

    inspection = inspect(b"payload", "text/plain", "payload", scanner=broken)
    assert inspection.malware_scan is ScanStatus.FAILED


# ==========================================================================
# live — only with VOUCH_LIVE_AWS=1
# ==========================================================================


@pytest.fixture
def dynamo():
    from vouch.v2.aws import DynamoCapabilityStore

    store = DynamoCapabilityStore()
    return store, store._mint_issuer(PolicyEngine.IDENTITY)


def _fresh_lot(store, version: int = 1, status: str = "RECEIVED") -> str:
    lot_id = f"PYTEST-{uuid.uuid4().hex[:10]}"
    store.put_state("lot", lot_id, status, version)
    return lot_id


def _cap(store, issuer, lot_id, action=Action.RELEASE_LOT, version=1, ttl=300):
    return store.issue(
        issuer, decision_record_id=f"DR-{lot_id}", target_type=TargetType.LOT,
        target_id=lot_id, action=action, observed_state_version=version,
        ttl_seconds=ttl,
    )


@live_only
def test_live_s3_round_trip_with_version_and_hash():
    from vouch.v2.aws import S3EvidenceStore

    store = S3EvidenceStore(prefix=f"pytest/{uuid.uuid4().hex[:8]}")
    payload = b"Certificate of Analysis - Lot LOT-1001\n"
    uri, digest, version_id = store.put_original("LOT-1001/ART-1", payload)

    assert uri.startswith("s3://")
    assert len(digest) == 64
    assert version_id, "bucket versioning must be on for originals to be durable"
    assert store.get_original("LOT-1001/ART-1", version_id) == payload


@live_only
def test_live_capability_consume_mutates_and_ledgers(dynamo):
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    capability = _cap(store, issuer, lot_id)

    entry = store.consume(capability.capability_id)

    assert entry["before_version"] == 1
    assert entry["after_version"] == 2
    assert store.get_state("lot", lot_id)["status"] == "RELEASED"
    ledger = store.ledger_for(f"DR-{lot_id}")
    assert len(ledger) == 1
    assert ledger[0]["capability_id"] == capability.capability_id


@live_only
def test_live_forged_capability_is_refused(dynamo):
    store, _ = dynamo
    with pytest.raises(VouchFailure) as exc:
        store.consume(f"CAP-{uuid.uuid4().hex}")
    assert exc.value.category is FailureCategory.POLICY_REFUSAL


@live_only
def test_live_expired_capability_is_refused(dynamo):
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    capability = _cap(store, issuer, lot_id, ttl=-1)
    with pytest.raises(VouchFailure):
        store.consume(capability.capability_id)
    assert store.get_state("lot", lot_id)["status"] == "RECEIVED"


@live_only
def test_live_replay_is_refused_as_policy_not_state(dynamo):
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    capability = _cap(store, issuer, lot_id)
    store.consume(capability.capability_id)

    with pytest.raises(VouchFailure) as exc:
        store.consume(capability.capability_id)
    assert exc.value.category is FailureCategory.POLICY_REFUSAL


@live_only
def test_live_stale_state_is_refused(dynamo):
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    capability = _cap(store, issuer, lot_id, version=1)
    store.put_state("lot", lot_id, "PENDING_QA", 9)  # someone else moved it

    with pytest.raises(VouchFailure) as exc:
        store.consume(capability.capability_id)
    assert exc.value.category is FailureCategory.STATE_CONFLICT


@live_only
def test_live_wrong_bound_version_is_refused(dynamo):
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    capability = _cap(store, issuer, lot_id, version=99)
    with pytest.raises(VouchFailure):
        store.consume(capability.capability_id)


@live_only
def test_live_two_concurrent_consumers_one_winner(dynamo):
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    capability = _cap(store, issuer, lot_id)
    results: list[str] = []

    def attempt():
        try:
            store.consume(capability.capability_id)
            results.append("ok")
        except Exception:  # noqa: BLE001
            results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1
    assert len(store.ledger_for(f"DR-{lot_id}")) == 1


@live_only
def test_live_two_conflicting_capabilities_one_transition(dynamo):
    """Exactly one legal transition may win."""
    store, issuer = dynamo
    lot_id = _fresh_lot(store)
    release = _cap(store, issuer, lot_id, Action.RELEASE_LOT, version=1)
    quarantine = _cap(store, issuer, lot_id, Action.QUARANTINE_LOT, version=1)
    results: list[str] = []

    def attempt(capability):
        try:
            store.consume(capability.capability_id)
            results.append("ok")
        except Exception:  # noqa: BLE001
            results.append("refused")

    threads = [
        threading.Thread(target=attempt, args=(c,)) for c in (release, quarantine)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1
    assert store.get_state("lot", lot_id)["state_version"] == 2
