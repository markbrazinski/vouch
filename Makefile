# Vouch — developer shortcuts.
#
# Deliberately thin. These wrap commands that already exist; none of them is a
# second implementation of anything.

AWS := AWS_PROFILE=gatehouse AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1
PY  := .venv/bin/python

.PHONY: reseed check-seed bff ui test

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

test:
	$(PY) -m pytest tests/ -q && cd frontend && npx vitest run
