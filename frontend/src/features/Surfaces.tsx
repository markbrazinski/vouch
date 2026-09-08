/**
 * The four product surfaces, each bound to its own read model.
 *
 * Each surface fetches, classifies and renders one of: an answer, a truthful
 * empty, an explicitly-blocked path, or a technical failure. None of them ever
 * substitutes fixture content for an answer it did not get.
 */

import { getToday, listDecisions, getDecision, getEvents } from '../adapter/client';
export { prefetchSurfaces } from './useSurfaceData';
import { SurfaceState, TechnicalFailure } from '../components/SurfaceState';
import { useSurfaceData } from './useSurfaceData';
import { toToday } from './today/model';
import { LiveTodayPage } from './today/LiveTodayPage';
import { toCurrentArrivals, toIncoming } from './incoming/model';
import { IncomingUnavailable, LedgerPage, LiveIncomingPage } from './incoming/LiveIncomingPage';
import { toSuppliers } from './suppliers/model';
import { LiveSuppliersPage } from './suppliers/LiveSuppliersPage';
import { DecisionWorkspace } from '../decision/DecisionWorkspace';
import { projectStoredDecision } from '../decision/fromRecord';
import type { LifecycleEventDTO, SourceArtifactDTO } from '../decision/dto';
import type { TodayDTO } from '../decision/dto';
import type { ListDecisionsDTO } from './incoming/model';

/** How much recent history Records shows. Audit density, not a full scroll. */
const RECENT_RECORDS = 20;

const Loading = ({ what }: { what: string }) => (
  <SurfaceState kind="loading" headline={`Reading ${what}…`} />
);

export function TodaySurface({ onOpenDecision }: { onOpenDecision?: (orderId: string) => void }) {
  const { status, data, detail } = useSurfaceData(
    getToday,
    (e) => toToday(e as TodayDTO),
    [],
    'today',
  );

  if (status === 'loading') return <Loading what="the production plan" />;
  if (status === 'blocked')
    return (
      <SurfaceState
        kind="blocked"
        headline="The production plan cannot be read in this deployment."
        detail={detail}
      />
    );
  if (status === 'failed' || !data) return <TechnicalFailure what="The production plan" detail={detail} />;
  if (data.lines.length === 0)
    return (
      <SurfaceState
        kind="empty"
        headline="No production orders are scheduled."
        detail="Orders appear here once they are planned against a line."
      />
    );
  return <LiveTodayPage vm={data} onOpenDecision={onOpenDecision} />;
}

/**
 * Incoming — what currently requires disposition.
 *
 * One row per LOT, not per decision record. The rows come from the same
 * `list_decisions` read the ledger uses, collapsed to the newest record per
 * `lot_id`; see `toCurrentArrivals`. Opening a row starts a FRESH evaluation of
 * that lot rather than reopening whichever historical execution the surviving
 * record happened to be — which is the single interaction model this surface
 * now has.
 */
export function IncomingSurface({ onEvaluate }: { onEvaluate: (lotId: string) => void }) {
  const { status, data, detail } = useSurfaceData(
    () => listDecisions(50),
    (e) => toCurrentArrivals(e as ListDecisionsDTO),
    [],
    'decisions',
  );

  if (status === 'loading') return <Loading what="today’s arrivals" />;
  // The known standing blocker: the recency index and its query grant.
  if (status === 'blocked') return <IncomingUnavailable detail={detail} />;
  if (status === 'failed' || !data) return <TechnicalFailure what="Arrivals" detail={detail} />;
  return (
    <LiveIncomingPage
      vm={data}
      onEvaluate={onEvaluate}
      heading="Material awaiting disposition"
      unit="lot"
    />
  );
}

export function SuppliersSurface({ onOpen }: { onOpen?: (decisionRecordId: string) => void }) {
  const { status, data, detail } = useSurfaceData(
    () => listDecisions(50),
    // Grouped by LOT, not by decision record. Grouping the raw ledger counted
    // qualification RUNS as arrivals, so one lot evaluated thirty times listed
    // its supplier thirty times — a count of our debugging, not of the
    // supplier's material.
    (e) => toSuppliers(toCurrentArrivals(e as ListDecisionsDTO).rows),
    [],
    'decisions',
  );

  if (status === 'loading') return <Loading what="supplier context" />;
  if (status === 'blocked')
    return (
      <SurfaceState
        kind="blocked"
        headline="Supplier context cannot be assembled in this deployment."
        detail={
          'Suppliers are grouped from the decisions on record, and that listing ' +
          'is unavailable here. Each decision can still be opened directly.'
        }
      />
    );
  if (status === 'failed' || !data) return <TechnicalFailure what="Supplier context" detail={detail} />;
  return <LiveSuppliersPage vm={data} onOpen={onOpen} />;
}

/**
 * One settled decision, in the SAME workspace a live run renders.
 *
 * Two reads, because they carry different things and only one of them is
 * authoritative for the chronology:
 *
 *   get_decision -> the settled record, its sources, archived run summaries
 *   get_events   -> the complete lifecycle history
 *
 * `record.events` is deliberately NOT used. It is a last-run-only summary that
 * drops the events `project()` needs to see an unsettled outcome, and on a
 * multi-run decision it projects "Released into usable inventory" over a
 * decision that is actually awaiting a quality decision. `fromRecord` strips it
 * structurally; see `stored-decision.test.ts`.
 *
 * When the chronology cannot be read this renders an unavailable state. It
 * never infers a history from the record — a workspace drawn on a partial
 * history would state an outcome no complete evidence supports.
 */
export function RecordSurface({ decisionRecordId }: { decisionRecordId: string }) {
  const { status, data, detail } = useSurfaceData(
    async () => {
      const [record, events] = await Promise.all([
        getDecision(decisionRecordId),
        getEvents(decisionRecordId, 0, 1000),
      ]);
      // Either read failing means the decision cannot be shown truthfully, so
      // the non-ok envelope is surfaced rather than half a workspace.
      if (record.ok === false) return record;
      if (events.ok === false) return events;
      return { ...record, events: events.events };
    },
    (e) =>
      projectStoredDecision({
        decisionRecordId,
        record: (e.record ?? e.decision_record ?? {}) as Record<string, unknown>,
        sources: (Array.isArray(e.sources) ? e.sources : []) as SourceArtifactDTO[],
        events: (Array.isArray(e.events) ? e.events : []) as LifecycleEventDTO[],
      }),
    [decisionRecordId],
  );

  if (status === 'loading') return <Loading what="the decision record" />;
  if (status === 'blocked')
    return (
      <SurfaceState
        kind="blocked"
        headline="This decision record cannot be read in this deployment."
        detail={detail}
      />
    );
  if (status === 'failed' || !data)
    return <TechnicalFailure what="The decision record" detail={detail} />;
  return <DecisionWorkspace vm={data} />;
}

/**
 * Records with no record selected.
 *
 * Listing every record needs the same blocked recency index Incoming needs, so
 * this states that rather than showing an empty table that would read as "no
 * decisions have ever been made".
 */
export function RecordsIndexSurface({ onOpen }: { onOpen?: (id: string) => void }) {
  const { status, data, detail } = useSurfaceData(
    () => listDecisions(50),
    (e) => toIncoming(e as ListDecisionsDTO),
    [],
    'decisions',
  );

  if (status === 'loading') return <Loading what="the decision ledger" />;
  if (status === 'blocked')
    return (
      <SurfaceState
        kind="blocked"
        headline="The decision ledger cannot be listed in this deployment."
        detail={
          'Listing records requires a recency index and a query grant this ' +
          'environment has not been given. Individual records are unaffected ' +
          'and open normally from a decision.'
        }
      />
    );
  if (status === 'failed' || !data) return <TechnicalFailure what="The decision ledger" detail={detail} />;
  if (data.rows.length === 0)
    return (
      <SurfaceState
        kind="empty"
        headline="No decisions have been recorded yet."
        detail="Every disposition Vouch reaches is kept here permanently."
      />
    );
  // Enough recent history to read as an audit trail without becoming a scroll.
  // The read already returns them newest-first; `LedgerPage` sorts regardless.
  return <LedgerPage vm={{ ...data, rows: data.rows.slice(0, RECENT_RECORDS) }} onOpen={onOpen} />;
}
