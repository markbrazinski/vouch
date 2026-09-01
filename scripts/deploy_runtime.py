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


def deploy(archive: Path) -> int:
    import boto3

    config = load()
    session = boto3.Session(profile_name="gatehouse", region_name=config.region)

    print(f"==> uploading to s3://{config.evidence_bucket}/{S3_PREFIX}")
    session.client("s3").upload_file(
        str(archive), config.evidence_bucket, S3_PREFIX
    )

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
            "VOUCH_MODE": "production",
            "VOUCH_STATE_TABLE": config.state_table,
            "VOUCH_EVIDENCE_BUCKET": config.evidence_bucket,
            # Prototype issuance key. Not a KMS/Secrets Manager service — see
            # docs/architecture/v2/AWS_STATUS.md, which says so plainly.
            "VOUCH_ISSUANCE_KEY": "vouch-demo-issuance-key",
            "AWS_REGION": config.region,
            # Real prompt-attack inspection on the deployed path. Absent this,
            # the runtime falls back to no detector rather than to a heuristic
            # pretending to be Guardrails.
            "VOUCH_GUARDRAIL_ID": os.environ.get("VOUCH_GUARDRAIL_ID", ""),
        },
    )
    version = response["agentRuntimeVersion"]
    print(f"    version {version}: {response['status']}")

    for _ in range(30):
        status = control.get_agent_runtime(agentRuntimeId=RUNTIME_ID)["status"]
        if status == "READY":
            print(f"    READY (version {version})")
            return 0
        if status.endswith("FAILED"):
            print(f"    {status}", file=sys.stderr)
            return 1
        time.sleep(10)

    print("    timed out waiting for READY", file=sys.stderr)
    return 1


def main() -> int:
    print(f"identity: {assert_vouch_identity()}")
    archive = build()
    if "--build-only" in sys.argv:
        return 0
    return deploy(archive)


if __name__ == "__main__":
    raise SystemExit(main())
