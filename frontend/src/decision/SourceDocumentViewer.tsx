/**
 * The source document viewer (modal, never navigates away).
 *
 * The rule that shapes this file: `view_ref` is a TRANSIENT BEARER CREDENTIAL.
 * A presigned S3 URL with a 300s TTL grants whoever holds it read access to the
 * evidence, so it is:
 *
 *   - fetched only when a viewer actually opens a document;
 *   - never written to component state that outlives the modal;
 *   - never put in localStorage, sessionStorage, or a URL;
 *   - never logged.
 *
 * It is used once, to fetch the bytes, and then dropped. `useRef` rather than
 * `useState` is deliberate — the URL must not become part of a render tree that
 * React could retain or a devtools session could inspect after the fact.
 *
 * The document is rendered IN PLACE rather than handed to a new tab. Navigating
 * away from the workspace to read the evidence loses the decision the evidence
 * belongs to, and handing a presigned S3 URL to a new tab also puts a live
 * bearer credential in the address bar and browser history. Fetching the bytes
 * into a same-origin `blob:` and framing that keeps the credential in this
 * document and out of everything that outlives it.
 *
 * When no reference can be signed, the metadata is still shown. "We cannot show
 * you the bytes" and "we know nothing about this document" are different states.
 */

import { useEffect, useRef, useState } from 'react';
import * as api from '../adapter/client';
import { GhostButton, INK, MONO, N, Pill, SANS, HAIR } from './primitives';
import type { SourceArtifactVM } from './model';

const TRUST_CHIP: Record<
  SourceArtifactVM['trustClass'],
  { text: string; fg: string; bg: string; br: string }
> = {
  supplier_untrusted: {
    text: 'Supplier-declared · Untrusted',
    fg: '#9A5A2A',
    bg: '#F6EEE6',
    br: 'rgba(154,90,42,.4)',
  },
  quarantined: {
    text: 'Quarantined · excluded from decision',
    fg: '#9A5A2A',
    bg: '#F6EEE6',
    br: 'rgba(154,90,42,.5)',
  },
  human_authorized: {
    text: 'Human-authorized · authoritative',
    fg: '#3E6B54',
    bg: '#E6EEE8',
    br: 'rgba(62,107,84,.4)',
  },
  internal: {
    text: 'Authoritative internal',
    fg: '#3E6B54',
    bg: '#E6EEE8',
    br: 'rgba(62,107,84,.4)',
  },
};

export function SourceDocumentViewer({
  artifact,
  decisionRecordId,
  onClose,
}: {
  artifact: SourceArtifactVM;
  decisionRecordId: string;
  onClose: () => void;
}) {
  // Never state. The URL must not persist in a render tree.
  const viewRef = useRef<string | null>(null);
  const [status, setStatus] = useState<'idle' | 'loading' | 'ready' | 'unavailable'>(
    artifact.openable ? 'idle' : 'unavailable',
  );
  /** The same-origin blob the frame renders. Not the presigned URL. */
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      // Drop the credential the moment the viewer closes.
      viewRef.current = null;
    };
  }, []);

  // The blob is released with the viewer; holding it would keep the document's
  // bytes alive in the tab for the rest of the session.
  useEffect(() => {
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  /**
   * Fetch the bytes as soon as the viewer opens.
   *
   * The operator asked to see the document by opening this; making them press a
   * second button to actually reveal it is a step with no meaning.
   */
  useEffect(() => {
    if (!artifact.openable) return;
    let live = true;
    setStatus('loading');
    void (async () => {
      try {
        const found = await api.fetchSourceObjectUrl(decisionRecordId, artifact.artifactId);
        if (!live) {
          if (found) URL.revokeObjectURL(found.url);
          return;
        }
        if (!found) {
          setStatus('unavailable');
          return;
        }
        setObjectUrl(found.url);
        setStatus('ready');
      } catch {
        // A failed signing or fetch is not a statement about the document.
        if (live) setStatus('unavailable');
      }
    })();
    return () => {
      live = false;
    };
  }, [artifact.openable, artifact.artifactId, decisionRecordId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const chip = TRUST_CHIP[artifact.trustClass];
  const locators = artifact.locators;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={`Source document ${artifact.displayName}`}
      data-testid="source-viewer"
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(33,31,27,.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 50,
        padding: 40,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 860,
          maxWidth: '100%',
          maxHeight: '100%',
          background: N.frame,
          borderRadius: 14,
          boxShadow: '0 30px 90px rgba(0,0,0,.45)',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
        }}
      >
        <div
          style={{
            flex: 'none',
            background: INK.primary,
            color: '#F6F3EC',
            padding: '14px 20px',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <div style={{ font: `700 14px ${SANS}` }}>{artifact.displayName}</div>
          <span
            style={{
              font: `700 9px ${MONO}`,
              letterSpacing: '.04em',
              color: chip.fg,
              background: chip.bg,
              border: `1px solid ${chip.br}`,
              borderRadius: 5,
              padding: '4px 9px',
            }}
          >
            {chip.text}
          </span>
          <div style={{ flex: 1 }} />
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            style={{
              background: 'rgba(255,255,255,.12)',
              border: 'none',
              color: '#F6F3EC',
              borderRadius: 7,
              width: 26,
              height: 26,
              cursor: 'pointer',
              font: `600 12px ${MONO}`,
            }}
          >
            ✕
          </button>
        </div>

        <div style={{ flex: 1, overflowY: 'auto', padding: '18px 20px', background: '#CFC9BD' }}>
          {/* The actual version-pinned bytes, framed same-origin. Never a
              reconstruction: if these cannot be fetched the panel below says
              so rather than drawing a substitute document. */}
          {artifact.openable && (
            <div
              data-testid="source-document-frame"
              style={{
                marginBottom: 16,
                height: 460,
                background: '#fff',
                border: '1px solid rgba(0,0,0,.14)',
                borderRadius: 4,
                boxShadow: '0 2px 12px rgba(0,0,0,.14)',
                overflow: 'hidden',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {objectUrl ? (
                <iframe
                  src={`${objectUrl}#view=FitH`}
                  title={`Source document ${artifact.displayName}`}
                  style={{ width: '100%', height: '100%', border: 'none' }}
                />
              ) : (
                <div
                  style={{
                    font: `400 11px ${MONO}`,
                    color: INK.placeholder,
                    animation: status === 'loading' ? 'vp 1.4s ease-in-out infinite' : undefined,
                  }}
                >
                  {status === 'unavailable'
                    ? 'the original bytes could not be retrieved'
                    : 'loading source document…'}
                </div>
              )}
            </div>
          )}

          <div
            style={{
              background: '#fff',
              border: '1px solid rgba(0,0,0,.14)',
              borderRadius: 4,
              padding: '22px 26px',
              boxShadow: '0 2px 12px rgba(0,0,0,.14)',
            }}
          >
            <div style={{ font: `400 10px ${MONO}`, color: INK.label }}>
              {[
                artifact.documentType?.toUpperCase(),
                artifact.pageCount ? `${artifact.pageCount} pp` : null,
                artifact.versionId ? `v${artifact.versionId.slice(0, 8)}` : null,
                artifact.hashSummary ? `hash ${artifact.hashSummary}` : null,
              ]
                .filter(Boolean)
                .join(' · ')}
            </div>

            {artifact.excludedFromDecision && (
              <div
                style={{
                  marginTop: 14,
                  background: '#F6EEE6',
                  border: '1px solid rgba(154,90,42,.4)',
                  borderLeft: '4px solid #9A5A2A',
                  borderRadius: 10,
                  padding: '13px 16px',
                }}
              >
                <Pill tone="quarantine" big>
                  ⊘ EXCLUDED FROM DECISION
                </Pill>
                <div style={{ font: `400 12.5px/1.55 ${SANS}`, color: '#5C4326', marginTop: 9 }}>
                  This artifact was preserved for the record. It was not used to decide anything.
                </div>
              </div>
            )}

            <div style={{ marginTop: 16 }}>
              <div style={{ font: `600 9.5px ${MONO}`, letterSpacing: '.08em', color: INK.label }}>
                DECLARED CLAIMS
              </div>
              {artifact.claims.length === 0 ? (
                <div style={{ font: `400 11px ${MONO}`, color: INK.placeholder, marginTop: 8 }}>
                  {/* Two different facts, two different sentences. Saying "no
                      claims" when the backend reported a count would be
                      asserting something about the document that is false. */}
                  {artifact.claimCount > 0
                    ? `${artifact.claimCount} claim${artifact.claimCount === 1 ? '' : 's'} were extracted and frozen into the decision snapshot. They are not itemized on this view.`
                    : 'No claims were extracted from this document.'}
                </div>
              ) : (
                artifact.claims.map((c, i) => (
                  <div
                    key={`${c.label}-${i}`}
                    style={{
                      display: 'flex',
                      alignItems: 'baseline',
                      gap: 10,
                      padding: '9px 0',
                      borderBottom: '1px solid rgba(0,0,0,.06)',
                    }}
                  >
                    <span
                      style={{
                        font: `600 8px ${MONO}`,
                        letterSpacing: '.05em',
                        color: '#9A5A2A',
                        border: '1px solid rgba(154,90,42,.4)',
                        borderRadius: 4,
                        padding: '2px 6px',
                        flex: 'none',
                      }}
                    >
                      SUPPLIER-DECLARED
                    </span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ font: `400 12px ${SANS}`, color: INK.dense }}>{c.label}</div>
                      {/* Provenance, not decoration: WHERE in this document the
                          value was read, and by what method. A claim without
                          its locator is an assertion; with it, it is evidence. */}
                      {(c.locator || c.method) && (
                        <div
                          data-testid="claim-provenance"
                          style={{ font: `400 9.5px ${MONO}`, color: INK.label, marginTop: 2 }}
                        >
                          {[c.locator, c.method, c.condition].filter(Boolean).join(' · ')}
                        </div>
                      )}
                    </div>
                    <div style={{ font: `700 12px ${MONO}`, color: INK.primary }}>{c.value}</div>
                  </div>
                ))
              )}
            </div>

            {status === 'unavailable' && (
              <div
                data-testid="source-unavailable"
                style={{
                  marginTop: 16,
                  background: N.fill,
                  border: `1px solid ${HAIR}`,
                  borderRadius: 10,
                  padding: '13px 16px',
                }}
              >
                <div style={{ font: `700 11px ${MONO}`, letterSpacing: '.05em', color: INK.muted }}>
                  SOURCE UNAVAILABLE
                </div>
                <div style={{ font: `400 12px/1.5 ${SANS}`, color: INK.prose, marginTop: 6 }}>
                  The original bytes could not be retrieved right now. Everything shown above is
                  from the durable record and remains accurate.
                </div>
              </div>
            )}
          </div>
        </div>

        <div
          style={{
            flex: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '11px 18px',
            background: N.card,
            borderTop: `1px solid ${HAIR}`,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ font: `400 10px ${MONO}`, color: INK.label }}>SOURCE LOCATOR</span>
          <span
            style={{ font: `600 11px ${MONO}`, color: INK.button }}
            data-testid="source-locator"
          >
            {/* Structured locators render as the approved
                "Page 3 · Table 1 · Tensile — mean · Result"; ordinary sources
                keep their existing plain locator shape. Both are valid. */}
            {locators.length
              ? locators[0].label
              : artifact.claims[0]?.locator || 'not recorded'}
          </span>
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 10 }}>
            <span style={{ font: `400 10px ${MONO}`, color: INK.label }}>
              {artifact.excludedFromDecision
                ? 'Preserved for the record · not used in decision'
                : 'Read-only source'}
            </span>
            <GhostButton small onClick={onClose}>
              Close
            </GhostButton>
          </div>
        </div>
      </div>
    </div>
  );
}
