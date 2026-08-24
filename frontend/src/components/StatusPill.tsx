import type { CSSProperties } from 'react';
import { SEM } from './tokens';
import type { ProductionReadiness, SemanticTone } from '../view-models/types';
import { readinessLabel, readinessTone } from './tokens';

export type PillSize = 'sm' | 'md' | 'lg';

const SIZES: Record<PillSize, { font: string; padding: string; radius: string }> = {
  sm: { font: "700 8px 'IBM Plex Mono',monospace", padding: '2px 6px', radius: '5px' },
  md: { font: "700 10px 'IBM Plex Mono',monospace", padding: '3px 8px', radius: '6px' },
  lg: { font: "700 11px 'IBM Plex Mono',monospace", padding: '4px 10px', radius: '6px' },
};

export function pillStyle(tone: SemanticTone, size: PillSize = 'md'): CSSProperties {
  const t = SEM[tone];
  const s = SIZES[size];
  return {
    display: 'inline-block',
    font: s.font,
    letterSpacing: size === 'sm' ? '.04em' : '.05em',
    color: t.fg,
    background: t.bg,
    border: `1px solid ${t.br}`,
    borderRadius: s.radius,
    padding: s.padding,
    whiteSpace: 'nowrap',
  };
}

export function StatusPill({
  tone,
  label,
  size = 'md',
  style,
}: {
  tone: SemanticTone;
  label: string;
  size?: PillSize;
  style?: CSSProperties;
}) {
  return <span style={{ ...pillStyle(tone, size), ...style }}>{label}</span>;
}

/** Readiness always renders its textual label — never color alone. */
export function ReadinessPill({
  readiness,
  size = 'md',
}: {
  readiness: ProductionReadiness;
  size?: PillSize;
}) {
  return (
    <StatusPill tone={readinessTone[readiness]} label={readinessLabel[readiness]} size={size} />
  );
}
