import type { DecisionRow } from '../../view-models/types';
import { IncomingDecisionRow } from './IncomingDecisionRow';

export function NeedsQualityDecisionList({
  rows,
  onOpen,
}: {
  rows: DecisionRow[];
  onOpen: (lotId: string) => void;
}) {
  return (
    <div style={{ marginTop: 13, display: 'flex', flexDirection: 'column', gap: 9 }}>
      {rows.map((r) => (
        <IncomingDecisionRow key={r.lotId} row={r} onOpen={onOpen} />
      ))}
    </div>
  );
}
