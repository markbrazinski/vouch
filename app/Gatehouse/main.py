"""Vouch V2 AgentCore Runtime entrypoint.

Hosts the same V2 pipeline the tests exercise. Deliberately NOT a chat
interface: the payload is a typed action and the response is a typed outcome.

Actions:
  {"action": "evaluate_lot",     "lot_id": ..., "document": "<coa text>"}
  {"action": "supply_evidence",  "decision_record_id": ..., "lot_id": ...,
                                 "document": ..., "authority_source": ...}
  {"action": "readiness",        "order_id": ...}
  {"action": "recovery",         "order_id": ...}
  {"action": "ledger"}

Three things this entrypoint deliberately does NOT do:

  * It does not silently fall back to in-memory state and call it authoritative
    (audit-2 F5). The composition is built once by `vouch.v2.runtime.build()`,
    which either returns a fully durable production stack or raises. There is
    no `except: use memory` path here, because a runtime with an unreachable
    table reporting successful "authorized" mutations is the worst possible
    failure mode.
  * It does not construct a fixture corpus in production mode. `build_corpus`
    is not imported on the production path at all.
  * It exposes no fixture-specific evidence writer. V1 shipped `add_qa_evidence`
    as a runtime action; the human-continuation path takes caller-supplied
    content through the real ingestion boundary instead.

Every response reports the ACTUAL backend for every authoritative component, so
a caller can tell durability from simulation without trusting a summary word.
"""

from __future__ import annotations

import sys
from pathlib import Path

# The runtime ships src/vouch alongside this entrypoint.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from vouch.v2.consequences import compute_readiness, enumerate_recovery  # noqa: E402
from vouch.v2.contracts import FailureCategory, VouchFailure  # noqa: E402
from vouch.v2.lifecycle import EventLog  # noqa: E402
from vouch.v2.runtime import build  # noqa: E402

app = BedrockAgentCoreApp()
log = app.logger

# audit-2 F5: ONE composition, chosen in one place, and it does not mix a
# fixture corpus with durable records. `build()` returns either a fully durable
# production stack or an explicitly labeled local one — never a blend that a
# response could describe as "the production backend".
#
# Composition failure is deliberately NOT caught here. A runtime that cannot
# reach its authoritative state must fail to start rather than come up serving
# memory: the previous behavior logged a warning and continued, which meant a
# runtime with an unreachable table reported successful authorized mutations
# against state that evaporated.
_COMPOSITION = build()
_VOUCH = _COMPOSITION.workflow
_CORPUS = _COMPOSITION.corpus
_BACKEND = _COMPOSITION.backend
log.info("vouch v2 runtime %s", _BACKEND.describe())


def _ledger(decision_record_id: str) -> list[dict]:
    """Authority ledger entries, from whichever store is authoritative."""
    store = _VOUCH.capabilities
    if hasattr(store, "ledger_for"):
        if not decision_record_id:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                "the durable ledger is queried by decision_record_id",
            )
        return store.ledger_for(decision_record_id)
    entries = store.ledger
    if decision_record_id:
        entries = [
            e for e in entries if e.get("decision_record_id") == decision_record_id
        ]
    return entries


def _record_summary(record) -> dict:
    """Structured audit facts. No chain-of-thought, no rationale text."""
    if record is None:
        return {}
    return {
        "record_id": record.identity.record_id,
        "lot_id": record.identity.lot_id,
        "run_count": record.run_count,
        "security": {
            "inspection_performed": record.security.inspection_performed,
            "prompt_attack_detected": record.security.prompt_attack_detected,
            "blocked": record.security.blocked,
        },
        "snapshot_hash": record.snapshot.claim_set_hash,
        "investigator": {
            "model_id": record.investigator.model_id,
            "prompt_version": record.investigator.prompt_version,
            "brief_hash": record.investigator.brief_hash,
            "tool_calls": len(record.investigator.tool_events),
        },
        "verifier": {
            "model_id": record.verifier.model_id,
            "prompt_version": record.verifier.prompt_version,
            "brief_hash": record.verifier.brief_hash,
            "tool_calls": len(record.verifier.tool_events),
        },
        "reconciliation": record.reconciliation.outcome,
        "basis": {"spec_id": record.basis.spec_id, "revision": record.basis.revision},
        "disposition": record.disposition.disposition,
        "policy": {
            "version": record.policy.policy_version,
            "gate_decision": record.policy.gate_decision,
        },
        "capability": {
            "id": record.capability.capability_id,
            "consumed": record.capability.consumed,
        },
        "mutation": {
            "action": record.mutation.action,
            "before_version": record.mutation.before_version,
            "after_version": record.mutation.after_version,
            "inventory_delta": record.mutation.inventory_delta,
            "ledger_sequence": record.mutation.ledger_sequence,
        },
        "failure_category": record.failure_category,
        "caused_by": record.consequences.caused_by,
    }


def invoke(payload: dict, context=None) -> dict:
    """Typed invocation. Importable directly for runtime testing."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload must be a JSON object"}

    action = payload.get("action")
    log.info("vouch v2 action=%s", action)

    try:
        if action == "evaluate_lot":
            events = EventLog()
            document = payload.get("document")
            documents = [{"raw": document.encode()}] if document else []
            outcome = _VOUCH.evaluate_lot(
                payload["lot_id"], documents=documents, events=events
            )
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "decision_record_id": outcome.decision_record_id,
                "lot_id": outcome.lot_id,
                "disposition": outcome.disposition,
                "failure_category": outcome.failure_category,
                "quality_decision_required": outcome.quality_decision_required,
                "reason": outcome.reason,
                "mutation": outcome.mutation,
                "consequences": outcome.consequences,
                "decision_record": _record_summary(outcome.record),
                "events": outcome.events,
            }

        if action == "supply_evidence":
            outcome = _VOUCH.supply_human_evidence(
                decision_record_id=payload["decision_record_id"],
                lot_id=payload["lot_id"],
                raw=payload["document"].encode(),
                authority_source=payload["authority_source"],
            )
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "decision_record_id": outcome.decision_record_id,
                "disposition": outcome.disposition,
                "reason": outcome.reason,
                "decision_record": _record_summary(outcome.record),
                "events": outcome.events,
            }

        if action == "readiness":
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                **compute_readiness(_CORPUS, payload["order_id"]).as_dict(),
            }

        if action == "recovery":
            options, selected = enumerate_recovery(_CORPUS, payload["order_id"])
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "order_id": payload["order_id"],
                # Deterministic. No "actor"/"verifier" keys — there is no
                # recovery agent, and pretending otherwise reads as theatre.
                "decided_by": "deterministic_recovery_engine",
                "candidates": [o.as_dict() for o in options],
                "selected": selected.as_dict() if selected else None,
            }

        if action == "ledger":
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                # The durable store answers by DecisionRecord; the in-memory
                # one exposes a whole-process list. Neither is described as
                # the other.
                "entries": _ledger(payload.get("decision_record_id", "")),
            }

        return {"ok": False, "error": f"unknown action: {action}"}

    except VouchFailure as failure:
        # audit-2 F5: an unavailable authoritative dependency is a TYPED
        # fail-closed result. It never degrades to an in-memory success.
        log.error("vouch v2 typed failure: %s", failure)
        return {
            "ok": False,
            "action": action,
            "backend": _BACKEND.as_dict(),
            "failure_category": failure.category.value,
            "error": failure.detail,
            "mutation": {},
        }
    except KeyError as exc:
        return {"ok": False, "error": f"missing required field: {exc}"}
    except Exception as exc:  # noqa: BLE001
        log.exception("vouch v2 action failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.entrypoint
def entrypoint(payload, context=None):
    return invoke(payload, context)


if __name__ == "__main__":
    app.run()
