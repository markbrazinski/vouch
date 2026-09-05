#!/usr/bin/env python3
"""Build and deploy the Vouch V2 AgentCore Runtime package.

    AWS_PROFILE=gatehouse python scripts/deploy_runtime.py [--build-only]

Why this exists rather than `agentcore deploy`: the supported CLI deploys
through CDK/CloudFormation, and gatehouse-dev is denied
`cloudformation:DescribeStacks`. The runtime itself, though, loads its code
from an S3 zip, and gatehouse-dev CAN write that bucket and call
`bedrock-agentcore-control:UpdateAgentRuntime`. So the deploy is: build the
package, upload it, point the runtime at it.

`agentcore validate` still passes and `agentcore deploy --dry-run` still
synthesises cleanly; only the CloudFormation status check is blocked. If that
permission is granted later, the CLI path becomes available and this script can
go away.

The package is a flat zip — vendored dependencies at the root, `main.py` at the
root, and `src/vouch/` alongside it, which is where the entrypoint puts it on
`sys.path`. Dependencies are resolved for linux/aarch64 + CPython 3.12 to match
the runtime, NOT for the host platform.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from vouch.config import assert_vouch_identity, load  # noqa: E402

RUNTIME_ID = "Gatehouse-IWAmEp93XP"
S3_PREFIX = "runtime/vouch-runtime-arm64.zip"
BUILD = ROOT / "build" / "runtime"
ARCHIVE = ROOT / "build" / "vouch-runtime-arm64.zip"

#: Resolved for the RUNTIME's platform, not the host's.
DEPENDENCIES = [
    "bedrock-agentcore",
    "strands-agents",
    "boto3",
    "pypdf",
    "aws-opentelemetry-distro",
]


def build() -> Path:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)

    print("==> vendoring dependencies (linux/aarch64, cp312)")
    subprocess.run(
        [
            "uv", "pip", "install", "--target", str(BUILD),
            "--python-platform", "aarch64-manylinux2014",
            "--python-version", "3.12",
            *DEPENDENCIES,
        ],
        check=True,
        capture_output=True,
    )

    print("==> staging entrypoint and vouch package")
    shutil.copy2(ROOT / "app" / "Gatehouse" / "main.py", BUILD / "main.py")
    shutil.copytree(
        ROOT / "src" / "vouch",
        BUILD / "src" / "vouch",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    print("==> zipping")
    ARCHIVE.unlink(missing_ok=True)
    with zipfile.ZipFile(ARCHIVE, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(BUILD.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(BUILD))

    size_mb = ARCHIVE.stat().st_size / 1_048_576
    print(f"    {ARCHIVE.relative_to(ROOT)} ({size_mb:.1f} MB)")
    return ARCHIVE


def deploy(archive: Path, guardrails: dict[str, str] | None = None) -> int:
    import boto3

    config = load()
    session = boto3.Session(profile_name="gatehouse", region_name=config.region)

    print(f"==> uploading to s3://{config.evidence_bucket}/{S3_PREFIX}")
    session.client("s3").upload_file(
        str(archive), config.evidence_bucket, S3_PREFIX
    )

    # Refuse before the update call, not after: a half-applied deploy is worse
    # than one that never started.
    guardrails = guardrail_config() if guardrails is None else guardrails

    print(f"==> updating runtime {RUNTIME_ID}")
    control = session.client("bedrock-agentcore-control")
    response = control.update_agent_runtime(
        agentRuntimeId=RUNTIME_ID,
        roleArn=config.runtime_role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
        agentRuntimeArtifact={
            "codeConfiguration": {
                "code": {
                    "s3": {"bucket": config.evidence_bucket, "prefix": S3_PREFIX}
                },
                "runtime": "PYTHON_3_12",
                "entryPoint": ["main.py"],
            }
        },
        environmentVariables={
            # BOTH switches. VOUCH_MODE selects the stores; VOUCH_V2_MODE
            # selects who decides. Setting only the first is the audit blocker:
            # durable AWS persistence with scripted reasoners. The composition
            # now refuses to start that way, so a deploy missing this line
            # fails loudly instead of quietly deciding with Python.
            "VOUCH_MODE": "production",
            "VOUCH_V2_MODE": "bedrock",
            "VOUCH_STATE_TABLE": config.state_table,
            "VOUCH_EVIDENCE_BUCKET": config.evidence_bucket,
            # Prototype issuance key. Not a KMS/Secrets Manager service — see
            # docs/architecture/v2/AWS_STATUS.md, which says so plainly.
            "VOUCH_ISSUANCE_KEY": "vouch-demo-issuance-key",
            "AWS_REGION": config.region,
            # Real prompt-attack inspection on the deployed path. Validated by
            # `guardrail_config()` BEFORE anything is built or uploaded — an
            # absent id refuses the deploy rather than shipping no detector.
            **guardrails,
            # Sponsor depth: structure recovery for table/scanned COAs. Off
            # unless set, so a deploy that omits it behaves exactly as before.
            "VOUCH_TEXTRACT_ENABLED": os.environ.get("VOUCH_TEXTRACT_ENABLED", ""),
            # Sponsor depth: AgentCore Observability. The distro was already
            # vendored and completely unused — aws/spans sat at 0 bytes while
            # Transaction Search was ACTIVE and the X-Ray IAM was attached.
            #
            # AGENT_OBSERVABILITY_ENABLED is what makes AgentCore route spans
            # to the GenAI observability surface; the OTEL_* pair names the
            # service so Investigator and Verifier spans are attributable.
            "AGENT_OBSERVABILITY_ENABLED": "true",
            "OTEL_PYTHON_DISTRO": "aws_distro",
            "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
            "OTEL_SERVICE_NAME": "vouch-v2",
            "OTEL_RESOURCE_ATTRIBUTES": "service.name=vouch-v2,service.version=v2",
            # SECURITY, non-negotiable. The audit found <thinking> blocks
            # already in CloudWatch; GenAI instrumentation would additionally
            # copy prompts and completions into a trace backend. Vouch's audit
            # record is the typed output, and it claims not to retain reasoning
            # — so content capture stays OFF and `vouch.v2.telemetry` drops any
            # reasoning-bearing payload before it can become a span attribute.
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
            "OTEL_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
            "STRANDS_OTEL_ENABLE_CONSOLE_EXPORT": "false",
        },
    )
    version = response["agentRuntimeVersion"]
    print(f"    version {version}: {response['status']}")

    for _ in range(30):
        status = control.get_agent_runtime(agentRuntimeId=RUNTIME_ID)["status"]
        if status == "READY":
            verify_deployed_guardrail(control, guardrails, version)
            print(f"    READY (version {version})")
            return 0
        if status.endswith("FAILED"):
            print(f"    {status}", file=sys.stderr)
            return 1
        time.sleep(10)

    print("    timed out waiting for READY", file=sys.stderr)
    return 1


class DeploymentRefused(RuntimeError):
    """A deployment was stopped because its security configuration is absent."""


#: The env var that lets a deploy proceed without Guardrails. Deliberately
#: long and unpleasant to type: it must never be set by habit, and it must be
#: obvious in shell history that a security control was waived on purpose.
UNSAFE_OPT_IN = "VOUCH_DEPLOY_WITHOUT_GUARDRAILS"


def guardrail_config(env: dict[str, str] | None = None) -> dict[str, str]:
    """The Guardrails configuration this deploy will ship, or refuse.

    Runtime v25 deployed successfully with no Guardrails at all: this script
    read `VOUCH_GUARDRAIL_ID` with a `""` default, the runtime saw an empty id
    and fell back to no detector, and nothing anywhere said so. A deploy that
    forgets a security control must not be indistinguishable from a deploy that
    never wanted one, so an absent id is now a hard stop.

    Returns the environment fragment to merge into the runtime configuration.
    Raises `DeploymentRefused` rather than returning a degraded default: there
    is no safe value to fall back TO.
    """
    env = os.environ if env is None else env
    guardrail_id = (env.get("VOUCH_GUARDRAIL_ID") or "").strip()
    version = (env.get("VOUCH_GUARDRAIL_VERSION") or "").strip() or "DRAFT"

    if guardrail_id:
        return {
            "VOUCH_GUARDRAIL_ID": guardrail_id,
            "VOUCH_GUARDRAIL_VERSION": version,
        }

    # No id. The ONLY way past this point is an explicit, named waiver.
    if (env.get(UNSAFE_OPT_IN) or "").strip() == "i-accept-no-prompt-attack-detection":
        print(
            "    WARNING: deploying with NO prompt-attack detection because "
            f"{UNSAFE_OPT_IN} is set.\n"
            "    This runtime is NOT qualified for demo or production use.",
            file=sys.stderr,
        )
        return {"VOUCH_GUARDRAIL_ID": "", "VOUCH_GUARDRAIL_VERSION": ""}

    raise DeploymentRefused(
        "VOUCH_GUARDRAIL_ID is empty or unset, so this deploy would ship a "
        "runtime with NO prompt-attack detection.\n\n"
        "  Set it to the Bedrock Guardrail backing the deployed security path:\n"
        "      export VOUCH_GUARDRAIL_ID=<guardrail-id>\n"
        "      export VOUCH_GUARDRAIL_VERSION=DRAFT   # or a published version\n\n"
        f"  A deploy WITHOUT Guardrails requires an explicit waiver:\n"
        f"      export {UNSAFE_OPT_IN}=i-accept-no-prompt-attack-detection\n"
        "  Such a runtime is not qualified for demo or production use."
    )


def verify_deployed_guardrail(control, expected: dict[str, str], version: str) -> None:
    """Read the deployed configuration back and confirm it carries what we sent.

    Sending the right value is not the same as the runtime HAVING it. v25 was
    caught by diffing deployed environment variables by hand; this does that
    automatically, on every deploy, before the script reports success.
    """
    deployed = control.get_agent_runtime(
        agentRuntimeId=RUNTIME_ID, agentRuntimeVersion=version
    ).get("environmentVariables", {})

    for key, want in expected.items():
        got = deployed.get(key, "")
        if got != want:
            raise DeploymentRefused(
                f"deployed runtime version {version} has {key}={got!r}, "
                f"expected {want!r}. The security configuration did not land."
            )
    if expected.get("VOUCH_GUARDRAIL_ID"):
        print(
            f"    guardrails verified: {expected['VOUCH_GUARDRAIL_ID']}"
            f":{expected['VOUCH_GUARDRAIL_VERSION']}"
        )


def main() -> int:
    print(f"identity: {assert_vouch_identity()}")

    # Validate security configuration BEFORE spending three minutes vendoring
    # dependencies. A deploy that is going to be refused should be refused now.
    try:
        guardrails = guardrail_config()
    except DeploymentRefused as refusal:
        print(f"\nDEPLOYMENT REFUSED\n\n{refusal}\n", file=sys.stderr)
        return 2

    archive = build()
    if "--build-only" in sys.argv:
        return 0
    try:
        return deploy(archive, guardrails)
    except DeploymentRefused as refusal:
        print(f"\nDEPLOYMENT REFUSED\n\n{refusal}\n", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
