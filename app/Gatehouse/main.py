"""Gatehouse AgentCore Runtime entrypoint.

Hosts the real Strands authority workflow — the same code path the S1-S9 tests
exercise. This is deliberately NOT a chat interface: the payload is a typed
action, and the response is a typed authority outcome.

Actions:
  {"action": "evaluate_lot",        "case_id": ..., "lot_id": ...}
  {"action": "evaluate_readiness",  "case_id": ..., "order_id": ...}
  {"action": "evaluate_recovery",   "case_id": ..., "order_id": ...}
  {"action": "authority_ledger"}
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# The runtime ships src/gatehouse alongside this entrypoint.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from gatehouse.fixtures import build_store  # noqa: E402
from gatehouse.workflow import Gatehouse  # noqa: E402

app = BedrockAgentCoreApp()
log = app.logger

def _make_store(namespace: str = "runtime"):
    """A2: DynamoDB is authoritative. Falls back to in-memory only if the table
    is unreachable, and says so loudly rather than pretending to persist."""
    if os.environ.get("GATEHOUSE_STATE_BACKEND", "dynamodb").lower() == "memory":
        return build_store(), "memory"
    try:
        from gatehouse.dynamo_store import DynamoStateStore

        store = DynamoStateStore(namespace=namespace)
        if store.get("lot", "LOT-1001") is None:  # seed once per namespace
            store.seed_from(build_store())
        return store, "dynamodb"
    except Exception as exc:  # noqa: BLE001
        log.error("DynamoDB state unavailable, falling back to memory: %s", exc)
        return build_store(), f"memory (dynamodb failed: {type(exc).__name__})"


_STORE, _BACKEND = _make_store()
_GATEHOUSE = Gatehouse(_STORE)
log.info("gatehouse state backend=%s", _BACKEND)


def _serialize_record(record) -> dict:
    return {
        "case_id": record.case_id,
        "evidence_refs": list(record.evidence_refs),
        "actor_disposition": record.actor_disposition,
        "actor_rationale": record.actor_rationale,
        "verifier_outcome": record.verifier_outcome,
        "verifier_rationale": record.verifier_rationale,
        "authority_source": record.authority_source,
        "authority_result": record.authority_result,
        "requested_tool": record.requested_tool,
        "mutation_result": record.mutation_result,
        "state_before": record.state_before,
        "state_after": record.state_after,
        "timestamp": record.timestamp,
        "idempotency_key": record.idempotency_key,
    }


def invoke(payload: dict, context=None) -> dict:
    """Typed authority invocation. Importable directly for S0 testing."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload must be a JSON object"}

    action = payload.get("action")
    log.info("gatehouse action=%s", action)

    try:
        if action == "evaluate_lot":
            result = _GATEHOUSE.evaluate_lot(payload["case_id"], payload["lot_id"])
            return {
                "ok": True,
                "action": action,
                "case_id": payload["case_id"],
                "lot_id": payload["lot_id"],
                "findings": result["findings"],
                "actor": result["actor"],
                "verifier": result["verifier"],
                "authority": {
                    "allowed": result["gate"].allowed,
                    "tool": result["gate"].tool,
                    "reason": result["gate"].reason,
                    "source": result["gate"].authority_source,
                },
                "mutation_result": result["mutation_result"],
                "state_before": result["state_before"],
                "state_after": result["state_after"],
                "authority_record": _serialize_record(result["authority_record"]),
            }

        if action == "evaluate_readiness":
            result = _GATEHOUSE.evaluate_production_readiness(
                payload["case_id"], payload["order_id"]
            )
            return {
                "ok": True,
                "action": action,
                "order_id": payload["order_id"],
                "shortage": result["shortage"],
                "readiness": result["readiness"],
                "mutation_result": result["mutation_result"],
                "state_before": result["state_before"],
                "state_after": result["state_after"],
                "authority_record": _serialize_record(result["authority_record"]),
            }

        if action == "evaluate_recovery":
            result = _GATEHOUSE.evaluate_recovery(payload["case_id"], payload["order_id"])
            return {
                "ok": True,
                "action": action,
                "order_id": payload["order_id"],
                "actor": result["actor"],
                "verifier": result["verifier"],
                "authority": {
                    "allowed": result["gate"].allowed,
                    "tool": result["gate"].tool,
                    "reason": result["gate"].reason,
                    "source": result["gate"].authority_source,
                },
                "mutation_result": result["mutation_result"],
                "state_before": result["state_before"],
                "state_after": result["state_after"],
                "authority_record": _serialize_record(result["authority_record"]),
            }

        if action == "add_qa_evidence":
            # S7: QA supplies the missing correct-method evidence, then the same
            # case is re-evaluated. Evidence entry is a human/QA action, not an
            # agent capability — no agent can call this.
            from gatehouse.fixtures import add_qa_evidence

            evidence_id = add_qa_evidence(_STORE, payload["lot_id"])
            return {
                "ok": True,
                "action": action,
                "lot_id": payload["lot_id"],
                "evidence_id": evidence_id,
            }

        if action == "authority_ledger":
            return {
                "ok": True,
                "action": action,
                "records": [_serialize_record(r) for r in _STORE.authority_log],
            }

        return {"ok": False, "error": f"unknown action: {action}"}

    except KeyError as exc:
        return {"ok": False, "error": f"missing required field: {exc}"}
    except Exception as exc:  # noqa: BLE001
        log.exception("gatehouse action failed")
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


@app.entrypoint
def entrypoint(payload, context=None):
    return invoke(payload, context)


if __name__ == "__main__":
    app.run()
