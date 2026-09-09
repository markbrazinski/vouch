"""Vouch BFF — the seam between a browser and the AgentCore runtime.

Why this exists at all: `InvokeAgentRuntime` is SigV4-signed and the runtime has
no CORS surface, so a browser cannot call it. The only ways to bridge that are
to ship AWS credentials to the client — which would hand every viewer the
ability to invoke the runtime directly — or to sign server-side. This signs
server-side.

It is transport and authorization ONLY. It holds no applicability, disposition,
policy, recovery, or view-model logic, and it invents no lifecycle events. If a
change here would decide something about manufacturing truth, it belongs in the
runtime or in the frontend adapter, not in the proxy.

Two rules do the security work:

  * an ACTION ALLOWLIST, checked before AWS is touched, so this cannot become a
    generic passthrough to whatever a caller names; and
  * structural validation of every identifier, so a crafted id cannot be
    smuggled into a runtime payload.

The presigned URL in a `get_source` response passes through to the caller and is
never logged: it carries its own authorization, so a log line holding one is an
unauthenticated copy of evidence that outlives the request.

WRITES ARE STARTED, NOT AWAITED. API Gateway's HTTP API has a hard 30s
integration timeout that cannot be raised, and a real two-agent evaluation
measured 35-110s. Waiting therefore returned 503 on decisions the runtime went
on to complete correctly — the browser was told the decision failed while it
was still being made. So `evaluate` and `evidence` hand the work to a background
invocation of THIS SAME function and return 202 with the decision id.

That id is the whole mechanism: the runtime accepts a caller-supplied
`decision_record_id` and continues that record rather than replacing it, so the
UI can poll `/events` and `/decisions/{id}` for a decision it named before the
work began. Nothing here waits, and nothing here decides.

Self-invocation is deliberate over a queue or a step function: the work is
already one `InvokeAgentRuntime` call, so a second Lambda, an SQS queue or a
state machine would add an orchestration layer that carries no logic and one
more place for a decision to get lost. The cost is one narrowly-scoped IAM
statement — `lambda:InvokeFunction` on this function alone.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

RUNTIME_ARN = os.environ.get("VOUCH_RUNTIME_ARN", "")
ALLOWED_ORIGIN = os.environ.get("VOUCH_ALLOWED_ORIGIN", "")

#: Exactly the browser-facing actions. Anything else is refused here, before an
#: AWS call is made. A generic passthrough would make the runtime's own action
#: surface the security boundary, which is not what it was designed to be.
READ_ACTIONS = frozenset(
    {"list_decisions", "get_decision", "get_events", "get_source", "get_today"}
)
WRITE_ACTIONS = frozenset(
    {"evaluate_lot", "supply_evidence", "submit_quality_authority"}
)
ALLOWED_ACTIONS = READ_ACTIONS | WRITE_ACTIONS

#: Identifier shapes. Ids are generated as `DR-<12 hex>` / `ART-<12 hex>`, and
#: anything else is refused rather than forwarded — a payload field is a poor
#: place to discover that an id was hostile.
RECORD_ID = re.compile(r"^DR-[A-Za-z0-9]{1,40}$")
ARTIFACT_ID = re.compile(r"^ART-[A-Za-z0-9]{1,40}$")
LOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ORDER_ID = LOT_ID

MAX_BODY_BYTES = 6 * 1024 * 1024  # API Gateway's own payload ceiling.

_client = None


def runtime_client():
    global _client
    if _client is None:
        _client = boto3.client("bedrock-agentcore")
    return _client


class BadRequest(Exception):
    """A request this proxy refuses without asking the runtime."""


def _validated(action: str, body: dict) -> dict:
    """The payload to forward, containing only fields this action accepts.

    Rebuilt field by field rather than forwarded wholesale: passing the caller's
    object through would let an unmodelled key reach the runtime, and the
    allowlist would then be the only thing standing between a browser and an
    action's private parameters.
    """
    payload: dict = {"action": action}

    def record_id(required: bool = True) -> None:
        value = body.get("decision_record_id", "")
        if not value and not required:
            return
        if not isinstance(value, str) or not RECORD_ID.match(value):
            raise BadRequest("decision_record_id is malformed")
        payload["decision_record_id"] = value

    def identifier(field: str, pattern: re.Pattern, required: bool) -> None:
        value = body.get(field, "")
        if not value:
            if required:
                raise BadRequest(f"{field} is required")
            return
        if not isinstance(value, str) or not pattern.match(value):
            raise BadRequest(f"{field} is malformed")
        payload[field] = value

    def positive_int(field: str) -> None:
        if field not in body or body[field] is None:
            return
        try:
            number = int(body[field])
        except (TypeError, ValueError) as exc:
            raise BadRequest(f"{field} must be an integer") from exc
        if number < 0:
            raise BadRequest(f"{field} must not be negative")
        payload[field] = number

    def text(field: str, limit: int = 4096) -> None:
        value = body.get(field)
        if value is None:
            return
        if not isinstance(value, str):
            raise BadRequest(f"{field} must be a string")
        if len(value) > limit:
            raise BadRequest(f"{field} is too long")
        payload[field] = value

    if action == "list_decisions":
        positive_int("limit")
    elif action == "get_decision":
        record_id()
    elif action == "get_events":
        record_id()
        positive_int("after_sequence")
        positive_int("limit")
    elif action == "get_source":
        record_id()
        identifier("artifact_id", ARTIFACT_ID, required=False)
    elif action == "get_today":
        pass
    elif action == "evaluate_lot":
        identifier("lot_id", LOT_ID, required=True)
        record_id(required=False)
        # Document bodies are bounded but not inspected here: what a document
        # means is the runtime's evidence pipeline to decide, not the proxy's.
        text("document", limit=MAX_BODY_BYTES)
        text("document_b64", limit=MAX_BODY_BYTES)
        text("artifact_ref", limit=2048)
        text("content_type", limit=128)
        text("document_type", limit=128)
    elif action == "supply_evidence":
        record_id()
        identifier("lot_id", LOT_ID, required=True)
        text("document", limit=MAX_BODY_BYTES)
        text("document_b64", limit=MAX_BODY_BYTES)
        text("artifact_ref", limit=2048)
        text("content_type", limit=128)
        text("document_type", limit=128)
        value = body.get("authority_source")
        if not isinstance(value, str) or not value.strip():
            raise BadRequest("authority_source is required")
        payload["authority_source"] = value[:256]
    elif action == "submit_quality_authority":
        # Transport only. The proxy checks SHAPE — that the fields are present,
        # typed and bounded — and nothing else. Whether this record is actually
        # awaiting this question, whether the snapshot still matches and
        # whether the decision may be recorded at all are authority questions,
        # and they are answered by the runtime against durable state.
        record_id()
        decision = body.get("decision")
        if decision not in ("AUTHORIZE_APPLICABILITY", "KEEP_HELD"):
            raise BadRequest("decision is not a recognised quality authority decision")
        payload["decision"] = decision
        for field in ("accountable_actor", "authority_source"):
            value = body.get(field)
            if not isinstance(value, str) or not value.strip():
                raise BadRequest(f"{field} is required")
            payload[field] = value[:256]
        text("claim_set_hash", limit=128)
        text("question_id", limit=256)

    return payload


#: Actions whose runtime work outlives an API Gateway request. Started in the
#: background; the browser polls the decision record it named.
ASYNC_ACTIONS = frozenset({"evaluate_lot", "supply_evidence"})

#: Marks an invocation that IS the background worker, so it runs the action
#: instead of dispatching it again. Internal only — it is never read from an
#: HTTP request, so a caller cannot set it to make a request run inline.
WORKER_MARKER = "__vouch_worker__"

FUNCTION_NAME = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "")

_lambda_client = None


def lambda_client():
    global _lambda_client
    if _lambda_client is None:
        _lambda_client = boto3.client("lambda")
    return _lambda_client


def start_background(payload: dict) -> None:
    """Hand one already-validated payload to a background copy of this function.

    `InvocationType="Event"` returns as soon as AWS has accepted the payload, so
    the caller answers in well under the gateway's ceiling while the real work
    runs for as long as it needs.

    The payload forwarded is the VALIDATED one. Re-validating in the worker
    would be the only guard if a raw body were passed, and a background path is
    the worst place to discover an identifier was hostile.
    """
    if not FUNCTION_NAME:
        raise RuntimeError("AWS_LAMBDA_FUNCTION_NAME is not set")
    lambda_client().invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="Event",
        Payload=json.dumps({WORKER_MARKER: True, "payload": payload}).encode(),
    )


def _route(method: str, path: str, query: dict) -> tuple[str, dict]:
    """Map an HTTP route to one allowlisted action.

    Explicit routes rather than an `/api/invoke` that names its own action: a
    generic endpoint makes the allowlist the only boundary, and a bug in it
    exposes everything at once.
    """
    parts = [segment for segment in path.strip("/").split("/") if segment]
    if parts and parts[0] == "api":
        parts = parts[1:]

    if method == "POST":
        if parts == ["evaluate"]:
            return "evaluate_lot", {}
        if parts == ["evidence"]:
            return "supply_evidence", {}
        if parts == ["quality-authority"]:
            return "submit_quality_authority", {}
    elif method == "GET":
        if parts == ["today"]:
            return "get_today", {}
        if parts == ["decisions"]:
            return "list_decisions", {"limit": query.get("limit")}
        if len(parts) == 2 and parts[0] == "decisions":
            return "get_decision", {"decision_record_id": parts[1]}
        if len(parts) == 3 and parts[0] == "decisions":
            record = {"decision_record_id": parts[1]}
            if parts[2] == "events":
                record["after_sequence"] = query.get("after_sequence")
                record["limit"] = query.get("limit")
                return "get_events", record
            if parts[2] == "sources":
                record["artifact_id"] = query.get("artifact_id")
                return "get_source", record

    raise BadRequest(f"no route for {method} {path}")


def _cors() -> dict:
    """Same-origin by default.

    An allowed origin is opt-in through configuration; the fallback is to send
    no CORS header at all rather than a wildcard, because a wildcard on a
    credential-bearing proxy is an open invocation path.
    """
    if not ALLOWED_ORIGIN:
        return {}
    return {
        "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
        "Access-Control-Allow-Headers": "content-type",
        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        "Vary": "Origin",
    }


def _respond(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", **_cors()},
        "body": json.dumps(body),
    }


def _failure(status: int, reason: str, failure_class: str) -> dict:
    """A transport failure, typed so a UI never reads it as a disposition.

    `disposition` is deliberately absent rather than empty: a client that sees
    the key at all may render it, and no transport error has ever decided
    whether a material may enter production.
    """
    return _respond(status, {"ok": False, "error": reason, "failure_class": failure_class})


#: One session id reused by every READ.
#:
#: AgentCore gives each `runtimeSessionId` its own execution environment and
#: cold-starts it on first use. Measured against the deployed runtime: a fresh
#: session costs ~3.3s, a reused one ~0.2s — the same work, 20x apart. Minting a
#: new id per request, as this did, meant every read paid a cold start and the
#: product looked empty for four seconds on every navigation.
#:
#: Reads are safe to share: `list_decisions`, `get_decision`, `get_events`,
#: `get_source` and `get_today` are pure queries against DynamoDB and S3, they
#: hold no per-caller state, and the runtime keeps no cross-invocation memory
#: (AGENTS.md §3: authoritative truth lives in application state, never in agent
#: memory). WRITES deliberately keep a fresh session each — an evaluation is a
#: long-running unit of work, and isolating it keeps one decision's execution
#: from sharing an environment with another's.
#:
#: Process-lifetime, not persisted. A new Lambda instance or a restarted local
#: BFF simply pays one cold start and is warm thereafter.
READ_SESSION = uuid.uuid4().hex + uuid.uuid4().hex


def invoke_runtime(payload: dict, session_id: str | None = None) -> dict:
    """Sign and forward. The only place AWS is touched."""
    if not RUNTIME_ARN:
        raise RuntimeError("VOUCH_RUNTIME_ARN is not configured")
    # AgentCore requires a session id of at least 33 characters.
    session = session_id or (uuid.uuid4().hex + uuid.uuid4().hex)
    response = runtime_client().invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session,
        payload=json.dumps(payload).encode(),
    )
    raw = response["response"].read()
    return json.loads(raw)


def handler(event, context=None):  # noqa: ARG001
    # The background worker. Reached only by `start_background`.
    #
    # The marker alone is not the guard: an HTTP request must be rejected even
    # if one somehow carried the key. A proxied request always brings
    # `requestContext`, `rawPath`/`path` or `httpMethod` with it, so requiring
    # their ABSENCE means the worker branch is unreachable over HTTP by shape
    # rather than by trust.
    #
    # The payload was validated by the request that scheduled it. Failures are
    # logged and swallowed because there is no caller left to answer — the
    # decision's own authoritative state is what the UI reads, and a background
    # crash must not retry a decision the runtime may already have applied.
    http_shaped = any(
        key in event for key in ("requestContext", "rawPath", "path", "httpMethod")
    ) if isinstance(event, dict) else False
    if isinstance(event, dict) and event.get(WORKER_MARKER) and not http_shaped:
        work = event.get("payload") or {}
        # The action name only. The same rule as the request path: a document
        # and an authority source are in here, and a log is the wrong place for
        # either — so nothing but the verb is ever written.
        action = work.get("action")
        log.info("vouch bff worker action=%s", action)
        try:
            invoke_runtime(work)
        except Exception as exc:  # noqa: BLE001
            log.error("background invocation failed: %s", type(exc).__name__)
        return {"ok": True}

    method = (
        event.get("requestContext", {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "GET"
    ).upper()
    path = event.get("rawPath") or event.get("path") or "/"
    query = event.get("queryStringParameters") or {}

    if method == "OPTIONS":
        return _respond(200, {"ok": True})

    try:
        action, from_route = _route(method, path, query)

        body: dict = {}
        if event.get("body"):
            raw = event["body"]
            if event.get("isBase64Encoded"):
                import base64

                raw = base64.b64decode(raw).decode()
            if len(raw) > MAX_BODY_BYTES:
                return _failure(413, "request body is too large", "TECHNICAL_FAILURE")
            try:
                body = json.loads(raw)
            except json.JSONDecodeError:
                return _failure(400, "request body is not valid JSON", "TECHNICAL_FAILURE")
            if not isinstance(body, dict):
                return _failure(400, "request body must be an object", "TECHNICAL_FAILURE")

        body = {**body, **{k: v for k, v in from_route.items() if v is not None}}

        # The allowlist is checked BEFORE anything reaches AWS. A route can only
        # produce a known action, and this is the second lock on that.
        if action not in ALLOWED_ACTIONS:
            log.warning("refused action=%s", action)
            return _failure(403, f"action {action} is not available", "TECHNICAL_FAILURE")

        payload = _validated(action, body)

    except BadRequest as bad:
        return _failure(400, str(bad), "TECHNICAL_FAILURE")

    # Log the action, never the payload: documents and authority sources are in
    # there, and a log is the wrong place for either.
    log.info("vouch bff action=%s", action)

    if action in ASYNC_ACTIONS:
        # The runtime names the record when the caller does not, but the caller
        # cannot poll an id it has not been told. Generating it here keeps the
        # 202 answerable and matches the id shape the runtime already accepts.
        record_id = payload.get("decision_record_id") or f"DR-{uuid.uuid4().hex[:12]}"
        payload["decision_record_id"] = record_id
        try:
            start_background(payload)
        except Exception as exc:  # noqa: BLE001
            # A startup failure is real and immediate: nothing was scheduled, so
            # no amount of polling would ever produce a terminal state. It is
            # reported now rather than leaving the UI watching a decision that
            # does not exist.
            log.error("could not start background work: %s", type(exc).__name__)
            return _failure(502, "the decision service could not be started", "TECHNICAL_FAILURE")
        # 202, not 200: the work is accepted and running, and there is
        # deliberately no disposition here to mistake for an outcome.
        return _respond(202, {"ok": True, "action": action, "decision_record_id": record_id, "status": "STARTED"})

    try:
        # Reads share one warm session; see READ_SESSION.
        result = invoke_runtime(payload, session_id=READ_SESSION)
    except Exception as exc:  # noqa: BLE001
        # A transport failure is NOT a business outcome. It carries no
        # disposition, and the type name is logged rather than the message,
        # which can echo request content back.
        log.error("runtime invocation failed: %s", type(exc).__name__)
        return _failure(502, "the decision service is unavailable", "TECHNICAL_FAILURE")

    status = 200 if result.get("ok") else 400
    return _respond(status, result)
