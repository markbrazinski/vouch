/**
 * Truthful surface states.
 *
 * "No records" and "records have not loaded yet" are different facts about the
 * world, and a surface that renders one when the other is true is lying to an
 * operator. So is a technical failure that reads like a quality verdict — the
 * distinction the integration contract's invariant 1 exists to protect
 * ("a failure never becomes a disposition").
 *
 * The kinds here are deliberately not one `error` state:
 *
 *   loading      — the answer is on its way
 *   empty        — the backend answered, and the answer is genuinely nothing
 *   blocked      — an authoritative path exists but this deployment cannot
 *                  reach it (a missing grant, not a missing fact)
 *   failure      — the request did not complete; NOTHING is known
 *   unavailable  — a sub-resource (a source document) could not be produced
 */

import type { ReactNode } from 'react';
import { T } from './tokens';

export type SurfaceStateKind = 'loading' | 'empty' | 'blocked' | 'failure' | 'unavailable';

const ACCENT: Record<SurfaceStateKind, string> = {
  loading: T.faint,
  empty: T.faint,
  blocked: '#8a6318',
  failure: '#8E2B24',
  unavailable: '#8a6318',
};

/** The word that names the state. Never "Error" for a domain outcome. */
const KICKER: Record<SurfaceStateKind, string> = {
  loading: 'LOADING',
  empty: 'NOTHING TO SHOW',
  blocked: 'NOT AVAILABLE IN THIS DEPLOYMENT',
  failure: 'COULD NOT LOAD',
  unavailable: 'SOURCE UNAVAILABLE',
};

export function SurfaceState({
  kind,
  headline,
  detail,
  children,
}: {
  kind: SurfaceStateKind;
  headline: string;
  /**
   * Why. For `blocked` and `failure` this is the operator's only route to a
   * cause, so it should name the thing that is missing rather than apologise.
   */
  detail?: string;
  children?: ReactNode;
}) {
  return (
    <div
      role={kind === 'failure' || kind === 'blocked' ? 'alert' : 'status'}
      aria-busy={kind === 'loading' || undefined}
      data-surface-state={kind}
      style={{
        margin: '18px 0',
        padding: '22px 24px',
        background: T.panel,
        border: `1px solid ${kind === 'failure' ? 'rgba(142,43,36,.34)' : T.hairline}`,
        borderRadius: 13,
        maxWidth: 720,
      }}
    >
      <div
        style={{
          font: "600 10px 'IBM Plex Mono'",
          letterSpacing: '.1em',
          color: ACCENT[kind],
        }}
      >
        {KICKER[kind]}
      </div>
      <div
        style={{
          margin: '7px 0 0',
          font: "700 15px 'Public Sans'",
          color: T.ink,
        }}
      >
        {headline}
      </div>
      {detail && (
        <p
          style={{
            margin: '6px 0 0',
            font: "400 12.5px/1.55 'Public Sans'",
            color: T.muted,
            maxWidth: 620,
          }}
        >
          {detail}
        </p>
      )}
      {children && <div style={{ marginTop: 12 }}>{children}</div>}
    </div>
  );
}

/**
 * A technical failure, stated as one.
 *
 * It carries no disposition and no readiness on purpose: when a fetch fails,
 * nothing has been established about any material or any order.
 */
export function TechnicalFailure({ what, detail }: { what: string; detail?: string }) {
  return (
    <SurfaceState
      kind="failure"
      headline={`${what} could not be loaded`}
      detail={
        detail ??
        'This is a transport or persistence failure, not a quality outcome. ' +
          'Nothing has been decided about any lot or order as a result.'
      }
    />
  );
}
