# Vouch V2 — FE ↔ BE Integration Contract

**Status: FROZEN_PENDING_ADMIN_QUALIFICATION** — Runtime Qualification /
Contract Correction Gate, 2026-09-02.
**Runtime:** `Gatehouse-IWAmEp93XP` **version 24** · `us-east-1`
**Backend suite:** 687 passed / 19 skipped · **Frontend:** 52 passed

> **Not `FINAL_RUNTIME_AND_INTEGRATION_CONTRACT_FROZEN`.** Three AWS
> permissions required by this gate are denied to `gatehouse-dev` and were
> verified denied by direct call, so `list_decisions`, Textract and the BFF
> deployment could not be qualified. Everything else in this document is now
> captured from **live AWS on version 24**. See §8 and
> `docs/sponsor-depth/ADMIN_STEP.md`.

This is the wire contract between the browser and Vouch. Every shape below was
captured from the **deployed runtime on version 24**, not read off the source,
except the two marked `BLOCKED` — which cannot be captured until the admin step
in `docs/sponsor-depth/ADMIN_STEP.md` runs.

Freezing means: the frontend may be built against this. A change to anything
here after this point is a contract change and needs its own gate.

---

## 0. Transport

```
browser → API Gateway → Lambda (bff/handler.py) → InvokeAgentRuntime → AgentCore
```

The BFF exists because `InvokeAgentRuntime` is SigV4-signed and AgentCore has no
CORS surface. It is **transport and authorization only** — it holds no
applicability, disposition, policy, recovery or view-model logic, and it invents
no lifecycle events.

> **Deployment status:** `bff/handler.py` is written, tested (`test_bff.py`) and
> Lambda-shaped, but **is not deployed**. `gatehouse-dev` cannot create Lambda
> or API Gateway. Until it is, the frontend talks to a local proxy with the same
> routes. This is a deployment gap, not a contract gap.

### Routes

| Method | Path | Action | Kind |
|---|---|---|---|
| POST | `/api/evaluate` | `evaluate_lot` | write |
| POST | `/api/evidence` | `supply_evidence` | write |
| GET | `/api/today` | `get_today` | read |
| GET | `/api/decisions` | `list_decisions` | read |
| GET | `/api/decisions/{id}` | `get_decision` | read |
| GET | `/api/decisions/{id}/events` | `get_events` | read |
| GET | `/api/decisions/{id}/sources` | `get_source` | read |

Actions the runtime supports but the browser **cannot** reach: `readiness`,
`recovery`, `ledger`. The allowlist is checked before any AWS call.

### Identifier shapes (validated at the BFF, before AWS)

```
DR-[A-Za-z0-9]{1,40}      decision record
ART-[A-Za-z0-9]{1,40}     evidence artifact
[A-Za-z0-9][A-Za-z0-9._-]{0,63}   lot / order
```

---

## 1. The envelope

Every response carries `ok`, `action` and `backend`.

```ts
interface Envelope {
  ok: boolean
  action: string
  backend: {
    mode: "production" | "local"
    durable: boolean          // false ⇒ do NOT present results as authoritative
    corpus: string            // e.g. "AWS_DYNAMODB"
    evidence: string          // e.g. "AWS_S3"
    reasoners: string         // e.g. "BEDROCK_NOVA"
  }
}
```

### Typed failure — **captured live**

```json
{
  "ok": false,
  "action": "list_decisions",
  "backend": { "...": "..." },
  "failure_category": "PERSISTENCE_FAILURE",
  "error": "could not list decisions: An error occurred (AccessDeniedException)…",
  "mutation": {}
}
```

**A failure envelope has no `disposition`, and the UI must never synthesise
one.** A transport or persistence failure is not a quality verdict. The BFF
additionally returns `failure_class: "TECHNICAL_FAILURE"` for transport errors,
for exactly this reason.

`failure_category` ∈ `PERSISTENCE_FAILURE` · `MODEL_UNAVAILABLE` ·
`TOOL_FAILURE` · `SCHEMA_FAILURE` · `SECURITY_QUARANTINE` ·
`EXTRACTION_LOW_CONFIDENCE` · `EVIDENCE_BINDING_MISMATCH` · `EVIDENCE_UNBOUND` ·
`EVIDENCE_IDENTITY_CONFLICT`.

---

## 2. `evaluate_lot` — **captured live**

```ts
POST /api/evaluate
{ lot_id: string
  document?: string          // inline text
  document_b64?: string      // real PDF bytes
  artifact_ref?: string      // already in evidence storage
  content_type?: "text/plain" | "text/csv" | "application/pdf"
  decision_record_id?: string   // caller may NAME the decision before it starts
}
```

Supplying `decision_record_id` is how a browser polls a decision it is waiting
on: invocation is synchronous (~15–60s), so without it the id only arrives once
there is nothing left to watch. A supplied id is **continued**, never replaced.

```ts
interface EvaluateResponse extends Envelope {
  decision_record_id: string
  lot_id: string
  disposition: "" | "RELEASE" | "QUARANTINE" | "INSUFFICIENT_EVIDENCE"
  failure_category: string
  quality_decision_required: boolean
  reason: string
  mutation: Record<string, unknown>      // {} when nothing changed
  consequences: {
    readiness_changes?: { order_id: string; from: string; to: string }[]
    recovery?: {
      executed: boolean
      candidates: { candidate_id: string; verdict: RecoveryVerdict; reason: string }[]
    }
  }
  decision_record: RecordSummary
  events: LifecycleEvent[]
}

type RecoveryVerdict = "ELIGIBLE" | "REFUSED" | "NOT_FEASIBLE"
```

**There is deliberately no `in_progress` state.** Invocation is synchronous, so
no decision is ever persisted mid-flight and any such value would be fiction.

---

## 3. `get_today` — **captured live**

```json
{
  "readiness_counts": { "READY": 2, "AT_RISK": 0, "BLOCKED": 1, "COMPLETE": 0 },
  "lines": [{
    "line_id": "LINE-1",
    "orders": [{
      "order_id": "C-417", "product": "P-417",
      "planned_slot": "2026-08-15T08:00",
      "status": "READY", "readiness": "BLOCKED",
      "reason": "MAT-ALLOY-7 short by 900.0 (need 900.0, have 0)",
      "coverage": [{ "material_id": "MAT-ALLOY-7", "required": 900.0,
                     "available": 0, "short_by": 900.0, "ratio": 0.0 }],
      "requirements": [{ "material_id": "MAT-ALLOY-7", "quantity": 900.0 }],
      "customer_committed": true, "need_by": "2026-08-20", "state_version": 1
    }]
  }]
}
```

`status` is the **stored** order state; `readiness` is the **computed** one.
They differ legitimately (`READY` / `BLOCKED` above) and the UI must not
collapse them. All shortage arithmetic is Python, never a model.

---

## 4. `list_decisions` — Incoming — **BLOCKED, shape from source**

> Requires the `decisions-by-recency` GSI **and** the runtime's
> `dynamodb:Query` on `.../index/*`. Both are pending the admin step. Live today
> this returns the `PERSISTENCE_FAILURE` envelope in §1, and Incoming is the one
> surface that cannot yet be demonstrated.

```ts
interface ListDecisionsResponse extends Envelope {
  rows: IncomingRow[]
  cursor: object | null
  counts: { returned: number }      // no in_progress, no completed_by_vouch
}

interface IncomingRow {
  decision_record_id: string
  lot_id: string
  material_id: string
  material_name: string      // joined server-side from the authoritative corpus
  supplier_id: string
  supplier_name: string      // joined server-side
  supplier_site: string
  received_at: string
  quantity: number | null
  units: string
  lot_status: string
  disposition: string
  failure_category: string
  row_state: RowState        // computed server-side, never derived in the browser
  attention_required: boolean
  decided_at: string
}

type RowState =
  | "EVIDENCE_RECEIVED" | "RELEASED" | "QUARANTINED"
  | "QUALITY_DECISION_REQUIRED" | "SECURITY_HOLD"
```

`row_state` and the display names are computed **server-side on purpose**: two
clients deriving them independently would eventually disagree about what the
same record means, and a client resolving ids itself could render a name the
plant does not use.

---

## 5. `get_decision` / `get_events` / `get_source`

`get_events` accepts `after_sequence` for incremental polling; events are
written live by a sink, so a UI sees a decision progress rather than replaying
a finished one.

`get_source` returns a **presigned S3 URL, TTL ≤ 300s**, pinned to the exact
`VersionId` the claim was bound to. It is never logged, at any layer, and must
never be persisted client-side: it is a bearer credential that outlives the
request.

### Lifecycle events

26 types, frozen. Full list in `docs/architecture/v2/LIFECYCLE_EVENTS.md`.

**Structural guarantee:** `LifecycleEvent.__post_init__` raises on any payload
key containing `chain_of_thought`, `reasoning`, `rationale`, `raw_prompt` or
`prompt_text`. Model reasoning cannot reach this surface, by construction rather
than by convention.

`PRECEDENT_CONSULTED` is declared but **not emitted** in Milestone 1.

---

## 6. Sponsor-depth provenance (optional, additive)

All fields optional and absent for ordinary documents. Full detail in the
addendum to `VOUCH_V2_FRONTEND_DATA_CONTRACT.md`.

```ts
structuredExtraction: boolean        // present on every artifact; false normally
confidenceGatePassed?: boolean
identityTrusted?: boolean
structuredReason?: string
sourceLocators?: { page: number; table: number; rowLabel: string
                   columnLabel: string; cell: string; line: number
                   confidence: number }[]
```

`extractionMethod` gains `"TEXTRACT_TABLES"`. **Treat it as an open value set.**

**`identityTrusted === false` is a genuinely new state:** a document readable
enough to yield measurements but not readable enough to bind a lot id. It binds
to nothing and routes to a human — the same fail-closed outcome an unreadable
scan already produces.

**No new lifecycle event.** `EVIDENCE_EXTRACTED` carries it.

---

## 7. Invariants the frontend may rely on

1. **A failure never becomes a disposition.** `ok: false` has no `disposition`.
2. **`mutation: {}` means nothing changed.** Never infer a state change.
3. **`backend.durable === false` means results are not authoritative.**
4. **Ids are opaque.** Never parse `DR-…` / `ART-…` for meaning.
5. **Server-side truth is server-side.** `row_state`, `readiness`, `coverage`,
   display names and all arithmetic are computed by the backend.
6. **Security halts the spine.** A `SECURITY_QUARANTINE` decision has no
   extraction, no claims, no agent activity — do not render placeholders.
7. **Abstention is a first-class outcome**, not an error.
8. **Presigned URLs are transient credentials.** Never store or log one.
9. **Event payloads never contain reasoning.** Do not build a UI expecting it.
10. **`extractionMethod` and `failure_category` are open value sets.**

---

## 8. Live qualification standing — runtime version 24

| Path | Status | Evidence |
|---|---|---|
| Hero A | **AWS_LIVE_VERIFIED** | `DR-f30c8cb193d9`, 43.4s, `QUARANTINE` → C-417 `READY→BLOCKED` → C-418 resequenced. 9/9 checks, re-run after the 900.0 correction |
| Hero B | **AWS_LIVE_VERIFIED** | 49.2s, abstain → human evidence → same record, `run_count 2` → `RELEASE`. 10/10 checks |
| Hostile | **AWS_LIVE_VERIFIED** | Guardrail `DETECTED` → `QUARANTINED_SECURITY`, agents never invoked, zero mutation, LOT-1004 `RECEIVED` |
| `get_today` | **AWS_LIVE_VERIFIED** | `MAT-ALLOY-7 short by 900.0 (need 900.0, have 0)` — the corrected canonical figure, captured from v24 |
| Canonical reseed | **AWS_LIVE_VERIFIED** | 35 rows; every lot `RECEIVED`, every order `READY`, zero usable inventory |
| Observability | **AWS_LIVE_VERIFIED** | 63 spans, Investigator 8.62s / Verifier 6.42s, token usage preserved, **0 content leaks** |
| Log content boundary | **AWS_LIVE_VERIFIED** | **0** `<thinking>` lines in CloudWatch across two Hero runs (was 86) |
| `list_decisions` | **BLOCKED** | GSI + runtime `index/*` grant. `dynamodb:UpdateTable` and `iam:PutRolePolicy` denied to `gatehouse-dev`, verified by direct call |
| Textract | **BLOCKED** | `textract:AnalyzeDocument` denied, verified by a real SDK call with real PDF bytes |
| BFF (Lambda/APIGW) | **LOCAL_VERIFIED** | Written and tested; `lambda:*` and `apigateway:GET` denied to `gatehouse-dev` |

### Why three items are still blocked

`gatehouse-dev` holds none of `dynamodb:UpdateTable`, `iam:PutRolePolicy`,
`textract:AnalyzeDocument`, `lambda:*` or `apigateway:*`, and cannot
`sts:AssumeRole` into `GatehouseAgentCoreRuntimeRole`. Every one of those was
tested directly this gate rather than inferred. That is the identity boundary
working as designed — the identity that runs Vouch is deliberately not the
identity that grants Vouch permissions — and it is why this document is
`FROZEN_PENDING_ADMIN_QUALIFICATION` rather than final.

Run `docs/sponsor-depth/ADMIN_STEP.md`, then
`scripts/verify_sponsor_depth_live.py`. It flips to `PASS` only when all 13
checks read `AWS_LIVE_VERIFIED`.

---

## 9. Freeze

`FROZEN_PENDING_ADMIN_QUALIFICATION`, 2026-09-02, runtime version 24.

**The frontend may be built against this document.** Everything the Decision
Workspace, Today, Evidence, Investigator, Verifier, Reconciliation, Disposition,
Consequence/Recovery and Source surfaces need is captured from live AWS.

Two shapes still carry a caveat, and neither blocks frontend work:

1. **`list_decisions` (§4)** — specified from source. It backs **Incoming**
   only. Every field is server-computed and its shape is fixed by
   `_incoming_row`, so the risk is that it cannot yet be *demonstrated*, not
   that it will change.
2. **Sponsor-depth provenance (§6)** — implemented and locally verified across
   22 tests, but never observed from a real Textract response. If the live call
   contradicts §6 — most plausibly in column-header naming — that is a contract
   change and it will be recorded here rather than absorbed in an adapter.

**One correction landed in this gate rather than being papered over.** The
frozen contract carried `C-417 required: 800.0`, captured from a live corpus
that had never been migrated. The FE↔BE gate (D10) had decided `900.0` so the
demo copy "C-417 · 900 kg uncovered" would be backed by real state. The fixture
is now 900.0, reseeded, redeployed and re-qualified: both Heroes still CLEAN,
and live `get_today` now reads `short by 900.0`. See
`tests/v2/test_canonical_demo_data.py`.
