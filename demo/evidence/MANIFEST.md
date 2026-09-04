# Canonical Supplier Evidence — Manifest

The three synthetic supplier documents the Vouch demo runs on. They are the
**exact bytes** that were qualified: each one was run through the real evidence
pipeline (real `pypdf` extraction, real deterministic parser, real security
inspection, real binding) before being tracked here.

Content is frozen by
`contracts/demo/VOUCH_V2_CANONICAL_SUPPLIER_DOCUMENT_BRIEF.md`.
`tests/v2/test_canonical_pdf_assets.py` re-checks these hashes and facts on
every run, so a re-export that changes a measurement, an identifier or the
hostile payload fails the build rather than silently reaching a demo.

**All three are wholly synthetic.** No real company, plant, person or
certificate is represented, and each document says so on its face.

---

## eastern-metals-coa-lot-1002.pdf

| | |
|---|---|
| Supplier | Eastern Metals (`SUP-EAST`), site `SITE-E1` |
| Lot | `LOT-1002` · `MAT-ALLOY-7` · PO-78 · 400 kg |
| Document type | Certificate of Analysis |
| Cites | `SPEC-A7` **Revision B** (superseded; `C` governs on receipt) |
| Measurements | tensile_strength 462 MPa (ASTM-E8, room_temp) · hardness 30 HRC (HRC, as_received) |
| SHA-256 | `4d36065a15b5a60bfd90d8004784c81de24da0b0a6768fdd2caa296b05ca5ac7` |
| Intended path | **ordinary extraction** — Textract NOT required |
| Qualified outcome | 2 claims @ confidence 1.0 → `BOUND` → both agents → `QUARANTINE` → C-417 `READY→BLOCKED` |

## northern-alloys-mtr-lot-1001.pdf

| | |
|---|---|
| Supplier | Northern Alloys (`SUP-NORTH`), site `SITE-N1` |
| Lot | `LOT-1001` · `MAT-ALLOY-7` · PO-77 · 500 kg |
| Document type | Materials Test Report |
| Cites | `SPEC-A7` **Revision C** (the governing revision) |
| Measurements | tensile_strength 512 MPa (ASTM-E8, Room Temperature) · hardness 31 HRC (HRC, As Received) |
| Supporting synthetic facts | heat H-4471 · C 0.41% · Mn 1.12% · diameter 50.0 mm |
| SHA-256 | `3e9af50d2b56e9dc59151c1b9dd3005916e375baa23053c5bb3604300aae0ccf` |
| Intended path | **`Textract AnalyzeDocument(TABLES)`** — results live in a real table |
| Qualified outcome | ordinary extraction yields **0 claims** → `structure_needed()` fires → identity still `BOUND` → abstains safely with no mutation until structure recovery runs |

## central-forgeworks-coa-lot-1004.pdf

| | |
|---|---|
| Supplier | Central Forgeworks (`SUP-CENTRAL`), site `SITE-C1` |
| Lot | `LOT-1004` · `MAT-ALLOY-7` · PO-80 · 200 kg |
| Document type | Certificate of Analysis (**hostile**) |
| Cites | `SPEC-A7` Revision C |
| Measurements | tensile_strength 402 MPa (ASTM-E8, room_temp) |
| Payload | prompt-injection text in SUPPLEMENTAL REMARKS, as real selectable PDF text |
| SHA-256 | `fd78264210f4314b69d801262e5a127f8f7b40ba82e80010fdd7f59d65c6ce75` |
| Intended path | **security quarantine before any agent runs** |
| Qualified outcome | injection `DETECTED` → `SECURITY_QUARANTINE` → artifact retained and `excluded_from_decision_use` → neither agent started → zero mutation → `LOT-1004` stays `RECEIVED` |

The 402 MPa value would fail Revision C anyway. That is deliberate: the security
control fires **before** the quality question is reached, so the demonstrated
outcome can never be mistaken for a quality verdict.
