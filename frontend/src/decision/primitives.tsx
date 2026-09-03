/**
 * The reusable visual primitives from the approved design reference.
 *
 * These are a faithful port of the reference's inline styles, lifted into
 * components so the literals live in one place. The reference itself has no
 * classes and no custom properties — every value is repeated inline — so
 * extracting them is the only way to keep the React version consistent.
 *
 * What is deliberately NOT ported: the demo's timers, transport controls,
 * layout toggle and fabricated event arrays. Those drive the reference's
 * playback and would make the product lie about what the backend did.
 */

import type { CSSProperties, ReactNode } from 'react';
import { SEM } from '../components/tokens';
import type { SemanticTone } from '../view-models/types';

/** Neutral ramp, from the reference. */
export const N = {
  canvas: '#CFC9BD',
  frame: '#F0EDE6',
  card: '#F6F3EC',
  recessed: '#F1EEE7',
  nested: '#FBFAF6',
  chip: '#EFEBE2',
  fill: '#EAE6DD',
  newest: '#EFE9DE',
} as const;

/** Ink ramp. */
export const INK = {
  primary: '#211F1B',
  dense: '#413D35',
  prose: '#57534A',
  button: '#4A463E',
  muted: '#6B655B',
  label: '#8A8478',
  faint: '#9A9384',
  placeholder: '#A39C8D',
  chevron: '#B7B0A2',
} as const;

export const HAIR = 'rgba(0,0,0,.1)';
export const MONO = "'IBM Plex Mono', ui-monospace, monospace";
export const SANS = "'Public Sans', system-ui, sans-serif";

/** Actor → color. Drives the rail gutter, rail actor text and stage dots. */
export const ACTOR_COLOR: Record<string, string> = {
  evidence: '#9A5A2A',
  security: '#9A5A2A',
  investigator: '#6B655B',
  verifier: '#211F1B',
  system: '#3E6B54',
  operations: '#8E2B24',
  human: '#45508C',
};

export const STAGE_DOT: Record<string, string> = {
  evidence: '#9A5A2A',
  investigator: '#6B655B',
  verifier: '#211F1B',
  reconciliation: '#3E6B54',
  disposition: '#3E6B54',
  consequence: '#8E2B24',
};

/**
 * The single pill primitive. Two sizes, eight tones, nothing else.
 *
 * Every significant state ships its meaning in the LABEL, so the pill survives
 * grayscale and colour-blindness: `blocked` is the only inverted fill and
 * `quarantine` the only transparent outline, but neither carries meaning that
 * the text does not also carry.
 */
export function Pill({
  tone,
  children,
  big = false,
  style,
}: {
  tone: SemanticTone;
  children: ReactNode;
  big?: boolean;
  style?: CSSProperties;
}) {
  const t = SEM[tone];
  return (
    <span
      style={{
        display: 'inline-block',
        font: `700 ${big ? 11 : 10}px ${MONO}`,
        letterSpacing: '.05em',
        color: t.fg,
        background: t.bg,
        border: `1px solid ${t.br}`,
        borderRadius: 6,
        padding: big ? '5px 12px' : '3px 9px',
        whiteSpace: 'nowrap',
        ...style,
      }}
    >
      {children}
    </span>
  );
}

/** Eyebrow label above a panel or section. */
export function Eyebrow({ children, size = 9 }: { children: ReactNode; size?: number }) {
  return (
    <div style={{ font: `600 ${size}px ${MONO}`, letterSpacing: '.08em', color: INK.label }}>
      {children}
    </div>
  );
}

/** The micro-label + mono-value field pair used throughout the context column. */
export function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: string;
}) {
  return (
    <div>
      <div style={{ font: `500 9px ${MONO}`, letterSpacing: '.06em', color: INK.label }}>
        {label}
      </div>
      <div
        style={{
          font: `600 12px ${MONO}`,
          color: tone ?? INK.primary,
          marginTop: 3,
          wordBreak: 'break-word',
        }}
      >
        {value}
      </div>
    </div>
  );
}

/** A surface card. `recessed` is the collapsed/secondary tone. */
export function Panel({
  children,
  recessed = false,
  style,
}: {
  children: ReactNode;
  recessed?: boolean;
  style?: CSSProperties;
}) {
  return (
    <div
      style={{
        background: recessed ? N.recessed : N.card,
        border: `1px solid ${recessed ? 'rgba(0,0,0,.08)' : HAIR}`,
        borderRadius: 13,
        padding: '15px 16px',
        ...style,
      }}
    >
      {children}
    </div>
  );
}

/** Ghost button. The only button shape in the product surface. */
export function GhostButton({
  children,
  onClick,
  small = false,
  disabled = false,
  title,
}: {
  children: ReactNode;
  onClick?: () => void;
  small?: boolean;
  disabled?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        font: `600 ${small ? 10 : 11}px ${MONO}`,
        color: disabled ? INK.placeholder : INK.button,
        background: N.chip,
        border: `1px solid rgba(0,0,0,.14)`,
        borderRadius: small ? 7 : 8,
        padding: small ? '5px 10px' : '8px',
        width: small ? undefined : '100%',
        textAlign: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.6 : 1,
        whiteSpace: 'nowrap',
        fontFamily: MONO,
      }}
    >
      {children}
    </button>
  );
}

/** Rounded-square status dot. Never the sole carrier of meaning. */
export function Dot({ color, round = false }: { color: string; round?: boolean }) {
  return (
    <span
      style={{
        width: round ? 6 : 8,
        height: round ? 6 : 8,
        borderRadius: round ? '50%' : 2,
        background: color,
        flex: 'none',
        display: 'inline-block',
      }}
    />
  );
}
