import { useMemo, useState } from 'react';
import type { Command, FixtureId } from '../view-models/types';
import { fixtureState, reduce, selectView, type VouchState } from '../view-models/fixture-adapter';
import { VouchScreens } from '../app/VouchApp';
import '../app/global.css';

/**
 * DEV ONLY. Reachable at /dev/vouch-states in a development build and imported
 * dynamically behind `import.meta.env.DEV`, so no fixture control reaches the
 * production bundle. Everything here is harness chrome, never product chrome.
 */

const FIXTURES: { id: FixtureId; group: string; label: string }[] = [
  { id: 'incoming-normal', group: 'INCOMING', label: 'Normal' },
  { id: 'incoming-incident', group: 'INCOMING', label: 'Incident (24)' },
  { id: 'today-normal', group: 'TODAY', label: 'Normal' },
  { id: 'today-disrupted', group: 'TODAY', label: 'Disrupted' },
  { id: 'quality-decision', group: 'DRAWER', label: 'Open decision' },
  { id: 'resolved', group: 'DRAWER', label: 'Resolved' },
  { id: 'decision-record', group: 'OTHER', label: 'Decision record' },
  { id: 'suppliers', group: 'OTHER', label: 'Suppliers' },
  { id: 'records', group: 'OTHER', label: 'Records' },
];

const btn = (on: boolean) => ({
  font: "600 11px 'Public Sans'",
  color: on ? '#211F1B' : '#B3AC9E',
  background: on ? '#EFEBE2' : 'rgba(255,255,255,.06)',
  border: 'none',
  borderRadius: 6,
  padding: '4px 11px',
  cursor: 'pointer',
});

export function VouchStateHarness() {
  const [fixture, setFixture] = useState<FixtureId>('incoming-normal');
  const [state, setState] = useState<VouchState>(() => fixtureState('incoming-normal'));
  const [fold, setFold] = useState(false);

  const vm = useMemo(() => selectView(state), [state]);
  const dispatch = (cmd: Command) => setState((s) => reduce(s, cmd));

  const load = (id: FixtureId) => {
    setFixture(id);
    setState(fixtureState(id));
  };

  const groups = [...new Set(FIXTURES.map((f) => f.group))];

  return (
    <div style={{ position: 'relative' }}>
      <VouchScreens vm={vm} dispatch={dispatch} />

      {fold && (
        <div
          style={{
            position: 'absolute',
            left: 'calc(50% - 720px)',
            width: 1440,
            top: 920,
            height: 0,
            pointerEvents: 'none',
            borderTop: '2px dashed rgba(142,43,36,.55)',
            zIndex: 40,
          }}
        >
          <span
            style={{
              position: 'absolute',
              right: 10,
              top: -19,
              font: "600 10px 'IBM Plex Mono'",
              letterSpacing: '.08em',
              color: '#8E2B24',
              background: '#F6EEEC',
              border: '1px solid rgba(142,43,36,.4)',
              borderRadius: 5,
              padding: '2px 8px',
            }}
          >
            1440 × 900 FOLD
          </span>
        </div>
      )}

      <div
        data-testid="vouch-state-harness"
        style={{
          position: 'fixed',
          left: '50%',
          transform: 'translateX(-50%)',
          bottom: 12,
          width: 1440,
          maxWidth: 'calc(100vw - 24px)',
          display: 'flex',
          alignItems: 'center',
          gap: 14,
          background: '#211F1B',
          borderRadius: 10,
          padding: '9px 16px',
          color: '#C7C0B2',
          font: "600 11px 'Public Sans'",
          zIndex: 100,
          flexWrap: 'wrap',
        }}
      >
        <span
          style={{ font: "600 10px 'IBM Plex Mono'", letterSpacing: '.12em', color: '#7C766A' }}
        >
          PROTOTYPE STATES
        </span>
        {groups.map((g) => (
          <div key={g} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
            <span style={{ color: '#8F887A', fontSize: 10 }}>{g}</span>
            {FIXTURES.filter((f) => f.group === g).map((f) => (
              <button key={f.id} onClick={() => load(f.id)} style={btn(fixture === f.id)}>
                {f.label}
              </button>
            ))}
          </div>
        ))}
        <button onClick={() => setFold((v) => !v)} style={btn(fold)}>
          Fold @900
        </button>
      </div>
    </div>
  );
}
