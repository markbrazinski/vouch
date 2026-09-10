import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import './app/global.css';
import { RoutedShell } from './app/RoutedShell';
import type { ArrivalDocuments, HeroAEntry } from './decision/entry';
// Vite emits this as a fingerprinted asset URL. The file is a symlink to the
// canonical tracked evidence, so the build cannot ship different bytes.
import COA_1001 from './evidence/northern-alloys-coa-lot-1001.pdf?url';
import HERO_A_COA from './evidence/eastern-metals-coa-lot-1002.pdf?url';
import COA_BATCH_WP from './evidence/northern-alloys-coa-batch-wp-26-0317-b.pdf?url';
import COA_1004 from './evidence/central-forgeworks-coa-lot-1005.pdf?url';
import COA_1006 from './evidence/western-polymers-coa-lot-1003.pdf?url';

const root = createRoot(document.getElementById('root')!);

/**
 * The arrival Hero A opens.
 *
 * This is receipt IDENTITY, not a decision outcome: the lot, what it is, and
 * the supplier's own certificate. Nothing here says what Vouch will conclude —
 * the disposition, the governing basis and every consequence come from the
 * backend as the decision runs.
 *
 * The document is the CANONICAL tracked asset, not a transcription of it.
 * `demo/evidence/eastern-metals-coa-lot-1002.pdf` is the exact PDF qualified by
 * the canonical PDF gate (SHA-256 4d36065a15b5…, frozen in
 * `demo/evidence/MANIFEST.md` and re-checked by
 * `tests/v2/test_canonical_pdf_assets.py`). `src/evidence/` symlinks it rather
 * than copying it, so the bytes the UI submits cannot drift from the bytes that
 * were qualified.
 *
 * It is imported as a Vite URL asset: the bundler fingerprints and emits it, so
 * there is no developer absolute path and the production build carries the file
 * it references. The bytes are fetched and base64-encoded at click time and
 * handed to the SAME `evaluate_lot` ingestion path a text document uses — the
 * backend already accepts `document_b64` + `content_type`, so this adds no
 * PDF-specific decision path.
 *
 * The certificate declares CONFORMS and cites revision B; whether that revision
 * still governs is exactly the question the Investigator and Verifier answer,
 * and neither this file nor any other part of the frontend presumes the answer.
 */
const HERO_A: HeroAEntry = {
  lotId: 'LOT-1002',
  material: 'MAT-ALLOY-7',
  receiptMeta: 'SUP-EAST · site SITE-E1 · 400 kg',
  contentType: 'application/pdf',
  documentUrl: HERO_A_COA,
  documentName: 'eastern-metals-coa-lot-1002.pdf',
};

/**
 * Every canonical arrival and the certificate that came with it.
 *
 * One entry per lot Incoming lists. Each document is attached ONLY to the lot
 * its supplier issued it for — sending Northern Alloys' report with LOT-1005
 * would assert they certified Central Forgeworks' material — and a lot with no
 * entry here simply starts from the evidence already on its record, which is
 * what the backend does when no document is supplied.
 *
 * The outcomes these produce (release, quarantine, unbound, security halt) are
 * the backend's to decide. Nothing here presumes any of them.
 */
const ARRIVALS: ArrivalDocuments = {
  'LOT-1001': {
    lotId: 'LOT-1001',
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-NORTH · site SITE-N1 · 500 kg',
    contentType: 'application/pdf',
    documentUrl: COA_1001,
    documentName: 'northern-alloys-coa-lot-1001.pdf',
  },
  'LOT-1002': HERO_A,
  'LOT-1004': {
    lotId: 'LOT-1004',
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-NORTH · site SITE-N1 · 450 kg',
    contentType: 'application/pdf',
    documentUrl: COA_BATCH_WP,
    documentName: 'northern-alloys-coa-batch-wp-26-0317-b.pdf',
  },
  'LOT-1005': {
    lotId: 'LOT-1005',
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-CENTRAL · site SITE-C1 · 200 kg',
    contentType: 'application/pdf',
    documentUrl: COA_1004,
    documentName: 'central-forgeworks-coa-lot-1005.pdf',
  },
  'LOT-1003': {
    lotId: 'LOT-1003',
    material: 'MAT-RESIN-3',
    receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
    contentType: 'application/pdf',
    documentUrl: COA_1006,
    documentName: 'western-polymers-coa-lot-1003.pdf',
  },
};

// The dev fixture harness is referenced only inside this `import.meta.env.DEV`
// branch. Vite replaces DEV with `false` in a production build, so the branch
// and its dynamic import are dropped and the harness chunk is never emitted.
if (import.meta.env.DEV && window.location.pathname === '/dev/vouch-states') {
  void import('./dev/VouchStateHarness').then(({ VouchStateHarness }) =>
    root.render(
      <StrictMode>
        <VouchStateHarness />
      </StrictMode>,
    ),
  );
} else if (import.meta.env.DEV && window.location.pathname === '/dev/visual-baseline') {
  // The deterministic visual baseline. Live Hero A legitimately reaches more
  // than one valid outcome, so screenshots must not be taken from whichever one
  // the model produced last. This route replays a captured real decision so a
  // pixel diff means a rendering change. DEV-only; dropped from the production
  // bundle, and the state it pins is named in the baseline module, not here.
  void import('./dev/HeroAVisualBaseline').then(({ HeroAVisualBaseline }) =>
    root.render(
      <StrictMode>
        <HeroAVisualBaseline />
      </StrictMode>,
    ),
  );
} else if (import.meta.env.DEV && window.location.pathname.startsWith('/dev/baseline/')) {
  // Hero B (both runs) and the hostile path, pinned the same way and for the
  // same reason as Hero A. Which journeys exist, and what each concludes, is
  // declared inside the DEV-only module — never here: `main.tsx` is product
  // surface and must not name an outcome Vouch is supposed to derive.
  void import('./dev/HeroAVisualBaseline').then(({ renderBaselineRoute }) =>
    renderBaselineRoute(window.location.pathname, root),
  );
} else {
  // The URL is the source of truth for navigation. `BrowserRouter` uses real
  // history, so Back and Forward are the browser's own and a refresh on any
  // routed path reconstructs that surface from authoritative state.
  root.render(
    <StrictMode>
      <BrowserRouter>
        <RoutedShell entry={HERO_A} arrivals={ARRIVALS} />
      </BrowserRouter>
    </StrictMode>,
  );
}
