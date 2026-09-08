/**
 * Work handed from Incoming to the decision workspace, across a navigation.
 *
 * Starting an evaluation and showing it are two different components on two
 * different routes. The click happens on `/incoming`; the run is owned by
 * `/decisions/:recordId`, which does not exist yet at that moment. This is the
 * handoff between them, keyed by the record id in the URL.
 *
 * It is deliberately NOT navigation state and NOT product state — it is a
 * one-shot intent, consumed by the first mount that claims it and deleted in
 * the same breath. That "take" is what guarantees a second evaluation is never
 * submitted: a remount, a Back, or a refresh finds nothing to start and
 * observes the authoritative decision instead.
 *
 * A module-level Map rather than context because it must survive the unmount of
 * the component that created it, and must NOT re-render anything when written.
 */

export interface PendingRun {
  lotId: string;
  decisionRecordId: string;
  document?: string;
  contentType?: string;
  /** Read at claim time, so a document that cannot be read fails only its run. */
  loadDocumentB64?: () => Promise<string>;
}

const pending = new Map<string, PendingRun>();

export const pendingRun = {
  set(recordId: string, run: PendingRun) {
    pending.set(recordId, run);
  },
  /** Claim the intent for this record. Returns it once, then never again. */
  take(recordId: string): PendingRun | undefined {
    const run = pending.get(recordId);
    pending.delete(recordId);
    return run;
  },
  /** Test seam. Production never needs to clear the whole map. */
  reset() {
    pending.clear();
  },
};
