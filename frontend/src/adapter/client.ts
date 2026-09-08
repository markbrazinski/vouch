/**
 * The only place the frontend talks to a server.
 *
 * Same-origin `/api/*` and nothing else. There is deliberately no AWS SDK here
 * and no request signing: `InvokeAgentRuntime` is SigV4-signed, so a browser
 * that could call it directly would need credentials, and any credential
 * shipped to a browser is a credential handed to every viewer. The BFF signs
 * server-side instead.
 *
 * This module knows transport only. Backend DTOs are returned verbatim; turning
 * them into view models is the adapter layer's job, kept separate so a change in
 * either shape does not drag the other with it.
 */

/** Raw backend envelope. Every action returns this shape. */
export interface VouchEnvelope {
  ok: boolean;
  action?: string;
  backend?: Record<string, unknown>;
  error?: string;
  /**
   * Set on a transport failure. Distinct from a domain outcome: a decision that
   * abstained is not an error, and a network failure is not a disposition.
   */
  failure_class?: 'TECHNICAL_FAILURE';
  failure_category?: string;
  [key: string]: unknown;
}

/**
 * A transport failure, never a business outcome.
 *
 * It carries no disposition on purpose. A UI that renders "QUARANTINED" because
 * a fetch failed would be asserting something about a material that nothing
 * decided.
 */
export class TransportError extends Error {
  readonly failureClass = 'TECHNICAL_FAILURE' as const;
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'TransportError';
  }
}

const BASE = '/api';

async function request<T extends VouchEnvelope>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      ...init,
      headers: { 'content-type': 'application/json', ...(init?.headers ?? {}) },
    });
  } catch (cause) {
    // The network never reached the server. Nothing is known about the decision.
    throw new TransportError('could not reach the decision service', 0);
  }

  let body: T;
  try {
    body = (await response.json()) as T;
  } catch {
    throw new TransportError('the decision service returned an unreadable response', response.status);
  }

  if (!response.ok && body?.ok !== false) {
    throw new TransportError(body?.error ?? 'request failed', response.status);
  }
  return body;
}

const query = (params: Record<string, string | number | undefined>): string => {
  const pairs = Object.entries(params).filter(([, value]) => value !== undefined);
  return pairs.length ? `?${new URLSearchParams(pairs.map(([k, v]) => [k, String(v)]))}` : '';
};

/** Start a decision. Naming it first is what makes live polling possible. */
export const evaluateLot = (input: {
  lotId: string;
  decisionRecordId?: string;
  document?: string;
  documentB64?: string;
  artifactRef?: string;
  contentType?: string;
  documentType?: string;
}) =>
  request('/evaluate', {
    method: 'POST',
    body: JSON.stringify({
      lot_id: input.lotId,
      decision_record_id: input.decisionRecordId,
      document: input.document,
      document_b64: input.documentB64,
      artifact_ref: input.artifactRef,
      content_type: input.contentType,
      document_type: input.documentType,
    }),
  });

/** Supply authoritative evidence to an open decision. Not an approval. */
export const supplyEvidence = (input: {
  decisionRecordId: string;
  lotId: string;
  authoritySource: string;
  document?: string;
  documentB64?: string;
  contentType?: string;
  documentType?: string;
}) =>
  request('/evidence', {
    method: 'POST',
    body: JSON.stringify({
      decision_record_id: input.decisionRecordId,
      lot_id: input.lotId,
      authority_source: input.authoritySource,
      document: input.document,
      document_b64: input.documentB64,
      content_type: input.contentType,
      document_type: input.documentType,
    }),
  });

export const listDecisions = (limit?: number) => request(`/decisions${query({ limit })}`);

export const getDecision = (decisionRecordId: string) =>
  request(`/decisions/${encodeURIComponent(decisionRecordId)}`);

/**
 * Events after a cursor. `afterSequence` is what keeps polling cheap and makes
 * re-delivery harmless — the caller asks only for what it has not seen.
 */
export const getEvents = (decisionRecordId: string, afterSequence = 0, limit?: number) =>
  request(
    `/decisions/${encodeURIComponent(decisionRecordId)}/events${query({
      after_sequence: afterSequence,
      limit,
    })}`,
  );

/**
 * Source metadata, and a short-lived `view_ref` when one can be signed.
 *
 * The reference expires, so it is fetched when a viewer opens a document rather
 * than stored alongside the decision.
 */
export const getSources = (decisionRecordId: string, artifactId?: string) =>
  request(
    `/decisions/${encodeURIComponent(decisionRecordId)}/sources${query({
      artifact_id: artifactId,
    })}`,
  );

export const getToday = () => request('/today');

/**
 * Fetch a signed source document as an object URL the page can render.
 *
 * S3 refuses to be framed cross-origin — the browser aborts the load silently
 * and an <iframe src=presigned> shows a blank white box, which is worse than no
 * preview at all. Fetching the bytes and wrapping them in a same-origin
 * `blob:` URL sidesteps that without touching the document.
 *
 * The presigned URL is used once, here, and never returned to the caller: it is
 * a bearer credential, and the blob URL that comes back grants no further S3
 * access. The caller MUST revoke the blob URL when it is done with it.
 */
export const fetchSourceObjectUrl = async (
  decisionRecordId: string,
  artifactId: string,
): Promise<{ url: string; contentType: string } | null> => {
  const body = (await getSources(decisionRecordId, artifactId)) as {
    sources?: { artifact_id: string; view_ref?: string; view_url?: string }[];
    artifacts?: { artifact_id: string; view_ref?: string; view_url?: string }[];
  };
  const list = body.sources ?? body.artifacts ?? [];
  const match = list.find((a) => a.artifact_id === artifactId) ?? list[0];
  const signed = match?.view_ref ?? match?.view_url;
  if (!signed) return null;

  const response = await fetch(signed);
  if (!response.ok) return null;
  const blob = await response.blob();
  return { url: URL.createObjectURL(blob), contentType: blob.type };
};

/**
 * Read a bundled asset as base64.
 *
 * The canonical COA is shipped as a build asset rather than inlined, so getting
 * its bytes needs a fetch — and every fetch in this app belongs here, in the one
 * sanctioned transport seam, rather than in a component. Same-origin only: the
 * URL comes from the bundler, never from a server response.
 *
 * Chunked because spreading a 160KB byte array into `String.fromCharCode`
 * overflows the argument limit.
 */
export const fetchAssetAsBase64 = async (url: string): Promise<string> => {
  const response = await fetch(url);
  if (!response.ok) {
    throw new TransportError('the source document could not be read', response.status);
  }
  const bytes = new Uint8Array(await response.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
};

/** A decision id the caller owns before any work starts. */
export const newDecisionRecordId = (): string => {
  const bytes = crypto.getRandomValues(new Uint8Array(6));
  return `DR-${Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('')}`;
};
