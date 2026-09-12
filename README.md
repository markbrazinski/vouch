# Vouch — Manufacturing Material Authority Control Plane

A certificate of analysis arrives with lot `LOT-1002` on a Thursday morning. It
reads `462 MPa`, it cites `SPEC-A7 Revision B`, and it concludes `CONFORMS to the
referenced specification` — and every one of those statements is true. Revision
B requires ≥450 MPa. But revision **C** governs by receipt date, it requires
≥480 MPa, and there is no covering deviation. The supplier's own conformance
claim is correct about the wrong document. A quality engineer catches this by
reading two documents side by side; a plant running a thousand receipts a month
does not catch it every time.

Vouch is the control plane that decides what may enter production. It
reconciles each incoming lot against the specification revision that actually
governs, quarantines what cannot be defended, recomputes what the factory can
still build, and repairs the schedule where a safe repair exists. Model
reasoning is advisory throughout: two agents establish what governs and what
applies, and **no model in this system can express a disposition** — the
vocabulary they emit has no field for one. Only a deterministic policy engine
may create authority, and it records a refusal as readily as a release.

![The authority workspace mid-run on LOT-1002: the Independent Verifier
reconstructs the case with "The Investigator's output was not provided to this
agent" on screen, while the activity ledger records each real
us.amazon.nova-pro-v1:0 tool call as it
arrives.](docs-images/workspace-independent-verification.png)

![The same lot settled: QUARANTINE against SPEC-A7:C with the failing
measurement stated, production order C-417 moved AT_RISK to BLOCKED, and C-418
resequenced into the slot C-417
vacated.](docs-images/quarantine-and-production-consequence.png)

## Architecture

Three planes, and the boundary between them is the product.

```
supplier evidence (assume hostile)
  → security boundary → stored original (S3, versioned) → parse → canonical claims
  → provenance + trust labels → frozen snapshot
      ├─→ Applicability Investigator   [Nova Pro, scoped read-only tools]
      └─→ Independent Verifier          [Nova Pro, no brief, no precedent]
  → deterministic reconcile → basis checks → disposition → policy engine
  → capability record → atomic conditional write → DecisionRecord
  → consequences → deterministic recovery
```

The **evidence boundary** treats every supplier document as hostile input.
Supplier text never occupies an instruction position, and the single model that
touches raw bytes is a confined extractor with no authority at all.

The **advisory plane** is two Nova Pro agents reading a frozen claim snapshot
through scoped read-only tools. They establish which revision governs and which
claims bear on it. They are structurally incapable of dispositioning:
`EvidenceApplicabilityBrief` has no disposition field, so the type system
forbids what a prompt would only discourage.

The **authoritative plane** is deterministic Python. It reconciles the two
independent reconstructions, runs the basis checks, computes every number, and
derives the disposition. Mutation requires a capability record issued by the
policy engine and bound to one target, one action, one DecisionRecord and one
observed state version — consumed by a single atomic conditional write. A forged
`CAP#` row written directly into the real DynamoDB table is refused.

## How it works

**Admit the evidence, assuming it is hostile.** The certificate for `LOT-1002`
crosses the security boundary, is stored as a versioned S3 original bound to
`sha256:bf3e80…`, and is parsed into two canonical claims — `tensile_strength:
462 MPa` and `hardness: 30 HRC`. Bedrock Guardrails screens it for prompt
injection. The claims are then frozen, so both agents reason over byte-identical
facts.

**Investigate and verify, independently.** The Applicability Investigator reads
the snapshot and establishes the governing basis. The Independent Verifier
reconstructs the same question from the authoritative records with no brief, no
precedent, and no sight of the Investigator's conclusion — the workspace says so
on screen. Both reach `SUFFICIENT` and the reconciler records an
`INDEPENDENT_MATCH`. Neither proposed an outcome, because neither can.

**Decide deterministically, then bind the authority.** Plain Python compares
`462.0` against revision C's `>= 480.0` floor, finds no covering deviation, and
computes `QUARANTINE`. The policy engine issues capability
`CAP-5b14575c4ebe4f0e` bound to `quarantine_lot` on `LOT-1002` at state version
30, and one conditional write consumes it. Disagreement would instead stop the
run and ask a human — and on `LOT-1003` it does.

**Recompute what the factory can still build.** C-417 needs `900.0` of
MAT-ALLOY-7 and now has `500.0`, so it is short by `400.0` and moves `AT_RISK →
BLOCKED`. C-418 needs `500.0`, has `500.0`, and is untouched. The causal link
from lot to order is persisted, not inferred later.

**Recover where recovery is safe, and refuse where it is not.** Four candidates
are evaluated deterministically. Existing inventory is `NOT_FEASIBLE`
(`INSUFFICIENT_QUANTITY`: 900 needed, 500 available). Substitute `MAT-SUB-9` is
**`REFUSED`** — `900.0` units are sitting in stock and only `400.0` are needed,
but it is `NOT_APPROVED` for product P-417, and available stock is not
authorization. Resequencing C-419 is `NOT_FEASIBLE`. Resequencing **C-418 is
`ELIGIBLE`**: materials ready, LINE-1 free, and the `08:00` slot vacated by
C-417 open — so C-418 moves `14:00 → 08:00` and the line keeps running.

## Run locally

There is no public deployment. The AgentCore Runtime is real and served every
recorded run in this repository, but it is reached by SigV4-signed
`InvokeAgentRuntime`, not by a browser, and the operator console authenticates
against Cognito. What follows is what you can actually run, and every command
below was executed to write this section.

### Prerequisites

- **Python 3.12** — `pyproject.toml` declares `>=3.10`; 3.12.12 is what the
  suite is verified on.
- **Node 20+** for the frontend suite. Verified on Node 25.2.1, npm 11.6.2.
- **No AWS account, credential, or network access is needed for anything in
  this section.** The decision core runs against in-memory stores and scripted
  reasoners. Credentials are required only for *Running against real AWS* below.

### Install

```bash
git clone https://github.com/markbrazinski/vouch.git
cd vouch
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python \
    strands-agents strands-agents-tools bedrock-agentcore \
    bedrock-agentcore-starter-toolkit pytest boto3 pypdf
```

The fastest proof the code works, with no configuration and no credentials:

```bash
.venv/bin/python -m pytest tests/ -q
# 1136 passed, 37 skipped in 17.27s
```

The 37 skips are the AWS-dependent tests, which skip by design without
`VOUCH_LIVE_AWS=1` — a laptop run reports skips rather than failures.

### Run one decision

The case from the top of this README, end to end, offline:

```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'src')
from vouch.v2.workflow import VouchV2
from vouch.v2.fixtures import build_corpus, COA_HERO
outcome = VouchV2(build_corpus()).evaluate_lot('LOT-1002', documents=[{'raw': COA_HERO}])
print(outcome.disposition, outcome.record.basis.revision)
"
```

```
QUARANTINE C
```

The certificate said `CONFORMS`. Vouch says `QUARANTINE`, and names revision `C`
as the basis on which it says it.

### Frontend suite

```bash
cd frontend && npm install && npx vitest run
```

Allow roughly four minutes. One test shells out to a real production `vite
build` and greps the emitted chunks to prove the dev fixture harness, the visual
baselines and the replay data are absent from the product bundle — so the
exclusion is verified against a real build rather than asserted.

### Configuration

Nothing above needs a `.env`. For the live paths:

```bash
cp .env.example .env      # .env is gitignored; keep it uncommitted
```

[`.env.example`](.env.example) documents every variable the code reads, what it
changes, and which are safe to leave unset. Two rules it states and this project
enforces:

- **AWS credentials never live in `.env` or any repository file.** They belong
  in `~/.aws/credentials` under the `gatehouse` profile, or in the ambient
  session or instance role.
- **Account-specific targeting lives in `provisioning.json`**, which is
  gitignored. `tests/v2/test_repo_hygiene.py` fails the build if an account id
  or real credential reaches a tracked file.

Every variable resolves as `VOUCH_<NAME>` first, falling back to the pre-rename
`GATEHOUSE_<NAME>` — the deployed runtime was launched with the old names, and
the fallback means the rename cannot break running infrastructure.

### Running against real AWS

Needs Bedrock access, the `gatehouse` profile, and the resources named in
`provisioning.json`. Not required for anything above. Verify identity first —
anything other than `gatehouse-dev` is a hard stop:

```bash
aws sts get-caller-identity --profile gatehouse --region us-east-1
# .../user/gatehouse-dev
```

```bash
make reseed   # reset the demo corpus in DynamoDB; re-deciding a quarantined
              # lot is correctly refused, so this runs before every live take
make bff      # local BFF, binds 127.0.0.1:8787
make ui       # vite dev server, binds :5173, proxying /api to the BFF
make live     # the AWS-dependent suite
AWS_PROFILE=gatehouse VOUCH_V2_MODE=bedrock \
    .venv/bin/python scripts/run_v2_gate.py --repeats 1
```

`make bff` calls STS at startup to compose the runtime ARN, so it exits
immediately without credentials rather than failing later in a confusing place.

### Shutdown

Ctrl-C each shell. Neither process holds state; authoritative state lives in
DynamoDB and S3, or in memory for the offline path.

## Technologies and dependencies

- **Python 3.12** — the entire decision core, including every consequential
  computation. No LLM performs arithmetic anywhere in this system.
- **Strands Agents `>=1.52.0`** — the two decision agents and their scoped tool
  surfaces. Read-only construction is enforced in code: passing a mutation tool
  to a verifier raises rather than warns.
- **Amazon Bedrock — Nova Pro (`us.amazon.nova-pro-v1:0`)** — the Investigator
  and the Verifier, at temperature 0, as two genuinely separate invocations.
  Their independence is observable as distinct, independently-timed OTel spans
  (7.67s and 7.85s on a measured 14.18s decision).
- **Amazon Bedrock Guardrails** — prompt-attack screening at the evidence
  boundary. Deliberately a layer and not the boundary: the injection test also
  runs with the detector forced to return clean, and the lot is still
  quarantined.
- **Amazon Bedrock AgentCore Runtime** — hosts the workflow. One runtime,
  serving the same code path the tests exercise. Runtime version 50 produced the
  five captured runs.
- **Amazon DynamoDB** — the authoritative corpus, DecisionRecords, event
  streams, and the conditional writes that make capability consumption atomic.
- **Amazon S3** — evidence originals, versioned and hash-bound. Versioned, *not*
  WORM — see Honest boundaries.
- **React 19 + Vite 7 + React Router 7** — the operator console. Holds no AWS
  SDK and no token; it talks only to same-origin `/api`.
- **AWS Lambda + API Gateway** (`bff/handler.py`) — transport and authorization
  only. It holds no applicability, disposition, policy, recovery or view-model
  logic, and invents no lifecycle events. That is why it vendors nothing.
- **pypdf `>=5.0.0`** — real PDF extraction. A PDF is a structured container;
  decoding its bytes as UTF-8 is not an implementation of reading one.

## Sample outputs

[`golden-runs/`](golden-runs/) holds five complete runs captured from the
deployed AgentCore Runtime against live Nova Pro — full event stream,
DecisionRecord, source artifacts and result for each. These are execution truth,
not fixtures: `LOT-1002` alone carries 48 raw lifecycle events.

| Lot | Scenario | Outcome |
|---|---|---|
| `LOT-1001` | Agents agree, deterministic checks pass | `RELEASE` |
| `LOT-1002` | Certificate cites superseded revision B; revision C governs and fails at 462 < 480 MPa | `QUARANTINE` → C-417 `AT_RISK → BLOCKED`, C-418 resequenced `14:00 → 08:00` |
| `LOT-1003` | Two honest readings by different methods disagree — 178 cP by the named method, 312 cP by a genuinely equivalent one | `MATERIAL_DISAGREEMENT` → human establishes controlling evidence → run 2 `RELEASE` |
| `LOT-1004` | Certificate names batch `WP-26-0317-B` and no lot, so it cannot be attributed | identity gate → human confirms binding → run 2 `RELEASE` |
| `LOT-1005` | Prompt injection inside an authentic-looking certificate | `SECURITY_QUARANTINE` — 4 events, zero claims, agents never invoked |

`LOT-1003` is worth reading closely. An earlier version of that fixture had both
viscosity readings passing, which made the human's answer ceremonial — a quality
decision that cannot change the outcome is not a decision. It was rebuilt so the
two readings point genuinely opposite ways.

[`golden-runs/README.md`](golden-runs/README.md) documents each package's
contents, how to read one, what the integrity test guards, and what these
recordings do **not** prove. The five source certificates are catalogued in
[`demo/evidence/MANIFEST.md`](demo/evidence/MANIFEST.md), and
[`fixtures/README.md`](fixtures/README.md) explains the corpus arithmetic and
the extraction-boundary documents.

## Repository structure

```
src/vouch/v2/
  contracts.py       brief schema, trust labels, authority validators, failure taxonomy
  corpus.py          authoritative objects with currency/supersession/scope semantics
  evidence.py        the hostile-evidence boundary (S1–S7)
  tools.py           scoped read-only Strands tools
  agents.py          Investigator, Verifier, confined extractor
  reconcile.py       deterministic reconciliation + basis checks
  disposition.py     deterministic Disposition Engine
  authority.py       capability records, Policy Engine, atomic mutation
  consequences.py    readiness, causal links, deterministic recovery
  workflow.py        the deterministic state machine
  evalcases.py       segmented evaluation corpus
bff/handler.py       transport/authorization only — the browser's security boundary
frontend/src/        operator console (Today, Incoming, Suppliers, Records)
golden-runs/         five runs captured from the deployed runtime — see its README
demo/evidence/       the five canonical supplier PDFs — see MANIFEST.md
fixtures/            extraction-boundary documents — see its README
tests/v2/            capability, security red-team, pipeline, evaluation integrity
iam/                 the policy documents asserting the CAP# deny boundary
.env.example         every variable the code reads, and what it changes
AGENTS.md CLAUDE.md  operating contract; byte-identical, sync-enforced
```

Each directory carrying evidence documents itself, so a reviewer can judge
provenance without reading the code that produced it:

| Doc | Covers |
|---|---|
| [`golden-runs/README.md`](golden-runs/README.md) | The five captured runs: package contents, integrity guarantees, and limits |
| [`demo/evidence/MANIFEST.md`](demo/evidence/MANIFEST.md) | The five supplier PDFs, per-document, and the brief freezing their content |
| [`fixtures/README.md`](fixtures/README.md) | Corpus arithmetic, certificate bodies, the Textract seam |
| [`iam/README.md`](iam/README.md) | The `CAP#` deny boundary these policies express, and whether they are attached |

## Verification

Whole backend suite, offline, no credentials:

```bash
.venv/bin/python -m pytest tests/ -q          # 1136 passed, 37 skipped
```

The demo-critical product contract, and the frontend including a real
production build:

```bash
make gate                                     # 257 backend + the FE contract tests
cd frontend && npx vitest run                 # 538 passed, plus 2 real-build tests
```

The two extra frontend files run a production `vite build` and take minutes
each; the 538 figure is the suite without them.

Live provider integration:

```bash
make live                                     # needs gatehouse credentials
```

These suites cover deterministic behavior, the capability properties and the
red-team boundary. Live Bedrock, Guardrails, AgentCore, DynamoDB and S3 are
exercised by `make live` and by the captured runs in `golden-runs/`.

## License

Apache-2.0. See [`LICENSE`](LICENSE).

## AWS implementation

Vouch has been exercised live on AWS across the core decision path:

- Amazon S3 stores versioned, hash-bound supplier evidence.
- Amazon DynamoDB is the authoritative state, DecisionRecord, and event store.
- Capability consumption is transactional; a forged capability row written
  directly into the live table was refused.
- DecisionRecords and lifecycle events persist across restart and same-record
  continuation.
- Amazon Nova Pro performs the live Investigator and Independent Verifier
  reasoning.
- Amazon Bedrock AgentCore Runtime serves the live agent workflow.
- Amazon Bedrock Guardrails detects prompt-injection content before it reaches
  either decision agent.

For this prototype, evidence is versioned and hash-bound. S3 Object Lock,
KMS-backed issuance keys, and malware scanning are out of scope for the deployed
demo.

## Security properties

41 capability tests and 22 red-team tests cover supplier-claimed authority,
out-of-scope deviations and equivalences, expired deviations, fabricated
evidence references, schema failures, model outage, and superseded revisions
that *both* models agree on.

Among them is proof that an injected supplier document is inert **with the
prompt-attack detector disabled**. Detection is a layer; the structural controls
are what carry it — supplier text never occupies an instruction position, the
model that touches raw bytes has no authority, and authority is sourced only
from internal objects.

Where the two agents materially disagree, the run escalates to a human instead
of mutating. `LOT-1003` and `LOT-1004` are that path, and the human's answer
continues the same DecisionRecord rather than starting a new case.

## Scope

What Vouch covers, and what it deliberately does not:

- **Not connected to a live ERP or MES.** The material master, production plan
  and inventory are Vouch's own authoritative state, seeded from a fixture
  corpus rather than synchronised from a plant system.
- **A canonical corpus, not a plant catalog.** Five lots, two materials and a
  handful of production orders — sized so one disposition visibly moves the
  board, not to model a full site.
- **All manufacturing data is synthetic.** Suppliers, specifications, lots,
  production orders and certificates are fictional, generated for this
  demonstration. No real company is represented.
- **A prototype, not a qualified quality system.** Vouch makes no regulatory
  determination and grants no real release authority.

## Contributing

`AGENTS.md` is canonical and must stay byte-identical to `CLAUDE.md`:

```bash
python scripts/check_agent_docs_sync.py --fix
```
