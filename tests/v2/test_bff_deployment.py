"""The BFF deployment path: fail closed, and stay transport-only.

The BFF is the one component a browser can reach, so two properties matter more
than anything it does: it must never be provisioned with a wildcard CORS origin,
and it must never grow business logic. Both are asserted here rather than left
to review, because both are easy to violate accidentally and neither shows up in
a functional test.

Deployment itself is blocked: `gatehouse-dev` is denied `lambda:*` and
`apigateway:*` by design. These tests cover everything up to that boundary.
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEPLOY_BFF = ROOT / "scripts" / "deploy_bff.py"
HANDLER = ROOT / "bff" / "handler.py"


@pytest.fixture(scope="module")
def bff_deploy():
    sys.path.insert(0, str(ROOT / "src"))
    spec = importlib.util.spec_from_file_location("vouch_deploy_bff", DEPLOY_BFF)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ==========================================================================
# CORS — the origin is never implicit
# ==========================================================================


def test_a_missing_origin_refuses_the_deploy(bff_deploy, monkeypatch) -> None:
    monkeypatch.delenv("VOUCH_ALLOWED_ORIGIN", raising=False)
    with pytest.raises(bff_deploy.DeploymentRefused) as refusal:
        bff_deploy.allowed_origin()
    assert "VOUCH_ALLOWED_ORIGIN" in str(refusal.value)


def test_a_wildcard_origin_is_refused(bff_deploy, monkeypatch) -> None:
    """This API can start a decision. It is not public."""
    monkeypatch.setenv("VOUCH_ALLOWED_ORIGIN", "*")
    with pytest.raises(bff_deploy.DeploymentRefused) as refusal:
        bff_deploy.allowed_origin()
    assert "not public" in str(refusal.value)


def test_an_empty_origin_is_refused(bff_deploy, monkeypatch) -> None:
    monkeypatch.setenv("VOUCH_ALLOWED_ORIGIN", "   ")
    with pytest.raises(bff_deploy.DeploymentRefused):
        bff_deploy.allowed_origin()


def test_an_explicit_origin_is_accepted(bff_deploy, monkeypatch) -> None:
    monkeypatch.setenv("VOUCH_ALLOWED_ORIGIN", "https://app.example.com")
    assert bff_deploy.allowed_origin() == "https://app.example.com"


# ==========================================================================
# the package — transport only
# ==========================================================================


def test_the_package_contains_only_the_handler(bff_deploy) -> None:
    """One file. A vendored dependency would be a place for logic to accumulate."""
    names = zipfile.ZipFile(BytesIO(bff_deploy.package())).namelist()
    assert names == ["handler.py"]


def test_the_handler_holds_no_domain_logic() -> None:
    """The BFF signs and forwards. It decides nothing.

    A disposition, a readiness rule or a policy decision appearing here would
    mean two systems could disagree about what Vouch concluded.
    """
    source = HANDLER.read_text()
    for forbidden in (
        "QUARANTINE", "RELEASE", "INSUFFICIENT_EVIDENCE",
        "readiness", "coverage", "short_by", "disposition =",
        "row_state =", "governing", "spec_revision",
    ):
        assert forbidden not in source, f"business logic in the BFF: {forbidden!r}"


def test_the_allowlist_is_exactly_the_browser_actions() -> None:
    """No generic passthrough: the runtime's action surface is not the boundary.

    Nine actions, not eight: `reset_demo` is the canonical demo reset the judge
    deployment exposes. It belongs on a browser-facing list because a judge
    invokes it from the product, and it is safe to expose because it accepts NO
    caller input — see `test_judge_deployment.py`.
    """
    sys.path.insert(0, str(ROOT / "bff"))
    import handler  # noqa: PLC0415

    assert handler.ALLOWED_ACTIONS == {
        "evaluate_lot", "supply_evidence", "submit_quality_authority",
        "list_decisions", "get_decision", "get_events", "get_source", "get_today",
        "reset_demo",
    }
    # Actions the runtime supports but a browser must never reach.
    for internal in ("readiness", "recovery", "ledger"):
        assert internal not in handler.ALLOWED_ACTIONS


def test_the_execution_role_may_invoke_only_the_one_runtime() -> None:
    """Scoped in the admin step, and asserted here so it stays scoped."""
    admin = (ROOT / "docs" / "sponsor-depth" / "ADMIN_STEP_BFF.md").read_text()
    assert "bedrock-agentcore:InvokeAgentRuntime" in admin
    # No DynamoDB or S3 for a transport component.
    assert "dynamodb:" not in admin
    assert "s3:" not in admin


# ==========================================================================
# no credentials or content reach the browser or the logs
# ==========================================================================


def test_the_handler_logs_no_document_bytes_or_urls() -> None:
    """A presigned URL outlives the request; a document is the evidence itself."""
    source = HANDLER.read_text()
    for line in source.splitlines():
        stripped = line.strip()
        if not stripped.startswith("log."):
            continue
        for leaky in ("document", "document_b64", "view_ref", "body", "payload"):
            assert leaky not in stripped, f"log line may leak {leaky!r}: {stripped}"


def test_the_frontend_ships_no_aws_sdk() -> None:
    """The browser holds no credentials, so it cannot sign anything."""
    import json

    package = json.loads((ROOT / "frontend" / "package.json").read_text())
    dependencies = {
        **package.get("dependencies", {}),
        **package.get("devDependencies", {}),
    }
    for name in dependencies:
        assert not name.startswith("@aws-sdk"), f"the browser bundle pulls {name}"
        assert name != "aws-sdk"
