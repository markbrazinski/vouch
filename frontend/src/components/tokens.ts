import type { ProductionReadiness, SemanticTone } from '../view-models/types';

/** Foundation — warm neutral. */
export const T = {
  desk: '#CFC9BD',
  frame: '#F0EDE6',
  panel: '#F6F3EC',
  panel2: '#EFEBE2',
  rowHover: '#F1EDE5',
  ink: '#211F1B',
  ink70: '#3F3A32',
  muted: '#6B655B',
  faint: '#8A8478',
  hairline: 'rgba(0,0,0,.1)',
} as const;

export interface ToneSpec {
  fg: string;
  bg: string;
  br: string;
  /** Glyph prefix. Significant state never relies on color alone. */
  glyph?: string;
}

/** Semantic states. Each survives grayscale via its textual label / glyph. */
export const SEM: Record<SemanticTone, ToneSpec> = {
  progress: { fg: '#6E685C', bg: '#EAE6DD', br: 'rgba(0,0,0,.1)' },
  decision: { fg: '#45508C', bg: '#EAEBF4', br: 'rgba(69,80,140,.32)' },
  released: { fg: '#3E6B54', bg: '#E6EEE8', br: 'rgba(62,107,84,.32)' },
  blocked: { fg: '#FFFFFF', bg: '#8E2B24', br: '#8E2B24' },
  atrisk: { fg: '#8a6318', bg: '#F5EED9', br: 'rgba(181,133,42,.36)' },
  quarantine: { fg: '#9A5A2A', bg: 'transparent', br: '#9A5A2A', glyph: '⊘' },
  refused: { fg: '#4A2018', bg: '#EDE2DE', br: 'rgba(74,32,24,.42)', glyph: '✕' },
};

/** Readiness maps onto the tone set; the textual label always ships with it. */
export const readinessTone: Record<ProductionReadiness, SemanticTone> = {
  READY: 'released',
  AT_RISK: 'atrisk',
  BLOCKED: 'blocked',
};

export const readinessLabel: Record<ProductionReadiness, string> = {
  READY: 'READY',
  AT_RISK: 'AT RISK',
  BLOCKED: 'BLOCKED',
};

export const readinessDot: Record<ProductionReadiness, string> = {
  READY: '#3E6B54',
  AT_RISK: '#B5852A',
  BLOCKED: '#8E2B24',
};
