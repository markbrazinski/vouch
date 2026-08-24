import type { Command, ProductionLine as LineVM, VouchViewModel } from '../../view-models/types';
import { ProductionOrderCell } from './ProductionOrderCell';
import { RecoveryEvaluation } from './RecoveryEvaluation';
import { LineSequence, ResequencePanel } from './ResequencePanel';

type Disruption = NonNullable<NonNullable<VouchViewModel['today']>['disruption']>;

function DisruptionBody({ d, dispatch }: { d: Disruption; dispatch: (cmd: Command) => void }) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        padding: '14px 16px 18px',
        animation: 'vFade .3s ease-out both',
      }}
    >
      <div
        style={{
          background: '#F6EEE6',
          border: '1px solid rgba(154,90,42,.36)',
          borderRadius: 10,
          padding: '11px 15px',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexWrap: 'wrap',
        }}
      >
        <span style={{ font: "600 13px 'IBM Plex Mono'", color: '#211F1B' }}>
          {d.lotId} · {d.material}
        </span>
        <span
          style={{
            font: "700 10px 'IBM Plex Mono'",
            color: '#3E6B54',
            background: '#E6EEE8',
            borderRadius: 5,
            padding: '3px 8px',
          }}
        >
          {d.coaClaim}
        </span>
        <span aria-hidden="true" style={{ font: "600 14px 'IBM Plex Mono'", color: '#A39C8D' }}>
          →
        </span>
        <span
          style={{
            font: "700 10px 'IBM Plex Mono'",
            letterSpacing: '.05em',
            color: '#9A5A2A',
            background: 'transparent',
            border: '1px solid #9A5A2A',
            borderRadius: 5,
            padding: '3px 8px',
          }}
        >
          {d.disposition}
        </span>
        <span style={{ font: "400 12px 'Public Sans'", color: '#5C4326' }}>{d.consequence}</span>
        <button
          onClick={() => dispatch({ type: 'NAVIGATE', screen: 'record' })}
          style={{
            marginLeft: 'auto',
            padding: '6px 12px',
            background: 'transparent',
            border: '1px solid rgba(0,0,0,.16)',
            borderRadius: 7,
            font: "600 11.5px 'Public Sans'",
            color: '#4A463E',
            cursor: 'pointer',
          }}
        >
          Decision record →
        </button>
      </div>

      <LineSequence cells={d.sequence} />
      <RecoveryEvaluation verdicts={d.recovery} />
      <ResequencePanel resequence={d.resequence} />
    </div>
  );
}

export function ProductionLine({
  line,
  disruption,
  dispatch,
}: {
  line: LineVM;
  disruption?: Disruption;
  dispatch: (cmd: Command) => void;
}) {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'stretch',
        borderBottom: '1px solid rgba(0,0,0,.07)',
        transition: 'opacity .2s ease',
        background: line.expanded ? '#FCF7F2' : 'transparent',
        // Surrounding lines get quieter — they never disappear.
        opacity: line.deEmphasized ? 0.5 : 1,
      }}
    >
      <div
        style={{
          width: 150,
          flex: 'none',
          padding: '14px 16px',
          borderRight: '1px solid rgba(0,0,0,.07)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}
      >
        <div style={{ font: "700 13px 'Public Sans'", color: '#211F1B' }}>{line.name}</div>
        <div
          style={{
            font: "400 10px 'IBM Plex Mono'",
            color: line.expanded ? '#9A5A2A' : '#8A8478',
            marginTop: 3,
          }}
        >
          {line.note}
        </div>
      </div>

      {line.expanded && disruption ? (
        <DisruptionBody d={disruption} dispatch={dispatch} />
      ) : (
        <div
          style={{
            flex: 1,
            minWidth: 0,
            padding: '10px 12px',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            overflowX: 'auto',
          }}
        >
          {line.orders.map((o) => (
            <ProductionOrderCell key={o.id} order={o} />
          ))}
        </div>
      )}
    </div>
  );
}
