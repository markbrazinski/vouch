"""The judge deployment: authentication, authorization, and the demo reset.

What these protect is the security boundary of a publicly-reachable deployment.
Three properties, each of which would be a real incident if it regressed:

  * an unauthenticated caller cannot reach ANY API route, so nobody who finds
    the URL can read plant state or spend model budget;
  * a session cookie cannot be forged, replayed past expiry, or manufactured
    from a malformed one;
  * the reset action accepts NO caller input, so reaching it can never become a
    way to write a chosen value into authoritative state.

The reset's own semantics — what it restores, and that it leaves the ledger
alone — are `test_demo_reset.py`'s subject and are not re-tested here.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bff"))

import handler as bff  # noqa: E402

SECRET = "test-session-secret-not-a-real-one"


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch):
    """A known signing secret, so a test can mint and forge cookies."""
    monkeypatch.setattr(bff, "SESSION_SECRET", SECRET)
    monkeypatch.setattr(bff, "RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/T")


def event(method: str, path: str, body: dict | None = None, cookie: str | None = None) -> dict:
    shaped: dict = {
        "requestContext": {"http": {"method": method}},
        "rawPath": path,
        "headers": {},
    }
    if body is not None:
        shaped["body"] = json.dumps(body)
    if cookie is not None:
        shaped["cookies"] = [f"{bff.SESSION_COOKIE}={cookie}"]
    return shaped


# ==========================================================================
# an unauthenticated caller reaches nothing
# ==========================================================================

#: Every browser-facing route. Listed explicitly rather than derived from the
#: router, because a derived list would shrink silently if a route stopped
#: being registered — and this test exists to notice exactly that.
PROTECTED = [
    ("GET", "/api/today"),
    ("GET", "/api/decisions"),
    ("GET", "/api/decisions/DR-abc123abc123"),
    ("GET", "/api/decisions/DR-abc123abc123/events"),
    ("GET", "/api/decisions/DR-abc123abc123/sources"),
    ("POST", "/api/evaluate"),
    ("POST", "/api/evidence"),
    ("POST", "/api/quality-authority"),
    ("POST", "/api/reset-demo"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_no_route_is_reachable_without_a_session(method, path):
    assert bff.handler(event(method, path))["statusCode"] == 401


@pytest.mark.parametrize("method,path", PROTECTED)
def test_a_forged_cookie_reaches_nothing(method, path):
    """A signature the server did not produce is not a session."""
    payload = bff.issue_session("judge").split(".")[0]
    assert bff.handler(event(method, path, cookie=f"{payload}.forged"))["statusCode"] == 401


def test_refusal_happens_before_aws_is_touched(monkeypatch):
    """An anonymous request must not reach the runtime at all.

    Refusing after invoking would still answer 401 while having already spent
    the call — which is the cost this gate exists to prevent.
    """
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the runtime was invoked for an anonymous caller")

    monkeypatch.setattr(bff, "invoke_runtime", explode)
    monkeypatch.setattr(bff, "start_background", explode)
    assert bff.handler(event("GET", "/api/today"))["statusCode"] == 401
    assert bff.handler(event("POST", "/api/reset-demo"))["statusCode"] == 401


# ==========================================================================
# the session cookie
# ==========================================================================


def test_a_minted_session_names_its_user():
    assert bff.session_user(bff.issue_session("judge")) == "judge"


@pytest.mark.parametrize(
    "hostile",
    ["", "nonsense", "a.b.c", ".", "eyJ1IjoiaiJ9.", "....", "x" * 5000],
)
def test_a_malformed_cookie_authenticates_nobody(hostile):
    assert bff.session_user(hostile) == ""


def test_an_expired_session_authenticates_nobody(monkeypatch):
    monkeypatch.setattr(bff, "SESSION_TTL_SECONDS", -1)
    assert bff.session_user(bff.issue_session("judge")) == ""


def test_a_cookie_signed_with_another_secret_is_refused(monkeypatch):
    """The signature, not the payload, is what authenticates."""
    stolen = bff.issue_session("judge")
    monkeypatch.setattr(bff, "SESSION_SECRET", "a-different-secret")
    assert bff.session_user(stolen) == ""


def test_the_payload_cannot_be_edited_without_resigning():
    """Re-encoding a longer expiry invalidates the signature."""
    import base64

    payload = base64.urlsafe_b64encode(
        json.dumps({"u": "judge", "exp": 99999999999}).encode()
    ).decode().rstrip("=")
    signature = bff.issue_session("judge").split(".")[1]
    assert bff.session_user(f"{payload}.{signature}") == ""


def test_no_session_is_issued_without_a_signing_secret(monkeypatch):
    """Fail closed. An unconfigured deployment authenticates nobody rather
    than signing every cookie with the empty string."""
    monkeypatch.setattr(bff, "SESSION_SECRET", "")
    assert bff.session_user(bff.issue_session("judge")) == ""


def test_the_session_cookie_carries_every_protective_flag():
    cookie = bff._session_cookie("value", 100)
    for flag in ("HttpOnly", "Secure", "SameSite=Strict", "Path=/"):
        assert flag in cookie


# ==========================================================================
# sign-in
# ==========================================================================


def test_a_rejected_credential_answers_401_and_sets_no_cookie(monkeypatch):
    monkeypatch.setattr(bff, "authenticate", lambda u, p: False)
    response = bff.handler(
        event("POST", "/api/auth/login", {"username": "judge", "password": "wrong"})
    )
    assert response["statusCode"] == 401
    assert "cookies" not in response


def test_an_accepted_credential_sets_a_session(monkeypatch):
    monkeypatch.setattr(bff, "authenticate", lambda u, p: True)
    response = bff.handler(
        event("POST", "/api/auth/login", {"username": "judge", "password": "right"})
    )
    assert response["statusCode"] == 200
    assert bff.session_user(response["cookies"][0].split("=")[1].split(";")[0]) == "judge"


def test_sign_in_does_not_distinguish_unknown_user_from_wrong_password(monkeypatch):
    """One answer for both. Two would be an account-enumeration oracle."""
    monkeypatch.setattr(bff, "authenticate", lambda u, p: False)
    a = bff.handler(event("POST", "/api/auth/login", {"username": "nobody", "password": "x"}))
    b = bff.handler(event("POST", "/api/auth/login", {"username": "judge", "password": "x"}))
    assert a["statusCode"] == b["statusCode"] == 401
    assert a["body"] == b["body"]


def test_a_non_string_credential_is_refused_without_reaching_cognito(monkeypatch):
    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("cognito was called with a non-string credential")

    monkeypatch.setattr(bff, "authenticate", explode)
    response = bff.handler(
        event("POST", "/api/auth/login", {"username": {"$ne": None}, "password": []})
    )
    assert response["statusCode"] == 400


def test_logout_clears_the_cookie():
    response = bff.handler(event("POST", "/api/auth/logout"))
    assert response["statusCode"] == 200
    assert "Max-Age=0" in response["cookies"][0]


def test_the_password_is_never_echoed(monkeypatch):
    monkeypatch.setattr(bff, "authenticate", lambda u, p: False)
    response = bff.handler(
        event("POST", "/api/auth/login", {"username": "judge", "password": "hunter2"})
    )
    assert "hunter2" not in response["body"]


# ==========================================================================
# the reset action carries no caller input
# ==========================================================================


def test_reset_forwards_the_action_and_nothing_else():
    """The whole security argument for exposing a reset at all.

    A caller cannot name a lot, a status, a version or any other field: the
    payload built for the runtime is the action alone.
    """
    hostile = {
        "lot_id": "LOT-9999",
        "status": "RELEASED",
        "state_version": 1,
        "decision_record_id": "DR-aaaaaaaaaaaa",
        "scope": "EVERYTHING",
        "__proto__": {"admin": True},
    }
    assert bff._validated("reset_demo", hostile) == {"action": "reset_demo"}


def test_reset_is_answered_synchronously():
    """It restores seeded rows in well under the gateway ceiling, and the UI
    needs the restored state to render. Scheduling it in the background would
    answer 202 with nothing for the judge to read."""
    assert "reset_demo" not in bff.ASYNC_ACTIONS


def test_reset_is_in_the_allowlist_but_is_not_a_decision():
    assert "reset_demo" in bff.ALLOWED_ACTIONS
    assert "reset_demo" not in bff.WRITE_ACTIONS
    assert "reset_demo" not in bff.READ_ACTIONS


def test_an_authenticated_reset_reaches_the_runtime(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        bff, "invoke_runtime",
        lambda payload, session_id=None: seen.update(payload) or {"ok": True},
    )
    response = bff.handler(
        event("POST", "/api/reset-demo", {"lot_id": "LOT-9999"},
              cookie=bff.issue_session("judge"))
    )
    assert response["statusCode"] == 200
    assert seen == {"action": "reset_demo"}


def test_there_is_no_route_that_resets_a_named_lot():
    """The dev/film per-lot reset must not exist in the deployed handler. It
    lives in `scripts/local_bff.py`, which is never deployed."""
    with pytest.raises(bff.BadRequest):
        bff._route("POST", "/api/dev/reset-lot", {})
    assert "reset_lot" not in bff.ALLOWED_ACTIONS
