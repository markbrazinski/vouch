"""audit-2 F2 — the IAM half of the authority boundary, asserted statically.

The audit's finding: the one AgentCore runtime role holds broad write rights on
the whole table, Investigator/Verifier/workflow/Policy Engine share that
identity, and `consume()` validated nothing an attacker with those rights could
not also write.

The correction has two halves and this file tests one of them. The tests here
assert what the tracked policy DOCUMENTS say — they do not and cannot assert
that those documents are attached in the account. That is live qualification,
recorded separately in docs/architecture/v2/AWS_STATUS.md, and a green run here
is NOT evidence that AWS is configured.

The other half — the cryptographic one — is tested in test_aws_adapters.py and
is the load-bearing control: it holds even when an attacker HAS full PutItem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IAM = ROOT / "iam"
RUNTIME_POLICY = IAM / "agent_runtime_policy.json"
POLICY_ENGINE_POLICY = IAM / "policy_engine_policy.json"

CAPABILITY_WRITES = {
    "dynamodb:PutItem",
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
}


def _load(path: Path) -> dict:
    assert path.exists(), f"{path.name} is missing; the boundary is undocumented"
    return json.loads(path.read_text())


def _statements(document: dict, effect: str) -> list[dict]:
    return [s for s in document["Statement"] if s["Effect"] == effect]


def test_policy_documents_exist_and_are_valid_json():
    for path in (RUNTIME_POLICY, POLICY_ENGINE_POLICY):
        document = _load(path)
        assert document["Version"] == "2012-10-17"
        assert document["Statement"]


def test_agent_runtime_is_explicitly_denied_capability_row_writes():
    """F2: the decision-agent execution identity cannot write a CAP# item.

    An explicit Deny cannot be overridden by any Allow, so this holds even if
    another attached policy grants table-wide write access.
    """
    document = _load(RUNTIME_POLICY)
    denies = _statements(document, "Deny")

    matching = [
        statement
        for statement in denies
        if CAPABILITY_WRITES <= set(statement["Action"])
        and any(
            key.startswith("CAP#")
            for key in statement.get("Condition", {})
            .get("ForAnyValue:StringLike", {})
            .get("dynamodb:LeadingKeys", [])
        )
    ]
    assert matching, (
        "no explicit Deny on CAP# writes: the agent execution identity could "
        "forge a capability row"
    )


def test_agent_runtime_allows_no_unconditional_table_writes():
    """F2: every Allow that writes must be scoped by LeadingKeys.

    An unconditional `dynamodb:PutItem` on the table would make the Deny above
    the only thing standing between agent code and a forged CAP# row, and a
    condition typo would silently remove it.
    """
    document = _load(RUNTIME_POLICY)
    for statement in _statements(document, "Allow"):
        writes = CAPABILITY_WRITES & set(statement["Action"])
        if not writes:
            continue
        keys = (
            statement.get("Condition", {})
            .get("ForAllValues:StringLike", {})
            .get("dynamodb:LeadingKeys")
        )
        assert keys, f"{statement['Sid']} writes without a LeadingKeys condition"
        assert not any(key.startswith("CAP#") for key in keys), (
            f"{statement['Sid']} permits a capability-row write"
        )


def test_agent_runtime_cannot_delete_evidence():
    """Evidence originals must survive the identity that wrote them."""
    document = _load(RUNTIME_POLICY)
    denied = {
        action
        for statement in _statements(document, "Deny")
        for action in statement["Action"]
    }
    assert "s3:DeleteObject" in denied
    assert "s3:DeleteObjectVersion" in denied


def test_only_the_policy_engine_policy_allows_capability_row_writes():
    """F2: exactly one principal may create authority."""
    engine = _load(POLICY_ENGINE_POLICY)
    issuing = [
        statement
        for statement in _statements(engine, "Allow")
        if "dynamodb:PutItem" in statement["Action"]
        and any(
            key.startswith("CAP#")
            for key in statement.get("Condition", {})
            .get("ForAllValues:StringLike", {})
            .get("dynamodb:LeadingKeys", [])
        )
    ]
    assert issuing, "the Policy Engine policy grants no capability issuance"


def test_the_issuance_key_is_readable_only_by_the_policy_engine():
    """F2: signing authority must be inaccessible to agent/tool code."""
    engine = _load(POLICY_ENGINE_POLICY)
    runtime = _load(RUNTIME_POLICY)

    engine_actions = {
        action for s in _statements(engine, "Allow") for action in s["Action"]
    }
    assert "secretsmanager:GetSecretValue" in engine_actions

    runtime_actions = {
        action for s in _statements(runtime, "Allow") for action in s["Action"]
    }
    assert "secretsmanager:GetSecretValue" not in runtime_actions
    assert "kms:Decrypt" not in runtime_actions


def test_policy_documents_carry_no_account_identifiers():
    """Account ids are targeting information; they live in provisioning.json."""
    import re

    for path in (RUNTIME_POLICY, POLICY_ENGINE_POLICY):
        text = path.read_text()
        assert not re.search(r"\b\d{12}\b", text), f"{path.name} leaks an account id"


def test_the_iam_readme_does_not_claim_the_policies_are_attached():
    """Honesty: a tracked document is not applied infrastructure."""
    readme = (IAM / "README.md").read_text().lower()
    assert "not applied infrastructure" in readme or "tracked source" in readme
    assert "aws_status" in readme
