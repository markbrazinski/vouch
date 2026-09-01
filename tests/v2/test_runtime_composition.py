"""audit-2 F5 — the runtime uses authoritative state, or it fails closed.

The Iteration 2 audit found the AgentCore entrypoint composing `build_corpus()`
fixtures, a `LocalEvidenceStore`, an in-memory `CapabilityStore` and an
in-memory ledger, while only DecisionRecords reached DynamoDB — and describing
the result as a production backend. Manufacturing truth and authority were
process memory; a restart lost both.

These tests are static and structural: they assert what the composition WOULD
build and what it refuses to build. Nothing here touches AWS, and nothing here
is evidence that the live resources work — that is a separate live
qualification, recorded in docs/architecture/v2/AWS_STATUS.md.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from vouch.v2.contracts import FailureCategory, VouchFailure
from vouch.v2.runtime import LOCAL, PRODUCTION, Backend, build, requested_mode

ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "app" / "Gatehouse" / "main.py"


# ==========================================================================
# what production composes
# ==========================================================================


def test_production_mode_uses_durable_stores_for_every_authoritative_role(monkeypatch):
    """F5: S3 evidence + Dynamo state, capability, record and event stores."""
    monkeypatch.setenv("VOUCH_STATE_TABLE", "test-table")
    monkeypatch.setenv("VOUCH_EVIDENCE_BUCKET", "test-bucket")
    from vouch import config

    config.load.cache_clear()

    composition = build(PRODUCTION)
    backend = composition.backend

    assert backend.corpus == "AWS_DYNAMODB"
    assert backend.evidence_store == "AWS_S3"
    assert backend.capability_store == "AWS_DYNAMODB"
    assert backend.record_store == "AWS_DYNAMODB"
    assert backend.event_store == "AWS_DYNAMODB"
    assert backend.is_production

    # And the objects really are those adapters, not labels over local ones.
    from vouch.v2.aws import DynamoCapabilityStore, S3EvidenceStore
    from vouch.v2.persistence import DynamoRecordStore
    from vouch.v2.state import DynamoCorpus

    assert isinstance(composition.corpus, DynamoCorpus)
    assert isinstance(composition.workflow.evidence_store, S3EvidenceStore)
    assert isinstance(composition.workflow.capabilities, DynamoCapabilityStore)
    assert isinstance(composition.workflow.record_store, DynamoRecordStore)


def test_production_mode_constructs_no_fixture_corpus(monkeypatch):
    """F5: fixtures must be unreachable from the production path.

    Asserted by patching `build_corpus` to explode: if the production path
    calls it at all, this test fails rather than quietly serving demo data.
    """
    monkeypatch.setenv("VOUCH_STATE_TABLE", "test-table")
    monkeypatch.setenv("VOUCH_EVIDENCE_BUCKET", "test-bucket")
    from vouch import config

    config.load.cache_clear()

    import vouch.v2.fixtures as fixtures

    def explode(*args, **kwargs):
        raise AssertionError("production mode constructed the fixture corpus")

    monkeypatch.setattr(fixtures, "build_corpus", explode)
    composition = build(PRODUCTION)
    assert composition.backend.is_production


@pytest.mark.parametrize(
    "missing", ["VOUCH_STATE_TABLE", "VOUCH_EVIDENCE_BUCKET"]
)
def test_production_without_an_authoritative_dependency_fails_closed(
    monkeypatch, missing
):
    """F5: unavailable authoritative dependency -> typed failure, no fallback."""
    monkeypatch.setenv("VOUCH_STATE_TABLE", "test-table")
    monkeypatch.setenv("VOUCH_EVIDENCE_BUCKET", "test-bucket")
    monkeypatch.delenv(missing, raising=False)
    monkeypatch.delenv(missing.replace("VOUCH_", "GATEHOUSE_"), raising=False)
    monkeypatch.setattr(
        "vouch.config.MANIFEST", ROOT / "does-not-exist.json", raising=False
    )
    from vouch import config

    config.load.cache_clear()

    with pytest.raises(VouchFailure) as caught:
        build(PRODUCTION)
    assert caught.value.category is FailureCategory.PERSISTENCE_FAILURE
    assert "refusing to run on memory" in caught.value.detail
    config.load.cache_clear()


def test_an_unknown_mode_is_refused():
    with pytest.raises(VouchFailure):
        build("almost-production")


def test_local_mode_is_labeled_and_never_claims_durability():
    composition = build(LOCAL)
    backend = composition.backend
    assert backend.mode == LOCAL
    assert backend.is_production is False
    assert backend.as_dict()["durable"] is False
    assert "NOT_DURABLE" in backend.capability_store
    assert "SIMULATION" in backend.evidence_store


def test_backend_metadata_names_every_authoritative_component():
    """F5: the response cannot say 'production' while one component is memory."""
    mixed = Backend(
        mode=PRODUCTION,
        corpus="IN_MEMORY_FIXTURES",  # the exact audited defect
        evidence_store="AWS_S3",
        capability_store="AWS_DYNAMODB",
        record_store="AWS_DYNAMODB",
        event_store="AWS_DYNAMODB",
    )
    assert mixed.is_production is False
    assert mixed.as_dict()["durable"] is False
    assert mixed.as_dict()["corpus"] == "IN_MEMORY_FIXTURES"

    fields = set(Backend.__dataclass_fields__) - {"mode"}
    rendered = mixed.as_dict()
    for name in fields:
        assert name in rendered, f"{name} is not reported to the caller"


def test_production_is_the_default_mode(monkeypatch):
    """A deployment that forgot the variable must fail loudly, not serve
    fixtures."""
    monkeypatch.delenv("VOUCH_MODE", raising=False)
    monkeypatch.delenv("GATEHOUSE_MODE", raising=False)
    assert requested_mode() == PRODUCTION


# ==========================================================================
# the entrypoint itself
# ==========================================================================


def _entrypoint_ast() -> ast.Module:
    return ast.parse(ENTRYPOINT.read_text())


def test_entrypoint_does_not_import_the_fixture_corpus():
    """F5: `build_corpus` must not be reachable from the runtime module."""
    source = ENTRYPOINT.read_text()
    assert "build_corpus" not in source.replace(
        "`build_corpus`", ""
    ), "the entrypoint still references the fixture corpus"


def test_entrypoint_builds_exactly_one_composition():
    """F5: one place chooses the stack, so 'what is this using' has one answer."""
    source = ENTRYPOINT.read_text()
    assert "from vouch.v2.runtime import build" in source
    assert source.count("_COMPOSITION = build(") == 1


def test_entrypoint_has_no_memory_fallback():
    """F5: the audited defect was `except: use memory`. It must not exist.

    Walks the AST rather than grepping, so a fallback cannot hide behind
    different formatting.
    """
    tree = _entrypoint_ast()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        body = ast.dump(node)
        for forbidden in ("InMemoryRecordStore", "build_corpus", "LocalEvidenceStore"):
            assert forbidden not in body, (
                f"entrypoint falls back to {forbidden} inside an except handler"
            )


def test_entrypoint_reports_typed_failures_without_mutating():
    """F5: a VouchFailure becomes a typed response, not a generic 500."""
    source = ENTRYPOINT.read_text()
    assert "except VouchFailure" in source
    assert '"failure_category": failure.category.value' in source
    assert '"mutation": {}' in source
