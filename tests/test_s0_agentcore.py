"""S0 — prove AgentCore is real.

invoke -> AgentCore Runtime -> Strands workflow -> response, with usable
logs/traces. Requires live AWS; skips (never silently passes) without it.

Run:  GATEHOUSE_MODE=bedrock AWS_PROFILE=<profile> pytest tests/test_s0_agentcore.py -v
"""

from __future__ import annotations

import json
import os

import pytest


def _bedrock_available() -> tuple[bool, str]:
    try:
        import boto3

        client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        model = os.environ.get("GATEHOUSE_BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
        client.converse(
            modelId=model,
            messages=[{"role": "user", "content": [{"text": "ok"}]}],
            inferenceConfig={"maxTokens": 5},
        )
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


AVAILABLE, REASON = _bedrock_available()
requires_bedrock = pytest.mark.skipif(not AVAILABLE, reason=f"Bedrock unavailable — {REASON}")


@requires_bedrock
def test_s0_local_runtime_entrypoint_runs_real_workflow():
    """The AgentCore entrypoint must run the same workflow the tests exercise."""
    from app import invoke

    response = invoke({"action": "evaluate_lot", "case_id": "S0-CASE", "lot_id": "LOT-1001"})

    assert response["ok"] is True
    assert response["lot_id"] == "LOT-1001"
    assert response["actor"]["disposition"] in ("RELEASE", "QUARANTINE", "INSUFFICIENT_EVIDENCE")
    assert response["verifier"]["outcome"] in ("VERIFIED", "REJECTED", "INSUFFICIENT_EVIDENCE")
    assert "authority" in response


@requires_bedrock
def test_s0_bedrock_model_returns_typed_structured_output():
    """A real model call must yield the typed contract the gate consumes."""
    os.environ["GATEHOUSE_MODE"] = "bedrock"
    from gatehouse.agents.roles import material_disposition_agent
    from gatehouse.fixtures import build_store
    from gatehouse.tools import EvalTools, ReadTools

    store = build_store()
    facts = EvalTools(store).evaluate_evidence_against_spec("LOT-1002")
    agent = material_disposition_agent(ReadTools(store))

    result = agent.run(facts)

    assert result["disposition"] in ("RELEASE", "QUARANTINE", "INSUFFICIENT_EVIDENCE")
    assert result["rationale"]
    assert isinstance(result["evidence_refs"], list)


@pytest.mark.skipif(
    not os.environ.get("GATEHOUSE_RUNTIME_ARN"),
    reason="no deployed AgentCore runtime (set GATEHOUSE_RUNTIME_ARN after `agentcore deploy`)",
)
def test_s0_deployed_runtime_invoke_returns_trace():
    """Full S0: invoke the deployed runtime and capture runtime + trace ids."""
    import boto3

    client = boto3.client(
        "bedrock-agentcore", region_name=os.environ.get("AWS_REGION", "us-east-1")
    )
    runtime_arn = os.environ["GATEHOUSE_RUNTIME_ARN"]

    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        payload=json.dumps(
            {"action": "evaluate_lot", "case_id": "S0-DEPLOYED", "lot_id": "LOT-1001"}
        ).encode(),
    )

    body = response["response"].read()
    parsed = json.loads(body)
    assert parsed["ok"] is True

    trace_id = response.get("traceId") or response["ResponseMetadata"]["RequestId"]
    print(f"\nS0 runtime : {runtime_arn}")
    print(f"S0 trace   : {trace_id}")
    assert trace_id
