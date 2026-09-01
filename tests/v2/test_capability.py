"""The ten capability security properties (contract D12) — proven, not asserted.

V1's AuthorityToken failed most of these. The audit minted one with
authority_source="i_made_this_up" and released a lot. Each test below is the
counter-proof.

Iteration 2 adds the two boundaries the independent audit proved were missing at
b8f54b0 and which no test then covered:

  P0-1  authority cannot be created outside the Policy Engine;
  P0-2  consumption dispatches internally and cannot execute caller-supplied
        mutation logic against an arbitrary target.

The capabilities used here are obtained the only way the architecture permits —
from the Policy Engine — because there is no longer any other way to obtain one.
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
    IssuerViolation,
    PolicyEngine,
    TargetType,
    execute,
    freeze_parameters,
)
from vouch.v2.issuance import IssuanceAuthority, IssuanceViolation
from vouch.v2.contracts import Disposition, FailureCategory, VouchFailure
from vouch.v2.corpus import (
    Corpus,
    InventoryRecord,
    Lot,
    MaterialRequirementLine,
    ProductionOrder,
    SupplierQualification,
)
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


def _issue(world, action=Action.RELEASE_LOT, version=1, lot_id="LOT-1", **parameters):
    """Obtain a capability the only way the architecture allows: via policy.

    `policy._issuer` is the Policy Engine's own `IssuanceAuthority`. Reaching
    into it here is deliberate — these tests need capabilities with specific
    bindings that the disposition path would not naturally produce (a
    quarantine capability for a clean lot, an already-expired TTL). Every OTHER
    test in the suite obtains capabilities through `evaluate_lot_disposition`,
    and the F1 tests below prove no caller lacking that authority can do what
    this helper does.
    """
    _, capabilities, policy, _ = world
    target_type = (
        TargetType.LOT
        if action in (Action.RELEASE_LOT, Action.QUARANTINE_LOT, Action.CREATE_QA_REVIEW)
        else TargetType.PRODUCTION_ORDER
    )
    return capabilities.issue(
        policy._issuer,
        decision_record_id="DR-1", target_type=target_type, target_id=lot_id,
        action=action, observed_state_version=version, parameters=parameters,
    )


def _authorize_release(world, lot_id="LOT-1"):
    """The real path: policy evaluates, and only then is authority created."""
    corpus, _, policy, events = world
    return policy.evaluate_lot_disposition(
        decision_record_id="DR-1", lot_id=lot_id, disposition=Disposition.RELEASE,
        reconciliation_ok=True, basis_checks_ok=True,
        observed_state_version=corpus.version_of("lot", lot_id), events=events,
    )


# ==========================================================================
# P0-1 — issuance is enforced, not conventional
# ==========================================================================


def test_policy_engine_can_issue(world):
    decision = _authorize_release(world)
    assert decision.allowed
    assert decision.capability is not None
    assert decision.capability.issuer_identity == PolicyEngine.IDENTITY


def test_normal_application_caller_cannot_issue(world):
    """The exact audit bypass: `store.issue(...)` from ordinary code.

    It no longer compiles as a call — the issuer credential is a required
    positional argument, so the attempt fails before any row is created.
    """
    _, capabilities, _, _ = world
    with pytest.raises(TypeError):
        capabilities.issue(  # type: ignore[call-arg]
            decision_record_id="DR-EVIL", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )
    assert capabilities.ledger == []


class _FakeAuthority:
    """A look-alike with the right shape and the right name, no real key."""

    def __init__(self, identity: str = "vouch.policy-engine", proof: str = "deadbeef"):
        self.identity = identity
        self._proof = proof

    def sign(self, binding: dict) -> str:
        return self._proof


@pytest.mark.parametrize(
    "impostor",
    [
        _FakeAuthority("investigator"),
        _FakeAuthority("verifier"),
        _FakeAuthority("vouch.policy-engine"),  # right NAME, no key
        _FakeAuthority("vouch.policy-engine", proof="a" * 64),  # plausible digest
        _FakeAuthority("arbitrary-caller", proof=""),
    ],
    ids=["investigator", "verifier", "name-only", "fake-proof", "empty-proof"],
)
def test_unauthorized_identities_cannot_issue(world, impostor):
    """Asserting the Policy Engine's name is not the same as being it (F1).

    Authorization rests on a signature the store cannot produce and the
    impostor cannot forge — never on the identity string, which is recorded as
    provenance only.
    """
    corpus, capabilities, _, _ = world
    with pytest.raises(IssuerViolation):
        capabilities.issue(
            impostor,
            decision_record_id="DR-EVIL", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )
    assert capabilities.ledger == []
    assert capabilities._rows == {}
    assert corpus.lot("LOT-1").status == "RECEIVED"


def test_arbitrary_direct_store_caller_cannot_issue(world):
    """Even holding the store object itself grants nothing (F1)."""
    _, capabilities, _, _ = world
    for bogus in (None, object(), "vouch.policy-engine", 42):
        with pytest.raises((IssuerViolation, TypeError, AttributeError)):
            capabilities.issue(
                bogus,  # type: ignore[arg-type]
                decision_record_id="DR-EVIL", target_type=TargetType.LOT,
                target_id="LOT-1", action=Action.RELEASE_LOT,
                observed_state_version=1,
            )
    assert capabilities.ledger == []
    assert capabilities._rows == {}


def test_store_has_no_minting_operation(world):
    """The exact audit exploit (F1): `store._mint_issuer("arbitrary-caller")`.

    The finding was not that the method was named with an underscore — it was
    that the object which VALIDATES authority also VENDED it. There is now no
    minting operation on the store under any name, and the store holds no key
    material to mint from.
    """
    _, capabilities, _, _ = world
    assert not hasattr(capabilities, "_mint_issuer")
    # No attribute on the store returns anything that can sign.
    for name in dir(capabilities):
        attribute = getattr(capabilities, name, None)
        assert not isinstance(attribute, IssuanceAuthority), (
            f"{name} hands out issuance authority"
        )
    # And no attribute holds key bytes.
    for name in vars(capabilities):
        assert not isinstance(vars(capabilities)[name], (bytes, bytearray)), name


def test_exact_audit_exploit_is_impossible(world):
    """The verbatim exploit from the Iteration 2 audit, end to end (F1).

        store = CapabilityStore()
        issuer = store._mint_issuer("arbitrary-caller")
        capability = store.issue(issuer, ..., action=RELEASE_LOT, ...)
        store.consume(capability.capability_id, corpus)

    Every step must fail, zero capability rows must exist, and LOT-X must not
    become RELEASED.
    """
    corpus, _, _, _ = world
    store = CapabilityStore()

    with pytest.raises(AttributeError):
        store._mint_issuer("arbitrary-caller")  # type: ignore[attr-defined]

    # Even given the shape of the old credential, issuance refuses.
    with pytest.raises(IssuerViolation):
        store.issue(
            _FakeAuthority("arbitrary-caller"),
            decision_record_id="DR-EVIL", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )

    assert store._rows == {}
    assert store.ledger == []
    assert corpus.lot("LOT-1").status == "RECEIVED"
    assert corpus.get("inventory", "LOT-1").usable is False


def test_investigator_and_verifier_cannot_obtain_issuance_authority():
    """The decision agents cannot claim the issuance role (F1)."""
    from vouch.v2 import issuance

    class ApplicabilityInvestigator:  # look-alike defined outside the package
        pass

    class IndependentVerifier:
        pass

    for claimant in (ApplicabilityInvestigator, IndependentVerifier):
        with pytest.raises(IssuanceViolation):
            issuance.authority(claimant, "vouch.policy-engine")


def test_fake_policy_engine_class_cannot_claim_authority():
    """A class NAMED PolicyEngine, defined anywhere else, is refused (F1)."""
    from vouch.v2 import issuance

    class PolicyEngine:  # same qualname, different module
        IDENTITY = "vouch.policy-engine"

    with pytest.raises(IssuanceViolation):
        issuance.authority(PolicyEngine, "vouch.policy-engine")


def test_missing_issuer_is_a_type_error(world):
    """Omitting the issuer entirely creates nothing (F1)."""
    _, capabilities, _, _ = world
    with pytest.raises(TypeError):
        capabilities.issue(  # type: ignore[call-arg]
            decision_record_id="DR-EVIL", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )
    assert capabilities._rows == {}


def test_copied_issuer_object_cannot_be_reconstructed(world):
    """Copying the AUTHORITY object's visible fields yields nothing (F1).

    An attacker who can see `policy._issuer` in a traceback learns its identity
    string. Reconstructing a dataclass with that identity and any signing
    callable they can write does not produce a verifiable proof.
    """
    from dataclasses import replace as dc_replace

    _, capabilities, policy, _ = world
    genuine = policy._issuer

    # Reconstruct with the same identity but the attacker's own signer.
    forged = IssuanceAuthority(identity=genuine.identity, _sign=lambda binding: "0" * 64)
    with pytest.raises(IssuerViolation):
        capabilities.issue(
            forged,
            decision_record_id="DR-EVIL", target_type=TargetType.LOT,
            target_id="LOT-1", action=Action.RELEASE_LOT, observed_state_version=1,
        )
    assert capabilities._rows == {}

    # A genuine copy is NOT an escalation: obtaining one in the first place is
    # the guarded step, and it still signs exactly what policy already approved.
    copied = dc_replace(genuine)
    issued = capabilities.issue(
        copied,
        decision_record_id="DR-1", target_type=TargetType.LOT, target_id="LOT-1",
        action=Action.RELEASE_LOT, observed_state_version=1,
    )
    assert issued.issuer_identity == PolicyEngine.IDENTITY


def test_legitimate_policy_engine_issuance_succeeds(world):
    """The one authorized path still works (F1 pass condition)."""
    corpus, capabilities, _, events = world
    decision = _authorize_release(world)
    assert decision.allowed and decision.capability is not None
    entry = execute(decision.capability, corpus, capabilities, events)
    assert corpus.lot("LOT-1").status == "RELEASED"
    assert entry["issuer_identity"] == PolicyEngine.IDENTITY
    assert len(capabilities.ledger) == 1


def test_issuer_identity_alone_does_not_authenticate(world):
    """A stored row whose identity says policy-engine but whose proof is junk
    is refused at consume (F1/F2)."""
    corpus, capabilities, _, _ = world
    capability = _issue(world)
    capabilities._rows[capability.capability_id] = replace(
        capability, issuer_proof="f" * 64
    )
    with pytest.raises(VouchFailure) as caught:
        capabilities.consume(capability.capability_id, corpus)
    assert caught.value.category is FailureCategory.POLICY_REFUSAL
    assert corpus.lot("LOT-1").status == "RECEIVED"


def test_issuer_authority_is_not_exposed_by_repr(world):
    """The signing callable must not leak through logs or tracebacks."""
    _, _, policy, _ = world
    rendered = repr(policy._issuer)
    assert "_sign" not in rendered
    assert "lambda" not in rendered and "function" not in rendered


# ==========================================================================
# P0-2 — consumption dispatches internally
# ==========================================================================


def test_consume_accepts_no_callable(world):
    """The exact audit bypass: a caller-supplied mutation callback.

    `consume` has no parameter that accepts executable logic, so the attack has
    no argument to travel through.
    """
    corpus, capabilities, _, _ = world
    capability = _issue(world)

    def malicious(*args, **kwargs):
        corpus.bump("lot", "LOT-2", status="RELEASED")
        return {"result": "pwned", "inventory_delta": 0.0}

    with pytest.raises(TypeError):
        capabilities.consume(capability.capability_id, corpus, malicious)  # type: ignore[misc]


def test_release_capability_cannot_quarantine(world):
    """The action is read from the STORED row, not from the caller."""
    corpus, capabilities, _, events = world
    capability = _issue(world, action=Action.RELEASE_LOT)
    entry = capabilities.consume(capability.capability_id, corpus)
    assert entry["action"] == "release_lot"
    assert corpus.lot("LOT-1").status == "RELEASED"


def test_release_capability_cannot_mutate_another_lot(world):
    """A capability for LOT-1 cannot touch LOT-2 (the audit's stated attack)."""
    corpus, capabilities, _, _ = world
    corpus.put("lot", "LOT-2", Lot("LOT-2", "SUP-A", "MAT-1", "PO-2", 50.0))
    capability = _issue(world, lot_id="LOT-1")

    capabilities.consume(capability.capability_id, corpus)

    assert corpus.lot("LOT-1").status == "RELEASED"
    assert corpus.lot("LOT-2").status == "RECEIVED"  # untouched


def test_lot_capability_cannot_mutate_a_production_order(world):
    corpus, capabilities, _, _ = world
    corpus.put(
        "production_order", "ORD-1",
        ProductionOrder("ORD-1", "P", 10.0, (MaterialRequirementLine("MAT-1", 5.0),),
                        "LINE-1", "SLOT-1"),
    )
    capability = _issue(world)
    capabilities.consume(capability.capability_id, corpus)
    order = corpus.order("ORD-1")
    assert order.status == "READY"
    assert order.state_version == 1  # never touched


def test_consume_changes_the_bound_target_exactly_as_declared(world):
    corpus, capabilities, _, _ = world
    capability = _issue(world, action=Action.QUARANTINE_LOT)
    entry = capabilities.consume(capability.capability_id, corpus)

    assert entry["target_id"] == "LOT-1"
    assert entry["action"] == "quarantine_lot"
    assert corpus.lot("LOT-1").status == "QUARANTINED"
    assert entry["before_version"] == 1
    assert entry["after_version"] == 2
    assert corpus.usable_inventory("MAT-1") == 0.0


def test_unsupported_action_fails_closed(world, monkeypatch):
    """An action with no dispatch entry refuses rather than improvising."""
    import vouch.v2.authority as authority

    corpus, capabilities, _, _ = world
    capability = _issue(world, action=Action.RELEASE_LOT)
    monkeypatch.setattr(authority, "MUTATIONS", {})

    with pytest.raises(VouchFailure) as exc:
        capabilities.consume(capability.capability_id, corpus)
    assert exc.value.category is FailureCategory.POLICY_REFUSAL
    assert corpus.lot("LOT-1").status == "RECEIVED"


def test_missing_target_refuses(world):
    corpus, capabilities, _, _ = world
    capability = _issue(world, lot_id="LOT-1")
    corpus._t["lot"].pop("LOT-1")
    with pytest.raises(VouchFailure) as exc:
        capabilities.consume(capability.capability_id, corpus)
    assert exc.value.category is FailureCategory.STATE_CONFLICT


# ==========================================================================
# D12 properties 1-10
# ==========================================================================


# -- 1. unforgeability -----------------------------------------------------
def test_forged_capability_is_refused(world):
    """Constructing the data object yields no authority: there is no row."""
    corpus, capabilities, _, _ = world
    forged = CapabilityRecord(
        capability_id="CAP-forged", decision_record_id="DR-1",
        target_type=TargetType.LOT, target_id="LOT-1", action=Action.RELEASE_LOT,
        observed_state_version=1, policy_version="anything",
        expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        nonce="n", issuer_proof="i_made_this_up",
    )
    with pytest.raises(VouchFailure) as exc:
        capabilities.consume(forged.capability_id, corpus)
    assert exc.value.category is FailureCategory.POLICY_REFUSAL
    assert corpus.lot("LOT-1").status == "RECEIVED"


# -- 2. issuer authenticity ------------------------------------------------
def test_tampered_row_fails_authentication(world):
    """Editing a stored row without the secret invalidates its proof."""
    corpus, capabilities, _, _ = world
    capability = _issue(world)
    capabilities._rows[capability.capability_id] = replace(
        capability, action=Action.QUARANTINE_LOT
    )
    with pytest.raises(VouchFailure) as exc:
        capabilities.consume(capability.capability_id, corpus)
    assert "issuer authentication" in exc.value.detail
    assert corpus.lot("LOT-1").status == "RECEIVED"


def test_capability_from_another_store_is_refused(world):
    """A record issued by a different issuer is unknown to this store."""
    corpus, capabilities, _, _ = world
    other_store = CapabilityStore()
    other_corpus = Corpus()
    other_corpus.put("lot", "LOT-1", Lot("LOT-1", "SUP-A", "MAT-1", "PO-1", 100.0))
    other_policy = PolicyEngine(other_corpus, other_store)
    foreign = other_store.issue(
        other_policy._issuer,
        decision_record_id="DR-1", target_type=TargetType.LOT, target_id="LOT-1",
        action=Action.RELEASE_LOT, observed_state_version=1,
    )
    with pytest.raises(VouchFailure):
        capabilities.consume(foreign.capability_id, corpus)
    assert corpus.lot("LOT-1").status == "RECEIVED"


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
    """Rebinding the in-hand copy changes nothing; the row is authoritative."""
    corpus, capabilities, _, _ = world
    corpus.put("lot", "LOT-2", Lot("LOT-2", "SUP-A", "MAT-1", "PO-2", 50.0))
    capability = _issue(world)
    redirected = replace(capability, target_id="LOT-2")

    capabilities.consume(redirected.capability_id, corpus)

    assert corpus.lot("LOT-2").status == "RECEIVED"
    assert corpus.lot("LOT-1").status == "RELEASED"


def test_capability_is_bound_to_one_action(world):
    corpus, capabilities, _, events = world
    capability = _issue(world, action=Action.QUARANTINE_LOT)
    swapped = replace(capability, action=Action.RELEASE_LOT)

    entry = capabilities.consume(swapped.capability_id, corpus)

    assert entry["action"] == "quarantine_lot"
    assert corpus.lot("LOT-1").status == "QUARANTINED"


# -- 5. decision-record binding -------------------------------------------
def test_capability_traces_to_one_decision_record(world):
    corpus, capabilities, _, events = world
    capability = _issue(world)
    entry = execute(capability, corpus, capabilities, events)
    assert entry["decision_record_id"] == "DR-1"
    assert entry["issuer_identity"] == PolicyEngine.IDENTITY


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
    corpus, capabilities, policy, events = world
    capability = capabilities.issue(
        policy._issuer,
        decision_record_id="DR-1", target_type=TargetType.LOT, target_id="LOT-1",
        action=Action.RELEASE_LOT, observed_state_version=1, ttl_seconds=-1,
    )
    with pytest.raises(VouchFailure) as exc:
        execute(capability, corpus, capabilities, events)
    assert "expired" in exc.value.detail
    assert corpus.lot("LOT-1").status == "RECEIVED"


# -- 8. replay resistance (nonce) -----------------------------------------
def test_consumed_capability_cannot_be_revived_by_cloning(world):
    corpus, capabilities, _, events = world
    capability = _issue(world)
    execute(capability, corpus, capabilities, events)
    # A clone under a fresh id corresponds to no stored row.
    clone = replace(capability, capability_id="CAP-clone", used=False, consumed_at="")
    with pytest.raises(VouchFailure):
        capabilities.consume(clone.capability_id, corpus)
    assert len(capabilities.ledger) == 1


# -- 9. mutation-time verification ----------------------------------------
def test_all_checks_happen_at_consume_time(world):
    """A capability valid at issuance but invalid at consume time is refused."""
    corpus, capabilities, _, events = world
    capability = _issue(world, version=1)
    corpus.bump("lot", "LOT-1", status="QUARANTINED")  # now version 2
    with pytest.raises(VouchFailure):
        execute(capability, corpus, capabilities, events)


def test_direct_mutation_without_capability_is_impossible(world):
    """There is no unguarded mutation entry point."""
    corpus, capabilities, _, _ = world
    with pytest.raises(VouchFailure):
        capabilities.consume("CAP-never-issued", corpus)
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


def test_two_concurrent_consumers_of_one_capability(world):
    """The same capability consumed twice in parallel: exactly one wins."""
    corpus, capabilities, _, events = world
    capability = _issue(world)
    results = []

    def attempt():
        try:
            execute(capability, corpus, capabilities, events)
            results.append("ok")
        except VouchFailure:
            results.append("refused")

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1
    assert len(capabilities.ledger) == 1
    assert corpus.usable_inventory("MAT-1") == 100.0


# ==========================================================================
# policy engine refusals
# ==========================================================================


def test_policy_refuses_when_basis_checks_failed(world):
    corpus, capabilities, policy, events = world
    decision = policy.evaluate_lot_disposition(
        decision_record_id="DR-1", lot_id="LOT-1", disposition=Disposition.RELEASE,
        reconciliation_ok=True, basis_checks_ok=False, observed_state_version=1,
        events=events,
    )
    assert not decision.allowed
    assert decision.capability is None
    assert capabilities.ledger == []


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
