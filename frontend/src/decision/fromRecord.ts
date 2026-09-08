/**
 * A SETTLED decision, rebuilt into the same workspace a live run renders.
 *
 * Records and Today open decisions that finished long ago. Those must show the
 * same thing a live run shows — one workspace, one projection — so this module
 * turns `get_decision` + `get_events` into a `ProjectInput` and hands it to the
 * SAME `project()` the live path uses. There is deliberately no second
 * rendering path: a parallel one could disagree with the live one about what a
 * decision concluded, and the whole point of the audit surface is that it
 * cannot.
 *
 * WHERE THE EVENTS COME FROM, AND WHY IT MATTERS
 *
 * `get_events` is the authoritative chronology. `get_decision` also carries a
 * `record.events` array, and it is NOT the same thing — it is a flattened
 * summary of the LAST RUN only:
 *
 *   DR-herob000001 (2 runs)   record.events  38 events, last run only
 *                             get_events    168 events, both runs
 *
 * and it drops the event types `project()` needs to see a run that did not
 * settle cleanly — `QUALITY_DECISION_REQUIRED` and `BRIEF_VALIDATION_FAILED`
 * are absent from it. Projecting the summary renders that decision as
 * "Released into usable inventory" when the truth is "Quality decision
 * required": a disposition the gate explicitly refused, asserted as an outcome.
 *
 * So `record.events` is non-authoritative for reconstruction and this module
 * refuses it structurally rather than by convention — `stripEvents` removes the
 * key before the record reaches `project()`, so there is nothing to fall back
 * TO even if a future caller tried. When the chronology is missing the caller
 * renders an unavailable state; it never infers one from the record.
 *
 * `fromRecordEvents` exists only so a regression test can prove the divergence
 * above is real. It is not exported to the app.
 */

import { project, type ProjectInput } from './adapter';
import { mergeEvents } from './useDecisionRun';
import type { DecisionWorkspaceVM } from './model';
import type { EvaluateDTO, LifecycleEventDTO, SourceArtifactDTO } from './dto';

/** Thrown when a settled decision has no authoritative chronology to project. */
export class ChronologyUnavailable extends Error {
  constructor(readonly decisionRecordId: string) {
    super('the decision chronology could not be read');
    this.name = 'ChronologyUnavailable';
  }
}

const str = (v: unknown): string => (typeof v === 'string' ? v : '');
const obj = (v: unknown): Record<string, unknown> =>
  v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>) : {};

/**
 * The record, minus its non-authoritative event summary.
 *
 * `project()` reads `record.evidence.canonical_claims` and nothing else from
 * the record's chronology, so dropping `events` costs the projection nothing
 * and removes the only thing a fallback could reach for.
 */
export function stripEvents(record: Record<string, unknown>): Record<string, unknown> {
  const { events: _discarded, ...rest } = record;
  return rest;
}

/**
 * The terminal response, reconstructed from the stored record.
 *
 * `project()` accepts either a live `evaluate_lot` response or a stored record;
 * both carry the same fields under the same names, so the settled path
 * synthesises the former from the latter rather than teaching the adapter a
 * second shape.
 */
function terminalFrom(
  decisionRecordId: string,
  record: Record<string, unknown>,
  events: LifecycleEventDTO[],
): EvaluateDTO {
  const disposition = obj(record.disposition);
  return {
    ok: true,
    action: 'evaluate_lot',
    backend: { mode: 'production', durable: true },
    decision_record_id: decisionRecordId,
    lot_id: str(record.lot_id) || str(obj(record.identity).lot_id),
    disposition: str(disposition.disposition),
    failure_category: str(record.failure_category),
    quality_decision_required: false,
    reason: str(disposition.reason),
    mutation: obj(record.mutation),
    // The authoritative consequence, carried through.
    //
    // `project()` reads readiness changes from either the response or the
    // READINESS_TRANSITIONED events, but recovery CANDIDATES exist only on
    // `consequences.recovery` — the events record that recovery ran and what it
    // executed, not the four candidates it weighed. Omitting this rendered a
    // settled Hero A with its consequence and resequence visible but the
    // refused substitute and the ineligible alternatives missing, which is the
    // part that shows Vouch considered and REJECTED options before moving the
    // plan. The record holds them; this hands them to the same projection the
    // live path feeds.
    consequences: obj(record.consequences),
    events,
  } as unknown as EvaluateDTO;
}

export interface StoredDecisionInput {
  decisionRecordId: string;
  /** `get_decision`'s `record`. */
  record: Record<string, unknown>;
  /** `get_decision`'s `sources`. */
  sources?: SourceArtifactDTO[];
  /** `get_events`' `events`. The ONLY accepted chronology. */
  events: LifecycleEventDTO[];
  /** Overrides for the identity line. Defaults come from `record.identity`. */
  material?: string;
  receiptMeta?: string;
}

/**
 * The identity line, from the record itself.
 *
 * Taken from `record.identity` rather than threaded down from whichever list
 * the operator clicked, so a decision opened from a direct link states the same
 * lot, material and supplier as one opened from Incoming. Only what the record
 * actually holds is rendered — no placeholder where a field is absent.
 */
function identityFrom(record: Record<string, unknown>): { material: string; receiptMeta: string } {
  const identity = obj(record.identity);
  const site = str(identity.supplier_site);
  return {
    material: str(identity.material_id),
    receiptMeta: [str(identity.supplier_id), site && `site ${site}`].filter(Boolean).join(' · '),
  };
}

/**
 * Build the workspace view model for a settled decision.
 *
 * Throws `ChronologyUnavailable` rather than projecting a partial history: a
 * workspace built on no events would draw an empty spine beside a real
 * disposition, which reads as "nothing happened, and yet here is the outcome".
 */
export function projectStoredDecision(input: StoredDecisionInput): DecisionWorkspaceVM {
  if (!input.events.length) throw new ChronologyUnavailable(input.decisionRecordId);

  // Through the same dedupe the live path uses: the backend double-writes every
  // event (once live from the sink, once in the terminal batch) with distinct
  // sequences, so the raw stream is roughly twice the real length.
  const events = mergeEvents([], input.events);
  const record = stripEvents(input.record);
  const identity = identityFrom(record);

  const projectInput: ProjectInput = {
    decisionRecordId: input.decisionRecordId,
    lotId: str(record.lot_id) || str(obj(record.identity).lot_id) || '',
    material: input.material ?? identity.material,
    receiptMeta: input.receiptMeta ?? identity.receiptMeta,
    events,
    result: terminalFrom(input.decisionRecordId, record, events),
    sources: input.sources ?? [],
    record,
    running: false,
    durable: true,
  };
  return project(projectInput);
}

/**
 * TEST ONLY. Projects a record's own `record.events` summary.
 *
 * This is the thing production must never do. It exists so
 * `stored-decision.test.ts` can prove the divergence is real and current rather
 * than asserting it in a comment.
 */
export function projectFromRecordEventsForTest(
  input: Omit<StoredDecisionInput, 'events'>,
): DecisionWorkspaceVM {
  const events = (Array.isArray(input.record.events) ? input.record.events : []) as LifecycleEventDTO[];
  return projectStoredDecision({ ...input, events });
}
