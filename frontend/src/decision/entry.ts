/**
 * The arrival identity the app is opened with.
 *
 * This is receipt IDENTITY only: which lot, what it is, and the supplier's own
 * certificate. It says nothing about what Vouch will conclude — the
 * disposition, the governing basis and every consequence come from the backend
 * as the decision runs.
 *
 * It lived on `HeroAPage`, a component that both listed arrivals and owned an
 * `openLot` state deciding which one was showing. Routing replaced that: the
 * list is `IncomingRoute` and the workspace is `DecisionRoute`, addressed by
 * DecisionRecord id. The type outlived the component, so it lives here.
 */
export interface HeroAEntry {
  lotId: string;
  material?: string;
  receiptMeta?: string;
  /** Inline text evidence. Mutually exclusive with `documentUrl`. */
  document?: string;
  /**
   * A bundled binary source document (the canonical COA PDF). Fetched and
   * base64-encoded at click time and submitted through the same `evaluate_lot`
   * ingestion path text evidence uses.
   */
  documentUrl?: string;
  documentName?: string;
  contentType?: string;
}

/**
 * The canonical arrivals, by lot.
 *
 * Incoming lists four lots and each has exactly one qualified certificate, so
 * the app needs a MAP rather than a single entry. It carried one — the Hero A
 * lot — and attached its document only to that lot, correctly refusing to claim
 * Eastern Metals certified material they did not. The consequence was that the
 * other three lots could only be evaluated with no evidence at all, which is a
 * different untruth: an operator watching "0 claims frozen" is watching Vouch
 * reason about a document nobody supplied.
 *
 * Every document here is the SAME tracked byte-for-byte asset the canonical PDF
 * gate qualified, symlinked rather than copied so the UI cannot ship different
 * bytes than the ones under test.
 */
export type ArrivalDocuments = Record<string, HeroAEntry>;
