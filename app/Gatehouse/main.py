"""Vouch V2 AgentCore Runtime entrypoint.

Hosts the same V2 pipeline the tests exercise. Deliberately NOT a chat
interface: the payload is a typed action and the response is a typed outcome.

Actions:
  {"action": "evaluate_lot",     "lot_id": ..., "document": "<coa text>"}
  {"action": "supply_evidence",  "decision_record_id": ..., "lot_id": ...,
                                 "document": ..., "authority_source": ...}
  {"action": "submit_quality_authority",
                                 "decision_record_id": ..., "decision": ...,
                                 "accountable_actor": ..., "authority_source": ...}
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
from dataclasses import asdict
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
        # The open applicability question, if a disagreement raised one. The
        # frontend renders the question from these structured facts rather
        # than composing its own wording.
        "quality_authority": {
            "question": asdict(record.quality_authority.question),
            "decisions": [asdict(d) for d in record.quality_authority.decisions],
        },
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


#: Failures that describe a past ATTEMPT rather than the evidence itself.
#:
#: These are refusals the authority model produced against state that a reseed
#: has since rolled back — re-releasing an already-released lot, acting on a
#: stale version. They are true of the run that recorded them and say nothing
#: about whether the lot now needs a human, so Incoming ignores them once the
#: lot is undecided again. An evidence-level failure (a security quarantine, an
#: unreadable artifact) is NOT in here: those remain true across a reset.
_STALE_ON_RESET = frozenset({"POLICY_REFUSAL", "STATE_VERSION_CONFLICT"})


#: Lot statuses that mean "this arrival still needs a disposition".
#:
#: A lot the corpus holds at RECEIVED has physically arrived and nobody has
#: decided it. PENDING_QA has been decided far enough to know a human is owed
#: an answer. Both belong on a surface called "material awaiting disposition".
_AWAITING = frozenset({"RECEIVED", "PENDING_QA"})


def _is_test_artifact(lot_id: str) -> bool:
    """Debris written by the live AWS integration tests.

    `test_aws_adapters.py` writes `PYTEST-<hex>` lots straight into the shared
    dev table and does not remove them, so the state store holds hundreds of
    them. The decision ledger never surfaced these, which is why they were
    invisible until Incoming started reading arrivals from the corpus — 184 of
    them would have buried the six real lots.

    Filtered by NAME rather than by shape: a lot with missing fields is a data
    problem worth seeing, and silently hiding every malformed row would hide
    real corruption along with the test litter.
    """
    return lot_id.startswith("PYTEST-")


def _undecided_arrivals(seen: set[str]) -> list[dict]:
    """Arrivals the corpus knows about that have no DecisionRecord yet.

    Incoming is built from the decision ledger, which answers "lots Vouch has
    already looked at". That is not the same set as "lots awaiting a
    disposition": a lot that has arrived and never been evaluated has no
    record, so it could not appear at all — and a freshly seeded plant showed
    an empty Incoming while its receiving dock was full.

    These rows carry no `record_id` because no decision exists yet. Opening one
    starts a fresh evaluation, which is exactly what opening any Incoming row
    already does, so the interaction is unchanged. Nothing is invented: every
    field comes from the authoritative lot, and a lot that HAS a record keeps
    that record's row rather than being duplicated by this.
    """
    rows: list[dict] = []
    for lot in _CORPUS.all("lot"):
        if lot.lot_id in seen or lot.status not in _AWAITING:
            continue
        if _is_test_artifact(lot.lot_id):
            continue
        # A lot with no material cannot be joined to one, and asking the store
        # for an empty key is a hard error rather than a miss. Skipping it here
        # keeps one malformed row from failing the whole surface.
        if not lot.material_id:
            continue
        rows.append(
            {
                "record_id": "",
                "lot_id": lot.lot_id,
                "disposition": "",
                "failure_category": "",
                # No decision has been saved, so there is no decision time. The
                # receipt date is when this arrival became the plant's problem,
                # which is what an operator is ordering by.
                "saved_at": lot.received_at or "",
            }
        )
    return rows


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
    # Guarded on the id being non-empty, not just on the lot existing. A lot
    # with a blank material_id asks the store for an empty key, which DynamoDB
    # rejects outright — one malformed row would take down the whole surface
    # rather than rendering without a display name.
    material = _CORPUS.material(lot.material_id) if lot and lot.material_id else None
    supplier = (
        _CORPUS.get("supplier", lot.supplier_id) if lot and lot.supplier_id else None
    )

    # The LOT's current status wins over the record's disposition.
    #
    # A DecisionRecord is a historical account of one execution; the lot row is
    # what is true now. Deriving the state only from the record meant a reseeded
    # lot still displayed RELEASED from a previous run's record, and Incoming —
    # the surface whose entire job is "what needs disposition today" — showed a
    # decided lot that is once again awaiting one.
    #
    # A security hold is decided by the record, not the lot: the artifact was
    # refused before any lot state could change, so the lot legitimately reads
    # RECEIVED and only the record knows why.
    lot_status = lot.status if lot else ""
    if failure == "SECURITY_QUARANTINE":
        row_state = "SECURITY_HOLD"
    elif lot_status == "RELEASED":
        row_state = "RELEASED"
    elif lot_status == "QUARANTINED":
        row_state = "QUARANTINED"
    elif lot_status == "PENDING_QA":
        row_state = "QUALITY_DECISION_REQUIRED"
    elif lot_status == "RECEIVED":
        # Undecided now, whatever a past record concluded.
        #
        # A failure still means a human is needed — but only one that is ABOUT
        # THE EVIDENCE. `POLICY_REFUSAL` is about a past ATTEMPT: the authority
        # gate refusing to release a lot that was already released. Once the lot
        # is back at RECEIVED that refusal describes a world that no longer
        # exists, and letting it colour the row left a freshly reseeded lot
        # asking for a quality decision nobody owes it.
        # A record that reached a DISPOSITION has no open question, whatever
        # failure an earlier run of it recorded. `failure_category` is the
        # LAST failure this record saw; on a resumed case, run 1's
        # MATERIAL_DISAGREEMENT stays on the document after run 2 released the
        # lot. Reading it alone made a reseeded LOT-1006 ask for a quality
        # decision that had already been answered and rolled back.
        answered = bool(disposition)
        row_state = (
            "QUALITY_DECISION_REQUIRED"
            if failure and failure not in _STALE_ON_RESET and not answered
            else "EVIDENCE_RECEIVED"
        )
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
                "coverage": [
                    {
                        **line.as_dict(),
                        # WHICH lot was queued, and what became of it. A total
                        # alone cannot say "400 kg unavailable · LOT-1002
                        # quarantined", which is the sentence that explains the
                        # day; without it the UI can only show a number
                        # shrinking for no visible reason.
                        "planned_sources": [
                            {
                                "lot_id": row.lot_id,
                                "quantity": row.quantity,
                                "lot_status": (
                                    getattr(_CORPUS.lot(row.lot_id), "status", "")
                                ),
                            }
                            for row in _CORPUS.planned_coverage_rows(
                                order.order_id, line.material_id
                            )
                        ],
                    }
                    for line in result.coverage
                ],
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
        "causal_history": _today_causality(),
    }


def _coverage_now(order_id: str, material_id: str) -> dict:
    """Current composition of one requirement, for causal copy.

    A causal link records which way readiness moved; it does not record what
    the requirement is MADE of, and "C-417 is now at risk" is a poorer sentence
    than "500 kg released and 400 kg queued from LOT-1002". These are the facts
    that let the copy say the second one.
    """
    if not order_id or not material_id:
        return {}
    result = compute_readiness(_CORPUS, order_id)
    line = next((c for c in result.coverage if c.material_id == material_id), None)
    if line is None:
        return {}
    return {
        "required": line.required,
        "available": line.available,
        "planned": line.planned,
        "uncovered": line.uncovered,
        "planned_sources": [
            {"lot_id": row.lot_id, "quantity": row.quantity}
            for row in _CORPUS.planned_coverage_rows(order_id, material_id)
            if getattr(_CORPUS.lot(row.lot_id), "status", "")
            in _CORPUS.COVERABLE_LOT_STATES
        ],
    }


def _today_causality() -> list[dict]:
    """Why the plan looks like this — read back from the stored decisions.

    Today used to show a causal banner only while the stored status and the
    computed readiness DISAGREED, so the explanation vanished at the moment the
    plan caught up. The final frame was then the least explanatory one: an order
    blocked, another order moved, and nothing on screen said what did either.

    These links are not derived here. Each one was written by the consequence
    engine as `caused_by` when the mutation happened, and is replayed verbatim
    with the `decision_record_id` that produced it, so "Why did this change?"
    reaches the actual record rather than a reconstruction.
    """
    store = _VOUCH.record_store
    if not hasattr(store, "list_ids"):
        return []

    # Today explains TODAY, not the whole ledger.
    #
    # The durable store holds every execution ever run against these lots — 86
    # causal links after qualification, 38 of them the same LOT-1002 quarantine
    # replayed. Rendering all of them buries the day's actual decisions in
    # months of debugging history.
    #
    # So a link counts only if it still describes current authoritative state:
    # the lot it names is in the status that decision produced. A superseded run
    # (the lot was later reseeded, or re-decided) drops out, and Records keeps
    # the full ungrouped ledger, which is where history belongs.
    def _current(lot_id: str, disposition: str) -> bool:
        lot = _CORPUS.lot(lot_id) if lot_id else None
        if lot is None:
            return False
        if disposition == "RELEASE":
            return lot.status == "RELEASED"
        if disposition == "QUARANTINE":
            return lot.status == "QUARANTINED"
        # Anything else changed no plan state, so a record for it makes no
        # causal claim about today. A lot sitting at RECEIVED after a reseed is
        # precisely the case: an old run's links would otherwise survive it.
        return False

    # One record per lot: the CURRENT one.
    #
    # A lot accumulates a record per run, and several can pass the state check
    # above — LOT-1001 released once under the old readiness semantics and again
    # under the new one, so its stale record kept narrating a resequence that the
    # quarantine now performs. Whichever record was saved last is the one that
    # explains the lot's present state; the rest are history, and Records is
    # where history belongs.
    current: dict[str, tuple[str, str]] = {}
    for record_id in store.list_ids():
        document = store.load(record_id) or {}
        lot_id = (document.get("identity") or {}).get("lot_id", "")
        if not lot_id:
            continue
        stamp = document.get("saved_at") or document.get("created_at") or ""
        held = current.get(lot_id)
        # No timestamp is not a reason to lose: an unstamped record still beats
        # nothing, and later ids win ties so the newest run survives either way.
        if held is None or (stamp, record_id) >= held:
            current[lot_id] = (stamp, record_id)
    keep = {record_id for _stamp, record_id in current.values()}

    history: list[dict] = []
    seen: set[tuple] = set()
    for record_id in store.list_ids():
        if record_id not in keep:
            continue
        document = store.load(record_id) or {}
        consequences = document.get("consequences") or {}
        lot_id = (document.get("identity") or {}).get("lot_id", "")
        disposition = (document.get("disposition") or {}).get("disposition", "")

        if not _current(lot_id, disposition):
            continue

        for link in consequences.get("caused_by") or []:
            key = ("readiness", lot_id, link.get("order_id", ""))
            if key in seen:
                continue
            seen.add(key)
            history.append(
                {
                    "kind": "readiness",
                    "lot_id": link.get("lot_id", lot_id),
                    "disposition": disposition,
                    "order_id": link.get("order_id", ""),
                    "from": link.get("from", ""),
                    "to": link.get("to", ""),
                    "material_id": link.get("material_id", ""),
                    "inventory_delta": link.get("inventory_delta", 0),
                    "decision_record_id": link.get("decision_record_id", record_id),
                    "ledger_sequence": link.get("ledger_sequence", 0),
                    "saved_at": document.get("saved_at", ""),
                    # The order's coverage AS IT STANDS NOW, so the sentence can
                    # say what the order is made of rather than only which way
                    # its readiness moved. Read live rather than from the record:
                    # the record captured the moment of the decision, and this
                    # link is describing the plan as it is today.
                    **_coverage_now(link.get("order_id", ""), link.get("material_id", "")),
                }
            )

        # A QUARANTINE changes no readiness — a quarantined lot was never usable
        # inventory — so the consequence engine writes no `caused_by` for it and
        # it would be absent from this history entirely. That silence is wrong
        # on the surface whose job is explaining the day: the operator watched a
        # lot get quarantined and Today said nothing about it. Recorded here as
        # a QUALITY fact, carrying the governing basis that decided it, with no
        # claim that any material was removed.
        if disposition == "QUARANTINE" and ("quarantine", lot_id) not in seen:
            seen.add(("quarantine", lot_id))
            basis = document.get("basis") or {}
            blocked = [
                order.order_id
                for order in _CORPUS.all("production_order")
                if order.status == "BLOCKED"
                and any(
                    line.material_id == (document.get("identity") or {}).get("material_id", "")
                    for line in order.requirements
                )
            ]
            history.append(
                {
                    "kind": "quarantine",
                    "lot_id": lot_id,
                    "disposition": disposition,
                    "order_id": blocked[0] if blocked else "",
                    "spec_id": basis.get("spec_id", ""),
                    "revision": basis.get("revision", ""),
                    "decision_record_id": record_id,
                    # After every readiness link this run produced, and there
                    # are none, so it sorts on the mutation that did happen.
                    "ledger_sequence": ((document.get("mutation") or {}).get("ledger_sequence") or 0),
                    "saved_at": document.get("saved_at", ""),
                }
            )

        recovery = consequences.get("recovery") or {}
        moved = recovery.get("caused_by") or {}
        moved_key = ("resequence", lot_id, moved.get("order_id", ""))
        if moved and recovery.get("executed") and moved_key not in seen:
            seen.add(moved_key)
            history.append(
                {
                    "kind": "resequence",
                    "lot_id": lot_id,
                    "disposition": disposition,
                    "order_id": moved.get("order_id", ""),
                    "blocked_order_id": moved.get("blocked_order_id", ""),
                    "from_slot": moved.get("from_slot", ""),
                    "to_slot": moved.get("to_slot", ""),
                    "decision_record_id": moved.get("decision_record_id", record_id),
                    "ledger_sequence": moved.get("ledger_sequence", 0),
                    "saved_at": document.get("saved_at", ""),
                    "candidates": recovery.get("candidates") or [],
                }
            )

    # Ledger order is the order things actually happened in.
    history.sort(key=lambda row: (row.get("saved_at") or "", ledger_sequence_of(row)))
    return history


def ledger_sequence_of(row: dict) -> float:
    """Sort key for a causal entry, tolerant of how the store returned it.

    The durable store round-trips numbers as `Decimal` or `str` while the
    in-memory store keeps `int`, and sorting that mixed list raises
    `TypeError: '<' not supported between instances of 'int' and 'str'`. Since
    the sort happens while BUILDING the payload, that took the whole Today read
    down with a 400 — on the surface the demo opens on — while every local test
    passed, because the in-memory store only ever produces ints.

    An unparseable sequence sorts first rather than failing the read: a
    mis-ordered entry is a presentation problem, and Today refusing to load is
    a much worse one.
    """
    try:
        return float(row.get("ledger_sequence") or 0)
    except (TypeError, ValueError):
        return 0.0


def invoke(payload: dict, context=None) -> dict:
    """Typed invocation. Importable directly for runtime testing."""
    if not isinstance(payload, dict):
        return {"ok": False, "error": "payload must be a JSON object"}

    action = payload.get("action")
    log.info("vouch v2 action=%s", action)

    # Start every invocation from the authoritative table, not from whatever
    # the last one left in memory.
    #
    # `_CORPUS` is a module-level singleton and `DynamoCorpus` caches each
    # partition it has read, so a warm container answered from state that could
    # be arbitrarily old. Re-seeding the demo wrote RECEIVED to DynamoDB and the
    # API kept reporting PENDING_QA — the reset genuinely worked and was
    # invisible, which is the worst version of that bug. Two invocations of the
    # same runtime could also disagree about a lot's status depending on which
    # container answered.
    #
    # The cache is still worth having WITHIN one decision, where it stops `all()`
    # re-scanning a partition per tool call. It is not worth having across
    # decisions: authoritative state is the table's to define, and the read is
    # cheap next to a model invocation.
    if hasattr(_CORPUS, "refresh"):
        _CORPUS.refresh()

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

        if action == "submit_quality_authority":
            outcome = _VOUCH.submit_quality_authority(
                decision_record_id=payload["decision_record_id"],
                decision=payload["decision"],
                accountable_actor=payload["accountable_actor"],
                authority_source=payload["authority_source"],
                claim_set_hash=payload.get("claim_set_hash", ""),
                question_id=payload.get("question_id", ""),
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
            # Arrivals with no decision yet are appended, never substituted: a
            # lot that HAS a record keeps it, so nothing here can mask the
            # authoritative account of a decision that actually ran.
            rows = rows + _undecided_arrivals({r.get("lot_id", "") for r in rows})
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
            if not record_id:
                raise VouchFailure(
                    FailureCategory.PERSISTENCE_FAILURE,
                    "decision_record_id is required",
                )
            # Answer from the live event stream while the run is still going.
            #
            # Artifact metadata comes entirely from events — `_artifacts_from_
            # events` is the only place the id and its facts appear together —
            # but this required the STORED record first, and a record is not
            # persisted until the decision ends. So the source panel 400d for
            # most of a 30-60s run and read "Receiving source evidence…" the
            # whole time, on the one panel whose job is to be true while the
            # stages move past it. The certificate is known at EVIDENCE_RECEIVED;
            # there is no reason to withhold it until the verdict.
            #
            # The record still wins when it exists: it carries the exclusions
            # and joined metadata that only a completed decision knows.
            document = _VOUCH.record_store.load(record_id) or {}
            events = _VOUCH.record_store.events_for(document.get("record_id", "") or record_id)
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
