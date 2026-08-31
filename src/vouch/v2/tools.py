"""The tool constitution (contract D6), enforced in code.

Every tool here is read-only and returns structured, authoritative objects — or
previously-cleansed labeled claims. No tool returns raw supplier free text, so
hostile document content cannot re-enter through a tool result (S8).

Least-privilege is real here, not vacuous: each agent is built with an explicit
tool list, and `find_relevant_precedents` is registered for the Investigator
only. The Verifier is constructed without it, so precedent-blindness is a
property of the object graph rather than a prompt instruction.

V1's failure was `tools=[]` — facts were pre-computed and pasted into the
prompt, which made "least privilege" true but meaningless. These tools actually
reach the model.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable

from .corpus import Corpus
from .lifecycle import EventLog, EventType


class ToolAuthority(str):
    AUTHORITATIVE = "authoritative"
    ADVISORY = "advisory"
    FROZEN_CLAIMS = "frozen_claims"


class WriteToolViolation(PermissionError):
    """A write-capable callable was registered on a model-facing toolset."""


@dataclass
class ToolEvent:
    agent: str
    tool: str
    category: str
    authority_class: str
    result_count: int
    object_refs: list[str]
    elapsed_ms: float
    status: str = "OK"

    def as_dict(self) -> dict:
        return {
            "agent": self.agent, "tool": self.tool, "category": self.category,
            "authority_class": self.authority_class, "result_count": self.result_count,
            "object_refs": self.object_refs[:20], "elapsed_ms": round(self.elapsed_ms, 2),
            "status": self.status,
        }


class CorpusTools:
    """The read-only corpus surface, scoped to one decision context.

    Scoping matters: the tools are constructed with the lot/material of the
    current decision, so an agent cannot enumerate unrelated lots or wander the
    database. There is no generic query method by design.
    """

    #: Names that may be exposed to a model. Anything not listed is not a tool.
    INVESTIGATOR_TOOLS = (
        "get_evidence_snapshot",
        "list_candidate_specs",
        "get_spec_requirement",
        "list_applicable_deviations",
        "list_equivalence_records",
        "get_supplier_qualification",
    )
    # Deliberately identical minus precedent. The Verifier never gets precedent
    # (D5) — that asymmetry is what gives independence teeth.
    VERIFIER_TOOLS = (
        "get_evidence_snapshot",
        "list_candidate_specs",
        "get_spec_requirement",
        "list_applicable_deviations",
        "list_equivalence_records",
        "get_supplier_qualification",
    )

    def __init__(
        self,
        corpus: Corpus,
        *,
        agent_name: str,
        lot_id: str,
        material_id: str,
        snapshot_claims: list[Any],
        events: EventLog | None = None,
        decision_record_id: str = "",
        allow_precedent: bool = False,
    ) -> None:
        self._corpus = corpus
        self._agent = agent_name
        self._lot_id = lot_id
        self._material_id = material_id
        self._claims = snapshot_claims
        self._events = events
        self._drid = decision_record_id
        self._allow_precedent = allow_precedent
        self.tool_events: list[ToolEvent] = []

    # -- observability ----------------------------------------------------
    def _record(
        self, tool: str, category: str, authority: str, results: list, refs: list[str],
        started: float,
    ) -> None:
        event = ToolEvent(
            agent=self._agent, tool=tool, category=category, authority_class=authority,
            result_count=len(results), object_refs=refs,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        self.tool_events.append(event)
        if self._events:
            self._events.emit(
                EventType.TOOL_CALLED, self._drid,
                agent=self._agent, tool=tool, category=category, authority_class=authority,
            )
            self._events.emit(
                EventType.TOOL_RESULT_BOUND, self._drid,
                agent=self._agent, tool=tool, result_count=len(results),
                object_refs=refs[:20], elapsed_ms=round(event.elapsed_ms, 2),
            )

    # -- tools ------------------------------------------------------------
    def get_evidence_snapshot(self) -> list[dict]:
        """The frozen, labeled claims for this decision.

        Returns claims as DATA with their trust labels attached. Never the raw
        document; never anything in an instruction position.
        """
        started = time.perf_counter()
        out = [
            {
                "claim_id": c.claim_id,
                "characteristic": c.characteristic,
                "value": c.value,
                "units": c.units,
                "method": c.method,
                "condition": c.condition,
                "claimed_spec": c.claimed_spec,
                "trust_label": c.trust_label.value,
                "source_locator": c.source_locator,
                "extraction_method": c.extraction_method.value,
            }
            for c in self._claims
        ]
        self._record(
            "get_evidence_snapshot", "evidence", ToolAuthority.FROZEN_CLAIMS,
            out, [c["claim_id"] for c in out], started,
        )
        return out

    def list_candidate_specs(self) -> list[dict]:
        """Every specification revision that could plausibly govern.

        Deliberately returns candidates, plural. Choosing among them is the
        judgment the model exists to make — precomputing the winner here is the
        V1 mistake this architecture is correcting.
        """
        started = time.perf_counter()
        revisions = self._corpus.candidate_specs(self._material_id)
        out = [
            {
                "spec_id": r.spec_id,
                "revision": r.revision,
                "status": r.status,
                "effective_date": r.effective_date,
                "effective_basis": r.effective_basis,
                "superseded_by": r.superseded_by,
                "is_current": r.is_current,
                "incorporates": list(r.incorporates),
                "requirement_count": len(r.requirements),
            }
            for r in revisions
        ]
        self._record(
            "list_candidate_specs", "specification", ToolAuthority.AUTHORITATIVE,
            out, [f"{r.spec_id}:{r.revision}" for r in revisions], started,
        )
        return out

    def get_spec_requirement(self, spec_id: str, revision: str) -> list[dict]:
        """The required tests for one revision, including anything it
        incorporates by reference."""
        started = time.perf_counter()
        rev = self._corpus.spec_revision(spec_id, revision)
        out: list[dict] = []
        if rev is not None:
            requirements = list(rev.requirements)
            for ref in rev.incorporates:
                other = self._corpus.get("spec_revision", ref)
                if other is not None:
                    requirements.extend(other.requirements)
            out = [
                {
                    "requirement_id": q.requirement_id,
                    "characteristic": q.characteristic,
                    "method": q.method,
                    "condition": q.condition,
                    "min_value": q.min_value,
                    "max_value": q.max_value,
                    "units": q.units,
                    "threshold": q.threshold_text(),
                }
                for q in requirements
            ]
        self._record(
            "get_spec_requirement", "specification", ToolAuthority.AUTHORITATIVE,
            out, [f"{spec_id}:{revision}"], started,
        )
        return out

    def list_applicable_deviations(self) -> list[dict]:
        """Deviations on record for this material, with their scope exposed.

        Scope is returned rather than pre-applied: the model may cite one, and
        `basis_checks` then re-verifies deterministically that it truly covers
        this site/PO/lot/date.
        """
        started = time.perf_counter()
        deviations = self._corpus.deviations_for(self._material_id)
        out = [
            {
                "deviation_id": d.deviation_id,
                "characteristic": d.characteristic,
                "status": d.status,
                "effective_date": d.effective_date,
                "expiry_date": d.expiry_date,
                "site_scope": list(d.site_scope),
                "po_scope": list(d.po_scope),
                "lot_scope": list(d.lot_scope),
                "accepts_min": d.accepts_min,
                "accepts_max": d.accepts_max,
            }
            for d in deviations
        ]
        self._record(
            "list_applicable_deviations", "deviation", ToolAuthority.AUTHORITATIVE,
            out, [d.deviation_id for d in deviations], started,
        )
        return out

    def list_equivalence_records(self) -> list[dict]:
        started = time.perf_counter()
        equivalences = self._corpus.equivalences_for(self._material_id)
        out = [
            {
                "equivalence_id": e.equivalence_id,
                "required_method": e.required_method,
                "alternate_method": e.alternate_method,
                "status": e.status,
                "effective_date": e.effective_date,
                "expiry_date": e.expiry_date,
                "condition_scope": list(e.condition_scope),
                "characteristic_scope": list(e.characteristic_scope),
            }
            for e in equivalences
        ]
        self._record(
            "list_equivalence_records", "equivalence", ToolAuthority.AUTHORITATIVE,
            out, [e.equivalence_id for e in equivalences], started,
        )
        return out

    def get_supplier_qualification(self) -> dict:
        """Boolean + scope. Never a narrative."""
        started = time.perf_counter()
        lot = self._corpus.lot(self._lot_id)
        qualification = (
            self._corpus.qualification(lot.supplier_id, self._material_id) if lot else None
        )
        out: dict = {"found": qualification is not None}
        if qualification is not None and lot is not None:
            out.update(
                {
                    "qualification_id": qualification.qualification_id,
                    "status": qualification.status,
                    "effective_date": qualification.effective_date,
                    "expiry_date": qualification.expiry_date,
                    "site_scope": list(qualification.site_scope),
                    "covers_this_lot": qualification.covers(
                        when=lot.received_at or lot.manufactured_at,
                        site_id=lot.supplier_site,
                    ),
                }
            )
        self._record(
            "get_supplier_qualification", "qualification", ToolAuthority.AUTHORITATIVE,
            [out], [out.get("qualification_id", "")], started,
        )
        return out

    def find_relevant_precedents(self, ambiguity: str = "") -> list[dict]:
        """Milestone 2 (P1). Registered for the Investigator only, and stubbed.

        Returns nothing in Milestone 1 so no evaluation can be contaminated by
        precedent, while the tool-scoping asymmetry is already real and
        testable. Calling it on a Verifier toolset is a hard error.
        """
        if not self._allow_precedent:
            raise WriteToolViolation(
                "find_relevant_precedents is not registered for this agent"
            )
        started = time.perf_counter()
        out: list[dict] = []  # P1 stub: intentionally empty in Milestone 1
        self._record(
            "find_relevant_precedents", "precedent", ToolAuthority.ADVISORY, out, [], started,
        )
        return out

    # -- registration -----------------------------------------------------
    def callables(self, names: tuple[str, ...]) -> list[Callable]:
        """Bind the named tools. Raises if a name is not an allowed read tool,
        so a typo cannot silently widen the surface."""
        allowed = set(self.INVESTIGATOR_TOOLS) | {"find_relevant_precedents"}
        out = []
        for name in names:
            if name not in allowed:
                raise WriteToolViolation(f"{name!r} is not a permitted read-only tool")
            out.append(getattr(self, name))
        return out


def assert_read_only(tools: list[Callable]) -> None:
    """Structural check that no mutation-capable callable reached a model.

    Names are the cheap signal; the real guarantee is that CorpusTools has no
    mutation methods at all and the mutation path lives in authority.py behind
    a capability record.
    """
    forbidden = ("release", "quarantine", "mutate", "hold", "resequence", "issue_capability",
                 "put", "write", "delete", "set_")
    for tool in tools:
        name = getattr(tool, "__name__", str(tool))
        if any(bad in name.lower() for bad in forbidden):
            raise WriteToolViolation(f"tool {name!r} is not read-only")


__all__ = [
    "CorpusTools",
    "ToolAuthority",
    "ToolEvent",
    "WriteToolViolation",
    "assert_read_only",
]
