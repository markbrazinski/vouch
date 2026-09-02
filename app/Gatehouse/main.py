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

import base64
import binascii
import sys
from pathlib import Path

# The runtime ships src/vouch alongside this entrypoint.
_SRC = Path(__file__).resolve().parent / "src"
if _SRC.exists() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from bedrock_agentcore.runtime import BedrockAgentCoreApp  # noqa: E402

from vouch.v2.consequences import compute_readiness, enumerate_recovery  # noqa: E402
from vouch.v2.contracts import FailureCategory, VouchFailure  # noqa: E402
from vouch.v2.evidence import parse_storage_ref  # noqa: E402
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


# ==========================================================================
# read projections
#
# Every function below is READ-ONLY. None issues a capability, emits a
# lifecycle event, mutates a DecisionRecord, or touches corpus state. That is
# not a convention: an action that read the factory and changed it while doing
# so would make the authority ledger an incomplete account of what happened.
# ==========================================================================


def _documents_from(payload: dict) -> list[dict]:
    """The documents an invocation should evaluate.

    Three shapes, one pipeline. `document` is inline text, as before.
    `document_b64` carries bytes that are not text — a real PDF cannot survive
    a JSON string. `artifact_ref` names something already in evidence storage,
    which is how a PDF uploaded ahead of the decision is evaluated without
    being copied into the request.

    Every shape lands in the SAME `ingest_evidence` call: same security
    inspection, same binding validation, same parser, same canonicalization,
    same trust labels. There is deliberately no separate "demo PDF" route —
    a second ingestion path would be a second set of security properties.
    """
    content_type = payload.get("content_type") or "text/plain"
    document_identity = payload.get("document_type") or payload.get("document_identity")

    def shaped(raw: bytes) -> dict:
        entry: dict = {"raw": raw, "content_type": content_type}
        if document_identity:
            entry["document_identity"] = document_identity
        return entry

    if payload.get("artifact_ref"):
        return [shaped(_bytes_for_ref(payload["artifact_ref"]))]

    if payload.get("document_b64"):
        try:
            return [shaped(base64.b64decode(payload["document_b64"], validate=True))]
        except (ValueError, binascii.Error) as exc:
            raise VouchFailure(
                FailureCategory.PERSISTENCE_FAILURE,
                f"document_b64 is not valid base64: {type(exc).__name__}",
            ) from exc

    document = payload.get("document")
    return [shaped(document.encode())] if document else []


def _bytes_for_ref(storage_ref: str) -> bytes:
    """Read an artifact already in evidence storage, by its stored reference.

    Reading the original back and re-ingesting it keeps ONE ingestion path
    rather than a second one that skips inspection. The re-ingested copy gets
    its own artifact id and its own security verdict, which is the honest
    outcome: this is a fresh submission of those bytes for this decision.
    """
    _, _, key = parse_storage_ref(storage_ref)
    try:
        return _VOUCH.evidence_store.get_original(key)
    except VouchFailure:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            f"could not read {storage_ref}: {type(exc).__name__}",
        ) from exc


def _view_ref(storage_ref: str, object_version: str) -> str | None:
    """A short-lived, credential-free way for a browser to open the original.

    Returns None whenever the store cannot sign one — a local simulation, or a
    signing failure. That is the honest answer: the frontend renders "source
    unavailable" beside real metadata rather than a broken viewer.

    The URL is never logged. It carries its own authorization, so a log line
    holding one is a copy of the evidence that outlives the request.
    """
    store = _VOUCH.evidence_store
    if not storage_ref or not hasattr(store, "presigned_get"):
        return None
    try:
        _, _, key = parse_storage_ref(storage_ref)
        return store.presigned_get(key, object_version)
    except Exception:  # noqa: BLE001
        return None


def _stored_record(decision_record_id: str) -> dict:
    """The DecisionRecord document, straight from the durable store.

    Deliberately NOT `_record_summary`: that projection drops evidence,
    extraction, corpus versions, the archived runs and both reconciliation
    value maps, which is most of what an audit surface exists to show. A
    caller asking for a record should get the record.
    """
    if not decision_record_id:
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            "decision_record_id is required",
        )
    document = _VOUCH.record_store.load(decision_record_id)
    if document is None:
        raise VouchFailure(
            FailureCategory.PERSISTENCE_FAILURE,
            f"no decision record {decision_record_id}",
        )
    return document


def _artifacts_from_events(events: list[dict]) -> dict[str, dict]:
    """Source-artifact metadata, assembled from the events that recorded it.

    `EvidenceSegment` keeps hashes, refs and versions in index-aligned lists but
    carries no artifact id, so the events are the only place the id and its
    metadata appear together. Reading them here keeps that join in one function
    rather than in every caller.

    No `view_ref` is returned. Serving bytes to a browser needs a presigned URL
    that does not exist yet, and inventing the field would be worse than
    omitting it: a frontend would render a broken viewer instead of the honest
    "source unavailable" state the contract asks for.
    """
    artifacts: dict[str, dict] = {}
    for event in events:
        artifact_id = event.get("artifact_id")
        if not artifact_id:
            continue
        entry = artifacts.setdefault(
            artifact_id,
            {
                "artifact_id": artifact_id,
                "document_identity": "",
                "content_type": "",
                "trust_class": "",
                "security_state": "PENDING",
                "content_hash": "",
                "object_version": "",
                "storage_ref": "",
                "binding_status": "",
                "received_at": "",
                "page_count": None,
                "claim_count": None,
                "excluded_from_decision_use": False,
                "prompt_attack_detected": False,
                "view_ref": None,
            },
        )
        name = event.get("event")
        if name == "EVIDENCE_RECEIVED":
            entry["content_type"] = event.get("content_type", "")
            entry["trust_class"] = event.get("trust_label", "")
            entry["content_hash"] = event.get("content_hash", "")
            entry["object_version"] = event.get("object_version", "")
            entry["storage_ref"] = event.get("storage_ref", "")
            entry["received_at"] = event.get("at", "")
        elif name == "EVIDENCE_SECURITY_COMPLETED":
            quarantined = bool(event.get("quarantined"))
            entry["security_state"] = "QUARANTINED" if quarantined else "CLEARED"
            entry["prompt_attack_detected"] = bool(event.get("prompt_attack_detected"))
            entry["binding_status"] = event.get("binding_status", entry["binding_status"])
        elif name == "EVIDENCE_BINDING_COMPLETED":
            entry["binding_status"] = event.get("binding_status", "")
        elif name == "EVIDENCE_EXTRACTED":
            entry["claim_count"] = event.get("claim_count")
        elif name == "HUMAN_EVIDENCE_RECEIVED":
            entry["trust_class"] = event.get("trust_label", "")
            entry["document_identity"] = event.get("document_identity", "")
            entry["content_hash"] = event.get("content_hash", "")
            entry["object_version"] = event.get("object_version", "")
            entry["storage_ref"] = event.get("storage_ref", "")
            entry["received_at"] = event.get("at", "")
            entry["binding_status"] = event.get("binding_status", "")
            entry["security_state"] = "CLEARED"

    # A view reference is minted per read, not stored: it expires, so a saved
    # one would be a dead link in an audit record.
    for entry in artifacts.values():
        entry["view_ref"] = _view_ref(entry["storage_ref"], entry["object_version"])
    return artifacts


def _join_record_metadata(artifacts: dict[str, dict], record: dict) -> None:
    """Fill in what the events do not carry, from the record that does.

    `EVIDENCE_RECEIVED` carries the content type but not the document
    classification, and adding it to the event would change the lifecycle
    vocabulary — out of bounds here, and unnecessary: `EvidenceSegment` already
    stores `document_identities` and `content_types` index-aligned with
    `storage_refs`, so the storage ref is a reliable join key.
    """
    evidence = record.get("evidence") or {}
    refs = evidence.get("storage_refs") or []
    identities = evidence.get("document_identities") or []
    content_types = evidence.get("content_types") or []

    by_ref = {}
    for index, ref in enumerate(refs):
        by_ref[ref] = (
            identities[index] if index < len(identities) else "",
            content_types[index] if index < len(content_types) else "",
        )

    for entry in artifacts.values():
        identity, content_type = by_ref.get(entry["storage_ref"], ("", ""))
        entry["document_identity"] = entry["document_identity"] or identity
        entry["content_type"] = entry["content_type"] or content_type


def _apply_exclusions(artifacts: dict[str, dict], record: dict) -> None:
    """Mark every artifact the decision was not allowed to reason from.

    Security quarantine and the three binding failures are different reasons
    with the same consequence, and the frontend needs the consequence stated
    rather than inferred from which list an id happens to appear in.
    """
    security = record.get("security") or {}
    excluded = set()
    for key in (
        "quarantined_artifact_ids",
        "rejected_artifact_ids",
        "unbound_artifact_ids",
        "identity_conflicts",
    ):
        excluded.update(security.get(key) or [])
    for artifact_id in excluded:
        if artifact_id in artifacts:
            artifacts[artifact_id]["excluded_from_decision_use"] = True


def _decision_summaries(limit: int, cursor: dict | None) -> tuple[list[dict], dict | None]:
    """One page of decisions, newest first.

    The durable store answers through the decisions-by-recency index. The
    in-memory store has no index and no recency, so it answers from what it
    holds — labeled as itself by `backend`, never described as the other.
    """
    store = _VOUCH.record_store
    if hasattr(store, "list_decisions"):
        return store.list_decisions(limit, cursor)
    rows = []
    for record_id in store.list_ids():
        document = store.load(record_id) or {}
        rows.append(
            {
                "record_id": record_id,
                "lot_id": (document.get("identity") or {}).get("lot_id", ""),
                "disposition": (document.get("disposition") or {}).get("disposition", ""),
                "failure_category": document.get("failure_category", ""),
                "saved_at": document.get("saved_at", ""),
            }
        )
    rows.sort(key=lambda row: row["saved_at"], reverse=True)
    return rows[:limit], None


def _incoming_row(summary: dict) -> dict:
    """One Incoming row, from the indexed columns plus the lot it names.

    `row_state` is computed here rather than left to the frontend: deriving it
    from a disposition and a stage would be a heuristic, and two clients would
    eventually disagree about what the same record means.
    """
    lot = _CORPUS.lot(summary.get("lot_id", "")) if summary.get("lot_id") else None
    disposition = summary.get("disposition", "")
    failure = summary.get("failure_category", "")

    # Display names are joined here, from the authoritative corpus. The
    # alternative — shipping ids and letting the browser resolve them — would
    # mean every client reimplementing the same lookup, and a client that got
    # it wrong would render a name the plant does not use.
    material = _CORPUS.material(lot.material_id) if lot else None
    supplier = _CORPUS.get("supplier", lot.supplier_id) if lot else None

    if failure == "SECURITY_QUARANTINE":
        row_state = "SECURITY_HOLD"
    elif disposition == "RELEASE":
        row_state = "RELEASED"
    elif disposition == "QUARANTINE":
        row_state = "QUARANTINED"
    elif disposition == "INSUFFICIENT_EVIDENCE" or failure:
        row_state = "QUALITY_DECISION_REQUIRED"
    else:
        row_state = "EVIDENCE_RECEIVED"

    return {
        "decision_record_id": summary.get("record_id", ""),
        "lot_id": summary.get("lot_id", ""),
        "material_id": lot.material_id if lot else "",
        "material_name": getattr(material, "name", "") or "",
        "supplier_id": lot.supplier_id if lot else "",
        "supplier_name": getattr(supplier, "name", "") or "",
        "supplier_site": lot.supplier_site if lot else "",
        "received_at": lot.received_at if lot else "",
        "quantity": lot.quantity if lot else None,
        "units": lot.units if lot else "",
        "lot_status": lot.status if lot else "",
        "disposition": disposition,
        "failure_category": failure,
        "row_state": row_state,
        "attention_required": row_state in ("QUALITY_DECISION_REQUIRED", "SECURITY_HOLD"),
        "decided_at": summary.get("saved_at", ""),
    }


def _today_plan() -> dict:
    """Authoritative readiness for every order, grouped by resource.

    Readiness is recomputed from live inventory by the same deterministic
    function the decision path uses, so this cannot drift from what a decision
    would conclude.

    There is deliberately no before/after here. Which change to highlight is a
    presentation question the frontend answers from `caused_by` links; a
    backend that guessed at it would be inventing operational history.
    """
    lines: dict[str, list[dict]] = {}
    counts = {"READY": 0, "AT_RISK": 0, "BLOCKED": 0, "COMPLETE": 0}
    for order in _CORPUS.all("production_order"):
        result = compute_readiness(_CORPUS, order.order_id)
        readiness = result.readiness.value
        counts[readiness] = counts.get(readiness, 0) + 1
        lines.setdefault(order.resource, []).append(
            {
                "order_id": order.order_id,
                "product": order.product,
                "planned_slot": order.planned_slot,
                "status": order.status,
                "readiness": readiness,
                "reason": result.reason,
                "coverage": [line.as_dict() for line in result.coverage],
                "requirements": [
                    {"material_id": line.material_id, "quantity": line.quantity}
                    for line in order.requirements
                ],
                "customer_committed": order.customer_committed,
                "need_by": order.need_by,
                "state_version": order.state_version,
            }
        )
    for orders in lines.values():
        orders.sort(key=lambda row: row["planned_slot"])
    return {
        "readiness_counts": counts,
        "lines": [
            {"line_id": resource, "orders": orders}
            for resource, orders in sorted(lines.items())
        ],
    }


def invoke(payload: dict, context=None) -> dict:
    """Typed invocation. Importable directly for runtime testing."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload must be a JSON object"}

    action = payload.get("action")
    log.info("vouch v2 action=%s", action)

    try:
        if action == "evaluate_lot":
            documents = _documents_from(payload)
            # A caller may name the decision before it starts.
            #
            # Invocation is synchronous, so a browser that does not know the id
            # until the call returns cannot poll the decision it is waiting on —
            # by the time it could ask, there is nothing left to watch. Letting
            # the caller supply the id closes that without touching what the
            # decision does: `evaluate_lot` has always accepted one, and a
            # supplied id is CONTINUED rather than replaced, which is the same
            # path a resumed case already uses.
            #
            # No `events=` argument. Passing a bare EventLog here was silently
            # opting out of the sink that makes events visible during the run,
            # so every event still landed in one batch at the end.
            outcome = _VOUCH.evaluate_lot(
                payload["lot_id"],
                documents=documents,
                decision_record_id=payload.get("decision_record_id"),
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
            supplied = _documents_from(payload)
            if not supplied:
                raise VouchFailure(
                    FailureCategory.PERSISTENCE_FAILURE,
                    "supply_evidence requires a document or an artifact_ref",
                )
            document = supplied[0]
            outcome = _VOUCH.supply_human_evidence(
                decision_record_id=payload["decision_record_id"],
                lot_id=payload["lot_id"],
                raw=document["raw"],
                authority_source=payload["authority_source"],
                document_identity=document.get("document_identity", "QA_RETEST"),
            )
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "decision_record_id": outcome.decision_record_id,
                "disposition": outcome.disposition,
                "failure_category": outcome.failure_category,
                "quality_decision_required": outcome.quality_decision_required,
                "reason": outcome.reason,
                # The resumed run mutates too — it is the release the whole
                # continuation exists to reach. Omitting the mutation and its
                # consequences here left a caller unable to see the outcome of
                # the second half of the story without reading the record.
                "mutation": outcome.mutation,
                "consequences": outcome.consequences,
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

        # ------------------------------------------------------------------
        # read actions. None of these mutates anything.
        # ------------------------------------------------------------------
        if action == "list_decisions":
            limit = int(payload.get("limit") or 50)
            rows, cursor = _decision_summaries(limit, payload.get("cursor"))
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "rows": [_incoming_row(row) for row in rows],
                "cursor": cursor,
                # Only counts with an authoritative meaning. There is
                # deliberately no `in_progress`: invocation is synchronous, so
                # no decision is ever persisted mid-flight and any number here
                # would be fiction. `completed_by_vouch` is absent for the same
                # reason — nothing in the model attributes a decision to Vouch
                # rather than a human.
                "counts": {"returned": len(rows)},
            }

        if action == "get_decision":
            document = _stored_record(payload.get("decision_record_id", ""))
            events = _VOUCH.record_store.events_for(document.get("record_id", ""))
            artifacts = _artifacts_from_events(
                [{**row["payload"], "event": row["event"], "at": row["at"]} for row in events]
            )
            _join_record_metadata(artifacts, document)
            _apply_exclusions(artifacts, document)
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                # The whole stored document, archived runs included. A caller
                # reconstructing an audit needs the record, not a digest of it.
                "record": document,
                "sources": list(artifacts.values()),
                "last_event_sequence": (document.get("storage") or {}).get(
                    "last_event_sequence", 0
                ),
            }

        if action == "get_events":
            record_id = payload.get("decision_record_id", "")
            if not record_id:
                raise VouchFailure(
                    FailureCategory.PERSISTENCE_FAILURE,
                    "decision_record_id is required",
                )
            after = int(payload.get("after_sequence") or 0)
            limit = payload.get("limit")
            rows = _VOUCH.record_store.events_for(
                record_id, after, int(limit) if limit else None
            )
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "decision_record_id": record_id,
                # The PERSISTED shape: event_id and sequence included, payload
                # nested. The in-process log flattens payload and has neither,
                # and a cursor cannot be built on a shape with no sequence.
                "events": rows,
                "after_sequence": after,
                "last_event_sequence": rows[-1]["sequence"] if rows else after,
            }

        if action == "get_source":
            record_id = payload.get("decision_record_id", "")
            document = _stored_record(record_id)
            events = _VOUCH.record_store.events_for(document.get("record_id", ""))
            artifacts = _artifacts_from_events(
                [{**row["payload"], "event": row["event"], "at": row["at"]} for row in events]
            )
            _join_record_metadata(artifacts, document)
            _apply_exclusions(artifacts, document)

            artifact_id = payload.get("artifact_id")
            if artifact_id:
                found = artifacts.get(artifact_id)
                if found is None:
                    raise VouchFailure(
                        FailureCategory.PERSISTENCE_FAILURE,
                        f"no artifact {artifact_id} on record {record_id}",
                    )
                sources = [found]
            else:
                sources = list(artifacts.values())

            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                "decision_record_id": record_id,
                "sources": sources,
                # Stated per read, never assumed. False means the store cannot
                # sign a link (a local simulation, or a signing failure), and
                # the caller must render "source unavailable" beside the
                # metadata rather than a broken viewer.
                "retrieval_available": any(s.get("view_ref") for s in sources),
            }

        if action == "get_today":
            return {
                "ok": True,
                "action": action,
                "backend": _BACKEND.as_dict(),
                **_today_plan(),
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
