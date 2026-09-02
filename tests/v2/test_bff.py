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
    """Capture what would have been sent to AgentCore, and send nothing."""
    calls = []

    def fake(payload, session_id=None):
        calls.append(payload)
        return {"ok": True, "action": payload["action"], "echo": payload}

    monkeypatch.setattr(bff, "invoke_runtime", fake)
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
            "lot_id": "LOT-1003",
            "authority_source": "PLANT-QA-LAB",
            "document": "x",
        },
        "supply_evidence",
    ),
]


@pytest.mark.parametrize("method,path,body,action", ROUTES)
def test_every_authorized_action_reaches_the_runtime(method, path, body, action, invoked):
    status, payload = _call(method, path, body)

    assert status == 200, payload
    assert [call["action"] for call in invoked] == [action]


def test_the_allowlist_covers_exactly_the_browser_facing_actions():
    assert bff.ALLOWED_ACTIONS == {
        "list_decisions", "get_decision", "get_events", "get_source", "get_today",
        "evaluate_lot", "supply_evidence",
    }


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

    assert status == 200
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
