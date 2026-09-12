# Vouch golden runs — captured execution truth

Five complete decisions, one per canonical lot, captured from the **deployed
AgentCore Runtime** against real Nova Pro reasoners, real Bedrock Guardrails,
real DynamoDB and real S3. They let a reviewer inspect exactly what Vouch did —
every lifecycle event, the durable record, the source artifacts and the
resulting state change — without AWS credentials or a deployment.

These are recordings, not fixtures. `scripts/capture_golden_runs.py` writes
whatever the runtime produced:

> This script RECORDS. It never asserts an outcome into existence: the run is
> whatever the deployed runtime, real Nova reasoners, real Guardrails, real
> DynamoDB and real S3 produced. A non-golden outcome is written and reported as
> non-golden rather than retried into the shape someone wanted.

All five were captured on **2026-09-10** against AgentCore Runtime
`Gatehouse-IWAmEp93XP` **version 50**, model `us.amazon.nova-pro-v1:0`, with
`backend.mode = production` (`corpus`, `evidence_store`, `capability_store`,
`record_store` and `event_store` all on real AWS).

---

## The five runs

| Lot | Scenario | Runs | Events | Human | Outcome |
|---|---|---|---|---|---|
| [`LOT-1001`](LOT-1001/) | Agents agree, deterministic checks pass | 1 | 32 | — | `RELEASE` |
| [`LOT-1002`](LOT-1002/) | Certificate cites superseded revision B; revision C governs and fails | 1 | 48 | — | `QUARANTINE` |
| [`LOT-1003`](LOT-1003/) | Two honest readings by different methods disagree | 2 | 74 | `QUALITY` | `RELEASE` |
| [`LOT-1004`](LOT-1004/) | Certificate names a batch and no lot | 2 | 37 | `IDENTITY` | `RELEASE` |
| [`LOT-1005`](LOT-1005/) | Prompt injection inside an authentic-looking certificate | 1 | 4 | — | `SECURITY_QUARANTINE` |

`LOT-1005`'s event count is the point of it: **4 events, zero claims, and the
decision agents are never invoked.** Guardrails halts the document at the
evidence boundary, so there is nothing for a model to be persuaded by.

`LOT-1003` and `LOT-1004` are two-run decisions. The same `DecisionRecord`
continues across the human's answer — `run_count` reaches 2 and the event
sequence extends rather than restarting — which is what makes the human's
contribution auditable rather than a separate case.

---

## What each package contains

| File | Contents |
|---|---|
| `manifest.json` | What this run was and what it did: disposition, mutation with capability id, production consequence, human interaction kind, runtime and model identity, capture timestamp |
| `events.json` | The **complete ordered lifecycle stream, unfiltered** — the authoritative history |
| `decision-record.json` | The durable `DecisionRecord`, archived runs included |
| `sources.json` | The source artifacts the decision read, with S3 version ids and SHA-256 |
| `result.json` | The terminal result envelope, as the API returned it |
| `beats.json` | Per-beat film index: which event sequences open and close each narrative beat |

`beats.json` deliberately stores **boundaries, not durations.** Playback cadence
can be retuned per lot and per beat without re-executing anything, which is why
tuning the film never required another live run.

---

## Reading one

The flagship case, `LOT-1002`:

```bash
python -c "
import json
m = json.load(open('golden-runs/LOT-1002/manifest.json'))
print(m['terminal_outcome'], '|', m['mutation']['action'], '|', m['mutation']['capability_id'])
for r in m['production_consequence']['readiness_changes']:
    print(r['order_id'], r['from'], '->', r['to'], '|', r['reason'])
"
```

```
QUARANTINE | quarantine_lot | CAP-5b14575c4ebe4f0e
C-417 AT_RISK -> BLOCKED | MAT-ALLOY-7 short by 400.0 (need 900.0, have 500.0)
```

The recovery block in the same manifest carries the four candidates that were
evaluated, including the substitute that was **refused with 900 units in
stock** because it is not approved for product P-417.

---

## Integrity

`tests/v2/test_golden_runs.py` checks every package that is present, and states
the expected outcomes **in the test** rather than reading them from the package
— so a package that recorded the wrong thing fails instead of describing itself
as correct. It skips cleanly when `golden-runs/` is absent, so a checkout
without capture artifacts is not failed by their absence.

`scripts/sync_golden_to_frontend.py` copies these packages into the frontend
bundle input for recorded-run playback. `golden-runs/` stays the source of
truth; the test fails if the copy drifts.

---

## Provenance

- **All five lots, suppliers, specifications and certificates are synthetic.**
  See [`demo/evidence/MANIFEST.md`](../demo/evidence/MANIFEST.md) for the source
  documents and the brief that freezes their content.
- Presigned S3 URLs in captured `sources.json` expire minutes after capture.
  Where a captured URL was retained for shape, its credential components are
  placeholders — a real signature is never committed.
- Each package records one execution on a stated runtime version and date. The
  live model path is non-deterministic, so a fresh run is a new recording rather
  than a replay of these.
- Timing is not captured here, by design: `beats.json` stores boundaries so
  playback cadence can be retuned without re-executing. Latency and token counts
  are not in these packages.
