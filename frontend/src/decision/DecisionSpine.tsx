/**
 * The four-node causal band: Evidence → Investigation‖Verification →
 * Disposition → Consequence.
 *
 * The middle node is deliberately split into two lanes with a seal between
 * them. That is the one piece of chrome carrying the architecture's most
 * contested claim — that verification is a genuinely independent second read —
 * so the two lanes are populated from their OWN brief events and never from
 * each other.
 */

import { findingLabel, findingTone, SEM } from '../components/tokens';
import { Pill, Eyebrow, INK, MONO, SANS, N, HAIR } from './primitives';
import type { SpineNodeVM } from './model';
import type { SemanticTone } from '../view-models/types';

const nodeSurface = (active: boolean) => ({
  border: `1px solid ${active ? 'rgba(0,0,0,.2)' : 'rgba(0,0,0,.12)'}`,
  background: active ? N.nested : N.card,
  borderRadius: 10,
  padding: '11px 12px',
  minHeight: 68,
  display: 'flex',
  flexDirection: 'column' as const,
  justifyContent: 'center',
});

const SEAL_STYLE: Record<
  NonNullable<SpineNodeVM['reconciliationSeal']>,
  { text: string; fg: string; bg: string; br: string }
> = {
  match: { text: '✓ INDEPENDENT MATCH', fg: '#fff', bg: '#3E6B54', br: '#3E6B54' },
  disagreement: { text: '✕ MATERIAL DISAGREEMENT', fg: '#fff', bg: '#45508C', br: '#45508C' },
  halted: { text: '— HALTED', fg: INK.label, bg: N.fill, br: 'rgba(0,0,0,.12)' },
  pending: { text: 'PENDING', fg: INK.label, bg: N.fill, br: 'rgba(0,0,0,.12)' },
};

function nodePill(node: SpineNodeVM): { label: string; tone: SemanticTone } {
  switch (node.state) {
    case 'halted':
      return { label: '⊘ HALTED', tone: 'quarantine' };
    case 'material_disagreement':
      return { label: node.headline.toUpperCase(), tone: 'decision' };
    case 'terminal':
      return {
        label: node.headline.toUpperCase(),
        tone:
          node.headline === 'RELEASE'
            ? 'released'
            : node.headline === 'QUARANTINE'
              ? 'quarantine'
              : 'decision',
      };
    case 'completed':
      return { label: node.headline.toUpperCase(), tone: 'released' };
    case 'active':
      return { label: node.headline.toUpperCase(), tone: 'progress' };
    default:
      return { label: 'PENDING', tone: 'progress' };
  }
}

function Lane({ label, value }: { label: string; value: string | null | undefined }) {
  const empty = !value;
  // The raw enum is the fallback, not the design: an unmapped value still
  // renders rather than disappearing, which is how a new backend outcome
  // announces itself instead of silently showing a blank lane.
  const text = value ? (findingLabel[value] ?? value) : '';
  const tone = value ? SEM[findingTone[value] ?? 'progress'] : null;
  return (
    <div
      style={{
        flex: 1,
        background: tone ? tone.bg : N.nested,
        border: `1px solid ${tone ? tone.br : HAIR}`,
        borderRadius: 7,
        padding: '5px 8px',
        minWidth: 0,
      }}
    >
      <div style={{ font: `600 8px ${MONO}`, color: INK.label }}>{label}</div>
      <div
        style={{
          // Wraps rather than truncates. This lane carried the single most
          // important word on the screen and cut it to `INSUFFICIENT_EV…`.
          font: `700 10px 'Public Sans'`,
          color: empty ? INK.placeholder : (tone?.fg ?? INK.dense),
          marginTop: 2,
          lineHeight: 1.35,
          overflowWrap: 'anywhere',
        }}
      >
        {/* An em-dash, not a spinner: the lane is genuinely unknown until the
            agent's own brief lands, and a placeholder that looked like data
            would be asserting something nothing has established. */}
        {text || '—'}
      </div>
    </div>
  );
}

export function DecisionSpine({ nodes }: { nodes: SpineNodeVM[] }) {
  const halted = nodes[0]?.state === 'halted';

  return (
    <div
      style={{
        marginTop: 14,
        background: N.card,
        border: `1px solid ${HAIR}`,
        borderRadius: 13,
        padding: '15px 20px',
      }}
      data-testid="decision-spine"
    >
      <div style={{ display: 'flex', alignItems: 'stretch' }}>
        {nodes.map((node, index) => {
          const isAgents = node.key === 'agents';
          const active = node.state === 'active';
          // Downstream nodes dim rather than disappear when evidence halted:
          // the causal chain is still the truth, it simply stopped.
          const dim = halted && index > 0 ? 0.4 : 1;
          const pill = nodePill(node);

          return (
            <div key={node.key} style={{ display: 'flex', flex: isAgents ? 1.7 : 1, minWidth: 0 }}>
              <div style={{ flex: 1, minWidth: 0, opacity: dim }}>
                <div
                  style={{
                    font: `600 8.5px ${MONO}`,
                    letterSpacing: '.1em',
                    marginBottom: 7,
                    color: active ? INK.primary : INK.label,
                  }}
                >
                  {isAgents ? 'INVESTIGATION  ‖  VERIFICATION' : node.label.toUpperCase()}
                </div>

                {isAgents ? (
                  <div
                    style={{
                      ...nodeSurface(active),
                      padding: '8px 10px',
                      background: active ? '#EEF2ED' : N.card,
                    }}
                  >
                    <div style={{ display: 'flex', gap: 7 }}>
                      <Lane label="INVESTIGATOR" value={node.investigatorLane} />
                      <Lane label="VERIFIER" value={node.verifierLane} />
                    </div>
                    <div style={{ marginTop: 7, display: 'flex', justifyContent: 'center' }}>
                      {(() => {
                        const seal = SEAL_STYLE[node.reconciliationSeal ?? 'pending'];
                        return (
                          <span
                            style={{
                              whiteSpace: 'nowrap',
                              font: `700 9px ${MONO}`,
                              letterSpacing: '.04em',
                              color: seal.fg,
                              background: seal.bg,
                              border: `1px solid ${seal.br}`,
                              borderRadius: 6,
                              padding: '4px 10px',
                            }}
                          >
                            {seal.text}
                          </span>
                        );
                      })()}
                    </div>
                  </div>
                ) : (
                  <div style={nodeSurface(active)}>
                    <div>
                      <Pill tone={pill.tone}>{pill.label}</Pill>
                    </div>
                    <div
                      style={{
                        font: `400 10.5px ${SANS}`,
                        color: INK.muted,
                        marginTop: 6,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                      }}
                    >
                      {node.note}
                    </div>
                  </div>
                )}
              </div>

              {index < nodes.length - 1 && (
                <div
                  aria-hidden
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 8px',
                    font: `400 16px ${MONO}`,
                    color: INK.chevron,
                  }}
                >
                  ›
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { Eyebrow };
