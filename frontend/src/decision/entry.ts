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
