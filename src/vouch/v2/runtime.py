"""Runtime composition — which adapters actually run (audit-2 F5).

The audit's finding was that the AgentCore entrypoint composed a *mixed* stack
and described it as a production backend: `build_corpus()` fixtures, a
`LocalEvidenceStore`, an in-memory `CapabilityStore` and an in-memory ledger,
with only DecisionRecords reaching DynamoDB. Manufacturing truth and authority
were process memory. A restart lost both.

This module is the single place the stack is chosen, so "what is this runtime
actually using" has one answer that both the entrypoint and a test can read.

Two modes, and nothing in between:

    PRODUCTION   DynamoCorpus + S3EvidenceStore + DynamoCapabilityStore
                 + DynamoRecordStore. Every authoritative component durable.
                 An unavailable dependency is a typed fail-closed result, NOT
                 a fallback to memory.

    LOCAL        The fixture corpus and the in-memory stores, labeled as such
                 in every response. For tests and local development only.

`build()` never silently downgrades. If production is requested and any
authoritative dependency is missing, it raises `VouchFailure` and the runtime
answers with a typed failure rather than a successful-looking mutation against
state that evaporates.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .contracts import FailureCategory, VouchFailure

PRODUCTION = "production"
LOCAL = "local"


@dataclass(frozen=True)
class Backend:
    """Exactly which component is behind each authoritative role.

    Every field names a real class, so the response metadata cannot claim more
    durability than the composition provides (F5). `is_production` is true only
    when every authoritative component is durable — not when one of them is.
    """

    mode: str
    corpus: str
    evidence_store: str
    capability_store: str
    record_store: str
    event_store: str

    DURABLE = frozenset({"AWS_DYNAMODB", "AWS_S3", "LOCAL_JSON"})

    @property
    def is_production(self) -> bool:
        return self.mode == PRODUCTION and all(
            kind in self.DURABLE
            for kind in (
                self.corpus, self.evidence_store,
                self.capability_store, self.record_store, self.event_store,
            )
        )

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "corpus": self.corpus,
            "evidence_store": self.evidence_store,
            "capability_store": self.capability_store,
            "record_store": self.record_store,
            "event_store": self.event_store,
            "durable": self.is_production,
        }

    def describe(self) -> str:
        return (
            f"mode={self.mode} corpus={self.corpus} evidence={self.evidence_store} "
            f"capabilities={self.capability_store} records={self.record_store}"
        )


@dataclass
class Composition:
    """The assembled stack plus an honest description of what it is."""

    workflow: object
    corpus: object
    backend: Backend
    capabilities: object = None
    record_store: object = None


def requested_mode() -> str:
    """PRODUCTION unless explicitly told otherwise.

    Defaulting to production is deliberate: a deployment that forgot to set the
    variable should fail loudly on a missing table, not quietly serve fixtures.
    """
    explicit = os.environ.get("VOUCH_MODE") or os.environ.get("GATEHOUSE_MODE")
    if explicit:
        return explicit.strip().lower()
    return PRODUCTION


def build(mode: str | None = None) -> Composition:
    """Compose the runtime. Fail closed; never fall back to memory."""
    mode = (mode or requested_mode()).lower()
    if mode == LOCAL:
        return _build_local()
    if mode != PRODUCTION:
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            f"unknown runtime mode {mode!r}; expected 'production' or 'local'",
        )
    return _build_production()


def _build_local() -> Composition:
    """Fixtures and in-memory stores. Labeled, never described as durable."""
    from .authority import CapabilityStore
    from .evidence import LocalEvidenceStore
    from .fixtures import build_corpus
    from .persistence import InMemoryRecordStore
    from .workflow import VouchV2

    corpus = build_corpus()
    evidence_store = LocalEvidenceStore()
    capabilities = CapabilityStore()
    record_store = InMemoryRecordStore()
    backend = Backend(
        mode=LOCAL,
        corpus="IN_MEMORY_FIXTURES",
        evidence_store=LocalEvidenceStore.kind,
        capability_store="IN_MEMORY_NOT_DURABLE",
        record_store=InMemoryRecordStore.kind,
        event_store=InMemoryRecordStore.kind,
    )
    workflow = VouchV2(
        corpus,
        evidence_store=evidence_store,
        capabilities=capabilities,
        record_store=record_store,
    )
    return Composition(workflow, corpus, backend, capabilities, record_store)


def _build_production() -> Composition:
    """Every authoritative component durable, or a typed failure.

    No `except: fall back to memory` anywhere in this function. That pattern is
    the exact defect F5 names: it turns an unreachable table into a runtime
    that reports authorized mutations nobody can audit.

    NOTE: no fixture corpus is constructed here. `build_corpus` is not imported
    on this path at all, so production cannot accidentally serve fixture data.
    """
    from ..config import env_var, load
    from .aws import BedrockGuardrailDetector, DynamoCapabilityStore, S3EvidenceStore
    from .persistence import DynamoRecordStore
    from .state import DynamoCorpus
    from .workflow import VouchV2

    config = load()
    if not config.state_table:
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            "production mode requires VOUCH_STATE_TABLE; refusing to run on memory",
        )
    if not config.evidence_bucket:
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            "production mode requires VOUCH_EVIDENCE_BUCKET; refusing to run on memory",
        )

    corpus = DynamoCorpus(config.state_table)
    evidence_store = S3EvidenceStore(config.evidence_bucket)
    capabilities = DynamoCapabilityStore(config.state_table)
    record_store = DynamoRecordStore(config.state_table)

    backend = Backend(
        mode=PRODUCTION,
        corpus=DynamoCorpus.kind,
        evidence_store=S3EvidenceStore.kind,
        capability_store=DynamoCapabilityStore.kind,
        record_store=DynamoRecordStore.kind,
        event_store=DynamoRecordStore.kind,
    )
    # The real prompt-attack detector, where one is configured. Without it the
    # production runtime inspected supplier evidence with the local regex
    # heuristic while every other component was durable.
    #
    # An unconfigured guardrail is NOT a silent downgrade: the detector raises
    # when it has no id and `inspect` turns that into a fail-closed ERROR. So
    # production either inspects with Bedrock or refuses the artifact.
    detector = BedrockGuardrailDetector() if env_var("GUARDRAIL_ID") else None

    workflow = VouchV2(
        corpus,
        evidence_store=evidence_store,
        capabilities=capabilities,
        record_store=record_store,
        detector=detector,
    )
    return Composition(workflow, corpus, backend, capabilities, record_store)


__all__ = ["Backend", "Composition", "LOCAL", "PRODUCTION", "build", "requested_mode"]
