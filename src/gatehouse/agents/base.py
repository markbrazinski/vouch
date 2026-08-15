"""Agent construction with structurally-enforced permission separation.

Two things are enforced here, in code, not by prompt instruction:

  1. A verifier constructed with any mutation-capable tool raises immediately.
  2. No agent receives MutationTools at all. Mutations happen only in the
     authority gate path, which agents cannot reach.

The model layer is swappable: `bedrock` runs the real Strands agent against
Bedrock; `local` runs a deterministic scripted model so the graph, gates, and
state machine are testable without model access. Both paths return the same
typed structured output, so the smoke test exercises identical control flow.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable

from ..tools import MutationTools, ReadTools


class PermissionViolation(PermissionError):
    """A verifier was handed a tool it must never hold."""


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str  # "actor" | "verifier" | "evaluator"
    system_prompt: str
    output_keys: tuple[str, ...]


def assert_readonly_toolset(agent_name: str, tools: Any) -> None:
    """Hard error if a verifier holds mutation capability."""
    if isinstance(tools, MutationTools):
        raise PermissionViolation(f"verifier {agent_name} must not receive MutationTools")
    for attr in ("release_lot", "quarantine_lot", "hold_production_order",
                 "resequence_production_order", "create_qa_review"):
        if hasattr(tools, attr):
            raise PermissionViolation(
                f"verifier {agent_name} must not hold mutation tool '{attr}'"
            )


def mode() -> str:
    # Read env directly so tests can flip modes without a cache reset.
    return os.environ.get("GATEHOUSE_MODE", "local").lower()


def model_id(role: str = "actor") -> str:
    """Baseline is Nova Pro; per-role overrides exist for eval comparisons."""
    from ..config import load

    return os.environ.get("GATEHOUSE_BEDROCK_MODEL_ID") or load().model_for(role)


class GatehouseAgent:
    """One Strands agent node.

    In `bedrock` mode this wraps a real strands.Agent with a BedrockModel and
    asks for typed JSON output. In `local` mode it calls a scripted reasoner
    with the same inputs and output contract.
    """

    def __init__(
        self,
        spec: AgentSpec,
        read_tools: ReadTools,
        local_fn: Callable[[dict], dict],
    ) -> None:
        self.spec = spec
        self.local_fn = local_fn

        if spec.role == "verifier":
            assert_readonly_toolset(spec.name, read_tools)

        # Never hand any agent mutation capability.
        self.tools = read_tools
        self._strands_agent = None

    # -- bedrock path -----------------------------------------------------
    def _build_strands_agent(self):
        if self._strands_agent is not None:
            return self._strands_agent

        from strands import Agent
        from strands.models import BedrockModel

        from ..config import load

        # ponytail: streaming off by default. Gatehouse consumes one typed JSON
        # object per call, so streaming buys nothing, and InvokeModelWithResponseStream
        # is a separate IAM action that some runtime roles are not granted.
        streaming = os.environ.get("GATEHOUSE_BEDROCK_STREAMING", "false").lower() == "true"

        self._strands_agent = Agent(
            model=BedrockModel(
                model_id=model_id(self.spec.role),
                region_name=load().region,
                streaming=streaming,
            ),
            system_prompt=self.spec.system_prompt,
            name=self.spec.name,
            tools=[],  # facts are passed in; no mutation surface, by design
        )
        return self._strands_agent

    def run(self, facts: dict) -> dict:
        """Return typed structured output. Same contract in both modes."""
        if mode() == "bedrock":
            agent = self._build_strands_agent()
            prompt = (
                "Authoritative facts (JSON). Reason only from these. "
                "Do not invent specifications, inventory, substitutions, or qualification.\n\n"
                f"{json.dumps(facts, indent=2, default=str)}\n\n"
                f"Respond with ONLY a JSON object containing keys: {list(self.spec.output_keys)}."
            )
            raw = str(agent(prompt))
            return self._parse(raw)
        return self.local_fn(facts)

    def _parse(self, raw: str) -> dict:
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end == -1:
            raise ValueError(f"{self.spec.name}: no JSON object in model output: {raw[:200]}")
        parsed = json.loads(raw[start : end + 1])
        missing = [k for k in self.spec.output_keys if k not in parsed]
        if missing:
            raise ValueError(f"{self.spec.name}: output missing keys {missing}")
        return self._coerce_enums(parsed)

    def _coerce_enums(self, parsed: dict) -> dict:
        """Constrain model output to the declared vocabulary, failing safe.

        Observed on Nova Pro: a verifier returned the actor's verb ("REFUSE")
        instead of a VerifierOutcome. An out-of-vocabulary value must never
        crash the workflow or be silently coerced to a permissive one — the
        safe reading of an unintelligible verdict is INSUFFICIENT_EVIDENCE,
        which denies mutation and escalates to QA.
        """
        from ..state import Disposition, RecoveryAction, VerifierOutcome

        vocab = {
            "outcome": (VerifierOutcome, VerifierOutcome.INSUFFICIENT_EVIDENCE),
            "disposition": (Disposition, Disposition.INSUFFICIENT_EVIDENCE),
            "action": (RecoveryAction, RecoveryAction.ESCALATE),
        }
        for key, (enum_cls, fallback) in vocab.items():
            if key not in parsed:
                continue
            value = str(parsed[key]).strip().upper()
            try:
                parsed[key] = enum_cls(value).value
            except ValueError:
                parsed[key] = fallback.value
                note = (
                    f"[gatehouse] {self.spec.name} returned out-of-vocabulary "
                    f"{key}={value!r}; failing safe to {fallback.value}."
                )
                for field in ("rationale", "reason"):
                    if field in parsed:
                        parsed[field] = f"{note} {parsed[field]}"
                        break
                else:
                    parsed["rationale"] = note
        return parsed
