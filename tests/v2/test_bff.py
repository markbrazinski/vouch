"""The BFF — transport and authorization, and nothing else.

A browser cannot call AgentCore: `InvokeAgentRuntime` is SigV4-signed and the
runtime has no CORS surface. The only two bridges are shipping AWS credentials
to the client — which hands every viewer the ability to invoke the runtime
directly — or signing server-side. This signs server-side.

Two rules carry the security, and both are tested here rather than described:
the action allowlist is checked BEFORE any AWS call, and every identifier is
validated structurally before it can reach a runtime payload.

What this must never become is a generic passthrough. An `/api/invoke` that
names its own action would make the runtime's action surface the security
boundary, and the runtime was not designed to be one.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bff"))

import handler as bff  # noqa: E402


@pytest.fixture(autouse=True)
def runtime_arn(monkeypatch):
    monkeypatch.setattr(bff, "RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/T")


@pytest.fixture
def invoked(monkeypatch):
    """Every payload that would reach AgentCore, by either path, sending none.

    Writes are now scheduled onto a background invocation rather than awaited,
    so a fixture that watched only `invoke_runtime` would see nothing for
    `evaluate`/`evidence` and quietly stop testing them. Both paths are captured
    here so the allowlist and validation guarantees are asserted against the
    payload that actually reaches the runtime, whichever way it travels.
    """
    calls = []

    def fake(payload, session_id=None):
        calls.append(payload)
        return {"ok": True, "action": payload["action"], "echo": payload}

    monkeypatch.setattr(bff, "invoke_runtime", fake)
    monkeypatch.setattr(bff, "FUNCTION_NAME", "vouch-bff")
    monkeypatch.setattr(bff, "start_background", lambda payload: calls.append(payload))
    return calls


def _event(method, path, body=None, query=None):
    return {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "queryStringParameters": query or {},
        "body": json.dumps(body) if body is not None else None,
    }


def _call(method, path, body=None, query=None):
    response = bff.handler(_event(method, path, body, query))
    return response["statusCode"], json.loads(response["body"])


# ======================================================================
# the allowlist
# ======================================================================


ROUTES = [
    ("GET", "/api/today", None, "get_today"),
    ("GET", "/api/decisions", None, "list_decisions"),
    ("GET", "/api/decisions/DR-abc123", None, "get_decision"),
    ("GET", "/api/decisions/DR-abc123/events", None, "get_events"),
    ("GET", "/api/decisions/DR-abc123/sources", None, "get_source"),
    ("POST", "/api/evaluate", {"lot_id": "LOT-1002"}, "evaluate_lot"),
    (
        "POST",
        "/api/evidence",
        {
            "decision_record_id": "DR-abc123",
            "lot_id": "LOT-1005",
            "authority_source": "PLANT-QA-LAB",
            "document": "x",
        },
        "supply_evidence",
    ),
    (
        "POST",
        "/api/quality-authority",
        {
            "decision_record_id": "DR-abc123",
            "decision": "ESTABLISH_EVIDENCE",
            "evidence_ref": "CLM-abc123-01",
            "accountable_actor": "QA-LEAD",
            "authority_source": "Plant Quality Authority",
        },
        "submit_quality_authority",
    ),
]


@pytest.mark.parametrize("method,path,body,action", ROUTES)
def test_every_authorized_action_reaches_the_runtime(method, path, body, action, invoked):
    status, payload = _call(method, path, body)

    # Reads answer with the result; writes answer 202 once the work is
    # scheduled. Either way exactly one payload reaches the runtime.
    assert status == (202 if action in bff.ASYNC_ACTIONS else 200), payload
    assert [call["action"] for call in invoked] == [action]


def test_the_allowlist_covers_exactly_the_browser_facing_actions():
    assert bff.ALLOWED_ACTIONS == {
        "list_decisions", "get_decision", "get_events", "get_source", "get_today",
        "evaluate_lot", "supply_evidence", "submit_quality_authority",
    }


def test_the_dev_reset_route_does_not_exist_in_the_deployed_bff(invoked):
    """The film/dev LOT reset is served ONLY by `scripts/local_bff.py`.

    It mutates authoritative corpus state, so adding it to the deployed
    handler's allowlist would widen the browser-to-runtime security boundary
    for production in order to serve a filming convenience. Here it must be
    an ordinary unrouted path: refused before AWS is touched.
    """
    for method, body in (("POST", {"lot_id": "LOT-1006"}), ("GET", None)):
        status, _ = _call(method, "/api/dev/reset-lot", body)
        assert status == 400, method
    assert invoked == [], "a reset request reached the runtime"
    assert not any("reset" in action for action in bff.ALLOWED_ACTIONS)


@pytest.mark.parametrize(
    "path",
    ["/api/ledger", "/api/recovery", "/api/readiness", "/api/invoke", "/api/anything"],
)
def test_an_unrouted_path_never_reaches_aws(path, invoked):
    """Refused at the proxy, before a single AWS call is made."""
    status, payload = _call("GET", path)

    assert status == 400
    assert invoked == [], "an unauthorized request reached the runtime"


def test_there_is_no_generic_invoke_endpoint(invoked):
    """A caller must not be able to name its own action."""
    status, _ = _call("POST", "/api/invoke", {"action": "ledger"})

    assert status == 400
    assert invoked == []


def test_an_action_named_in_the_body_cannot_override_the_route(invoked):
    """The route decides the action; the body never does."""
    status, _ = _call("POST", "/api/evaluate", {"lot_id": "LOT-1", "action": "ledger"})

    assert status == 202
    assert invoked[0]["action"] == "evaluate_lot"


# ======================================================================
# structural validation
# ======================================================================


@pytest.mark.parametrize(
    "record_id",
    # No empty string here: `/api/decisions/` collapses to `/api/decisions`,
    # which is the list route and legitimately answers 200. That is correct
    # routing rather than a validation hole, and an earlier version of this
    # test asserted otherwise.
    ["not-an-id", "DR-../../etc/passwd", "DR-" + "x" * 100, "'; DROP TABLE"],
)
def test_a_malformed_decision_id_is_refused(record_id, invoked):
    status, _ = _call("GET", f"/api/decisions/{record_id}")

    assert status == 400
    assert invoked == []


def test_an_empty_decision_path_lists_rather_than_leaking(invoked):
    """`/api/decisions/` is the list route, and must not become a wildcard read."""
    status, _ = _call("GET", "/api/decisions/")

    assert status == 200
    assert invoked[0]["action"] == "list_decisions"
    assert "decision_record_id" not in invoked[0]


def test_a_malformed_artifact_id_is_refused(invoked):
    status, _ = _call(
        "GET", "/api/decisions/DR-abc123/sources", query={"artifact_id": "../secret"}
    )
    assert status == 400
    assert invoked == []


def test_a_negative_cursor_is_refused(invoked):
    status, _ = _call(
        "GET", "/api/decisions/DR-abc123/events", query={"after_sequence": "-5"}
    )
    assert status == 400
    assert invoked == []


def test_a_non_numeric_cursor_is_refused(invoked):
    status, _ = _call(
        "GET", "/api/decisions/DR-abc123/events", query={"after_sequence": "abc"}
    )
    assert status == 400
    assert invoked == []


def test_only_modelled_fields_are_forwarded(invoked):
    """A rebuilt payload, so an unmodelled key cannot ride along to the runtime."""
    _call(
        "POST",
        "/api/evaluate",
        {"lot_id": "LOT-1002", "smuggled": "value", "authority_source": "forged"},
    )

    assert "smuggled" not in invoked[0]
    assert "authority_source" not in invoked[0]


def test_evidence_requires_an_authority_source(invoked):
    status, _ = _call(
        "POST",
        "/api/evidence",
        {"decision_record_id": "DR-abc123", "lot_id": "LOT-1", "document": "x"},
    )
    assert status == 400
    assert invoked == []


# ======================================================================
# malformed requests fail safely
# ======================================================================


def test_a_non_json_body_fails_safely(invoked):
    event = _event("POST", "/api/evaluate")
    event["body"] = "{not json"
    response = bff.handler(event)

    assert response["statusCode"] == 400
    assert json.loads(response["body"])["failure_class"] == "TECHNICAL_FAILURE"
    assert invoked == []


def test_a_non_object_body_fails_safely(invoked):
    event = _event("POST", "/api/evaluate")
    event["body"] = '["a", "list"]'
    response = bff.handler(event)

    assert response["statusCode"] == 400
    assert invoked == []


def test_an_oversized_body_is_refused_before_parsing(invoked):
    event = _event("POST", "/api/evaluate")
    event["body"] = "x" * (bff.MAX_BODY_BYTES + 1)
    response = bff.handler(event)

    assert response["statusCode"] == 413
    assert invoked == []


# ======================================================================
# a transport failure is not a business outcome
# ======================================================================


def test_a_runtime_failure_becomes_a_typed_transport_error(monkeypatch):
    def exploding(payload, session_id=None):
        raise RuntimeError("connection reset while sending LOT-1002 document bytes")

    monkeypatch.setattr(bff, "invoke_runtime", exploding)
    status, body = _call("GET", "/api/today")

    assert status == 502
    assert body["ok"] is False
    assert body["failure_class"] == "TECHNICAL_FAILURE"
    # No disposition, not even an empty one: a client that sees the key may
    # render it, and no transport error decided anything about a material.
    assert "disposition" not in body


def test_a_runtime_failure_does_not_echo_the_request(monkeypatch, caplog):
    def exploding(payload, session_id=None):
        raise RuntimeError("failed sending secret-document-bytes")

    monkeypatch.setattr(bff, "invoke_runtime", exploding)
    with caplog.at_level(logging.ERROR):
        _, body = _call("GET", "/api/today")

    assert "secret-document-bytes" not in json.dumps(body)
    assert "secret-document-bytes" not in caplog.text


# ======================================================================
# logging boundary
# ======================================================================


def test_document_bytes_never_reach_the_logs(invoked, caplog):
    with caplog.at_level(logging.INFO):
        _call("POST", "/api/evaluate", {"lot_id": "LOT-1", "document": "SENSITIVE-COA-TEXT"})

    assert "SENSITIVE-COA-TEXT" not in caplog.text


def test_a_presigned_url_is_returned_but_never_logged(monkeypatch, caplog):
    """It carries its own authorization; a logged copy outlives the request."""
    url = "https://bkt.s3.amazonaws.com/evidence/x?X-Amz-Signature=SECRETSIG"

    def with_source(payload, session_id=None):
        return {"ok": True, "action": "get_source", "sources": [{"view_ref": url}]}

    monkeypatch.setattr(bff, "invoke_runtime", with_source)
    with caplog.at_level(logging.INFO):
        status, body = _call("GET", "/api/decisions/DR-abc123/sources")

    assert status == 200
    assert body["sources"][0]["view_ref"] == url, "the viewer needs the reference"
    assert "SECRETSIG" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


# ======================================================================
# CORS
# ======================================================================


def test_no_cors_header_is_sent_by_default(invoked):
    """Same-origin. A wildcard on a credential-bearing proxy is an open door."""
    response = bff.handler(_event("GET", "/api/today"))
    assert "Access-Control-Allow-Origin" not in response["headers"]


def test_a_configured_origin_is_explicit_never_a_wildcard(monkeypatch, invoked):
    monkeypatch.setattr(bff, "ALLOWED_ORIGIN", "https://vouch.example.com")
    response = bff.handler(_event("GET", "/api/today"))

    assert response["headers"]["Access-Control-Allow-Origin"] == "https://vouch.example.com"
    assert response["headers"]["Access-Control-Allow-Origin"] != "*"


# ======================================================================
# no domain logic
# ======================================================================


def test_the_bff_carries_no_business_vocabulary():
    """Transport only. Domain judgment belongs to the runtime.

    Asserted against the source because the failure mode is gradual: one
    convenience mapping, then a default disposition, and the boundary is gone.
    """
    import ast

    # Compare the CODE, not the prose. The docstrings explain what this
    # deliberately does not do, so they name the very concepts being excluded —
    # stripping only `#` comments left those explanations looking like leaks.
    tree = ast.parse((ROOT / "bff" / "handler.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef)):
            if ast.get_docstring(node) and node.body:
                first = node.body[0]
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    first.value.value = ""
    body = ast.unparse(tree)

    forbidden = [
        "QUARANTINE", "RELEASE", "INSUFFICIENT_EVIDENCE", "governing_basis",
        "applicability", "reconcil", "capability", "readiness",
    ]
    for token in forbidden:
        assert token not in body, f"domain vocabulary {token!r} leaked into the proxy"


def test_the_bff_does_not_invent_lifecycle_events():
    source = (ROOT / "bff" / "handler.py").read_text()
    for event in ("EVIDENCE_RECEIVED", "DISPOSITION_COMPUTED", "DECISION_RESUMED"):
        assert event not in source


# ======================================================================
# the async contract
#
# API Gateway's HTTP API times out at 30s and cannot be raised. A real
# two-agent evaluation measured 35-110s, so the synchronous BFF returned 503
# on decisions the runtime went on to complete correctly. These tests pin the
# repair: a write is STARTED and answered immediately, and the outcome is
# reached by polling the record the caller was told about.
# ======================================================================


@pytest.fixture
def scheduled(monkeypatch):
    """Capture background dispatches instead of invoking Lambda."""
    calls = []
    monkeypatch.setattr(bff, "FUNCTION_NAME", "vouch-bff")
    monkeypatch.setattr(bff, "start_background", lambda payload: calls.append(payload))
    return calls


WRITE_ROUTES = [
    ("POST", "/api/evaluate", {"lot_id": "LOT-1002"}, "evaluate_lot"),
    (
        "POST",
        "/api/evidence",
        {
            "decision_record_id": "DR-abc123",
            "lot_id": "LOT-1005",
            "authority_source": "PLANT-QA-LAB",
            "document": "x",
        },
        "supply_evidence",
    ),
]


@pytest.mark.parametrize("method,path,body,action", WRITE_ROUTES)
def test_a_write_is_started_and_never_awaited(method, path, body, action, scheduled, monkeypatch):
    """The POST must not wait for the decision.

    If it awaited the runtime, a 35-110s evaluation would exceed the gateway
    ceiling and the browser would see 503 for a decision that succeeded.
    """
    inline = []
    monkeypatch.setattr(bff, "invoke_runtime", lambda p, session_id=None: inline.append(p))

    status, payload = _call(method, path, body)

    assert status == 202, payload
    assert payload["status"] == "STARTED"
    # Nothing was invoked inline; the work was handed to the background.
    assert inline == []
    assert [call["action"] for call in scheduled] == [action]


@pytest.mark.parametrize("method,path,body,action", WRITE_ROUTES)
def test_a_write_answers_with_the_pollable_record_id(method, path, body, action, scheduled):
    """The id is the whole mechanism: without it the UI cannot poll anything."""
    _, payload = _call(method, path, body)

    record_id = payload["decision_record_id"]
    assert bff.RECORD_ID.match(record_id), record_id
    # The background work must target the SAME record the caller was told to
    # poll, or the UI would watch a decision nothing is writing to.
    assert scheduled[0]["decision_record_id"] == record_id


def test_a_supplied_record_id_is_preserved(scheduled):
    """Hero B Run 2 continues an existing record rather than opening a new one."""
    _, payload = _call(
        "POST",
        "/api/evidence",
        {
            "decision_record_id": "DR-abc123",
            "lot_id": "LOT-1005",
            "authority_source": "QA-LEAD",
            "document": "x",
        },
    )
    assert payload["decision_record_id"] == "DR-abc123"
    assert scheduled[0]["decision_record_id"] == "DR-abc123"


@pytest.mark.parametrize("method,path,body,action", WRITE_ROUTES)
def test_a_started_write_carries_no_disposition(method, path, body, action, scheduled):
    """A 202 knows nothing about the material, and must not imply it does."""
    _, payload = _call(method, path, body)

    for key in ("disposition", "failure_category", "mutation", "consequences"):
        assert key not in payload, f"a STARTED response must not carry {key}"


@pytest.mark.parametrize("method,path,body,action", WRITE_ROUTES)
def test_a_long_runtime_call_cannot_delay_the_response(method, path, body, action, monkeypatch):
    """The gateway ceiling, expressed as a test.

    `invoke_runtime` is made to fail if called during the request. A handler
    that still awaited the runtime would trip it; one that schedules does not.
    """
    monkeypatch.setattr(bff, "FUNCTION_NAME", "vouch-bff")
    dispatched = []
    monkeypatch.setattr(bff, "start_background", lambda payload: dispatched.append(payload))

    def too_slow(payload, session_id=None):
        raise AssertionError("the request awaited the runtime and would have timed out")

    monkeypatch.setattr(bff, "invoke_runtime", too_slow)

    status, _ = _call(method, path, body)
    assert status == 202
    assert len(dispatched) == 1


@pytest.mark.parametrize("method,path,body,action", WRITE_ROUTES)
def test_a_startup_failure_is_reported_immediately(method, path, body, action, monkeypatch):
    """If nothing was scheduled, polling would never terminate. Say so now."""
    monkeypatch.setattr(bff, "FUNCTION_NAME", "vouch-bff")

    def cannot_start(payload):
        raise RuntimeError("no")

    monkeypatch.setattr(bff, "start_background", cannot_start)

    status, payload = _call(method, path, body)
    assert status == 502
    assert payload["ok"] is False
    assert payload["failure_class"] == "TECHNICAL_FAILURE"
    assert "disposition" not in payload


def test_reads_are_still_answered_synchronously(invoked):
    """Only writes are deferred. A read that returned 202 would break the UI."""
    status, payload = _call("GET", "/api/today")
    assert status == 200
    assert [call["action"] for call in invoked] == ["get_today"]


def test_the_worker_runs_the_action_it_was_given(monkeypatch):
    ran = []
    monkeypatch.setattr(bff, "invoke_runtime", lambda p, session_id=None: ran.append(p))

    result = bff.handler(
        {bff.WORKER_MARKER: True, "payload": {"action": "evaluate_lot", "lot_id": "LOT-1002"}}
    )

    assert result == {"ok": True}
    assert [call["action"] for call in ran] == ["evaluate_lot"]


def test_a_worker_failure_does_not_echo_the_request(monkeypatch, caplog):
    """No caller is left to answer, so it is logged — but never with content."""

    def boom(payload, session_id=None):
        raise RuntimeError("secret document text")

    monkeypatch.setattr(bff, "invoke_runtime", boom)

    with caplog.at_level(logging.ERROR):
        assert bff.handler({bff.WORKER_MARKER: True, "payload": {"action": "evaluate_lot"}})
    assert "secret document text" not in caplog.text


@pytest.mark.parametrize(
    "event",
    [
        # The marker inside a request body.
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/api/evaluate",
            "body": json.dumps(
                {"lot_id": "L", bff.WORKER_MARKER: True, "payload": {"action": "get_today"}}
            ),
        },
        # The marker smuggled alongside a real HTTP event.
        {
            "requestContext": {"http": {"method": "POST"}},
            "rawPath": "/api/evaluate",
            bff.WORKER_MARKER: True,
            "payload": {"action": "get_today"},
            "body": json.dumps({"lot_id": "L"}),
        },
    ],
)
def test_an_http_request_can_never_become_the_worker(event, monkeypatch):
    """The worker skips validation, so HTTP must not be able to reach it.

    Guarded by SHAPE, not by trust: anything carrying HTTP request keys is a
    request, whatever else it claims.
    """
    monkeypatch.setattr(bff, "FUNCTION_NAME", "vouch-bff")
    ran = []
    monkeypatch.setattr(bff, "invoke_runtime", lambda p, session_id=None: ran.append(p))
    monkeypatch.setattr(bff, "start_background", lambda payload: None)

    bff.handler(event)

    assert ran == [], "an HTTP request entered the unvalidated worker branch"


# ======================================================================
# quality authority — the proxy validates SHAPE and forwards nothing else
# ======================================================================


VALID_AUTHORITY = {
    "decision_record_id": "DR-abc123",
    "decision": "ESTABLISH_EVIDENCE",
    "evidence_ref": "CLM-abc123-01",
    "accountable_actor": "QA-LEAD",
    "authority_source": "Plant Quality Authority",
}


@pytest.mark.parametrize(
    "mutation",
    [
        {"decision": "RELEASE"},
        {"decision": "release_lot"},
        {"decision": "QUARANTINE"},
        {"decision": ""},
        {"decision": None},
        {"decision": "AUTHORIZE_APPLICABILITY"},
        {"evidence_ref": ""},
        {"evidence_ref": None},
        {"accountable_actor": ""},
        {"accountable_actor": "   "},
        {"authority_source": ""},
        {"decision_record_id": "not-a-record"},
        {"decision_record_id": "../../etc/passwd"},
    ],
)
def test_a_malformed_quality_authority_never_reaches_aws(mutation, invoked):
    body = {**VALID_AUTHORITY, **mutation}
    status, _ = _call("POST", "/api/quality-authority", body)

    assert status == 400
    assert invoked == [], "a malformed authority submission reached the runtime"


def test_the_proxy_cannot_invent_an_authority_decision(invoked):
    """Only the fields the action models are forwarded. A caller cannot smuggle
    an extra key through, and the proxy adds none of its own."""
    _call(
        "POST",
        "/api/quality-authority",
        {
            **VALID_AUTHORITY,
            "disposition": "RELEASE",
            "authorized_evidence_refs": ["CLM-forged"],
            "lot_id": "LOT-1006",
        },
    )

    assert len(invoked) == 1
    forwarded = invoked[0]
    assert forwarded["action"] == "submit_quality_authority"
    assert set(forwarded) <= {
        "action", "decision_record_id", "decision", "evidence_ref",
        "accountable_actor", "authority_source",
        "claim_set_hash", "question_id",
    }
    assert "disposition" not in forwarded
    assert "authorized_evidence_refs" not in forwarded
