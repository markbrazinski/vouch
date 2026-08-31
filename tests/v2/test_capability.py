"""The ten capability security properties (contract D12) — proven, not asserted.

V1's AuthorityToken failed most of these. The audit minted one with
authority_source="i_made_this_up" and released a lot. Each test below is the
counter-proof.
"""

from __future__ import annotations

import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from vouch.v2.authority import (
    Action,
    CapabilityRecord,
    CapabilityStore,
    PolicyEngine,
    TargetType,
    apply_release,
    execute,
)
from vouch.v2.contracts import Disposition, FailureCategory, VouchFailure
from vouch.v2.corpus import Corpus, InventoryRecord, Lot, SupplierQualification
from vouch.v2.lifecycle import EventLog


@pytest.fixture
def world():
    corpus = Corpus()
    corpus.put(
        "lot", "LOT-1",
        Lot("LOT-1", "SUP-A", "MAT-1", "PO-1", 100.0,
            supplier_site="SITE-1", received_at="2026-03-01"),
    )
    corpus.put("inventory", "LOT-1", InventoryRecord("MAT-1", "LOT-1", 100.0, usable=False))
    corpus.put(
        "supplier_qualification", "SUP-A:MAT-1",
        SupplierQualification("QUAL-1", "SUP-A", "MAT-1", "QUALIFIED", "2024-01-01"),
    )
    capabilities = CapabilityStore()
    return corpus, capabilities, PolicyEngine(corpus, capabilities), EventLog()


def _issue(world, action=Action.RELEASE_LOT, version=1):
    _, capabilities, _, _ = world
    return capabilities.issue(
        decision_record_id="DR-1", target_type=TargetType.LOT, target_id="LOT-1",
        action=action, observed_state_version=version,
    )


# -- 1. unforgeability -----------------------------------------------------
def test_forged_capability_is_refused(world):
    corpus, capabilities, _, _ = world
    forged = CapabilityRecord(
        capability_id="CAP-forged", decision_record_id="DR-1",
        target_type=TargetType.LOT, target_id="LOT-1", action=Action.RELEASE_LOT,
        observed_state_version=1, policy_version="anything",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        nonce="n", issuer_proof="i_made_this_up",
    )
    with pytest.raises(VouchFailure) as exc:
        capabilities.consume_atomically(forged, corpus, apply_release)
    assert exc.value.category is FailureCategory.POLICY_REFUSAL
    assert corpus.lot("LOT-1").status == "RECEIVED"


# -- 2. issuer authenticity ------------------------------------------------
def test_tampered_binding_fails_authentication(world):
    corpus, capabilities, _, _ = world
    capability = _issue(world)
    # Same id, but the caller widened the action after issuance.
    tampered = replace(capability, action=Action.QUARANTINE_LOT)
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(tampered, corpus, apply_release)
    assert corpus.lot("LOT-1").status == "RECEIVED"


def test_capability_from_another_store_is_refused(world):
    """A record issued by a different issuer (different secret) is worthless."""
    corpus, capabilities, _, _ = world
    other = CapabilityStore()
    foreign = other.issue(
        decision_record_id="DR-1", target_type=TargetType.LOT, target_id="LOT-1",
        action=Action.RELEASE_LOT, observed_state_version=1,
    )
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(foreign, corpus, apply_release)


# -- 3. single use ---------------------------------------------------------
def test_capability_cannot_be_replayed(world):
    corpus, capabilities, _, events = world
    capability = _issue(world)
    execute(capability, corpus, capabilities, events)
    assert corpus.lot("LOT-1").status == "RELEASED"

    with pytest.raises(VouchFailure) as exc:
        execute(capability, corpus, capabilities, events)
    assert "already consumed" in exc.value.detail
    # And critically: inventory did not double-apply.
    assert corpus.usable_inventory("MAT-1") == 100.0
    assert len(capabilities.ledger) == 1


# -- 4. target + action binding -------------------------------------------
def test_capability_is_bound_to_one_target(world):
    corpus, capabilities, _, _ = world
    corpus.put("lot", "LOT-2", Lot("LOT-2", "SUP-A", "MAT-1", "PO-2", 50.0))
    capability = _issue(world)
    redirected = replace(capability, target_id="LOT-2")
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(redirected, corpus, apply_release)
    assert corpus.lot("LOT-2").status == "RECEIVED"


def test_capability_is_bound_to_one_action(world):
    corpus, capabilities, _, events = world
    capability = _issue(world, action=Action.QUARANTINE_LOT)
    # Presenting a quarantine capability while asking for release must fail.
    swapped = replace(capability, action=Action.RELEASE_LOT)
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(swapped, corpus, apply_release)


# -- 5. decision-record binding -------------------------------------------
def test_capability_traces_to_one_decision_record(world):
    corpus, capabilities, _, events = world
    capability = _issue(world)
    entry = execute(capability, corpus, capabilities, events)
    assert entry["decision_record_id"] == "DR-1"

    other = replace(capability, decision_record_id="DR-2")
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(other, corpus, apply_release)


# -- 6. state-version binding (TOCTOU) ------------------------------------
def test_stale_state_version_refuses_mutation(world):
    corpus, capabilities, _, events = world
    capability = _issue(world, version=1)
    # Someone else moves the lot between judgment and mutation.
    corpus.bump("lot", "LOT-1", status="PENDING_QA")
    assert corpus.version_of("lot", "LOT-1") == 2

    with pytest.raises(VouchFailure) as exc:
        execute(capability, corpus, capabilities, events)
    assert exc.value.category is FailureCategory.STATE_CONFLICT
    assert corpus.lot("LOT-1").status == "PENDING_QA"


# -- 7. expiry -------------------------------------------------------------
def test_expired_capability_is_refused(world):
    corpus, capabilities, _, events = world
    capability = capabilities.issue(
        decision_record_id="DR-1", target_type=TargetType.LOT, target_id="LOT-1",
        action=Action.RELEASE_LOT, observed_state_version=1, ttl_seconds=-1,
    )
    with pytest.raises(VouchFailure) as exc:
        execute(capability, corpus, capabilities, events)
    assert "expired" in exc.value.detail
    assert corpus.lot("LOT-1").status == "RECEIVED"


# -- 8. replay resistance (nonce) -----------------------------------------
def test_consumed_nonce_cannot_be_reused_in_a_new_record(world):
    corpus, capabilities, _, events = world
    capability = _issue(world)
    execute(capability, corpus, capabilities, events)
    # Reusing the nonce under a fresh id yields no valid issuer proof.
    clone = replace(capability, capability_id="CAP-clone", used=False, consumed_at="")
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(clone, corpus, apply_release)


# -- 9. mutation-time verification ----------------------------------------
def test_all_checks_happen_at_consume_time(world):
    """A capability valid at issuance but invalid at consume time is refused."""
    corpus, capabilities, _, events = world
    capability = _issue(world, version=1)
    corpus.bump("lot", "LOT-1", status="QUARANTINED")  # now version 2
    with pytest.raises(VouchFailure):
        execute(capability, corpus, capabilities, events)


def test_direct_mutation_without_capability_is_impossible(world):
    """There is no unguarded mutation entry point.

    `execute` requires a CapabilityRecord; the mutation functions are only
    reachable through consume_atomically, which authenticates first.
    """
    corpus, capabilities, _, _ = world
    with pytest.raises(VouchFailure):
        capabilities.consume_atomically(
            CapabilityRecord(
                "CAP-x", "DR-1", TargetType.LOT, "LOT-1", Action.RELEASE_LOT, 1,
                "p", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "n", "",
            ),
            corpus, apply_release,
        )
    assert corpus.lot("LOT-1").status == "RECEIVED"


# -- 10. optimistic concurrency -------------------------------------------
def test_concurrent_conflicting_mutations_allow_exactly_one(world):
    """Two capabilities bound to the same version; only one may win."""
    corpus, capabilities, _, events = world
    first = _issue(world, action=Action.RELEASE_LOT, version=1)
    second = _issue(world, action=Action.QUARANTINE_LOT, version=1)

    results = []

    def attempt(capability):
        try:
            execute(capability, corpus, capabilities, events)
            results.append(("ok", capability.action))
        except VouchFailure as failure:
            results.append(("refused", failure.category))

    threads = [threading.Thread(target=attempt, args=(c,)) for c in (first, second)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sum(1 for outcome, _ in results if outcome == "ok") == 1
    assert sum(1 for outcome, _ in results if outcome == "refused") == 1
    assert len(capabilities.ledger) == 1


# -- policy engine is the only issuer -------------------------------------
def test_policy_refuses_when_basis_checks_failed(world):
    corpus, capabilities, policy, events = world
    decision = policy.evaluate_lot_disposition(
        decision_record_id="DR-1", lot_id="LOT-1", disposition=Disposition.RELEASE,
        reconciliation_ok=True, basis_checks_ok=False, observed_state_version=1,
        events=events,
    )
    assert not decision.allowed
    assert decision.capability is None


def test_policy_refuses_on_illegal_transition(world):
    corpus, capabilities, policy, events = world
    corpus.bump("lot", "LOT-1", status="RELEASED")
    decision = policy.evaluate_lot_disposition(
        decision_record_id="DR-1", lot_id="LOT-1", disposition=Disposition.RELEASE,
        reconciliation_ok=True, basis_checks_ok=True,
        observed_state_version=corpus.version_of("lot", "LOT-1"), events=events,
    )
    assert not decision.allowed
    assert "not permitted" in decision.reason


def test_policy_refuses_release_without_supplier_qualification(world):
    corpus, capabilities, policy, events = world
    corpus.put(
        "lot", "LOT-3",
        Lot("LOT-3", "SUP-UNKNOWN", "MAT-1", "PO-3", 10.0, received_at="2026-03-01"),
    )
    decision = policy.evaluate_lot_disposition(
        decision_record_id="DR-1", lot_id="LOT-3", disposition=Disposition.RELEASE,
        reconciliation_ok=True, basis_checks_ok=True, observed_state_version=1,
        events=events,
    )
    assert not decision.allowed
    assert "qualification" in decision.reason
