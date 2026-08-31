# Vouch

Manufacturing authority control plane on Strands Agents + Amazon Bedrock AgentCore.

**Make every material prove it belongs in production — then keep the factory
moving when one doesn't.**

Vouch decides what can safely enter production, blocks what cannot, and
repairs the day when reality changes. Its output is not advice: it is an
authorized state change, a refusal, or an escalation — each with an audit record.

---

## The architectural line (V2)

> **The model decides what governs and what applies. Deterministic code decides
> what happens.**

Two model-backed agents own the genuinely interpretive work — which
specification revision governs a lot, and whether each piece of evidence applies
to it. Everything consequential is deterministic: disposition, policy,
capability issuance, mutation, consequences, recovery.

```
supplier evidence (assume hostile)
  → security boundary → immutable original → parse → canonical claims
  → provenance + trust labels → frozen snapshot
      ├─→ Applicability Investigator   [model, scoped read-only tools]
      └─→ Independent Verifier          [model, no brief, no precedent]
  → deterministic reconcile → basis checks → disposition → policy
  → capability record → atomic mutation → DecisionRecord
  → consequences → deterministic recovery
```

### The core invariant

> A model can never express a disposition, and only the Policy Engine can create
> authority.

`EvidenceApplicabilityBrief` has no disposition field, so the vocabulary itself
forbids it. Mutation requires an issuer-authenticated capability record, bound
to one target, one action, one DecisionRecord and one observed state version,
consumed by a single atomic conditional write.

---

## Quickstart

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
    strands-agents strands-agents-tools bedrock-agentcore \
    bedrock-agentcore-starter-toolkit pytest boto3

.venv/bin/python -m pytest tests/ -q        # 78 passed
```

Tests run offline against scripted reasoners, so CI exercises the full
architecture — tools, reconciliation, capability security, concurrency — without
model access.

Run the pipeline:

```python
from vouch.v2.workflow import VouchV2
from vouch.v2.fixtures import build_corpus, COA_HERO

corpus = build_corpus()
outcome = VouchV2(corpus).evaluate_lot("LOT-1002", documents=[{"raw": COA_HERO}])
print(outcome.disposition, outcome.record.basis.revision)
# QUARANTINE C   — the COA cites rev B and says CONFORMS; rev C governs by receipt date
```

Run the load-bearing evaluation against live models:

```bash
AWS_PROFILE=gatehouse VOUCH_V2_MODE=bedrock \
    python scripts/run_v2_gate.py --repeats 1
```

---

## Layout

| Path | Purpose |
|---|---|
| `AGENTS.md` / `CLAUDE.md` | Operating contract. Byte-identical, sync-enforced. |
| `src/vouch/v2/contracts.py` | Brief schema, trust labels, authority validators, failure taxonomy |
| `src/vouch/v2/corpus.py` | Authoritative objects with currency/supersession/scope semantics |
| `src/vouch/v2/evidence.py` | S1–S7 hostile-evidence boundary |
| `src/vouch/v2/tools.py` | Scoped read-only Strands tools |
| `src/vouch/v2/agents.py` | Investigator, Verifier, confined extractor |
| `src/vouch/v2/reconcile.py` | Deterministic reconciliation + basis checks |
| `src/vouch/v2/disposition.py` | Deterministic Disposition Engine |
| `src/vouch/v2/authority.py` | Capability records, Policy Engine, atomic mutation |
| `src/vouch/v2/consequences.py` | Readiness, causal links, deterministic recovery |
| `src/vouch/v2/workflow.py` | The deterministic state machine |
| `src/vouch/v2/evalcases.py` | Segmented evaluation corpus |
| `src/vouch/adversarial.py` | V1 adversarial set (kept and promoted) |
| `tests/v2/` | Capability, security red-team, pipeline, evaluation integrity |

---

## Status

**`V2_AGENT_LOAD_BEARING_GATE_FAILED`.**

The architecture is implemented and its security properties hold locally: 78
tests pass, covering all ten capability properties and all fifteen red-team
attacks — including proof that injected supplier documents are inert *with the
prompt-attack detector disabled*, because detection is a layer and not the
boundary.

But on the D21 gate, the agents do **not** materially beat a strong
deterministic basis-selector on the `AGENT_VALUABLE` slice (A 21/22 vs B 20/22,
live Nova Pro). Under the arbitration contract §26 this is a stop-and-report
condition: no precedent work, no frontend redesign.

Two further limits, stated plainly:

- **Local-first.** S3 Object Lock, Bedrock Guardrails, DynamoDB conditional
  writes and AgentCore deployment are built against real interfaces and proven
  by local equivalents. That is not evidence the AWS controls behave as
  specified. Live qualification is required before any Milestone 1 claim.
- **The evaluation corpus is unreviewed.** It was authored alongside the code it
  measures, and case design materially determines the outcome.

## Contributing

`AGENTS.md` is canonical and must stay byte-identical to `CLAUDE.md`:

```bash
python scripts/check_agent_docs_sync.py --fix
```
