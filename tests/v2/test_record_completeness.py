"""audit-2 F9 — DecisionRecord completeness is decision-type aware.

The Iteration 2 audit found `is_reconstructable` and `is_re_derivable`
returning True after contract-critical components were removed one at a time:
storage refs, object versions, prompt hashes, tool arguments, capability
bindings, mutation facts. A completeness assertion that survives the removal of
the thing it asserts is worse than no assertion, because it launders an
incomplete record as an auditable one.

Every test here is a MUTATION test: take a genuinely complete record, remove
exactly ONE component, and assert reconstructability fails and names it. If a
removal does not fail, the check does not cover that component.
"""

from __future__ import annotations

import copy
from dataclasses import replace

import pytest

from vouch.v2.contracts import FailureCategory
from vouch.v2.fixtures import COA_AMBIGUOUS, COA_CLEAN, build_corpus
from vouch.v2.workflow import VouchV2


@pytest.fixture
def released():
    """A complete AUTONOMOUS_MUTATION record: the clean lot releases."""
    corpus = build_corpus()
    vouch = VouchV2(corpus)
    outcome = vouch.evaluate_lot("LOT-1001", documents=[{"raw": COA_CLEAN}])
    assert outcome.disposition == "RELEASE", "fixture must actually release"
    return outcome.record


@pytest.fixture
def escalated():
    """A complete ESCALATED record: ambiguous evidence abstains."""
    corpus = build_corpus()
    vouch = VouchV2(corpus)
    outcome = vouch.evaluate_lot("LOT-1003", documents=[{"raw": COA_AMBIGUOUS}])
    assert outcome.quality_decision_required, "fixture must actually escalate"
    return outcome.record


def test_a_complete_release_record_is_reconstructable(released):
    assert released.missing_components() == []
    assert released.is_reconstructable()
    assert released.is_re_derivable()


def test_a_complete_escalation_record_is_reconstructable(escalated):
    assert escalated.missing_components() == []
    assert escalated.is_reconstructable()


def test_decision_types_are_distinguished(released, escalated):
    """F9: one flat rule cannot serve these. They require different things.

    An abstention that created a QA review DID mutate state, so it needs the
    full authority chain — but it must not claim a basis pass or an inventory
    movement. That is a third decision type, not a special case of either.
    """
    assert released.decision_type == "AUTONOMOUS_MUTATION"
    assert escalated.decision_type == "AUTHORIZED_ESCALATION"


# ==========================================================================
# the mutation matrix — one component removed at a time
# ==========================================================================


def _blank(record, path: str):
    """Remove exactly one component, addressed as `segment.field`."""
    segment_name, _, field_name = path.partition(".")
    segment = getattr(record, segment_name) if field_name else record
    target = field_name or segment_name
    current = getattr(segment, target)
    if isinstance(current, list):
        setattr(segment, target, [])
    elif isinstance(current, dict):
        setattr(segment, target, {})
    elif isinstance(current, bool):
        setattr(segment, target, False)
    elif isinstance(current, (int, float)):
        setattr(segment, target, 0)
    else:
        setattr(segment, target, "")


#: Every component the contract requires for an autonomous mutation, with the
#: substring that must appear in the failure so the check is proven to be
#: about THAT component rather than incidentally failing on something else.
RELEASE_COMPONENTS = [
    ("evidence.storage_refs", "storage_refs"),
    ("evidence.object_versions", "object_versions"),
    ("evidence.source_artifact_hashes", "source_artifact_hashes"),
    ("evidence.document_identities", "document_identities"),
    ("evidence.binding_statuses", "binding_statuses"),
    ("snapshot.claim_set_hash", "claim_set_hash"),
    ("corpus.objects", "corpus.objects"),
    ("corpus.corpus_hash", "corpus_hash"),
    ("investigator.model_id", "investigator.model_id"),
    ("investigator.prompt_version", "investigator.prompt_version"),
    ("investigator.prompt_hash", "investigator.prompt_hash"),
    ("investigator.brief", "investigator.brief"),
    ("investigator.brief_hash", "investigator.brief_hash"),
    ("investigator.input_claim_set_hash", "input_claim_set_hash"),
    ("verifier.model_id", "verifier.model_id"),
    ("verifier.prompt_hash", "verifier.prompt_hash"),
    ("verifier.brief", "verifier.brief"),
    ("reconciliation.outcome", "reconciliation.outcome"),
    ("basis.spec_id", "basis.spec_id"),
    ("basis.revision", "basis.revision"),
    ("basis.checks_passed", "checks_passed"),
    ("disposition.disposition", "disposition.disposition"),
    ("disposition.reason", "disposition.reason"),
    ("policy.policy_version", "policy.policy_version"),
    ("policy.gate_decision", "gate_decision"),
    ("capability.capability_id", "capability.capability_id"),
    ("capability.issued", "capability.issued"),
    ("capability.consumed", "capability.consumed"),
    ("mutation.target_type", "mutation.target_type"),
    ("mutation.target_id", "mutation.target_id"),
    ("mutation.result", "mutation.result"),
    ("mutation.ledger_sequence", "ledger_sequence"),
    # A zero delta is legitimate (quarantining a not-yet-usable lot moves
    # nothing); what must be present is proof the inventory was evaluated.
    ("mutation.inventory_before", "inventory_before/after"),
    ("mutation.inventory_after", "inventory_before/after"),
    ("mutation.after_version", "state versions"),

    ("storage.record_ref", "record_ref"),
    ("identity.lot_id", "identity.lot_id"),
    ("identity.record_id", "identity.record_id"),
]


@pytest.mark.parametrize(
    "path,expected", RELEASE_COMPONENTS, ids=[p for p, _ in RELEASE_COMPONENTS]
)
def test_removing_a_required_component_breaks_reconstructability(
    released, path, expected
):
    """F9: each removal must make reconstructability fail, and say why."""
    record = copy.deepcopy(released)
    _blank(record, path)

    missing = record.missing_components()
    assert missing, f"removing {path} left the record 'reconstructable'"
    assert any(expected in entry for entry in missing), (
        f"removing {path} failed for the wrong reason: {missing}"
    )
    assert not record.is_reconstructable()
    assert not record.is_re_derivable()


# -- provenance inside aligned arrays -----------------------------------


def test_a_missing_storage_ref_for_one_artifact_fails(released):
    """F9: alignment, not merely non-emptiness. Two hashes and one ref means
    one artifact's exact bytes cannot be re-fetched."""
    record = copy.deepcopy(released)
    record.evidence.source_artifact_hashes.append("second-artifact-hash")
    missing = record.missing_components()
    assert any("aligned" in entry for entry in missing)


def test_an_empty_object_version_string_fails(released):
    """F9: a present-but-empty value is as unusable as an absent one."""
    record = copy.deepcopy(released)
    record.evidence.object_versions[0] = ""
    assert any("object_versions values" in e for e in record.missing_components())


def test_an_empty_source_hash_fails(released):
    record = copy.deepcopy(released)
    record.evidence.source_artifact_hashes[0] = ""
    assert any("source_artifact_hashes values" in e for e in record.missing_components())


# -- claim-level provenance ---------------------------------------------


@pytest.mark.parametrize("field", ["method", "version", "locator", "source_hash"])
def test_removing_claim_extraction_provenance_fails(released, field):
    """F9: extraction method/version, locator and source hash per claim."""
    record = copy.deepcopy(released)
    assert record.extraction.per_claim, "fixture must have claims"
    claim_id = next(iter(record.extraction.per_claim))
    record.extraction.per_claim[claim_id][field] = ""
    missing = record.missing_components()
    assert any(field in entry for entry in missing), missing


# -- tool provenance -----------------------------------------------------


@pytest.mark.parametrize("agent", ["investigator", "verifier"])
def test_removing_tool_arguments_fails(released, agent):
    """F9: a record saying a tool ran but not what was asked cannot be replayed."""
    record = copy.deepcopy(released)
    segment = getattr(record, agent)
    assert segment.tool_events, "fixture must have tool calls"
    del segment.tool_events[0]["arguments"]
    assert any("arguments" in e for e in record.missing_components())


@pytest.mark.parametrize("agent", ["investigator", "verifier"])
def test_removing_tool_result_reference_fails(released, agent):
    record = copy.deepcopy(released)
    segment = getattr(record, agent)
    del segment.tool_events[0]["result_ref"]
    assert any("result" in e for e in record.missing_components())


def test_removing_the_tool_name_fails(released):
    record = copy.deepcopy(released)
    record.investigator.tool_events[0]["tool"] = ""
    assert any("tool_events[0].tool" in e for e in record.missing_components())


# -- hash verification ---------------------------------------------------


def test_a_corpus_hash_that_does_not_match_its_objects_fails(released):
    """F9: verify hashes where possible, not merely that a hash is present."""
    record = copy.deepcopy(released)
    record.corpus.corpus_hash = "0" * 64
    missing = record.missing_components()
    assert any("does not match" in e for e in missing)
    assert not record.is_re_derivable()


def test_a_brief_claim_set_hash_that_does_not_match_the_snapshot_fails(released):
    """F9: the brief must be shown to have been produced from THIS snapshot."""
    record = copy.deepcopy(released)
    record.investigator.input_claim_set_hash = "0" * 64
    assert any("input_claim_set_hash" in e for e in record.missing_components())


def test_a_mutation_before_version_that_does_not_match_the_snapshot_fails(released):
    """F9: the mutation must be shown to have applied to the observed state."""
    record = copy.deepcopy(released)
    record.mutation.before_version = 99
    assert any("before_version" in e for e in record.missing_components())


def test_a_governing_spec_revision_without_its_revision_fails(released):
    """F9: an unversioned authoritative object cannot pin what governed."""
    record = copy.deepcopy(released)
    key = next(
        k for k, v in record.corpus.objects.items() if v.get("kind") == "spec_revision"
    )
    record.corpus.objects[key]["revision"] = ""
    record.corpus.corpus_hash = __import__(
        "vouch.v2.contracts", fromlist=["content_hash"]
    ).content_hash(record.corpus.objects)
    assert any("revision" in e for e in record.missing_components())


# -- disagreement --------------------------------------------------------


def test_a_disagreement_without_the_differing_values_fails(released):
    """F9: 'they disagreed on basis' is unreviewable without the values."""
    record = copy.deepcopy(released)
    record.reconciliation.differing_fields = ["governing_basis"]
    record.reconciliation.investigator_values = {}
    record.reconciliation.verifier_values = {}
    missing = record.missing_components()
    assert any("investigator_values" in e for e in missing)
    assert any("verifier_values" in e for e in missing)


def test_disagreement_values_must_cover_every_differing_field(released):
    record = copy.deepcopy(released)
    record.reconciliation.differing_fields = ["governing_basis", "coverage"]
    record.reconciliation.investigator_values = {"governing_basis": "A"}
    record.reconciliation.verifier_values = {"governing_basis": "B"}
    assert any("do not cover" in e for e in record.missing_components())


# -- escalation-specific rules ------------------------------------------


@pytest.mark.parametrize(
    "path,expected",
    [
        ("human.review_id", "human.review_id"),
        ("human.review_status", "human.review_status"),
        ("storage.record_ref", "record_ref"),
        ("identity.lot_id", "identity.lot_id"),
        ("capability.capability_id", "capability.capability_id"),
        ("capability.consumed", "capability.consumed"),
        ("mutation.ledger_sequence", "ledger_sequence"),
        ("disposition.reason", "disposition.reason"),
    ],
)
def test_escalation_requires_its_own_components(escalated, path, expected):
    record = copy.deepcopy(escalated)
    _blank(record, path)
    missing = record.missing_components()
    assert missing, f"removing {path} left the escalation 'reconstructable'"
    assert any(expected in entry for entry in missing), missing


def test_an_escalation_claiming_a_mutation_fails(escalated):
    """F9: a record cannot both escalate and claim it changed state."""
    record = copy.deepcopy(escalated)
    record.mutation.action = "release_lot"
    assert not record.is_reconstructable()


def test_an_escalation_claiming_a_consumed_capability_fails():
    """F9: a record with a failure and NO mutation must not claim it spent
    authority. That combination is either a lie or a lost mutation."""
    from vouch.v2.decision_record import DecisionRecord

    record = DecisionRecord(record_id="DR-x")
    record.failure_category = FailureCategory.MATERIAL_DISAGREEMENT.value
    record.capability.consumed = True
    assert record.decision_type == "ESCALATED"
    assert any("consumed capability" in e for e in record.missing_components())


def test_an_authorized_escalation_must_not_move_inventory(escalated):
    """F9: a QA review is not a release. It cannot change usable inventory."""
    record = copy.deepcopy(escalated)
    record.mutation.inventory_delta = 100.0
    assert any("must not move usable inventory" in e for e in record.missing_components())


def test_a_record_with_neither_a_mutation_nor_a_failure_is_incomplete():
    """F9: 'nothing happened' is not a decision an auditor can reconstruct."""
    from vouch.v2.decision_record import DecisionRecord

    record = DecisionRecord(record_id="DR-empty")
    assert record.decision_type == "INCOMPLETE"
    assert not record.is_reconstructable()


def test_an_agent_that_failed_records_why_rather_than_a_brief():
    """F9: a model that never ran cannot be required to have produced a brief,
    but it MUST have recorded its failure detail."""
    from vouch.v2.decision_record import DecisionRecord

    record = DecisionRecord(record_id="DR-x")
    record.investigator.failure_category = FailureCategory.MODEL_UNAVAILABLE.value
    record.investigator.failure = ""
    record.failure_category = FailureCategory.MODEL_UNAVAILABLE.value
    assert any("investigator.failure detail" in e for e in record.missing_components())


def test_consequence_analysis_is_required_but_may_be_coverage_only(released):
    """A release must record its consequence analysis — but a readiness
    TRANSITION is not the only honest form of one.

    Hero B releases a lot into an order that was already covered: coverage
    changes, readiness does not move, and `caused_by` is legitimately empty.
    Either field satisfies the requirement; losing BOTH does not.
    """
    record = copy.deepcopy(released)
    assert record.mutation.inventory_delta, "fixture must actually move inventory"

    _blank(record, "consequences.caused_by")
    assert record.is_reconstructable(), (
        "coverage_changes alone is a complete consequence analysis"
    )

    _blank(record, "consequences.coverage_changes")
    missing = record.missing_components()
    assert any("caused_by or coverage_changes" in entry for entry in missing), missing
    assert not record.is_reconstructable()
