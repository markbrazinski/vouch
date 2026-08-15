# Gatehouse — Vertical Smoke Test Report

**Date:** 2026-08-15
**Verdict:** **PASS WITH BLOCKERS**
**Suite:** 26 passed, 3 skipped (`pytest tests/`)

---

## Environment

| Component | Status |
|---|---|
| AgentCore CLI | `@aws/agentcore@0.27.0` (npm), verified |
| Strands Agents | `strands-agents==1.52.0`, `GraphBuilder` API confirmed |
| AgentCore SDK | `bedrock-agentcore==1.21.0` |
| Python | 3.12.12 |
| `agentcore validate` | **Valid** |
| `agentcore package` | **Succeeds** — `Gatehouse.zip`, 40.18 MB |
| `agentcore deploy --dry-run` | **Blocked** — `cloudformation:DescribeStacks` denied |
| Bedrock model invocation | **Blocked** — `AccessDeniedException` on all credentials |

**Correction to the commission's premise:** the AgentCore CLI is distributed as
`@aws/agentcore` on npm. The Python `bedrock-agentcore-starter-toolkit` also
ships an `agentcore` binary but self-deprecates and redirects to the npm CLI.
The npm CLI was used, and every flag in STEP 4 exists on it.

---

## S0–S9 results

| Test | PASS/FAIL | Starting state | Decision | Verifier | Tool | Ending state | Trace |
|---|---|---|---|---|---|---|---|
| **S0** | **BLOCKED** | — | — | — | — | — | no runtime; IAM denied |
| **S1** | **PASS** | `LOT-1001 RECEIVED`, usable 0 | `RELEASE` | `VERIFIED` | `release_lot` | `RELEASED`, usable +500 | local log |
| **S2** | **PASS** | `LOT-1002 RECEIVED` | `QUARANTINE` | `VERIFIED` | `quarantine_lot` | `QUARANTINED`, not usable | local log |
| **S3** | **PASS** | `C-417 READY` | `HOLD` (short 300) | deterministic calc | `hold_production_order` | `C-417 HOLD` | local log |
| **S4** | **PASS** | `C-417 HOLD`, sub stock 900 | `REFUSE` | `VERIFIED` | none | schedule unchanged | local log |
| **S5** | **PASS** | `C-418 @ 14:00` | `RESEQUENCE` | `VERIFIED` | `resequence_production_order` | `C-418 @ 08:00` | local log |
| **S6** | **PASS** | `LOT-1003 RECEIVED` | `INSUFFICIENT_EVIDENCE` | `INSUFFICIENT_EVIDENCE` | `create_qa_review` | `PENDING_QA` (not defective) | local log |
| **S7** | **PASS** | `LOT-1003 PENDING_QA` | `RELEASE` | `VERIFIED` | `release_lot` | `RELEASED`, same case | local log |
| **S8** | **PASS** | — | 7 authority records | complete | all | full ledger | local log |
| **S9** | **PASS** | — | invariants hold | — | — | — | local log |

Traces read "local log" because no AgentCore Runtime is deployed. The entrypoint
emits structured JSON logs (`bedrock_agentcore.app`) — the CloudWatch path — but
runtime and trace identifiers cannot be recorded until S0 unblocks.

### S9 invariants proven

- Verifier construction with `MutationTools` raises `PermissionViolation`.
- No agent holds mutation tools (asserted for all five).
- A mutation without a gate token raises `AuthorityError`.
- A token is bound to `(tool, target)` — reuse for another mutation raises.
- A hand-forged token is still bound, so forgery gains nothing.
- Disagreement fails safe, escalates to QA, and cites the verifier as cause.
- A forced verifier `REJECTED` blocks release end to end through the real workflow.
- Retries and replays are idempotent: inventory does not double-release, the
  schedule does not double-change.
- Illegal state transitions raise `TransitionError`.

### Test quality

Assertions were mutation-tested rather than trusted:

| Injected defect | Result |
|---|---|
| Gate ignores the verifier entirely | **2 tests fail** |
| Mutation authority guard removed | **3 tests fail** |
| Release idempotency removed | **1 test fails** |
| Governing spec loosened (hero lot passes) | **5 tests fail** |

The first mutation initially passed all 21 tests — `test_s9_disagreement_fails_safe`
asserted only "denied", which a gate that never consults the verifier also
satisfies. It now pins the deny reason and drives the real workflow. Recorded
because the weakness is the kind S9 exists to catch.

---

## Blockers

1. **Bedrock model invocation denied (blocks S0 and all live-model runs).**
   `bedrock:ListFoundationModels` succeeds; `Converse` returns `AccessDenied` on
   every model for both live identities. `default` and `brickweaver` sessions are
   expired; `onagain` has an invalid token.
   *Needs:* `bedrock:InvokeModel` on the inference-profile ARN, plus Anthropic
   model access enabled in the account/region.

2. **Deploy IAM insufficient.** `agentcore deploy --dry-run` fails on
   `cloudformation:DescribeStacks`. Deploy also needs CDK/CFN, ECR, IAM
   `PassRole`, and AgentCore runtime create.

3. **STEP 3 provisioning outputs never received.** No evidence bucket, table
   name, or region confirmation. `gate5-deployer` cannot `dynamodb:ListTables`,
   so they cannot be discovered. No resources were created, per the
   no-duplication rule. State is currently in-memory behind the interface a
   DynamoDB adapter implements.

4. **Deterministic baseline reproduces 4/4 agent dispositions** — see below.

---

## Deterministic baseline (ESCALATE condition)

`tests/test_deterministic_baseline.py` asserts the overlap rather than assuming
it. On the current fixtures, a ~6-line rules engine reproduces **every** actor
disposition, including the resumed S7 case.

This does not invalidate the architecture — the authority model, actor/verifier
separation, idempotency, and audit ledger are all independently valuable, and
S9 proves they hold. But **the agentic layer is not yet justified by these
fixtures.** The fixtures are clean, structured measurements, which is precisely
where rules win.

The agentic case has to be earned on inputs rules handle badly: unstructured or
inconsistently laid-out CoAs, ambiguous method naming, conflicting documents,
partially legible scans, supplier-specific phrasing. Until the eval set includes
those, "we need agents here" is unproven. Recommend this as the first task of
the next stage.

---

## Architecture notes

**Authority separation is structural, not advisory.** Mutation tools require an
`AuthorityToken`, minted only by a deterministic gate and bound to
`(case_id, tool, target)`. Agents never receive `MutationTools`; verifiers raise
on construction if handed one. A prompt cannot talk its way past this.

**No LLM does arithmetic.** Shortage, slot, and substitution-approval math run in
`EvalTools`. Agents receive computed facts.

**Evidence reconciliation is deterministic.** `evaluate_evidence_against_spec`
compares evidence to the governing plant spec and classifies each characteristic
as `IN_LIMITS` / `OUT_OF_LIMITS` / `METHOD_MISMATCH` / `NO_EVIDENCE`. This is
what separates S2 (wrong limit → defect) from S6 (wrong method → abstain), and
it is why no fixture outcome is hard-coded into a prompt.

**Absence of proof is not a defect finding.** S6 routes to `PENDING_QA`, never
`QUARANTINED`.

**Scope held.** No UI, no chat interface, no vector DB, no AgentCore Memory, no
Gateway, no OpenSearch, no RDS.

---

## Verdict: PASS WITH BLOCKERS

The architectural thesis holds where it could be tested. The full canonical
chain executes end to end, the authority model is enforced in code, and the
invariants survive mutation testing.

Not yet proven: S0 (no live runtime), agentic value over deterministic rules.

**Recommended before UI work:**
1. Grant Bedrock invoke + deploy IAM; land S0 and re-run S1–S7 on live models.
2. Build the adversarial fixture set that separates agents from rules.
3. Swap the in-memory store for the provisioned DynamoDB table.

Do not start product UI until (1) and (2) report.
