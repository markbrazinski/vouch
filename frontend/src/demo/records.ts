/**
 * Archived DecisionRecords, their events, and their source documents.
 *
 * Reached from Records after a run has been played, and from the workspace's
 * artifact panel. Everything served here is the captured package — the same
 * record the deployed runtime wrote, the same lifecycle events, the same
 * certificate bytes.
 *
 * THE SOURCE DOCUMENT IS A LOCAL ASSET, NOT A PRESIGNED URL.
 *
 * In live mode `get_source` returns a 300s presigned S3 link. Those expire, and
 * a clone has no bucket to sign against, so an archived run points at the
 * canonical PDF bundled into the build instead — the SAME tracked file the live
 * path uploads, imported through Vite so the bytes cannot drift from the ones
 * the capture was made against.
 *
 * LOT-1005's hostile certificate keeps its deliberate-view behaviour: the
 * record marks it quarantined and excluded from decision use, the viewer reads
 * that from the record exactly as it does live, and nothing here relaxes it.
 */

import { DEMO_LOTS } from './backend';

/** Lot -> the canonical certificate that arrived with it. */
const ASSETS: Record<string, () => Promise<string>> = {
  'LOT-1001': () => import('../evidence/northern-alloys-coa-lot-1001.pdf?url').then((m) => m.default),
  'LOT-1002': () => import('../evidence/eastern-metals-coa-lot-1002.pdf?url').then((m) => m.default),
  'LOT-1003': () => import('../evidence/western-polymers-coa-lot-1003.pdf?url').then((m) => m.default),
  'LOT-1004': () =>
    import('../evidence/northern-alloys-coa-batch-wp-26-0317-b.pdf?url').then((m) => m.default),
  'LOT-1005': () =>
    import('../evidence/central-forgeworks-coa-lot-1005.pdf?url').then((m) => m.default),
};

interface Package {
  events: unknown[];
  result: Record<string, unknown>;
  record: Record<string, unknown>;
  sources: Record<string, unknown>[];
  lotId: string;
}

/** Every archived package, indexed by the record id it was written under. */
let index: Map<string, Package> | null = null;

async function load(lotId: string): Promise<Package> {
  const [events, result, record, sources] = await Promise.all([
    import(`./packages/${lotId}/events.json`),
    import(`./packages/${lotId}/result.json`),
    import(`./packages/${lotId}/decision-record.json`),
    import(`./packages/${lotId}/sources.json`),
  ]);
  return {
    events: events.default,
    result: result.default,
    record: record.default,
    sources: sources.default,
    lotId,
  };
}

async function byRecordId(): Promise<Map<string, Package>> {
  if (index) return index;
  const loaded = await Promise.all(DEMO_LOTS.map(load));
  index = new Map(loaded.map((p) => [String(p.result.decision_record_id ?? ''), p]));
  return index;
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });

const BACKEND = {
  mode: 'archive',
  corpus: 'ARCHIVED_GOLDEN_RUN',
  evidence_store: 'LOCAL_CANONICAL_ASSET',
  reasoners: 'BEDROCK_NOVA',
  // The captured run WAS durable when it executed. This replay is not writing
  // anything, and says so rather than claiming a live store.
  durable: true,
};

/**
 * `/api/decisions/:id`, `/:id/events`, `/:id/sources`, answered from the archive.
 *
 * Returns `null` for a record the archive does not hold, which the interceptor
 * turns into an explicit "no archived answer" rather than a network call.
 */
export async function archivedRecordRoutes(
  parts: string[],
  url: URL,
): Promise<Response | null> {
  if (parts[0] !== 'decisions' || parts.length < 2) return null;
  const found = (await byRecordId()).get(parts[1]);
  if (!found) return null;

  if (parts.length === 2) {
    return json({
      ok: true,
      action: 'get_decision',
      backend: BACKEND,
      decision_record_id: parts[1],
      record: found.record,
      sources: found.sources,
    });
  }

  if (parts[2] === 'events') {
    return json({
      ok: true,
      action: 'get_events',
      backend: BACKEND,
      decision_record_id: parts[1],
      events: found.events,
    });
  }

  if (parts[2] === 'sources') {
    const wanted = url.searchParams.get('artifact_id');
    const asset = ASSETS[found.lotId];
    const href = asset ? await asset() : '';
    // `view_ref` points at the bundled asset. The client fetches it, re-types
    // the blob from the record's own `content_type` and frames it — the same
    // path it takes with a presigned URL, so nothing about the viewer changes.
    const sources = found.sources
      .filter((s) => !wanted || s.artifact_id === wanted)
      .map((s) => ({ ...s, view_ref: href }));
    return json({
      ok: true,
      action: 'get_source',
      backend: BACKEND,
      decision_record_id: parts[1],
      sources,
      retrieval_available: Boolean(href),
    });
  }

  return null;
}
