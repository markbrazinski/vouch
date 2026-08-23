# Vouch — Agent Operating Contract

**Product: Vouch** (formerly Gatehouse)

> **CANONICAL FILE.** `AGENTS.md` is the source of truth. `CLAUDE.md` MUST be a
> byte-for-byte copy. They are deliberately NOT symlinked. Any change to one MUST
> be mirrored to the other in the same commit.
>
> Sync is enforced by `scripts/check_agent_docs_sync.py` and by
> `tests/test_agent_docs_sync.py`. Both fail the build if the files differ.
>
> To resync after editing `AGENTS.md`:
> `python scripts/check_agent_docs_sync.py --fix`

---

## 1. Thesis

Factories run on a plan. One incoming material, missing test, or supplier
exception can make that plan wrong in minutes.

**Vouch decides what can safely enter production, blocks what cannot, and
repairs the day when reality changes.**

Product promise:

**Make every material prove it belongs in production — then keep the factory
moving when one doesn't.**

Vouch is a manufacturing **authority control plane**. Its output is not
advice. Its output is an authorized state change, a refusal, or an escalation —
each backed by an auditable record.

---

## 2. Canonical demo chain

This chain is the contract. Do not silently change it.

```
incoming lot
  → evidence assembled
  → Material Disposition Agent proposes disposition
  → independent Specification Verifier checks it
  → deterministic authority gate
  → lot state mutation
  → usable inventory changes
  → Production Readiness evaluates the affected production order
  → production HOLD if necessary
  → Recovery Agent evaluates safe recovery
  → independent Recovery Verifier
  → deterministic authority gate
  → schedule mutation or refusal
  → QA escalation where evidence is insufficient
  → new evidence resumes the same case
```

---

## 3. Architecture

**In scope**

- Python
- Strands Agents
- Strands `GraphBuilder` (or equivalent explicit graph orchestration)
- Amazon Bedrock
- Amazon Bedrock AgentCore Runtime
- AgentCore / CloudWatch observability
- DynamoDB for authoritative operating state
- S3 for evidence artifacts

**Explicitly OUT of scope until the smoke test proves a need**

- vector database
- AgentCore Memory
- AgentCore Gateway
- OpenSearch
- RDS
- full ERP / MRP implementation

**Authoritative manufacturing truth lives in application state, never in agent
memory.** An agent's context is an input to a proposal, never the record of what
is true. If the state store and an agent disagree, the state store wins.

### Model policy

- **Baseline runtime model: Amazon Nova Pro** (`us.amazon.nova-pro-v1:0`),
  via Bedrock in `us-east-1`. This is the smoke-test baseline for both actor and
  verifier roles.
- **Do not silently substitute Claude Sonnet or any other model.** If Nova Pro
  fails or is unavailable, that is a BLOCKER to report, not a reason to swap.
  A model change is a decision the product lead makes, never a workaround.
- Model configuration must not be hard-coded through application logic. It is
  read from `provisioning.json` / environment via `vouch.config`, and each
  role's model must stay independently overridable so evals can compare:
  Nova Pro actor + Nova Pro verifier; Nova Pro actor + alternate verifier;
  deterministic baseline.
- Future model choice is earned through evaluation evidence, not preference.

### Authority modes

Every consequential decision resolves to exactly one of:

- **ACT** — the evidence supports a state change.
- **REFUSE** — the evidence affirmatively does not support it.
- **ABSTAIN / INSUFFICIENT_EVIDENCE** — the evidence cannot establish an answer.

Never force an autonomous answer when the evidence cannot establish one.
Abstention is a first-class outcome, not a failure.

One AgentCore Runtime hosts the Vouch Strands workflow used by the smoke
test. The deployed runtime must be the same code path the tests exercise.

---

## 4. Authority model

The central invariant:

> **A proposal never mutates state. Only a deterministic authority gate mutates
> state, and only after independent verification passes.**

Four-stage pipeline for every consequential decision:

1. **Actor agent** reads authoritative evidence and proposes a typed
   disposition. It has read tools and no mutation tools during proposal.
2. **Verifier agent** independently examines the source evidence and the
   proposal. It has read tools only. It never receives mutation tools.
3. **Deterministic authority gate** — plain Python, no LLM. It compares actor
   and verifier outcomes against a fixed truth table and decides whether a
   mutation is authorized.
4. **Mutation tool** executes only when the gate authorizes it. Every mutation
   is idempotent and writes an authority record.

Gate truth table (deny by default):

| Actor | Verifier | Result |
|---|---|---|
| `RELEASE` | `VERIFIED` | allow `release_lot` |
| `QUARANTINE` | `VERIFIED` | allow `quarantine_lot` |
| any | `REJECTED` | deny, fail safe, QA case |
| any | `INSUFFICIENT_EVIDENCE` | deny, QA case |
| `INSUFFICIENT_EVIDENCE` | any | deny, QA case |
| actor ≠ verifier subject | any | deny |

Disagreement always fails safe. "Fail safe" means: no mutation, and the lot is
NOT marked defective merely because evidence is missing. Absence of evidence is
an escalation, not a defect finding.

---

## 5. Actor / verifier permissions

Enforced in code, not by prompt instruction:

- Verifier agents MUST be constructed with a read-only toolset. Passing a
  mutation tool to a verifier is a hard error, not a warning.
- Actor agents MUST NOT be able to call mutation tools directly. Mutations are
  invoked by the gate after authorization.
- Mutation tools MUST require an authority token/record proving gate approval.
  A direct call without gate authorization must raise.
- These invariants have explicit tests (S9). They are the product, not a
  detail.

---

## 6. Evidence and data rules

- Evidence is **referenced**, never invented. An agent may cite
  `evidence_id` + S3 reference. It may not generate a substitute for a document
  it did not read.
- Agents MUST NOT invent approved substitutions, specifications, supplier
  qualification status, inventory levels, or schedule facts. These come from
  authoritative read tools only.
- **LLMs never perform deterministic arithmetic.** Inventory math, shortage
  math, and schedule slot math run in Python tools. An agent receives computed
  facts and reasons about their consequences.
- Hidden chain-of-thought is NOT an audit artifact. The audit record is the
  typed structured output plus evidence references plus the actual state
  change.
- Fixture expected outcomes MUST NOT be hard-coded into agent prompts. The
  agent must derive the answer from evidence, or the test proves nothing.

---

## 7. State model (minimum viable)

Only what the canonical vertical requires. No broader ERP model.

- **Material** — `material_id`, `name`, `governing_spec_id`,
  `governing_spec_revision`
- **MaterialSpecification** — characteristics, required methods/conditions,
  limits, revision/status
- **SupplierQualification** — supplier, material, qualification status,
  effective/expiry dates
- **Lot / Receipt** — `lot_id`, supplier, material, PO reference, quantity,
  status
- **Evidence** — `evidence_id`, type, source, S3 reference, material/lot
  associations
- **Inventory** — material, lot, quantity, usability status
- **ProductionOrder** — `order_id`, product, quantity, material requirements,
  line/resource, planned slot, authority status
- **AuthorityRecord** — `case_id`, evidence refs, actor disposition, verifier
  result, authority source, requested tool, actual mutation/result, timestamp

DynamoDB is the authoritative store. A local in-memory/file-backed
implementation of the same interface is permitted for tests, but the deployed
runtime must use the real table.

---

## 8. Tools

**Read tools**
`get_lot`, `get_material`, `get_governing_spec`, `get_supplier_qualification`,
`get_evidence`, `get_usable_inventory`, `get_production_order`,
`get_material_requirements`, `get_approved_substitutions`,
`get_production_schedule`

**Deterministic evaluation tools** (no LLM)
`calculate_material_shortage`, `check_schedule_slot`,
`check_substitution_approval`

**Mutation tools** (gate-authorized only, idempotent)
`release_lot`, `quarantine_lot`, `create_qa_review`, `hold_production_order`,
`resequence_production_order`

Tools are small and deterministic. Every mutation tool enforces idempotency via
a stable key so retries and replays cannot double-apply.

---

## 9. Agent / graph roles

- **Material Disposition Agent** (actor) → `RELEASE` | `QUARANTINE` |
  `INSUFFICIENT_EVIDENCE`, plus evidence refs and requirements evaluated.
- **Specification Verifier** (verifier, read-only) → `VERIFIED` | `REJECTED` |
  `INSUFFICIENT_EVIDENCE`.
- **Deterministic Material Authority Gate** — allows mutation only when the
  verifier conditions pass.
- **Production Readiness Agent** — receives deterministic availability facts,
  evaluates whether production authority remains `READY`.
- **Recovery Agent** (actor) — evaluates only supplied/authoritative recovery
  candidates. May propose safe resequence, approved substitution, use of
  existing released inventory, `REFUSE`, or `ESCALATE`.
- **Recovery Verifier** (verifier, read-only) — independently checks the
  proposed recovery.
- **Deterministic Recovery Authority Gate** — controls schedule/substitution
  mutation.

---

## 10. Smoke-test requirements (S0–S9)

| ID | Requirement |
|---|---|
| **S0** | AgentCore is real: `invoke → AgentCore Runtime → Strands workflow → response`, with usable logs/traces. Record runtime id + trace/invocation id. |
| **S1** | Clean lot autonomously releases. Actor `RELEASE` → verifier `VERIFIED` → gate allow → `release_lot()` → usable inventory increases. |
| **S2** | Hero lot quarantines. Supplier evidence looks acceptable alone, but reconciliation against the correct governing plant spec shows release cannot be defended. Actor `QUARANTINE` → verifier `VERIFIED` → `quarantine_lot()` → lot `QUARANTINED`. |
| **S3** | Quarantine breaks production readiness. C-417 needs the quarantined lot. Deterministic usable-inventory calc → shortage → Production Readiness `HOLD` → C-417 `READY → HOLD`. |
| **S4** | Unsafe recovery refused. Candidate substitute has stock but is not approved for C-417. Recovery Agent `REFUSE`, verifier confirms, zero substitution/schedule mutation from that candidate. |
| **S5** | Safe recovery executes. C-418 has required released material, compatible resource, fits vacated slot. `RESEQUENCE` → `VERIFIED` → gate allow → schedule mutation. |
| **S6** | Ambiguous evidence abstains. Evidence relates to the characteristic but does not establish required method/condition. Actor + verifier `INSUFFICIENT_EVIDENCE`, no release, no quarantine-as-defective, QA case created. |
| **S7** | Human evidence resumes the case. QA adds acceptable evidence; same case resumes, actor and verifier reassess, release becomes authorized, history stays continuous. |
| **S8** | Authority ledger. Every consequential mutation carries evidence refs, actor disposition, verifier outcome, authority result, invoked tool, actual state change. |
| **S9** | Permission / fail-safe invariants: verifiers cannot mutate; unverified proposals cannot mutate; disagreement fails safe; retries idempotent; replay cannot double-release inventory or double-change schedule. |

Report S0–S9 as a table with: Test, PASS/FAIL, starting state, decision,
verifier, tool, ending state, trace. Conclude **GO**, **PASS WITH BLOCKERS**
(with concrete blockers), or **NO-GO** (with the failed architectural thesis).

---

## 11. MUST NOT DO

- Do not build frontend UI **until Vouch passes the adversarial Test A gate**.
- Do not create a chat interface.
- Do not let an LLM perform deterministic inventory arithmetic.
- Do not let agents invent approved substitutions, specifications, supplier
  qualification, inventory, or schedule facts.
- Do not give verifier agents mutation tools.
- Do not allow an actor proposal to mutate state without independent
  verification.
- Do not use hidden chain-of-thought as an audit artifact.
- Do not hard-code expected fixture outcomes into agent prompts.
- Do not provision a vector database, AgentCore Memory, or Gateway without
  evidence that the smoke test requires it.
- Do not commit credentials, `.env`, research, private demo documents,
  downloaded source evidence, local traces, or AWS targeting information that
  should remain private.
- Do not silently change the canonical smoke-test contract.

---

## 12. Preferences

- Typed structured outputs.
- Explicit state machines.
- Small deterministic tools.
- Evidence references rather than generated explanations pretending to be
  evidence.
- Idempotent state mutations.
- Actor / verifier separation.
- One AgentCore Runtime containing the Vouch Strands workflow.
- Tests before abstraction.
- Small fixture sets that can later become adversarial eval cases.

---

## 13. AWS safety constraints

### Infrastructure compatibility note

> Existing development AWS resources may retain the legacy `Gatehouse` prefix
> until Vouch passes the adversarial product gate. Do not rename/delete/recreate
> them solely for cosmetic consistency.

Legacy identifiers still in use (centralized in `vouch.config`, never scattered
through business logic):

| Logical name | Current value (legacy) |
|---|---|
| AWS profile | `gatehouse` |
| IAM user | `gatehouse-dev` |
| `VOUCH_RUNTIME_ROLE_ARN` | `GatehouseAgentCoreRuntimeRole` |
| `VOUCH_STATE_TABLE` | `gatehouse-dev-state` |
| `VOUCH_EVIDENCE_BUCKET` | `gatehouse-dev-evidence-*` |
| AgentCore Runtime | `Gatehouse-*` |

`VOUCH_*` environment variables fall back to their pre-rename `GATEHOUSE_*`
equivalents, so the already-deployed runtime keeps working until redeployed.

### Identity policy (binding)

- **All Vouch AWS development uses `AWS_PROFILE=gatehouse`**, which must
  authenticate as IAM user `gatehouse-dev` in the Vouch account. The account
  id is account-specific targeting information: it lives in the gitignored
  `provisioning.json`, never in tracked files.
- **Region is `us-east-1`** (`AWS_REGION` and `AWS_DEFAULT_REGION`).
- **Never use `tally`, `gate5-deployer`, `default`, `brickweaver`, `onagain`, or
  any other project's profile for Vouch work.** They belong to other
  projects; borrowing them produces misleading capability results. A bootstrap
  identity may repair Vouch IAM, never run Vouch.
- **`GatehouseAgentCoreRuntimeRole` is the service/runtime identity, not the
  local developer identity.** Do not configure it as a local profile, and do not
  create a second Vouch runtime role.
- Verify identity before any smoke run:
  `aws sts get-caller-identity --profile gatehouse --region us-east-1`
  must return exactly `.../user/gatehouse-dev`. Anything else is a hard stop.

### Credential handling

- Never commit AWS credentials, account IDs, or environment-specific targeting
  files.
- **Credentials never live in `.env` or any repository file.** They live in
  `~/.aws/credentials` under the `gatehouse` profile.
- Never print a secret access key to a terminal, log, or chat.
- Credentials come from the ambient AWS session or instance role. The repo
  stores none.
- Do not create duplicate cloud resources. Consume the values produced by the
  CloudShell provisioning commission (account id, region, evidence bucket,
  DynamoDB table, model/inference config, observability status).
- Runtime IAM should be scoped to the specific S3 bucket and DynamoDB table.
- `agentcore validate` and `agentcore deploy --dry-run` run before any real
  deploy.
- Local config carrying account/environment specifics is gitignored.

---

## 14. Escalate — stop and report if

- AgentCore or Bedrock is unavailable in the target environment.
- Required model invocation is blocked.
- Current Strands behavior materially differs from the proposed graph
  architecture.
- Actor/verifier permission separation cannot be enforced.
- AgentCore Runtime cannot access the scoped S3/DynamoDB resources.
- Simple deterministic rules reproduce essentially all supposedly agentic
  judgment. (If a rules engine matches the agents on every fixture, the agentic
  thesis is unproven — say so.)
- A requested architectural addition exists only to make the sponsor stack look
  larger.

---

## 15. Next stage (do not build yet)

After S0–S9 passes, the evaluation framework must cover: unsafe autonomous
action rate, correct ACT rate, correct REFUSE rate, correct ABSTAIN rate, false
abstention, actor/verifier disagreement, verifier rubber-stamping, robustness to
document wording/layout variation, deterministic-baseline comparison, and
end-to-end state correctness.

The AgentCore CLI supports evaluators and on-demand/online evaluation workflows.
Reserve the architecture for this, but do not provision evaluation
infrastructure before the core vertical passes.

---

## 16. Repository sync requirement

`AGENTS.md` and `CLAUDE.md` MUST remain byte-for-byte identical at all times.

- `AGENTS.md` is canonical.
- They are NOT symlinked, by design.
- `scripts/check_agent_docs_sync.py` verifies equality; `--fix` copies canonical
  over the mirror.
- `tests/test_agent_docs_sync.py` fails the suite when they diverge.
- No change to this contract lands without both files updated together.
