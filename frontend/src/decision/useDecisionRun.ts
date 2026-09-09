/**
 * The live decision run.
 *
 * This is the one place the frontend has any notion of "a decision is
 * happening". It implements §5 of the gate exactly:
 *
 *   1. the client owns a stable `decision_record_id` BEFORE any work starts;
 *   2. `/api/evaluate` is started and NOT awaited for display purposes;
 *   3. `/api/decisions/{id}/events?after_sequence=N` is polled independently;
 *   4. events are inserted as they arrive, deduped by sequence;
 *   5. once evaluate resolves, the authoritative `get_decision` is loaded.
 *
 * Why the id must come first: `/api/evaluate` now returns 202 STARTED as soon
 * as the work is scheduled, and the decision itself runs for 35-110s after the
 * POST has already resolved. The id is what connects the two — the backend
 * treats a caller-supplied id as CONTINUED rather than replaced, so the client
 * polls a decision it named before any work began.
 *
 * The POST therefore carries NO outcome. Terminal state is discovered by
 * polling `get_decision` until the stored record reports `terminal: true`, which
 * is the backend's own word for "this decision is finished" rather than an
 * inference drawn from which events happened to have arrived.
 *
 * There are no timers driving lifecycle truth here. The only interval is the
 * poll itself, and it asks the server what happened rather than deciding.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { invalidateSurfaces } from '../features/useSurfaceData';
import * as api from '../adapter/client';
import { TransportError } from '../adapter/client';
import type { EvaluateDTO, LifecycleEventDTO, SourceArtifactDTO } from './dto';
import type { FailureVM } from './model';

/** How often to ask for new events while a decision is running. */
const POLL_MS = 900;

/**
 * Ticks between terminal checks.
 *
 * Events poll every tick because that is what makes the rail feel live. The
 * terminal check does not need to: at ~4.5s it settles a run well within one
 * human beat of it finishing, while cutting the expected 400s during the run
 * from roughly a dozen to a few.
 */
const TERMINAL_CHECK_TICKS = 5;

/**
 * Ticks between attempts to load the source artifacts.
 *
 * `get_source` used to 400 for most of a run — it required the stored record,
 * and a record is not persisted until the decision ends — so this backed off to
 * the terminal cadence to keep the console clean. It now answers from the live
 * event stream as soon as evidence is received, so the retry is tight again:
 * the operator sees the certificate a beat after it is frozen, which is the
 * moment it becomes relevant to them.
 */
const SOURCE_RETRY_TICKS = 1;

export interface DecisionRunState {
  decisionRecordId: string;
  events: LifecycleEventDTO[];
  result: EvaluateDTO | null;
  sources: SourceArtifactDTO[];
  /**
   * The stored decision document, once `get_decision` has returned it.
   *
   * It is the only authoritative surface carrying `evidence.canonical_claims`,
   * which is what lets the source viewer itemize what was extracted rather than
   * report a bare count. Loaded at the terminal, because that is when the
   * record is complete.
   */
  record: Record<string, unknown> | null;
  running: boolean;
  failure: FailureVM | null;
  durable: boolean;
}

const EMPTY: Omit<DecisionRunState, 'decisionRecordId'> = {
  events: [],
  result: null,
  sources: [],
  record: null,
  running: false,
  failure: null,
  durable: true,
};

/**
 * Normalize one event to a flat shape.
 *
 * The two delivery paths disagree, and live traffic is what revealed it:
 *
 *   get_events  -> { event, sequence, event_id, at, payload: {...} }
 *   evaluate    -> { event, at, ...fields }        (flat, no sequence/id)
 *
 * Both are legitimate — the poll reads the durable store, which keys events by
 * sequence and stores the payload as a sub-document. Flattening here means the
 * adapter reads one shape and never has to know which path an event took.
 */
export function normalizeEvent(e: LifecycleEventDTO): LifecycleEventDTO {
  const payload = e.payload as Record<string, unknown> | undefined;
  return payload && typeof payload === 'object' ? { ...payload, ...e, payload: undefined } : e;
}

/**
 * The identity of an event, independent of how it was delivered.
 *
 * NOT the sequence. The backend deliberately writes each event twice — once
 * live from the sink so a UI can watch a decision progress, once in the
 * terminal batch so the record is complete — and gives the two copies DIFFERENT
 * sequence numbers. A 38-event run therefore polls back as 98 rows with 98
 * unique sequences and 98 unique event_ids.
 *
 * Deduping on either of those would leave the rail showing everything twice,
 * which is exactly what the first live run did. The stable identity is what the
 * backend itself uses: type + timestamp + payload. `at` is set once at
 * construction, so the same emitted event always carries the same instant while
 * two genuine TOOL_CALLEDs stay distinct.
 */
function identityOf(e: LifecycleEventDTO): string {
  const flat = normalizeEvent(e);
  const significant = Object.keys(flat)
    .filter((k) => !['sequence', 'event_id', 'payload'].includes(k))
    .sort()
    .map((k) => `${k}=${JSON.stringify(flat[k])}`)
    .join('|');
  return significant;
}

/**
 * Merge newly-arrived events into the ordered list.
 *
 * Re-delivery has to be free: the poll and the terminal response overlap by
 * design, and the backend double-writes on top of that.
 */
export function mergeEvents(
  existing: LifecycleEventDTO[],
  incoming: LifecycleEventDTO[],
): LifecycleEventDTO[] {
  if (!incoming.length) return existing;

  const byIdentity = new Map<string, LifecycleEventDTO>();
  for (const e of [...existing, ...incoming]) {
    const id = identityOf(e);
    const seen = byIdentity.get(id);
    // Keep whichever copy carries a real sequence, so ordering survives.
    if (!seen || (seen.sequence === undefined && e.sequence !== undefined)) {
      byIdentity.set(id, normalizeEvent(e));
    }
  }

  // Order by sequence where the backend gave one; otherwise by arrival, which
  // is already causal because the pipeline emits in order.
  const out = [...byIdentity.values()];
  out.sort((a, b) => {
    const sa = typeof a.sequence === 'number' ? a.sequence : Number.MAX_SAFE_INTEGER;
    const sb = typeof b.sequence === 'number' ? b.sequence : Number.MAX_SAFE_INTEGER;
    if (sa !== sb) return sa - sb;
    return String(a.at).localeCompare(String(b.at));
  });
  // Renumber densely so the UI has a stable, gap-free key per event.
  return out.map((e, i) => ({ ...e, sequence: i + 1 }));
}



/**
 * Classify a thrown error or a failure envelope.
 *
 * The distinction this function exists to protect: a TECHNICAL_FAILURE knows
 * nothing about the material. It must never render as a disposition, and the
 * caller enforces that by refusing to show one while `suppressesDisposition`.
 */
export function classifyFailure(input: unknown): FailureVM {
  if (input instanceof TransportError) {
    return {
      kind: 'TECHNICAL_FAILURE',
      headline: 'Vouch could not be reached',
      detail: 'No decision was made. Nothing about this lot has changed.',
      suppressesDisposition: true,
    };
  }

  const env = input as { failure_category?: string; error?: string; ok?: boolean };
  const category = env?.failure_category ?? '';
  const detail = env?.error ?? '';

  switch (category) {
    case 'SECURITY_QUARANTINE':
      return {
        kind: 'SECURITY_HOLD',
        headline: 'Evidence quarantined',
        detail: detail || 'The document was withheld from the decision agents.',
        suppressesDisposition: false,
      };
    case 'EXTRACTION_LOW_CONFIDENCE':
    case 'EVIDENCE_BINDING_MISMATCH':
    case 'EVIDENCE_UNBOUND':
    case 'EVIDENCE_IDENTITY_CONFLICT':
      return {
        kind: 'DOMAIN_ABSTENTION',
        headline: 'Vouch did not decide',
        detail: detail || 'The evidence could not establish an answer.',
        suppressesDisposition: false,
      };
    case 'STATE_CONFLICT':
      return {
        kind: 'CONFLICT_STALE',
        headline: 'The lot moved while this was being decided',
        detail: detail || 'Nothing was changed. Re-evaluate against current state.',
        suppressesDisposition: true,
      };
    case 'POLICY_REFUSAL':
      return {
        kind: 'POLICY_REFUSAL',
        headline: 'Policy refused the change',
        detail: detail || 'The requested state change was not authorized.',
        suppressesDisposition: false,
      };
    case 'PERSISTENCE_FAILURE':
    case 'MODEL_UNAVAILABLE':
    case 'TOOL_FAILURE':
    case 'SCHEMA_FAILURE':
    default:
      return {
        kind: 'TECHNICAL_FAILURE',
        headline: 'Vouch could not complete this decision',
        detail: detail || 'A technical failure occurred. No disposition was reached.',
        suppressesDisposition: true,
      };
  }
}

/**
 * The stored decision document from a response that carries one.
 *
 * `get_decision` returns it under `record`; the record path has historically
 * also used `decision_record`. Both are accepted rather than one being assumed.
 */
/**
 * Whether the run has stopped, so polling should too.
 *
 * Two backend-owned facts, because `terminal` alone is not the question the UI
 * is asking. The backend sets `terminal` when the LOT WAS DISPOSITIONED —
 * released or quarantined — and deliberately leaves it false for an
 * abstention, because that case is still open and awaiting a person.
 *
 * Live running is what exposed the difference: Hero B run 1 abstains to
 * INSUFFICIENT_EVIDENCE and opens a QA review, which is a correct and complete
 * outcome the operator must see. Watching `terminal` alone left the rail
 * spinning on a decision that had already finished deciding.
 *
 * So an OPEN review counts as stopped. Neither fact is inferred here; both are
 * read from the record exactly as the backend wrote them.
 */
function hasStopped(document: Record<string, unknown> | null): boolean {
  if (!document) return false;
  if (document.terminal === true) return true;
  const human = document.human as { review_status?: unknown } | undefined;
  return human?.review_status === 'OPEN';
}

function recordOf(body: unknown): Record<string, unknown> | null {
  const b = body as { record?: unknown; decision_record?: unknown } | null;
  const document = b?.record ?? b?.decision_record;
  return document && typeof document === 'object'
    ? (document as Record<string, unknown>)
    : null;
}

export function useDecisionRun(initialId?: string) {
  // The id exists before any work does. That is what makes polling possible.
  const [decisionRecordId, setId] = useState(() => initialId ?? api.newDecisionRecordId());
  const [state, setState] = useState<Omit<DecisionRunState, 'decisionRecordId'>>(EMPTY);
  const pollRef = useRef<number | null>(null);
  const liveRef = useRef(false);
  /**
   * The poll cursor: the highest sequence the SERVER has sent, never our own.
   *
   * After dedupe our numbering is denser than the store's (the backend
   * double-writes, so its sequences outrun ours), and asking
   * `after_sequence=<our count>` would skip events. Kept in a ref rather than a
   * module constant so two hooks — or two runs — never share one cursor.
   */
  const cursorRef = useRef(0);
  /** Whether sources have been successfully loaded for the current run. */
  const sourcesRef = useRef(false);
  /**
   * Whether the snapshot event has EVER been seen on this run.
   *
   * The retry has to survive the tick that delivered the event. `get_source`
   * legitimately 400s the first time — the artifact is recorded before the
   * decision record is queryable — so the load is retried on later ticks. But
   * the event only appears in ONE batch, and the poll cursor then moves past
   * it, so a per-batch flag retries exactly zero times.
   *
   * That is fine while a run is watched from its own first event, and wrong the
   * moment a run is OBSERVED: `observe` seeds the whole history at once, which
   * consumes the event before any tick can see it, and the source panel then
   * sat on "Receiving source evidence…" forever with the bytes sitting in S3.
   * Latching the fact rather than the news fixes both paths.
   */
  const sawEvidenceRef = useRef(false);
  /** Ticks since the last source-load attempt. See SOURCE_RETRY_TICKS. */
  const sinceSourceRef = useRef(0);
  /**
   * How many terminal checks have been skipped since the last one.
   *
   * `get_decision` is the ONLY signal that a run has stopped — `get_events`
   * carries no terminal marker — and it answers 400 until the record is
   * durable, which live timing showed is at the very END of a run: the snapshot
   * event lands at ~6s while the record becomes queryable at ~48s. So the 400
   * is not an error to avoid, it is the normal "still running" answer, and the
   * only thing worth tuning is how often it is asked.
   *
   * Asking every 900ms tick produced ~11 red console lines per run on a screen
   * a judge is watching. Checking every Nth tick keeps that to a handful while
   * still settling the run within a poll interval of it actually finishing.
   */
  const sinceCheckRef = useRef(0);

  const stopPolling = useCallback(() => {
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  useEffect(() => stopPolling, [stopPolling]);

  /** One poll tick. Asks only for what we have not seen. */
  const pollOnce = useCallback(async (recordId: string, loadSources: (id: string) => Promise<boolean>) => {
    try {
      const body = (await api.getEvents(recordId, cursorRef.current)) as {
        ok: boolean;
        events?: LifecycleEventDTO[];
      };
      if (!body.ok || !body.events?.length) return;
      let sawEvidence = false;
      for (const e of body.events) {
        if (typeof e.sequence === 'number') {
          cursorRef.current = Math.max(cursorRef.current, e.sequence);
        }
        // EVIDENCE_SNAPSHOT_CREATED, not EVIDENCE_RECEIVED.
        //
        // Live running showed why: the artifact is recorded at RECEIVED, but
        // the DECISION RECORD it hangs off is not queryable that early, so
        // get_source 400s. The snapshot event is the first point at which the
        // record is durable, and asking then succeeds first time instead of
        // retrying into the console.
        if (e.event === 'EVIDENCE_SNAPSHOT_CREATED') sawEvidence = true;
      }
      setState((prev) => ({ ...prev, events: mergeEvents(prev.events, body.events!) }));

      // Fetch as soon as the record is durable, so the context column is
      // populated while the decision is still running rather than only at the
      // end — it is the panel whose job is to stay true as stages move past.
      // The record may not be queryable the instant the event lands, so a
      // first attempt can legitimately 400. Only latch on success; the next
      // tick simply tries again.
      if (sawEvidence) sawEvidenceRef.current = true;
      // Retried on the same cadence as the terminal check rather than every
      // tick. `get_source` answers 400 until the decision record is queryable,
      // which is most of a run, and asking 900ms apart turned a normal wait
      // into a wall of red console lines on a screen a judge is watching.
      if (sawEvidenceRef.current && !sourcesRef.current) {
        sinceSourceRef.current += 1;
        if (sinceSourceRef.current >= SOURCE_RETRY_TICKS) {
          sinceSourceRef.current = 0;
          void loadSources(recordId).then((found) => {
            if (found) sourcesRef.current = true;
          });
        }
      }
    } catch {
      // A failed poll is not a failed decision. The evaluate call is the thing
      // that decides; losing a frame of the chronology must not surface as an
      // error, and the next tick will simply ask again from the same cursor.
    }
  }, []);

  /**
   * Load the source artifacts for this decision.
   *
   * Called as soon as evidence is RECEIVED, not only at the end. Live running
   * exposed why that matters: the context column is the persistent left-hand
   * panel, and fetching sources only after the terminal response left it
   * reading "No source artifact yet" for the entire 30-60s decision — the one
   * panel whose whole job is to stay true while stages move past it.
   */
  const loadSources = useCallback(async (recordId: string): Promise<boolean> => {
    try {
      const body = (await api.getSources(recordId)) as {
        ok: boolean;
        /** The live key. `artifacts` is accepted for the record path. */
        sources?: SourceArtifactDTO[];
        artifacts?: SourceArtifactDTO[];
      };
      if (!body.ok) return false;
      const list = body.sources ?? body.artifacts ?? [];
      if (list.length) setState((prev) => ({ ...prev, sources: list }));
      return list.length > 0;
    } catch {
      // Sources are supporting context. Failing to list them does not
      // invalidate the decision, and the viewer has its own empty state.
      return false;
    }
  }, []);

  /**
   * Finish the run from authoritative state.
   *
   * Called when the stored record reports `terminal`. The record is the
   * decision; `get_decision` is re-read here so the disposition, the failure
   * category and the events all come from the same durable document rather than
   * from whatever the POST happened to carry.
   */
  const settle = useCallback(
    async (recordId: string) => {
      stopPolling();
      try {
        const decision = (await api.getDecision(recordId)) as unknown as EvaluateDTO;
        const document = recordOf(decision);
        const category = (document?.failure_category as string) || '';
        // An abstention or a refusal is a real outcome carried on a record that
        // loaded fine. Only a genuine category makes it a failure.
        const failure = category ? classifyFailure({ failure_category: category, error: '' }) : null;
        setState((prev) => ({
          ...prev,
          running: false,
          result: decision,
          record: document,
          failure,
          events: mergeEvents(prev.events, (decision.events as LifecycleEventDTO[]) ?? []),
          durable: decision.backend?.durable ?? true,
        }));
        await loadSources(recordId);
      } catch (error) {
        setState((prev) => ({ ...prev, running: false, failure: classifyFailure(error) }));
      } finally {
        // The run changed authoritative state — lot status, usable inventory,
        // order readiness, the schedule. Any retained Today or Incoming
        // response now contradicts what the operator just watched happen, so
        // the next read of those surfaces must go to the backend.
        invalidateSurfaces();
        liveRef.current = false;
      }
    },
    [stopPolling, loadSources],
  );

  /**
   * Watch a running decision until the backend says it is over.
   *
   * The ONE interval in this hook. `start` and `resume` differ only in which
   * call sets the work going — what they watch, and how they learn it ended,
   * is identical, so it lives here rather than being written twice.
   */
  const watch = useCallback(
    (recordId: string) => {
      const tick = async () => {
        await pollOnce(recordId, loadSources);
        // The record is written when the run ends, so this legitimately 400s
        // for most of a decision. Ask every TERMINAL_CHECK_TICKS ticks rather
        // than every one.
        sinceCheckRef.current += 1;
        if (sinceCheckRef.current < TERMINAL_CHECK_TICKS) return;
        sinceCheckRef.current = 0;
        try {
          const body = (await api.getDecision(recordId)) as { ok: boolean };
          if (body.ok && hasStopped(recordOf(body))) await settle(recordId);
        } catch {
          // A record that was durable and is briefly unreadable is a transient
          // read, not a failed decision. The next tick asks again.
        }
      };
      stopPolling();
      pollRef.current = window.setInterval(() => void tick(), POLL_MS);
      void tick();
    },
    [pollOnce, loadSources, settle, stopPolling],
  );

  const start = useCallback(
    async (input: {
      lotId: string;
      document?: string;
      /** Base64 bytes for a binary source document (the canonical COA PDF). */
      documentB64?: string;
      contentType?: string;
      /**
       * The id to run under, when the CALLER minted it.
       *
       * Routing needs the id before the POST resolves: the workspace lives at
       * `/decisions/:recordId`, so the caller names the decision, navigates,
       * and hands the same id here. The backend treats a caller-supplied id as
       * CONTINUED rather than replaced, which is the same property that already
       * let this hook poll a decision it named first.
       */
      decisionRecordId?: string;
    }) => {
      if (liveRef.current) return;
      liveRef.current = true;
      const recordId = input.decisionRecordId ?? decisionRecordId;
      if (recordId !== decisionRecordId) setId(recordId);

      setState({ ...EMPTY, running: true });
      cursorRef.current = 0;
      sourcesRef.current = false;
      sawEvidenceRef.current = false;
      sinceSourceRef.current = 0;
      sinceCheckRef.current = 0;

      try {
        // Start the work. The response is an acknowledgement, never an outcome:
        // it resolves in well under a second and the decision is still running.
        const started = (await api.evaluateLot({
          lotId: input.lotId,
          decisionRecordId: recordId,
          document: input.document,
          documentB64: input.documentB64,
          contentType: input.contentType,
        })) as { ok: boolean; error?: string };

        // A refusal to START is immediate and real — nothing was scheduled, so
        // polling would never terminate. It is surfaced now rather than leaving
        // the rail watching a decision that does not exist.
        if (!started.ok) {
          setState((prev) => ({ ...prev, running: false, failure: classifyFailure(started) }));
          liveRef.current = false;
          return;
        }
      } catch (error) {
        setState((prev) => ({ ...prev, running: false, failure: classifyFailure(error) }));
        liveRef.current = false;
        return;
      }

      // Only now watch: the work is confirmed scheduled.
      watch(recordId);
    },
    [decisionRecordId, watch],
  );

  /**
   * Hero B Run 2: supply authoritative evidence to an open decision.
   *
   * The same record, the same polling path. `supply_evidence` is started rather
   * than awaited for the same reason `evaluate` is — a resumed run invokes the
   * same two agents and takes just as long — and the record id is already known
   * because the decision it continues is the one on screen.
   */
  const resume = useCallback(
    async (input: {
      lotId: string;
      authoritySource: string;
      document?: string;
      contentType?: string;
    }) => {
      if (liveRef.current) return;
      liveRef.current = true;
      const recordId = decisionRecordId;

      setState((prev) => ({ ...prev, running: true, failure: null }));
      sourcesRef.current = false;
      sawEvidenceRef.current = false;
      sinceSourceRef.current = 0;
      sinceCheckRef.current = 0;

      try {
        const started = (await api.supplyEvidence({
          decisionRecordId: recordId,
          lotId: input.lotId,
          authoritySource: input.authoritySource,
          document: input.document,
          contentType: input.contentType,
        })) as { ok: boolean; error?: string };
        if (!started.ok) {
          setState((prev) => ({ ...prev, running: false, failure: classifyFailure(started) }));
          liveRef.current = false;
          return;
        }
      } catch (error) {
        setState((prev) => ({ ...prev, running: false, failure: classifyFailure(error) }));
        liveRef.current = false;
        return;
      }

      watch(recordId);
    },
    [decisionRecordId, watch],
  );

  /**
   * Attach to a decision this client did not start, and follow it to its end.
   *
   * This is what makes the workspace addressable by URL. `start` submits work;
   * `observe` submits NOTHING — it reads the authoritative record, and if the
   * backend says the decision is still going it watches with the same poll loop
   * a live run uses. Navigating away and back therefore resumes observation of
   * the same execution rather than launching a second one, and a deep link into
   * `/decisions/:id` is just the same thing with no prior mount.
   *
   * The record legitimately 400s for most of a run (it becomes queryable only
   * at the end), so a failed read is NOT treated as a missing decision: if
   * events exist, the decision exists and is simply still running. Only the
   * absence of BOTH is a decision this deployment cannot show.
   */
  const observe = useCallback(
    async (recordId: string) => {
      if (liveRef.current) return;
      liveRef.current = true;
      setId(recordId);
      setState({ ...EMPTY, running: true });
      cursorRef.current = 0;
      sourcesRef.current = false;
      sawEvidenceRef.current = false;
      sinceSourceRef.current = 0;
      sinceCheckRef.current = 0;

      try {
        const [decision, events] = await Promise.all([
          api.getDecision(recordId).catch(() => ({ ok: false })) as Promise<EvaluateDTO>,
          api.getEvents(recordId, 0, 1000).catch(() => ({ ok: false })) as Promise<{
            ok: boolean;
            events?: LifecycleEventDTO[];
          }>,
        ]);

        const history = events.ok ? (events.events ?? []) : [];
        const document = decision.ok ? recordOf(decision) : null;

        // Neither the record nor a single event: nothing here to observe.
        if (!decision.ok && history.length === 0) {
          setState((prev) => ({ ...prev, running: false, failure: classifyFailure(decision) }));
          liveRef.current = false;
          return;
        }

        if (document && hasStopped(document)) {
          // Already finished. Take the durable answer; do not poll.
          setState((prev) => ({
            ...prev,
            events: mergeEvents(prev.events, history),
          }));
          await settle(recordId);
          return;
        }

        // Still running. Seed what has happened so far, then watch from that
        // cursor so the rail continues rather than replaying.
        for (const e of history) {
          if (typeof e.sequence === 'number') {
            cursorRef.current = Math.max(cursorRef.current, e.sequence);
          }
          // Seeding consumes the snapshot event, so the FACT is latched here.
          // Without this the poll would never retry the source load, because
          // the news of that event has already gone by.
          if (e.event === 'EVIDENCE_SNAPSHOT_CREATED') sawEvidenceRef.current = true;
        }
        setState((prev) => ({ ...prev, events: mergeEvents(prev.events, history) }));
        if (sawEvidenceRef.current) {
          void loadSources(recordId).then((found) => {
            if (found) sourcesRef.current = true;
          });
        }
        watch(recordId);
      } catch (error) {
        setState((prev) => ({ ...prev, running: false, failure: classifyFailure(error) }));
        liveRef.current = false;
      }
    },
    [settle, watch, loadSources],
  );

  /** Load a decision that already finished. No polling, no evaluate. */
  const load = useCallback(async (recordId: string) => {
    setId(recordId);
    setState({ ...EMPTY, running: true });
    try {
      const [decision, events] = await Promise.all([
        api.getDecision(recordId) as unknown as Promise<EvaluateDTO>,
        api.getEvents(recordId, 0) as Promise<{ ok: boolean; events?: LifecycleEventDTO[] }>,
      ]);
      if (!decision.ok) {
        setState((prev) => ({ ...prev, running: false, failure: classifyFailure(decision) }));
        return;
      }
      setState((prev) => ({
        ...prev,
        running: false,
        result: decision,
        events: mergeEvents(events.events ?? [], decision.events ?? []),
        record: recordOf(decision),
        durable: decision.backend?.durable ?? true,
      }));
    } catch (error) {
      setState((prev) => ({ ...prev, running: false, failure: classifyFailure(error) }));
    }
  }, []);

  return { decisionRecordId, ...state, start, resume, observe, load, setDecisionRecordId: setId };
}
