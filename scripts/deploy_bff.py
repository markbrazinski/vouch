#!/usr/bin/env python3
"""Deploy the Vouch BFF: Lambda + HTTP API.

    AWS_PROFILE=gatehouse VOUCH_ALLOWED_ORIGIN=https://... \
        python scripts/deploy_bff.py

    browser -> API Gateway (HTTP API) -> Lambda (bff/handler.py) -> AgentCore

The BFF exists because `InvokeAgentRuntime` is SigV4-signed and AgentCore has
no CORS surface. It is transport and authorization ONLY: it holds no
applicability, disposition, policy, recovery or view-model logic, and it
invents no lifecycle events. That is why this script ships `bff/handler.py`
alone and vendors nothing — a dependency here would be a place for logic to
accumulate.

Idempotent: re-running updates the function and reuses the existing API.

REQUIRED PERMISSIONS. `gatehouse-dev` is denied `lambda:*`, `apigateway:*` and
`iam:CreateRole`, by design — the identity that RUNS Vouch is not the identity
that PROVISIONS it. Run `docs/sponsor-depth/ADMIN_STEP_BFF.md` first, then run
this. It fails closed rather than partially provisioning.
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vouch.config import assert_vouch_identity, load  # noqa: E402

FUNCTION_NAME = "vouch-bff"
API_NAME = "vouch-bff-api"
EXEC_ROLE_NAME = "VouchBffLambdaRole"
RUNTIME_ID = "Gatehouse-IWAmEp93XP"
HANDLER = "handler.handler"
TIMEOUT_SECONDS = 90  # AgentCore evaluations run 15-60s.
MEMORY_MB = 512


class DeploymentRefused(RuntimeError):
    """Stopped because required configuration or permission is absent."""


def package() -> bytes:
    """The handler, and nothing else.

    No vendored dependencies: the handler uses only boto3, which the Lambda
    runtime already provides. Shipping one file also makes it obvious that no
    business logic crept in.
    """
    source = (ROOT / "bff" / "handler.py").read_text()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("handler.py", source)
    return buffer.getvalue()


def allowed_origin() -> str:
    """The single browser origin permitted to call this API.

    Refused when unset. A wildcard CORS policy on an endpoint that can start a
    decision would let any page on the internet spend model budget and read
    plant state, so there is deliberately no default.
    """
    origin = (os.environ.get("VOUCH_ALLOWED_ORIGIN") or "").strip()
    if not origin:
        raise DeploymentRefused(
            "VOUCH_ALLOWED_ORIGIN is unset, so this deploy would have no CORS "
            "origin.\n\n"
            "  Set it to the exact origin serving the frontend:\n"
            "      export VOUCH_ALLOWED_ORIGIN=https://app.example.com\n"
            "      export VOUCH_ALLOWED_ORIGIN=http://localhost:5173   # dev\n\n"
            "  '*' is not accepted: this API can start a decision."
        )
    if origin == "*":
        raise DeploymentRefused(
            "VOUCH_ALLOWED_ORIGIN='*' is refused. This API can start a "
            "decision and read authoritative plant state; it is not public."
        )
    return origin


def runtime_arn(config) -> str:
    return (
        f"arn:aws:bedrock-agentcore:{config.region}:{config.account_id}"
        f":runtime/{RUNTIME_ID}"
    )


def ensure_function(lam, config, origin: str) -> str:
    """Create or update the function. Returns its ARN."""
    env = {
        "Variables": {
            "VOUCH_RUNTIME_ARN": runtime_arn(config),
            "VOUCH_ALLOWED_ORIGIN": origin,
        }
    }
    code = package()

    try:
        lam.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except lam.exceptions.ResourceNotFoundException:
        exists = False

    if exists:
        print(f"==> updating function {FUNCTION_NAME}")
        lam.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=code)
        # Code and configuration are separate calls, and the second fails while
        # the first is still settling.
        for _ in range(30):
            state = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
            if state.get("LastUpdateStatus") != "InProgress":
                break
            time.sleep(2)
        lam.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Environment=env,
            Timeout=TIMEOUT_SECONDS,
            MemorySize=MEMORY_MB,
        )
    else:
        print(f"==> creating function {FUNCTION_NAME}")
        role = (
            f"arn:aws:iam::{config.account_id}:role/{EXEC_ROLE_NAME}"
        )
        lam.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role,
            Handler=HANDLER,
            Code={"ZipFile": code},
            Timeout=TIMEOUT_SECONDS,
            MemorySize=MEMORY_MB,
            Environment=env,
            Architectures=["arm64"],
        )

    for _ in range(30):
        state = lam.get_function_configuration(FunctionName=FUNCTION_NAME)
        if state.get("State") == "Active" and state.get("LastUpdateStatus") == "Successful":
            return state["FunctionArn"]
        time.sleep(2)
    raise DeploymentRefused("the function did not become Active")


def ensure_api(apigw, lam, config, function_arn: str, origin: str) -> str:
    """Create or reuse the HTTP API. Returns its invoke URL."""
    existing = next(
        (a for a in apigw.get_apis().get("Items", []) if a["Name"] == API_NAME),
        None,
    )
    if existing:
        api_id = existing["ApiId"]
        print(f"==> reusing api {api_id}")
        apigw.update_api(
            ApiId=api_id,
            CorsConfiguration={
                "AllowOrigins": [origin],
                "AllowMethods": ["GET", "POST", "OPTIONS"],
                "AllowHeaders": ["content-type"],
            },
        )
    else:
        print(f"==> creating api {API_NAME}")
        created = apigw.create_api(
            Name=API_NAME,
            ProtocolType="HTTP",
            Target=function_arn,
            CorsConfiguration={
                # Exactly one origin. Never "*": see `allowed_origin`.
                "AllowOrigins": [origin],
                "AllowMethods": ["GET", "POST", "OPTIONS"],
                "AllowHeaders": ["content-type"],
            },
        )
        api_id = created["ApiId"]

    try:
        lam.add_permission(
            FunctionName=FUNCTION_NAME,
            StatementId="apigw-invoke",
            Action="lambda:InvokeFunction",
            Principal="apigateway.amazonaws.com",
            SourceArn=(
                f"arn:aws:execute-api:{config.region}:{config.account_id}:{api_id}/*"
            ),
        )
    except lam.exceptions.ResourceConflictException:
        pass  # already granted

    return f"https://{api_id}.execute-api.{config.region}.amazonaws.com"


def main() -> int:
    print(f"identity: {assert_vouch_identity()}")
    try:
        origin = allowed_origin()
    except DeploymentRefused as refusal:
        print(f"\nDEPLOYMENT REFUSED\n\n{refusal}\n", file=sys.stderr)
        return 2

    import boto3

    config = load()
    if not config.account_id:
        print("no account id; provide provisioning.json", file=sys.stderr)
        return 2

    session = boto3.Session(region_name=config.region)
    lam = session.client("lambda")
    apigw = session.client("apigatewayv2")

    try:
        function_arn = ensure_function(lam, config, origin)
        url = ensure_api(apigw, lam, config, function_arn, origin)
    except DeploymentRefused as refusal:
        print(f"\nDEPLOYMENT REFUSED\n\n{refusal}\n", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        if "AccessDenied" in name or "AccessDenied" in str(exc):
            print(
                f"\nDEPLOYMENT REFUSED\n\n{exc}\n\n"
                "  gatehouse-dev cannot provision Lambda/API Gateway by design.\n"
                "  Run docs/sponsor-depth/ADMIN_STEP_BFF.md as your admin identity first.\n",
                file=sys.stderr,
            )
            return 2
        raise

    print(f"\n    endpoint: {url}")
    print(f"    origin:   {origin}")
    print("\n    routes: /api/evaluate /api/evidence /api/today /api/decisions")
    print("            /api/decisions/{id} /api/decisions/{id}/events")
    print("            /api/decisions/{id}/sources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
