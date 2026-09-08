/**
 * The persistent inner-left column: the source, and what has been established.
 *
 * It is sticky because its job is to stay true while stages move past it. The
 * reference calls the second panel "CASE — DURABLE FACTS", and the name is the
 * constraint: only facts that cannot later be retracted go here. A disposition
 * is not one of them until it has actually been computed, which is why
 * `holdTruth` is null for most of a run.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import * as api from '../adapter/client';
import { Eyebrow, Field, GhostButton, INK, MONO, N, Panel, Pill, SANS, HAIR } from './primitives';
import type { EstablishedTruthVM, SourceArtifactVM } from './model';

const TRUST_COPY: Record<SourceArtifactVM['trustClass'], { label: string; color: string }> = {
  supplier_untrusted: { label: 'Supplier-declared · Untrusted', color: '#9A5A2A' },
  quarantined: { label: 'Quarantined · excluded', color: '#9A5A2A' },
  human_authorized: { label: 'Human-authorized', color: '#3E6B54' },
  internal: { label: 'Authoritative internal', color: '#3E6B54' },
};

/**
 * The real first page of the real document.
 *
 * `view_ref` is a short-lived presigned URL and a bearer credential, so it is
 * fetched here the same way the full viewer fetches it — on demand, held in a
 * ref, never in state, never logged, never persisted — and dropped when the
 * component unmounts. It is rendered in a sandboxed <iframe> with the PDF
 * viewer's own chrome suppressed, so what an operator sees is the actual
 * version-pinned bytes rather than a drawing of them.
 *
 * Cross-origin S3 will not always render inline (a Content-Disposition or a
 * blocked frame ancestor both defeat it), and that failure is silent. So the
 * frame is given a bounded window to report load; if it does not, the component
 * falls back to the schematic below rather than showing an empty white box.
 * `pointer-events: none` keeps the preview a preview — opening the document is
 * the "Open source" affordance's job, and the credential is not reusable.
 */
function RealDocumentPreview({
  artifactId,
  decisionRecordId,
  onReady,
  onFail,
}: {
  artifactId: string;
  decisionRecordId: string;
  /** The bytes are in hand and framed; the schematic can stand down. */
  onReady: () => void;
  onFail: () => void;
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);

  /**
   * The callbacks, held so they cannot re-key the effect.
   *
   * `onReady` sets parent state, which gives both callbacks new identities on
   * the next render. With them in the dependency array the effect re-ran,
   * its cleanup revoked the object URL that had just been handed to the frame,
   * and the frame's src died mid-load — `onError` then fired and the panel fell
   * back to the schematic. The effect must depend on the ARTIFACT only.
   */
  const cbs = useRef({ onReady, onFail });
  cbs.current = { onReady, onFail };

  useEffect(() => {
    let live = true;
    let created: string | null = null;
    void (async () => {
      try {
        const found = await api.fetchSourceObjectUrl(decisionRecordId, artifactId);
        if (!live) {
          if (found) URL.revokeObjectURL(found.url);
          return;
        }
        if (!found) {
          cbs.current.onFail();
          return;
        }
        created = found.url;
        setObjectUrl(found.url);
        cbs.current.onReady();
      } catch {
        if (live) cbs.current.onFail();
      }
    })();
    return () => {
      live = false;
      // The blob is released with the component. Holding it would keep the
      // document's bytes alive in the tab for as long as the session lasts.
      if (created) URL.revokeObjectURL(created);
    };
  }, [artifactId, decisionRecordId]);

  if (!objectUrl) return null;

  return (
    <div
      data-testid="source-preview-real"
      style={{
        marginTop: 10,
        height: 132,
        background: '#fff',
        border: '1px solid rgba(0,0,0,.14)',
        borderRadius: 4,
        boxShadow: '0 1px 4px rgba(0,0,0,.08)',
        overflow: 'hidden',
        position: 'relative',
        animation: 'vFade .3s ease-out both',
      }}
    >
      <iframe
        src={`${objectUrl}#toolbar=0&navpanes=0&scrollbar=0&view=FitH`}
        title="Source document preview"
        tabIndex={-1}
        onError={() => cbs.current.onFail()}
        style={{
          // 161% wide, scaled to 62%: the first page fills the panel's width
          // instead of rendering as unreadable body text in a narrow column.
          width: '161%',
          height: 420,
          border: 'none',
          transform: 'scale(.62)',
          transformOrigin: 'top left',
          pointerEvents: 'none',
        }}
      />
    </div>
  );
}

/**
 * The neutral placeholder shown WHILE a real PDF is being fetched.
 *
 * The schematic below is a drawing of a document — fine as a stand-in when no
 * bytes exist, misleading while the actual bytes are on their way, because it
 * shows invented geometry where the real certificate is about to appear. This
 * says only "a document is loading" and asserts nothing about its contents.
 */
function DocumentLoading() {
  return (
    <div
      data-testid="source-preview-loading"
      style={{
        marginTop: 10,
        height: 132,
        background: '#fff',
        border: '1px solid rgba(0,0,0,.14)',
        borderRadius: 4,
        boxShadow: '0 1px 4px rgba(0,0,0,.08)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      aria-hidden
    >
      <div style={{ font: `400 9.5px ${MONO}`, color: INK.placeholder, animation: 'vp 1.4s ease-in-out infinite' }}>
        loading source document…
      </div>
    </div>
  );
}

/**
 * The fallback miniature, used ONLY when no real source can be previewed.
 *
 * Not decorative: it is the cue that a specific number in a specific document
 * is what the decision turned on. The highlighted bar sits where that value is.
 * Whenever the actual bytes can be shown, they are shown instead.
 */
function DocumentThumbnail({ fact }: { fact: string | null }) {
  return (
    <div
      data-testid="source-preview-schematic"
      style={{
        marginTop: 10,
        background: '#fff',
        border: '1px solid rgba(0,0,0,.14)',
        borderRadius: 4,
        padding: '13px 14px',
        boxShadow: '0 1px 4px rgba(0,0,0,.08)',
      }}
      aria-hidden
    >
      <div style={{ height: 7, width: '55%', background: '#e3ded3', borderRadius: 2 }} />
      {['82%', '72%', '78%'].map((w, i) => (
        <div
          key={w}
          style={{
            height: 5,
            width: w,
            background: '#eee9df',
            borderRadius: 2,
            marginTop: i === 0 ? 8 : 5,
          }}
        />
      ))}
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginTop: 9 }}>
        <div style={{ height: 9, width: '38%', background: '#f2d9c9', borderRadius: 2 }} />
        {fact && (
          <span style={{ font: `600 8.5px ${MONO}`, color: '#9A5A2A' }}>{fact}</span>
        )}
      </div>
    </div>
  );
}

export function CaseContextColumn({
  sources,
  selectedId,
  truth,
  pending = false,
  decisionRecordId,
  onSelect,
  onOpenSource,
}: {
  sources: SourceArtifactVM[];
  selectedId: string | null;
  /** Needed to sign a short-lived `view_ref` for the real preview. */
  decisionRecordId?: string;
  truth: EstablishedTruthVM;
  /**
   * An artifact is known to exist but has not arrived yet. Distinguishes
   * "not persisted yet" from "does not exist" — two different facts.
   */
  pending?: boolean;
  onSelect: (artifactId: string) => void;
  onOpenSource: (artifactId: string) => void;
}) {
  const selected = sources.find((s) => s.artifactId === selectedId) ?? sources[0] ?? null;
  const alternates = sources.filter((s) => s.artifactId !== selected?.artifactId);

  const meta = selected
    ? [
        selected.pageCount ? `${selected.pageCount} pp` : null,
        selected.documentType?.toUpperCase(),
        selected.versionId ? `v${selected.versionId.slice(0, 6)}` : null,
        selected.hashSummary ? `hash ${selected.hashSummary}` : null,
      ]
        .filter(Boolean)
        .join(' · ')
    : '';

  const keyFact =
    selected?.claims.find((c) => c.value)?.value ??
    (selected?.securityState === 'quarantined' ? '⊘ hold' : null);

  /**
   * Whether the real bytes can be shown for the CURRENT artifact.
   *
   * Keyed by artifact id so switching sources re-attempts the real preview
   * rather than inheriting a previous artifact's failure.
   */
  const [previewFailed, setPreviewFailed] = useState<string | null>(null);
  const [readyFor, setReadyFor] = useState<string | null>(null);
  const onPreviewFail = useCallback(
    () => setPreviewFailed(selected?.artifactId ?? null),
    [selected?.artifactId],
  );
  const onPreviewReady = useCallback(
    () => setReadyFor(selected?.artifactId ?? null),
    [selected?.artifactId],
  );
  const previewReady = !!selected && readyFor === selected.artifactId;
  // A quarantined artifact is deliberately never previewed: its bytes were
  // excluded from the decision, and rendering them beside the case would
  // present withheld material as though it had been read.
  const canPreviewReal =
    !!selected &&
    selected.openable &&
    selected.securityState !== 'quarantined' &&
    previewFailed !== selected.artifactId &&
    !!decisionRecordId;

  return (
    <div style={{ position: 'sticky', top: 0, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <Panel>
        <Eyebrow>SOURCE EVIDENCE</Eyebrow>

        {selected ? (
          <>
            {/* The real bytes when they can be shown, the schematic when they
                cannot. The schematic also holds the space WHILE the real
                preview loads, so the panel is never empty and never a blank
                white rectangle — which is what an unframeable cross-origin PDF
                produces, and which reads as a broken document rather than as a
                document that could not be previewed. */}
            {canPreviewReal && (
              <RealDocumentPreview
                artifactId={selected.artifactId}
                decisionRecordId={decisionRecordId!}
                onReady={onPreviewReady}
                onFail={onPreviewFail}
              />
            )}
            {/* Three distinct states, because they mean different things:
                the real page once it paints; a neutral "loading" card while the
                real bytes are in flight; and the schematic only when there are
                no bytes to show at all. Drawing the schematic under a document
                that is about to render put invented geometry where the real
                certificate belongs. */}
            {!previewReady &&
              (canPreviewReal ? <DocumentLoading /> : <DocumentThumbnail fact={keyFact} />)}
            <div style={{ font: `600 12.5px ${SANS}`, color: INK.primary, marginTop: 11 }}>
              {selected.displayName}
            </div>
            <div style={{ font: `400 10px ${MONO}`, color: INK.label, marginTop: 2 }}>{meta}</div>

            <div style={{ marginTop: 9, display: 'flex', alignItems: 'center', gap: 7 }}>
              <span
                style={{
                  font: `600 8px ${MONO}`,
                  letterSpacing: '.05em',
                  color: TRUST_COPY[selected.trustClass].color,
                  border: `1px solid ${TRUST_COPY[selected.trustClass].color}55`,
                  borderRadius: 4,
                  padding: '2px 6px',
                }}
              >
                {TRUST_COPY[selected.trustClass].label.toUpperCase()}
              </span>
              {selected.securityState === 'quarantined' && (
                <Pill tone="quarantine">⊘ EXCLUDED</Pill>
              )}
            </div>

            {/* Sponsor depth: the compact EXTRACTION row, in the existing
                provenance area. Meaning first; method is secondary metadata. */}
            {selected.extraction && (
              <div
                style={{
                  marginTop: 10,
                  paddingTop: 9,
                  borderTop: `1px solid rgba(0,0,0,.08)`,
                }}
                data-testid="extraction-row"
              >
                <div style={{ font: `500 9px ${MONO}`, letterSpacing: '.06em', color: INK.label }}>
                  EXTRACTION
                </div>
                <div style={{ font: `600 11px ${SANS}`, color: INK.dense, marginTop: 3 }}>
                  {selected.extraction.headline}
                  {selected.extraction.claimCount > 0 &&
                    ` · ${selected.extraction.claimCount} claim${selected.extraction.claimCount === 1 ? '' : 's'}`}
                </div>
                <div style={{ font: `400 9.5px ${MONO}`, color: INK.label, marginTop: 2 }}>
                  {selected.extraction.confidenceGatePassed === false
                    ? 'confidence gate not met'
                    : selected.extraction.confidenceGatePassed
                      ? 'confidence gate passed'
                      : ''}
                  {selected.extraction.method ? ` · ${selected.extraction.method.toLowerCase()}` : ''}
                </div>
                {selected.extraction.identityTrusted === false && (
                  <div style={{ font: `400 9.5px ${MONO}`, color: '#9A5A2A', marginTop: 3 }}>
                    identity not established from this reading
                  </div>
                )}
              </div>
            )}

            <div style={{ marginTop: 11 }}>
              <GhostButton
                onClick={() => onOpenSource(selected.artifactId)}
                disabled={!selected.openable}
                title={selected.openable ? undefined : 'No signed reference available'}
              >
                Open source
              </GhostButton>
            </div>

            {alternates.length > 0 && (
              <div style={{ marginTop: 11 }}>
                <div style={{ font: `500 9px ${MONO}`, letterSpacing: '.06em', color: INK.label }}>
                  ALTERNATE SOURCES
                </div>
                {alternates.map((a) => (
                  <button
                    key={a.artifactId}
                    type="button"
                    onClick={() => onSelect(a.artifactId)}
                    style={{
                      display: 'block',
                      width: '100%',
                      textAlign: 'left',
                      marginTop: 6,
                      background: N.nested,
                      border: `1px solid ${HAIR}`,
                      borderRadius: 7,
                      padding: '7px 9px',
                      cursor: 'pointer',
                      font: `600 10.5px ${MONO}`,
                      color: INK.dense,
                    }}
                  >
                    {a.displayName}
                  </button>
                ))}
              </div>
            )}
          </>
        ) : (
          /* "Not persisted yet" and "does not exist" are different facts.
             While a decision is in flight the artifact is being received and
             the record is not yet queryable, so the honest statement is that
             it is arriving — not that there is none. */
          <div
            data-testid="source-pending"
            style={{ font: `400 11px ${MONO}`, color: INK.placeholder, marginTop: 10 }}
          >
            {pending ? 'Receiving source evidence…' : 'No source artifact yet.'}
          </div>
        )}
      </Panel>

      <Panel style={{ display: 'flex', flexDirection: 'column', gap: 11 }}>
        <Eyebrow>CASE — DURABLE FACTS</Eyebrow>
        <Field label="LOT" value={truth.lotLine || '—'} />
        {/* Em-dash until the Investigator's brief actually resolves the basis.
            Showing anything else would imply it was known earlier than it was. */}
        <Field label="GOVERNING BASIS" value={truth.governingBasis ?? '—'} />
        <Field
          label="BOUND FACT"
          value={truth.boundFact ? `${truth.boundFact.value}` : '—'}
        />
        {truth.holdTruth && <Field label="STATE" value={truth.holdTruth} />}
      </Panel>
    </div>
  );
}
