# Canonical Supplier Evidence — Manifest

The five synthetic supplier documents the Vouch demo runs on. They are the
**exact bytes** that were qualified: each one was run through the real evidence
pipeline (real `pypdf` extraction, real deterministic parser, real security
inspection, real binding) before being tracked here.

Content is frozen by
`contracts/demo/VOUCH_V2_CANONICAL_SUPPLIER_DOCUMENT_BRIEF.md`.
`tests/v2/test_canonical_pdf_assets.py` re-checks these hashes and facts on
every run, so a re-export that changes a measurement, an identifier or the
hostile payload fails the build rather than silently reaching a demo.

**All five are wholly synthetic.** No real company, plant, person or
certificate is represented, and each document says so on its face.

The first four form a deliberate increasing-complexity ladder: a normal
release, a release that cannot be defended, evidence that cannot be safely
attached to a lot until a human says whose it is, and evidence that attacks the
reader. The fifth is a
different axis entirely — evidence that is entirely legitimate and still cannot
be acted on autonomously, because it supports two defensible readings.

---

## northern-alloys-coa-lot-1001.pdf

| | |
|---|---|
| Supplier | Northern Alloys (`SUP-NORTH`), site `SITE-N1` |
| Lot | `LOT-1001` · `MAT-ALLOY-7` · PO-77 · 500 kg |
| Document type | Certificate of Analysis |
| Cites | `SPEC-A7` **Revision C** (the governing revision) |
| Measurements | tensile_strength 512 MPa (ASTM-E8, room_temp) · hardness 31 HRC (HRC, as_received) |
| SHA-256 | `765839cc6520c58e454622ee280b5bea2498d24e7629298a26d32a3b10dee181` |
| Intended path | **ordinary extraction** — Textract NOT required |
| Qualified outcome | 2 claims @ confidence 1.0 → `BOUND` → both agents agree → `RELEASE` → `release_lot` → `LOT-1001` RELEASED, 500 kg becomes usable inventory |

The clean baseline. It teaches the normal Vouch grammar: ordinary evidence,
ordinary extraction, independent agreement, an authorized mutation.

## eastern-metals-coa-lot-1002.pdf

| | |
|---|---|
| Supplier | Eastern Metals (`SUP-EAST`), site `SITE-E1` |
| Lot | `LOT-1002` · `MAT-ALLOY-7` · PO-78 · 400 kg |
| Document type | Certificate of Analysis |
| Cites | `SPEC-A7` **Revision B** (superseded; `C` governs on receipt) |
| Measurements | tensile_strength 462 MPa (ASTM-E8, room_temp) · hardness 30 HRC (HRC, as_received) |
| SHA-256 | `bf3e80258af52dd098bc5a76e18b3603e024c3276bb56bdf9816f64fd5f459be` |
| Intended path | **ordinary extraction** — Textract NOT required |
| Qualified outcome | 2 claims @ confidence 1.0 → `BOUND` → both agents → `QUARANTINE` → `quarantine_lot` → `LOT-1002` QUARANTINED |

The supplier's own conclusion is `CONFORMS`, and against the revision it cites
that is true. Reconciliation against the revision that actually governs on
receipt is what changes the answer.

## northern-alloys-coa-batch-wp-26-0317-b.pdf

| | |
|---|---|
| Supplier | Northern Alloys (`SUP-NORTH`), site `SITE-N1` |
| Internal lot | `LOT-1003` · `MAT-ALLOY-7` · PO-82 · 450 kg |
| **Supplier batch (printed)** | **`WP-26-0317-B`** |
| Document type | Certificate of Analysis |
| Cites | `SPEC-A7` **Revision C** (the governing revision) |
| Measurements | tensile_strength 512 MPa (ASTM-E8, room_temp) · hardness 31 HRC (HRC, as_received) |
| SHA-256 | `326b4463ab1bf4222ea8466cc0997508a0f5e4bd0bec51180888054cc8721242` |
| Intended path | **ordinary extraction** — Textract NOT required |
| Qualified outcome | 2 claims @ confidence 1.0 → `UNRESOLVED_SUPPLIER_BATCH` → identity question → human confirms `WP-26-0317-B` = `LOT-1003` → **same record, run 2** → both agents → `RELEASE` → `release_lot` → 450 kg usable |

The human-resolvable case. The certificate is legitimate, parses cleanly,
clears security and extracts both measurements at full confidence. Supplier,
site, material and PO all agree with the receipt. The one thing it does not do
is name a Vouch lot — it names the supplier's own consignment, and nothing
authoritative maps `WP-26-0317-B` to `LOT-1003` until Quality establishes it.

> **The document must not name a Vouch lot.** Any `LOT-####` string on the page
> binds the certificate immediately and the human is never asked anything. This
> is not hypothetical: the document is derived from the LOT-1001 certificate and
> two re-renders reintroduced a `LOT` field printing `LOT-1001`, which resolved
> to `EVIDENCE_BINDING_MISMATCH` — "this is about another lot" — and skipped the
> identity question entirely. `test_pdf2_names_its_own_batch_and_never_a_vouch_lot`
> asserts on the PATTERN, not on that one known-bad value.

> **Nothing here is hard to read, and that is the point.** The predecessor was a
> table-based mill test report whose refusal turned on Textract cell confidence,
> which made a valid authority control look like an OCR failure. Extraction now
> succeeds completely and the refusal has exactly one cause: Vouch cannot prove
> whose lot these results describe. A perfectly valid test result for Lot A must
> never accidentally release Lot B.

Its 450 kg is deliberately too little to change the readiness of `C-417`,
`C-418` or `C-419`, so this case tells its own story without disturbing Hero A
or the LOT-1006 disagreement.

## central-forgeworks-coa-lot-1004.pdf

| | |
|---|---|
| Supplier | Central Forgeworks (`SUP-CENTRAL`), site `SITE-C1` |
| Lot | `LOT-1004` · `MAT-ALLOY-7` · PO-80 · 200 kg |
| Document type | Certificate of Analysis (**hostile**) |
| Cites | `SPEC-A7` Revision C |
| Measurements | tensile_strength 402 MPa (ASTM-E8, room_temp) |
| Payload | prompt-injection text in SUPPLEMENTAL REMARKS, as real selectable PDF text |
| SHA-256 | `5cc20bcbf5b74347158a8cef65894e9243ed4809a008f42ef1debf7275d03947` |
| Intended path | **security quarantine before any agent runs** |
| Qualified outcome | injection `DETECTED` → `SECURITY_QUARANTINE` → artifact retained and `excluded_from_decision_use` → neither agent started → zero mutation → `LOT-1004` stays `RECEIVED` |

The 402 MPa value would fail Revision C anyway. That is deliberate: the security
control fires **before** the quality question is reached, so the demonstrated
outcome can never be mistaken for a quality verdict.

## western-polymers-coa-lot-1006.pdf

| | |
|---|---|
| Supplier | Western Polymers (`SUP-WEST`), site `SITE-W1` |
| Lot | `LOT-1006` · `MAT-RESIN-3` · PO-86 · 200 kg |
| Document type | Certificate of Analysis |
| Cites | `SPEC-R3` **Revision A** (the governing revision) |
| Measurements | viscosity **178 cP** (ASTM-D2196, 25C) · viscosity 312 cP (ASTM-D445, 25C) |
| SHA-256 | `e2ea3ff42082fb6eedf49aaa8249cfb316f0c6296eb6bd50df5ad843718087b4` |
| Intended path | **ordinary extraction** — Textract NOT required |
| Qualified outcome | 2 claims @ confidence 1.0 → `BOUND` → agents select DIFFERENT evidence → `MATERIAL_DISAGREEMENT` → quality question → human authorizes applicability → **same record, run 2** → agents converge → `RELEASE` → `release_lot` → 200 kg usable → C-419 `AT_RISK → READY` |

Two viscosity results for the same governed characteristic, both real and both
applicable: one by `ASTM-D2196` at 25C, the method `SPEC-R3:A` names outright,
and one by `ASTM-D445` at 25C, which `EQV-1` genuinely covers for this
material, characteristic and condition. Nothing in the corpus ranks a
direct-method result against an equivalence-covered one, so which of the two
establishes the requirement is a real authority question with two defensible
answers.

**They point opposite ways against the `[200, 400] cP` limit.** 178 cP fails
it; 312 cP passes. That is deliberate, and it is what makes the human question
load-bearing: establish the direct result and the lot quarantines, establish
the equivalence-covered one and it releases. An earlier version had both
values passing, which made the disagreement real and the decision ceremonial —
whichever path was chosen the disposition was RELEASE and the answer changed
only a reason string.

The human never says RELEASE or QUARANTINE. They name which measurement is
controlling; the deterministic engine draws the conclusion.

> **The document must not resolve what it creates.** It names no equivalence
> record, states no precedence between the two methods, and contains no
> instruction about what to conclude. `EQV-1` is an internal authoritative
> object; a supplier document naming it would be asserting its own
> applicability, which is exactly the question a human is asked to settle.
> `test_pdf4_states_both_viscosity_paths_and_neither_precedence` pins this.

> Note `EQV-1` is the **same** record that does NOT cover `LOT-1005`'s 40C
> result. One equivalence, two lots, opposite outcomes, decided entirely by
> condition scope — the scoping field doing real work in both directions.
