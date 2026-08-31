"""Vouch provisioning configuration.

The single place where LEGACY AWS COMPATIBILITY IDENTIFIERS live. Product code
uses logical names (VOUCH_STATE_TABLE, VOUCH_EVIDENCE_BUCKET,
VOUCH_RUNTIME_ROLE_ARN); their VALUES currently point at resources still named
`gatehouse-*` from before the rename.

Those resources are deliberately NOT renamed: renaming or recreating live AWS
infrastructure for cosmetic consistency would risk the working deployment. They
stay until Vouch passes the adversarial product gate.

Values come from provisioning.json (gitignored, account-specific) with
environment-variable overrides. No credentials live in the repo — those come
from the ambient AWS session/profile.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST = ROOT / "provisioning.json"


# Vouch baseline model. AGENTS.md: do not silently substitute another model.
NOVA_PRO = "us.amazon.nova-pro-v1:0"

# --- LEGACY AWS COMPATIBILITY IDENTIFIERS -------------------------------
# Pre-rename names for live infrastructure. Intentionally unchanged; see the
# infrastructure compatibility note in AGENTS.md. Referenced ONLY from here.
LEGACY_AWS_PROFILE = "gatehouse"
LEGACY_IAM_USER = "gatehouse-dev"
LEGACY_RUNTIME_ROLE_NAME = "GatehouseAgentCoreRuntimeRole"
LEGACY_AGENTCORE_RUNTIME_NAME = "Gatehouse"

# Vouch development must run as this identity, in this region.
# The account id is deliberately NOT hard-coded here — it is account-specific
# targeting information and lives only in the gitignored provisioning manifest.
REQUIRED_PROFILE = LEGACY_AWS_PROFILE
REQUIRED_USER = LEGACY_IAM_USER
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

        VOUCH_MODEL_ACTOR / VOUCH_MODEL_VERIFIER override the baseline.
        Both default to Nova Pro.
        """
        override = env_var(f"MODEL_{role.upper()}")
        return override or self.bedrock_model_id


def env_var(name: str, default: str | None = None) -> str | None:
    """Read VOUCH_<name>, falling back to the pre-rename GATEHOUSE_<name>.

    The live AgentCore runtime was deployed with GATEHOUSE_* variables set. The
    fallback keeps that deployment working until it is redeployed, so the rename
    cannot break running infrastructure.
    """
    return os.environ.get(f"VOUCH_{name}") or os.environ.get(f"GATEHOUSE_{name}") or default


def _manifest() -> dict:
    if not MANIFEST.exists():
        return {}
    try:
        return json.loads(MANIFEST.read_text())
    except json.JSONDecodeError:
        return {}


class IdentityError(RuntimeError):
    """Vouch is running under the wrong AWS identity."""


def assert_vouch_identity(profile: str | None = None) -> str:
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
            f"Vouch requires IAM user '{REQUIRED_USER}' (profile "
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
        evidence_bucket=env_var("EVIDENCE_BUCKET") or m.get("evidence_bucket", ""),
        state_table=env_var("STATE_TABLE") or m.get("state_table", ""),
        runtime_role_arn=env_var("RUNTIME_ROLE_ARN") or m.get("runtime_role_arn", ""),
        # No silent substitution (AGENTS.md model policy, arbitration D18).
        # V1 fell back to Sonnet here whenever the manifest lacked the key, so an
        # auditor could not tell which model made a decision. The baseline is now
        # explicit; overriding it is a deliberate act that the DecisionRecord
        # records.
        bedrock_model_id=(
            env_var("BEDROCK_MODEL_ID") or m.get("bedrock_model_id") or NOVA_PRO
        ),
        aws_profile=env("AWS_PROFILE") or m.get("aws_profile", ""),
        mode=(env_var("MODE") or "local").lower(),
    )
