/**
 * The deterministic visual baseline for Hero A. DEV/TEST ONLY.
 *
 * WHY THIS EXISTS
 *
 * Hero A is genuinely nondeterministic on the live model path: the same lot and
 * the same document reach QUARANTINE on some runs and abstain to
 * INSUFFICIENT_EVIDENCE on others. Both are correct — the abstention is the
 * product refusing to answer on evidence it cannot establish — and the live E2E
 * must keep accepting either.
 *
 * That makes a live run a bad visual regression baseline. Screenshots taken
 * from whichever outcome Nova happened to produce would change meaning between
 * runs, and a diff would report a product regression when nothing regressed.
 *
 * So the two concerns are separated:
 *
 *   - LIVE QUALIFICATION  (`e2e/hero-a.mjs`) proves the real stack works and
 *     records whichever valid outcome occurred. It is evidence, not a baseline.
 *   - VISUAL BASELINE     (this file) pins ONE canonical state — QUARANTINE —
 *     so a screenshot diff means a rendering change and nothing else.
 *
 * WHAT MAKES THIS HONEST
 *
 * The fixture is not hand-written. It is a verbatim capture of a REAL decision
 * from the authoritative DynamoDB record — 76 lifecycle events and the stored
 * document, including its 2 canonical claims — taken from a run that actually
 * happened. It renders through the SAME `project()` adapter the live path uses,
 * so it exercises the real projection rather than a parallel one.
 *
 * It is therefore a frozen recording of production truth, not invented data.
 *
 * WHY IT CANNOT REACH PRODUCTION
 *
 * This module is imported only from within an `import.meta.env.DEV` branch in
 * `main.tsx`. Vite replaces DEV with `false` in a production build, so the
 * branch is dropped, the dynamic import is never emitted, and neither this file
 * nor its fixture appears in the shipped bundle. `build-excludes-harness.test.ts`
 * asserts that against the real production build.
 */

import { StrictMode, useMemo, type ReactNode } from 'react';
import { DecisionWorkspace } from '../decision/DecisionWorkspace';
import { project } from '../decision/adapter';
import { mergeEvents } from '../decision/useDecisionRun';
import type { EvaluateDTO, LifecycleEventDTO, SourceArtifactDTO } from '../decision/dto';
import capture from './fixtures/hero-a-quarantine.json';

interface Capture {
  decision_record_id: string;
  record: Record<string, unknown>;
  events: LifecycleEventDTO[];
}

const CAPTURED = capture as unknown as Capture;

/**
 * Rebuild the source artifacts the way the live path does.
 *
 * `get_source` derives them from the evidence lifecycle events, so deriving
 * them here from the same events keeps the baseline on the real code path
 * instead of restating artifacts as literals.
 */
function sourcesFrom(events: LifecycleEventDTO[]): SourceArtifactDTO[] {
  const byId = new Map<string, SourceArtifactDTO>();
  for (const e of events) {
    const id = typeof e.artifact_id === 'string' ? e.artifact_id : '';
    if (!id) continue;
    const entry: SourceArtifactDTO =
      byId.get(id) ?? ({ artifact_id: id, security_state: 'PENDING' } as SourceArtifactDTO);
    if (e.event === 'EVIDENCE_RECEIVED') {
      entry.trust_class = typeof e.trust_label === 'string' ? e.trust_label : undefined;
      entry.content_hash = typeof e.content_hash === 'string' ? e.content_hash : undefined;
      entry.object_version = typeof e.object_version === 'string' ? e.object_version : undefined;
      entry.content_type = typeof e.content_type === 'string' ? e.content_type : undefined;
    } else if (e.event === 'EVIDENCE_SECURITY_COMPLETED') {
      entry.security_state = e.quarantined === true ? 'QUARANTINED' : 'CLEARED';
    } else if (e.event === 'EVIDENCE_EXTRACTED') {
      entry.claim_count = typeof e.claim_count === 'number' ? e.claim_count : undefined;
      entry.extraction_method = typeof e.method === 'string' ? e.method : undefined;
    } else if (e.event === 'EVIDENCE_BINDING_COMPLETED') {
      entry.document_identity =
        typeof e.document_identity === 'string' ? e.document_identity : entry.document_identity;
    }
    byId.set(id, entry);
  }
  // No `view_ref`: nothing can be signed offline, and the viewer's
  // "source unavailable" state is itself part of the baseline.
  return [...byId.values()].map((a) => ({ ...a, document_type: a.document_type ?? 'COA' }));
}

/**
 * The Hero B and Hostile baselines, from the SAME real-capture discipline.
 *
 * These two are `evaluate_lot` / `supply_evidence` responses rather than stored
 * records, so they need no reconstruction: the response IS the terminal frame.
 * They deliberately reuse `DecisionWorkspace` and `project()` — the point of
 * the gate is that the existing workspace generalizes, so a second rendering
 * path here would prove nothing.
 */
export function CaptureBaseline({
  capture: dto,
  state,
  lotId,
  material,
  receiptMeta,
}: {
  capture: EvaluateDTO;
  state: string;
  lotId: string;
  material: string;
  receiptMeta: string;
}) {
  const vm = useMemo(() => {
    const events = mergeEvents([], (dto.events ?? []) as LifecycleEventDTO[]);
    return project({
      decisionRecordId: dto.decision_record_id,
      lotId,
      material,
      receiptMeta,
      events,
      result: dto,
      sources: sourcesFrom(events),
      running: false,
      durable: true,
    });
  }, [dto, lotId, material, receiptMeta]);

  return (
    <div data-testid="visual-baseline" data-baseline-state={state}>
      <DecisionWorkspace vm={vm} />
    </div>
  );
}

export function HeroAVisualBaseline() {
  const vm = useMemo(() => {
    // Through the SAME dedupe the live path uses, not around it.
    //
    // The capture is the raw durable stream, and the backend deliberately
    // double-writes every event — once live from the sink so a UI can watch,
    // once in the terminal batch so the record is complete. This capture is 76
    // rows for 38 distinct events, each with its own sequence and event_id.
    //
    // Feeding those in raw produced duplicate React keys, which is how this
    // baseline earned its keep on the first run: the deterministic replay
    // surfaced the collision immediately, where a live run's timing hid it.
    const events = mergeEvents([], CAPTURED.events);
    const record = CAPTURED.record;
    const disposition = (record.disposition ?? {}) as Record<string, unknown>;

    // The terminal response, reconstructed from the stored record. The adapter
    // reads the same fields either way.
    const result = {
      ok: true,
      action: 'evaluate_lot',
      backend: { mode: 'production', durable: true },
      decision_record_id: CAPTURED.decision_record_id,
      lot_id: String(record.lot_id ?? ''),
      disposition: String(disposition.disposition ?? ''),
      failure_category: '',
      quality_decision_required: false,
      reason: String(disposition.reason ?? ''),
      mutation: (record.mutation ?? {}) as Record<string, unknown>,
      events,
    } as unknown as EvaluateDTO;

    return project({
      decisionRecordId: CAPTURED.decision_record_id,
      lotId: String(record.lot_id ?? ''),
      material: 'MAT-ALLOY-7',
      receiptMeta: 'SUP-EAST · site SITE-E1 · 400 kg',
      events,
      result,
      sources: sourcesFrom(events),
      record,
      running: false,
      durable: true,
    });
  }, []);

  return (
    <div data-testid="visual-baseline" data-baseline-state="QUARANTINE">
      <DecisionWorkspace vm={vm} />
    </div>
  );
}

/**
 * Which non-Hero-A journeys have a pinned baseline, and what each concludes.
 *
 * This table lives HERE rather than in `main.tsx` on purpose: naming an outcome
 * is exactly what the product surface must never do, and
 * `production-safety.test.ts` enforces that. This module is DEV-only and is
 * dropped from the production bundle, so a fixture outcome named here cannot
 * ship or influence what Vouch derives at runtime.
 */
const BASELINE_ROUTES: Record<
  string,
  {
    state: string;
    lotId: string;
    material: string;
    receiptMeta: string;
    load: () => Promise<{ default: unknown }>;
  }
> = {
  '/dev/baseline/hero-b-run1': {
    state: 'QUALITY_DECISION_REQUIRED',
    lotId: 'LOT-1004',
    material: 'MAT-POLY-3',
    receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
    load: () => import('./fixtures/hero-b-run1.json'),
  },
  '/dev/baseline/hero-b-run2': {
    state: 'RELEASE',
    lotId: 'LOT-1004',
    material: 'MAT-POLY-3',
    receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
    load: () => import('./fixtures/hero-b-run2.json'),
  },
  '/dev/baseline/hostile': {
    state: 'SECURITY_QUARANTINE',
    lotId: 'LOT-1005',
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-EAST · site SITE-E1 · 300 kg',
    load: () => import('./fixtures/hostile.json'),
  },
};

export async function renderBaselineRoute(
  pathname: string,
  root: { render: (node: ReactNode) => void },
): Promise<void> {
  const spec = BASELINE_ROUTES[pathname];
  if (!spec) return;
  const capture = await spec.load();
  root.render(
    <StrictMode>
      <CaptureBaseline
        capture={capture.default as EvaluateDTO}
        state={spec.state}
        lotId={spec.lotId}
        material={spec.material}
        receiptMeta={spec.receiptMeta}
      />
    </StrictMode>,
  );
}
