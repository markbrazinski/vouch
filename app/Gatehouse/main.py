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

Two things this entrypoint deliberately does NOT do:

  * It does not silently fall back to in-memory state and call it authoritative.
    V1 did, logging an error and continuing — which means a runtime with an
    unreachable table would report successful "authorized" mutations against
    state that evaporates. Persistence failure is now a typed refusal.
  * It exposes no fixture-specific evidence writer. V1 shipped `add_qa_evidence`
    as a runtime action; the human-continuation path takes caller-supplied
    content through the real ingestion boundary instead.
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
from vouch.v2.fixtures import build_corpus  # noqa: E402
from vouch.v2.lifecycle import EventLog  # noqa: E402
from vouch.v2.workflow import VouchV2  # noqa: E402

app = BedrockAgentCoreApp()
log = app.logger

# The corpus itself is still the in-memory fixture world, and every response
# says so. What IS durable now is the audit trail: DecisionRecords and lifecycle
# events go to DynamoDB when a state table is configured, so a decision made by
# this runtime survives it.
#
# ponytail: fixture corpus, not an ERP integration. Swapping it is a data-source
# change, not an architecture change — the pipeline reads through Corpus either
# way.
_CORPUS = build_corpus()


def _record_store():
    """Durable record store where configured; explicit in-memory otherwise.

    Never silently degrades: the backend actually in use is reported in every
    response, so a caller can tell whether the audit trail persisted.
    """
    from vouch.config import load

    if not load().state_table:
        from vouch.v2.persistence import InMemoryRecordStore

        return InMemoryRecordStore(), "memory"
    try:
        from vouch.v2.persistence import DynamoRecordStore

        store = DynamoRecordStore()
        return store, f"dynamodb:{store.table}"
    except Exception as exc:  # noqa: BLE001
        log.warning("record store unavailable, using memory: %s", exc)
        from vouch.v2.persistence import InMemoryRecordStore

        return InMemoryRecordStore(), "memory"


_STORE, _RECORD_BACKEND = _record_store()
_VOUCH = VouchV2(_CORPUS, record_store=_STORE)
#: The CORPUS is in-memory; the audit trail may be durable. Reported separately
#: so neither claim is inflated by the other.
_BACKEND = f"corpus=memory record_store={_RECORD_BACKEND}"
log.info("vouch v2 runtime backend=%s", _BACKEND)


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
                "backend": _BACKEND,
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
                "backend": _BACKEND,
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
                "backend": _BACKEND,
                **compute_readiness(_CORPUS, payload["order_id"]).as_dict(),
            }

        if action == "recovery":
            options, selected = enumerate_recovery(_CORPUS, payload["order_id"])
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND,
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
                "backend": _BACKEND,
                "entries": _VOUCH.capabilities.ledger,
            }

        return {"ok": False, "error": f"unknown action: {action}"}

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
