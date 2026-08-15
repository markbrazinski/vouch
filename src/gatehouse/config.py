"""Provisioning configuration.

Values come from provisioning.json (gitignored, account-specific) with
environment-variable overrides. Nothing here is committed, and no credentials
live in the repo — those come from the ambient AWS session/profile.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = ROOT / "provisioning.json"


# Gatehouse baseline model. AGENTS.md: do not silently substitute another model.
NOVA_PRO = "us.amazon.nova-pro-v1:0"

# Gatehouse development must run as this identity, in this region.
# The account id is deliberately NOT hard-coded here — it is account-specific
# targeting information and lives only in the gitignored provisioning manifest.
REQUIRED_PROFILE = "gatehouse"
REQUIRED_USER = "gatehouse-dev"
REQUIRED_REGION = "us-east-1"


@dataclass(frozen=True)
class Config:
    account_id: str = ""
    region: str = REQUIRED_REGION
    evidence_bucket: str = ""
    state_table: str = ""
    runtime_role_arn: str = ""
    bedrock_model_id: str = NOVA_PRO
    aws_profile: str = ""
    mode: str = "local"  # local | bedrock

    @property
    def is_bedrock(self) -> bool:
        return self.mode == "bedrock"

    def model_for(self, role: str) -> str:
        """Per-role model, so evals can vary actor and verifier independently.

        GATEHOUSE_MODEL_ACTOR / GATEHOUSE_MODEL_VERIFIER override the baseline.
        Both default to Nova Pro.
        """
        override = os.environ.get(f"GATEHOUSE_MODEL_{role.upper()}")
        return override or self.bedrock_model_id


def _manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text())
    except json.JSONDecodeError:
        return {}


class IdentityError(RuntimeError):
    """Gatehouse is running under the wrong AWS identity."""


def assert_gatehouse_identity(profile: str | None = None) -> str:
    """Fail loudly if we are not gatehouse-dev.

    Borrowing another project's profile silently produces misleading capability
    results — that is exactly how Nova Pro looked 'blocked' when the real
    problem was a foreign identity. Verify before any live run.
    """
    import boto3

    profile = profile or os.environ.get("AWS_PROFILE") or REQUIRED_PROFILE
    session = boto3.Session(profile_name=profile, region_name=REQUIRED_REGION)
    identity = session.client("sts").get_caller_identity()
    arn = identity["Arn"]

    expected_account = load().account_id
    account_ok = not expected_account or identity["Account"] == expected_account
    user_ok = arn.endswith(f":user/{REQUIRED_USER}")

    if not (account_ok and user_ok):
        raise IdentityError(
            f"Gatehouse requires IAM user '{REQUIRED_USER}' (profile "
            f"'{REQUIRED_PROFILE}'), but profile '{profile}' resolved to {arn}. "
            f"Refusing to run under another project's credentials."
        )
    return arn


@lru_cache(maxsize=1)
def load() -> Config:
    m = _manifest()
    env = os.environ.get

    return Config(
        account_id=env("AWS_ACCOUNT_ID") or m.get("account_id", ""),
        region=env("AWS_REGION") or m.get("region") or "us-east-1",
        evidence_bucket=env("GATEHOUSE_EVIDENCE_BUCKET") or m.get("evidence_bucket", ""),
        state_table=env("GATEHOUSE_STATE_TABLE") or m.get("state_table", ""),
        runtime_role_arn=env("GATEHOUSE_RUNTIME_ROLE_ARN") or m.get("runtime_role_arn", ""),
        bedrock_model_id=(
            env("GATEHOUSE_BEDROCK_MODEL_ID")
            or m.get("bedrock_model_id")
            or "us.anthropic.claude-sonnet-4-6"
        ),
        aws_profile=env("AWS_PROFILE") or m.get("aws_profile", ""),
        mode=(env("GATEHOUSE_MODE") or "local").lower(),
    )
