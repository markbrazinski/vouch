/**
 * The four product surfaces, each bound to its own read model.
 *
 * Each surface fetches, classifies and renders one of: an answer, a truthful
 * empty, an explicitly-blocked path, or a technical failure. None of them ever
 * substitutes fixture content for an answer it did not get.
 */

import { getToday, listDecisions, getDecision } from '../adapter/client';
import { SurfaceState, TechnicalFailure } from '../components/SurfaceState';
import { useSurfaceData } from './useSurfaceData';
import { toToday } from './today/model';
import { LiveTodayPage } from './today/LiveTodayPage';
import { toIncoming } from './incoming/model';
import { IncomingUnavailable, LiveIncomingPage } from './incoming/LiveIncomingPage';
import { toSuppliers } from './suppliers/model';
import { LiveSuppliersPage } from './suppliers/LiveSuppliersPage';
import { toDecisionRecord } from './records/model';
import { LiveRecordsPage } from './records/LiveRecordsPage';
import type { TodayDTO } from '../decision/dto';
import type { ListDecisionsDTO } from './incoming/model';

const Loading = ({ what }: { what: string }) => (
  <SurfaceState kind="loading" headline={`Reading ${what}…`} />
);

export function TodaySurface({ onOpenDecision }: { onOpenDecision?: (orderId: string) => void }) {
  const { status, data, detail } = useSurfaceData(getToday, (e) => toToday(e as TodayDTO));

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

export function IncomingSurface({ onOpen }: { onOpen?: (decisionRecordId: string) => void }) {
  const { status, data, detail } = useSurfaceData(
    () => listDecisions(50),
    (e) => toIncoming(e as ListDecisionsDTO),
  );

  if (status === 'loading') return <Loading what="today’s arrivals" />;
  // The known standing blocker: the recency index and its query grant.
  if (status === 'blocked') return <IncomingUnavailable detail={detail} />;
  if (status === 'failed' || !data) return <TechnicalFailure what="Arrivals" detail={detail} />;
  return <LiveIncomingPage vm={data} onOpen={onOpen} />;
}

export function SuppliersSurface({ onOpen }: { onOpen?: (decisionRecordId: string) => void }) {
  const { status, data, detail } = useSurfaceData(
    () => listDecisions(50),
    (e) => toSuppliers(toIncoming(e as ListDecisionsDTO).rows),
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

export function RecordSurface({
  decisionRecordId,
  onOpenSource,
}: {
  decisionRecordId: string;
  onOpenSource?: (artifactId: string) => void;
}) {
  const { status, data, detail } = useSurfaceData(
    () => getDecision(decisionRecordId),
    (e) => {
      const record = (e.record ?? e.decision_record ?? {}) as Record<string, unknown>;
      const sources = Array.isArray(e.sources) ? (e.sources as unknown[]) : [];
      return toDecisionRecord(record, sources);
    },
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
  return <LiveRecordsPage vm={data} onOpenSource={onOpenSource} />;
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
  return <LiveIncomingPage vm={data} onOpen={onOpen} />;
}
