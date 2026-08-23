# Vouch

Manufacturing authority control plane on Strands Agents + Amazon Bedrock AgentCore.

**Make every material prove it belongs in production — then keep the factory
moving when one doesn't.**

Vouch decides what can safely enter production, blocks what cannot, and
repairs the day when reality changes. Its output is not advice: it is an
authorized state change, a refusal, or an escalation — each with an audit record.

---

## The core invariant

> A proposal never mutates state. Only a deterministic authority gate mutates
> state, and only after independent verification passes.

This is enforced structurally, not by prompt. Mutation tools require an
`AuthorityToken` that only a gate can mint, bound to `(case_id, tool, target)`.
Agents are never given mutation tools; a verifier handed one raises at
construction time.

```
evidence → actor proposes → independent verifier → deterministic gate
        → mutation (or refusal) → authority record
```

---

## Quickstart

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
    strands-agents strands-agents-tools bedrock-agentcore \
    bedrock-agentcore-starter-toolkit pytest boto3

.venv/bin/python -m pytest tests/ -q        # 26 passed, 3 skipped
```

The 3 skips are S0, which needs live Bedrock access.

Run the vertical through the AgentCore entrypoint:

```bash
cd app/Gatehouse && python -c "
import main
print(main.invoke({'action':'evaluate_lot','case_id':'DEMO','lot_id':'LOT-1002'}))"
```

---

## Layout

| Path | Purpose |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | Operating contract. Byte-identical, sync-enforced. |
| `src/vouch/state.py` | Entities, state machines, authoritative store |
| `src/vouch/tools.py` | Read / deterministic-eval / gated-mutation tools |
| `src/vouch/gates.py` | Deterministic authority gates (no LLM) |
| `src/vouch/agents/` | Actor and verifier roles, permission enforcement |
| `src/vouch/workflow.py` | The canonical chain |
| `src/vouch/fixtures.py` | Smoke-test world |
| `app/Gatehouse/main.py` | AgentCore Runtime entrypoint (typed, not chat) |
| `agentcore/` | CLI config + CDK |
| `SMOKE_TEST_REPORT.md` | S0–S9 results and blockers |
| `EVAL_PLAN.md` | Next-stage eval design |

---

## Status

**PASS WITH BLOCKERS.** S1–S9 pass; S0 is blocked on Bedrock IAM. A deterministic
baseline currently reproduces 4/4 agent dispositions, so the agentic layer is not
yet justified by the existing fixtures. See `SMOKE_TEST_REPORT.md`.

## Deploy

```bash
python scripts/stage_runtime.py     # stage src/vouch into the bundle
agentcore validate
agentcore deploy --dry-run
agentcore deploy
```

Requires Bedrock invoke permissions, CloudFormation/CDK deploy rights, and the
provisioned evidence bucket + DynamoDB table.

## Contributing

`AGENTS.md` is canonical and must stay byte-identical to `CLAUDE.md`:

```bash
python scripts/check_agent_docs_sync.py --fix
```
