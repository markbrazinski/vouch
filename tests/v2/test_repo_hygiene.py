"""No account-specific targeting information in tracked files.

An AWS account id is not a secret in the credential sense, but it is targeting
information (AGENTS.md §13) and this repository is headed for a public
submission freeze. `scripts/hero_acceptance.py` carried the literal account id
in the deployed runtime ARN; it now composes that ARN from `vouch.config`,
which reads the gitignored provisioning manifest.

This test reads what git actually TRACKS rather than what is on disk, because
the untracked working files (provisioning.json, build outputs, local traces)
are exactly where account-specific values are allowed to live.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Any 12-digit run is a candidate AWS account id.
ACCOUNT_ID = re.compile(r"\b\d{12}\b")

#: Numbers that are 12 digits by coincidence rather than by being an account id.
ALLOWED = {
    "000000000000",  # canonical placeholder
    "123456789012",  # AWS documentation example account
}

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".yaml", ".yml",
    ".toml", ".txt", ".html", ".css", ".sh", ".cfg", ".ini",
}


def _tracked_text_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout
    return [
        ROOT / name
        for name in out.split("\0")
        if name and Path(name).suffix in TEXT_SUFFIXES
    ]


def test_no_aws_account_id_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for line_no, line in enumerate(body.splitlines(), 1):
            for candidate in ACCOUNT_ID.findall(line):
                if candidate not in ALLOWED:
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{line_no} -> {candidate}"
                    )

    assert not offenders, (
        "account-specific targeting information is tracked; move it to "
        "provisioning.json or an environment variable:\n  "
        + "\n  ".join(offenders)
    )


def test_hero_acceptance_composes_the_runtime_arn() -> None:
    """The script must still resolve a real ARN, not just have lost the literal."""
    source = (ROOT / "scripts" / "hero_acceptance.py").read_text()
    assert "runtime_arn()" in source, "the ARN is no longer composed at call time"
    assert "VOUCH_RUNTIME_ARN" in source, "no override for a different deployment"
    assert not ACCOUNT_ID.search(source), "an account id came back"


#: Real AWS credential material. The account-id regex above cannot see these:
#: an STS session token is base64, so a real account id inside one is invisible
#: to a `\d{12}` scan. That is exactly how a live presigned S3 URL — captured
#: verbatim into a frontend test fixture — carried this account's id into
#: tracked source and past the check above.
CREDENTIAL_PATTERNS = (
    # Real access-key ids. AKIAEXAMPLE / ASIAEXAMPLE-style placeholders are
    # shorter than the 16-char real form and so do not match.
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    # A signed URL is only dangerous when it carries a real session token.
    re.compile(r"X-Amz-Security-Token=[A-Za-z0-9%+/=]{40,}"),
)


def test_no_real_aws_credentials_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _tracked_text_files():
        try:
            body = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        for line_no, line in enumerate(body.splitlines(), 1):
            for pattern in CREDENTIAL_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
                    break

    assert not offenders, (
        "real AWS credential material is tracked. A captured presigned URL is "
        "the usual cause: scrub the query string down to placeholders, keeping "
        "only the host/key/versionId shape the fixture needs:\n  "
        + "\n  ".join(offenders)
    )
