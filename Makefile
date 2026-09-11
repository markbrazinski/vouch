# Vouch — developer shortcuts.
#
# Deliberately thin. These wrap commands that already exist; none of them is a
# second implementation of anything.

AWS := AWS_PROFILE=gatehouse AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
PY  := .venv/bin/python

.PHONY: reseed check-seed bff ui test fast gate full live slowest

## Reset the demo corpus. Run before EVERY live Hero A take: a repeat run on a
## lot that is already quarantined is refused by the authority gate, correctly.
reseed:
	$(AWS) $(PY) scripts/seed_demo_corpus.py

## Prove the corpus is film-ready: LOT-1002 RECEIVED, C-417 READY.
check-seed:
	@curl -s "http://127.0.0.1:8787/api/decisions?limit=50" | $(PY) -c "import json,sys; r=[x for x in json.load(sys.stdin)['rows'] if x['lot_id']=='LOT-1002'][0]; print('LOT-1002', r['lot_status'], '<- expect RECEIVED')"
	@curl -s http://127.0.0.1:8787/api/today | $(PY) -c "import json,sys; o=[o for l in json.load(sys.stdin)['lines'] for o in l['orders'] if o['order_id']=='C-417'][0]; print('C-417   ', o['status'], '<- expect READY')"

bff:
	$(AWS) $(PY) scripts/local_bff.py

ui:
	cd frontend && VOUCH_BFF=http://127.0.0.1:8787 npm run dev

# ---------------------------------------------------------------------------
# Test tiers. Pick the smallest one that can disprove the change you made.
#
# The suite is ~900 tests and already fast; the point of tiering is SELECTION,
# not speed. Nothing here weakens an assertion or drops unique coverage —
# `full` still runs every test that `fast` and `gate` run.
# ---------------------------------------------------------------------------

## TIER 1 — inner loop (<60s budget; ~4s actual). Run after normal edits.
## Backend minus the deliberate-sleep concurrency probes, frontend minus the
## real-vite-build and real-poll-interval tests. Those belong to `gate`/`full`.
fast:
	$(PY) -m pytest tests/ -q --deselect tests/v2/test_inflight_discovery.py
	cd frontend && npx vitest run \
	  --exclude '**/build-excludes-harness.test.ts' \
	  --exclude '**/async-transport.test.tsx' \
	  --exclude '**/film-gate.test.tsx'

## TIER 2 — Vouch feature gate (<5min budget; ~6s actual). The normal
## "commission complete" gate: the demo-critical product contract only.
gate:
	$(PY) -m pytest -q \
	  tests/v2/test_canonical_pdf_pipeline.py \
	  tests/v2/test_today_causal_story.py \
	  tests/v2/test_security_redteam.py \
	  tests/v2/test_evidence_binding.py \
	  tests/v2/test_quality_authority.py \
	  tests/v2/test_restart_resume.py \
	  tests/v2/test_record_completeness.py \
	  tests/v2/test_identity_confidence_gate.py \
	  tests/v2/test_canonical_demo_data.py
	cd frontend && npx vitest run \
	  src/features/__tests__/today-causal.test.ts \
	  src/features/__tests__/incoming.test.ts \
	  src/features/__tests__/records.test.ts \
	  src/decision/__tests__/workspace.test.tsx \
	  src/decision/__tests__/hero-b-hostile.test.ts \
	  src/decision/__tests__/hero-b-rendering.test.tsx \
	  src/decision/__tests__/stored-decision.test.ts \
	  src/decision/__tests__/quality-authority.test.tsx \
	  src/decision/__tests__/adapter.test.ts \
	  src/app/__tests__/routing.test.tsx \
	  src/decision/replay/__tests__/film.test.tsx

## TIER 3 — full regression (~26s). Shared contracts, authority/mutation code,
## canonical fixtures, PDF/evidence pipeline, merge, deploy, film freeze.
full test:
	$(PY) -m pytest tests/ -q
	cd frontend && npx vitest run

## TIER 4 — live AWS qualification. Real credentials, real Bedrock/AgentCore.
## Separate from regression by design: only run when AWS-dependent behavior
## changed. Without VOUCH_LIVE_AWS=1 these tests skip, which is why Tier 3
## reports skips rather than failures on a laptop.
live:
	$(AWS) VOUCH_LIVE_AWS=1 $(PY) -m pytest tests/ -q

## Slowest tests, for keeping the tiers honest as the suite grows.
slowest:
	$(PY) -m pytest tests/ -q --durations=20
