"""P1-3 failure taxonomy, P1-6 readiness persistence, P1-7 recovery execution.

Three audit findings with a shared shape: the system computed the right answer
and then failed to keep it. Failures were relabeled, readiness was returned but
never written, recovery was selected but never executed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from vouch.v2.agents import (
    AgentRun,
    ApplicabilityInvestigator,
    IndependentVerifier,
    _classify_exception,
)
from vouch.v2.authority import Action
from vouch.v2.consequences import (
    Readiness,
    compute_readiness,
    enumerate_recovery,
    recalculate_consequences,
)
from vouch.v2.contracts import RETRYABLE, FailureCategory, VouchFailure
from vouch.v2.fixtures import COA_CLEAN, COA_HERO, build_corpus
from vouch.v2.lifecycle import EventLog, EventType
from vouch.v2.workflow import VouchV2


@pytest.fixture
def vouch():
    corpus = build_corpus()
    return corpus, VouchV2(corpus)


# ==========================================================================
# P1-3 — failures retain their actual category
# ==========================================================================


class _Boom(ApplicabilityInvestigator):
    """An investigator that fails a specific way, a counted number of times."""

    def __init__(self, corpus, failure: VouchFailure, succeed_after: int = 999):
        from vouch.v2.local_reasoners import investigator_reasoner

        super().__init__(corpus, local_fn=investigator_reasoner)
        self._failure = failure
        self._succeed_after = succeed_after
        self.calls = 0

    def run(self, **kwargs):
        self.calls += 1
        if self.calls > self._succeed_after:
            return super().run(**kwargs)
        return AgentRun(
            None, "m", "v", "h", [], False, self._failure.detail,
            failure_category=self._failure.category,
        )


@pytest.mark.parametrize(
    "category",
    [
        FailureCategory.MODEL_TIMEOUT,
        FailureCategory.MODEL_UNAVAILABLE,
        FailureCategory.TOOL_FAILURE,
        FailureCategory.INVESTIGATOR_SCHEMA_FAILURE,
    ],
)
def test_investigator_failure_keeps_its_category(vouch, category):
    """A model outage must not be reported as a schema failure."""
    corpus, _ = vouch
    v = VouchV2(corpus, investigator=_Boom(corpus, VouchFailure(category, "boom")))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == category.value
    assert outcome.disposition == ""
    assert not outcome.mutated
    assert outcome.record.investigator.failure_category == category.value


def test_verifier_failure_keeps_its_category(vouch):
    corpus, _ = vouch

    class Down(IndependentVerifier):
        def run(self, **kwargs):
            return AgentRun(
                None, "m", "v", "h", [], False, "bedrock down",
                failure_category=FailureCategory.MODEL_UNAVAILABLE,
            )

    v = VouchV2(corpus, verifier=Down(corpus))
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert outcome.failure_category == "MODEL_UNAVAILABLE"
    assert outcome.quality_decision_required
    assert not outcome.mutated


def test_retryable_failures_are_retried(vouch):
    """A schema failure may clear on a re-ask, so it gets the budget."""
    corpus, _ = vouch
    agent = _Boom(
        corpus,
        VouchFailure(FailureCategory.INVESTIGATOR_SCHEMA_FAILURE, "malformed"),
        succeed_after=1,
    )
    v = VouchV2(corpus, investigator=agent)
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert agent.calls == 2
    assert outcome.disposition == "RELEASE"  # the retry succeeded


def test_non_retryable_failures_are_not_retried(vouch):
    """P1-3: 'do not retry every failure identically.'

    A POLICY_REFUSAL will produce the identical result on every attempt.
    Retrying it burns budget and delays escalation.
    """
    corpus, _ = vouch
    agent = _Boom(corpus, VouchFailure(FailureCategory.POLICY_REFUSAL, "refused"))
    v = VouchV2(corpus, investigator=agent)
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    assert agent.calls == 1
    assert FailureCategory.POLICY_REFUSAL not in RETRYABLE


def test_retry_count_is_recorded(vouch):
    corpus, _ = vouch
    agent = _Boom(
        corpus, VouchFailure(FailureCategory.MODEL_TIMEOUT, "throttled"), succeed_after=1
    )
    v = VouchV2(corpus, investigator=agent)
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert outcome.record.investigator.attempts == 2


@pytest.mark.parametrize(
    "exc,expected",
    [
        (type("ThrottlingException", (Exception,), {})(), FailureCategory.MODEL_TIMEOUT),
        (type("ReadTimeoutError", (Exception,), {})(), FailureCategory.MODEL_TIMEOUT),
        (Exception("AccessDeniedException"), FailureCategory.MODEL_UNAVAILABLE),
        (Exception("ValidationException: bad model id"), FailureCategory.MODEL_UNAVAILABLE),
        (ConnectionError("no route"), FailureCategory.MODEL_TIMEOUT),
        (PermissionError("tool denied"), FailureCategory.TOOL_FAILURE),
    ],
)
def test_exception_classification(exc, expected):
    assert (
        _classify_exception(exc, FailureCategory.INVESTIGATOR_SCHEMA_FAILURE) is expected
    )


def test_security_quarantine_is_not_insufficiency(vouch):
    """Distinct categories stay distinct end to end."""
    from vouch.v2.fixtures import COA_HOSTILE

    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1004", documents=[{"raw": COA_HOSTILE}])
    assert outcome.failure_category == "SECURITY_QUARANTINE"
    assert outcome.failure_category != "DOMAIN_INSUFFICIENT_EVIDENCE"


# ==========================================================================
# P1-6 — readiness is persisted
# ==========================================================================


def test_readiness_transition_is_written_not_just_computed(vouch):
    corpus, v = vouch
    assert corpus.order("C-417").status == "READY"

    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    order = corpus.order("C-417")
    assert order.status == "BLOCKED"
    assert order.state_version == 2  # a real, versioned transition

    change = next(
        c for c in outcome.consequences["readiness_changes"] if c["order_id"] == "C-417"
    )
    assert change["persisted"] is True
    assert change["state_version"] == 2


def test_readiness_transition_goes_through_the_capability_ledger(vouch):
    """No side door: readiness uses the same authority path as any mutation."""
    corpus, v = vouch
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    entries = [e for e in v.capabilities.ledger if e["action"] == "set_order_readiness"]
    assert entries
    assert entries[0]["target_id"] == "C-417"
    assert entries[0]["target_type"] == "production_order"
    assert entries[0]["issuer_identity"] == "vouch.policy-engine"


def test_readiness_emits_a_transition_event(vouch):
    corpus, v = vouch
    events = EventLog()
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}], events=events)

    emitted = events.of_type(EventType.READINESS_TRANSITIONED)
    assert emitted
    assert emitted[0].payload["order_id"] == "C-417"
    assert emitted[0].payload["to"] == "BLOCKED"
    assert emitted[0].payload["caused_by_lot"] == "LOT-1001"


def test_causal_link_records_what_caused_the_transition(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    link = next(
        link for link in outcome.consequences["caused_by"] if link["order_id"] == "C-417"
    )
    assert link["cause"] == "lot_disposition"
    assert link["lot_id"] == "LOT-1001"
    assert link["ledger_sequence"]


def test_without_authority_readiness_is_not_silently_persisted(vouch):
    """The pure calculation stays callable, and says it did not write."""
    corpus, _ = vouch
    result = recalculate_consequences(
        corpus, decision_record_id="DR-1", lot_id="LOT-1001",
        inventory_delta=0.0, events=EventLog(),
    )
    assert all(not c["persisted"] for c in result["readiness_changes"])


# ==========================================================================
# P1-7 — recovery actually executes
# ==========================================================================


def test_recovery_executes_a_resequence(vouch):
    """The plan actually changes."""
    corpus, v = vouch
    before = corpus.order("C-418").planned_slot
    blocked_slot = corpus.order("C-417").planned_slot

    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    recovery = outcome.record.consequences.recovery

    assert recovery["executed"] is True
    assert recovery["selected"]["candidate_id"] == "C-418"

    after = corpus.order("C-418")
    assert after.planned_slot == blocked_slot != before
    assert after.state_version == 2


def test_recovery_mutation_is_capability_gated(vouch):
    corpus, v = vouch
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])

    entries = [
        e for e in v.capabilities.ledger
        if e["action"] == "resequence_production_order"
    ]
    assert entries
    assert entries[0]["target_id"] == "C-418"
    assert entries[0]["before_version"] == 1
    assert entries[0]["after_version"] == 2


def test_recovery_records_all_candidates_and_the_causal_link(vouch):
    corpus, v = vouch
    outcome = v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    recovery = outcome.record.consequences.recovery

    kinds = {c["kind"] for c in recovery["candidates"]}
    assert {"EXISTING_INVENTORY", "SUBSTITUTE", "RESEQUENCE"} <= kinds
    # REFUSED stays visibly distinct from NOT_FEASIBLE.
    assert any(c["verdict"] == "REFUSED" for c in recovery["candidates"])

    assert recovery["caused_by"]["cause"] == "order_blocked"
    assert recovery["caused_by"]["blocked_order_id"] == "C-417"
    assert recovery["caused_by"]["order_id"] == "C-418"


def test_recovery_reverifies_the_slot_at_execution(vouch):
    """P1-7: the slot is re-checked at MUTATION time, not trusted from
    enumeration.

    This is a genuine TOCTOU: the option is enumerated while the slot is free,
    and the slot is taken before the capability is consumed. The mutation must
    refuse rather than overwrite the order now sitting there.
    """
    from vouch.v2.authority import Action, execute

    corpus, v = vouch
    events = EventLog()
    corpus.bump("production_order", "C-417", status="BLOCKED")
    target_slot = corpus.order("C-417").planned_slot

    # Enumerate while the slot is genuinely free: C-418 is eligible.
    _, selected = enumerate_recovery(corpus, "C-417")
    assert selected.candidate_id == "C-418"

    candidate = corpus.order("C-418")
    decision = v.policy.authorize_order_action(
        decision_record_id="DR-1", order_id="C-418",
        action=Action.RESEQUENCE_PRODUCTION_ORDER,
        observed_state_version=candidate.state_version, events=events,
    )
    assert decision.allowed

    # ...and only NOW someone else parks an order in that slot.
    c419 = corpus.order("C-419")
    corpus.put(
        "production_order", "C-500",
        replace(c419, order_id="C-500", resource="LINE-1", planned_slot=target_slot),
    )

    with pytest.raises(VouchFailure) as exc:
        execute(
            decision.capability, corpus, v.capabilities, events,
            params={"target_slot": target_slot},
        )
    assert exc.value.category is FailureCategory.STATE_CONFLICT
    assert "occupied" in exc.value.detail
    assert corpus.order("C-418").planned_slot == "2026-08-15T14:00"  # unmoved


def test_recovery_never_invents_an_option(vouch):
    """No lawful option means escalation, not improvisation."""
    corpus, v = vouch
    for order in list(corpus.all("production_order")):
        if order.order_id != "C-417":
            corpus._t["production_order"].pop(order.order_id)
    corpus.bump("production_order", "C-417", status="BLOCKED")

    result = v.recover_order("C-417", decision_record_id="DR-1", events=EventLog())
    assert result["executed"] is False
    assert result["selected"] is None
    assert "no lawful recovery option" in result["reason"]


def test_recovery_emits_an_evaluation_event(vouch):
    corpus, v = vouch
    events = EventLog()
    v.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}], events=events)

    emitted = events.of_type(EventType.RECOVERY_EVALUATED)
    assert emitted
    assert emitted[0].payload["blocked_order_id"] == "C-417"
    assert emitted[0].payload["candidate_count"] >= 3
    assert emitted[0].payload["refused_count"] >= 1
