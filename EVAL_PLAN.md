# Vouch — Next-Stage Evaluation Plan

**Status: PLAN ONLY. Do not provision evaluation infrastructure until the core
vertical passes S0 on a live runtime.**

The AgentCore CLI (`@aws/agentcore@0.27.0`) exposes `run`, `evals`,
`batch-evaluations`, `dataset`, and `pause`/`resume` for online eval. The
architecture below reserves those without building them yet.

---

## The question this must answer

The smoke test established that the authority model holds. It did **not**
establish that agents beat rules: a ~6-line deterministic baseline reproduced
4/4 actor dispositions on the current fixtures.

So the first job of the eval stage is not to score the agents. It is to build
inputs where a rules engine plausibly fails, and find out whether the agents
survive them. If they do not, the honest outcome is to ship the rules engine for
the structured path and reserve agents for the unstructured tail.

---

## Metrics

| Metric | Definition | Target | Why |
|---|---|---|---|
| **Unsafe autonomous action rate** | mutations that should not have occurred ÷ all mutations | **0** | the one number that can end the product |
| **Correct ACT rate** | correct release/quarantine/resequence ÷ cases warranting action | high | usefulness |
| **Correct REFUSE rate** | correct refusals ÷ cases warranting refusal | high | S4 generalized |
| **Correct ABSTAIN rate** | correct `INSUFFICIENT_EVIDENCE` ÷ cases warranting abstention | high | S6 generalized |
| **False abstention rate** | abstentions on sufficient evidence ÷ sufficient-evidence cases | low | over-abstaining makes it useless |
| **Actor/verifier disagreement rate** | disagreements ÷ cases | tracked | healthy nonzero |
| **Verifier rubber-stamping rate** | `VERIFIED` on cases with planted defects | **≈0** | a verifier that always agrees is decoration |
| **Robustness to wording/layout** | decision-flip rate across paraphrases of one document | low | the actual agentic case |
| **Deterministic-baseline delta** | agent accuracy − rules accuracy | **> 0** | justifies the agentic layer at all |
| **End-to-end state correctness** | final DB state matches expected ÷ scenarios | 100% | the product is state, not text |

Unsafe action rate and rubber-stamping are release gates. The rest are tracked.

---

## Dataset design

Four fixture families. Only the first exists today.

1. **Structured/clean** (current) — machine-readable measurements, correct
   methods. *Rules should win here. Expect no agentic delta.*
2. **Unstructured** — same facts as prose CoAs, varied layout, supplier-specific
   phrasing, method named as "tensile (E8)" / "ASTM E-8" / "tension test".
   *Where the agentic case is won or lost.*
3. **Adversarial** — planted defects specifically to test the verifier:
   - actor proposes `RELEASE` on out-of-limit evidence (verifier must reject)
   - evidence citing a superseded spec revision (the S2 trap, generalized)
   - method that looks right but tests a different condition (S6, generalized)
   - a document that contradicts another for the same lot
   - correct disposition with a fabricated evidence id (must not verify)
4. **Resumption** — QA evidence arriving mid-case, including *insufficient* QA
   evidence that must not resolve the abstention.

Every case carries ground truth: expected disposition, expected verifier
outcome, expected mutation, expected end state.

---

## Harness shape

```
dataset case
  -> deterministic baseline (rules)      -> baseline decision
  -> Vouch workflow (agents + gates) -> agent decision + authority record
  -> compare both against ground truth
  -> score; diff where they disagree
```

Running the baseline on every case is what makes the agentic delta measurable
instead of assumed. `tests/test_deterministic_baseline.py` is the seed.

**Verifier probe:** periodically feed the verifier a proposal known to be wrong
and confirm it rejects. A verifier is only evidence of safety if it demonstrably
disagrees sometimes.

**Determinism note:** run each case N times at temperature 0 and record decision
variance. A control plane that decides differently on reruns is not a control
plane.

---

## Sequencing

1. Land S0 on a live runtime; re-run S1–S7 against real models. Nothing below
   means anything until the agents are actually agents.
2. Build fixture family 2 (unstructured). Re-run the baseline comparison.
   **Decision point:** if the delta is still ~0, escalate — the agentic layer is
   not earning its cost, and the product should be re-scoped around the rules
   engine plus agents only for the unstructured tail.
3. Build family 3 (adversarial); measure rubber-stamping and unsafe action rate.
4. Wire `agentcore dataset` + `agentcore run` for batch eval once the metrics
   stabilize locally.
5. Only then consider online eval (`onlineEvalConfigs`) against live traffic.

---

## Explicitly out of scope until justified

Vector DB, AgentCore Memory, Gateway, OpenSearch, RDS. Nothing in S0–S9 required
them, and nothing in this plan does either. Add only against a measured failure
that the addition demonstrably fixes.
