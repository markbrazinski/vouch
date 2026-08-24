import type { Command, RecordRow, VouchViewModel } from '../../view-models/types';
import { SEM } from '../../components/tokens';
import { SearchField } from '../../components/SearchField';

const GRID = '90px 1.3fr 1.4fr 160px 90px 1.2fr 90px';

const STATE_COLOR: Record<RecordRow['stateTone'], string> = {
  decision: '#45508C',
  released: '#3E6B54',
  atrisk: '#8a6318',
  quarantine: '#9A5A2A',
  blocked: '#8E2B24',
  refused: '#4A2018',
  progress: '#6E685C',
  muted: '#8A8478',
};

function Filters({ filters }: { filters: { label: string; active: boolean }[] }) {
  return (
    <div style={{ marginTop: 11, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
      {filters.map((f) => (
        <button
          key={f.label}
          aria-pressed={f.active}
          style={
            f.active
              ? {
                  font: "600 11.5px 'Public Sans'",
                  color: '#F6F3EC',
                  background: '#211F1B',
                  border: 'none',
                  borderRadius: 20,
                  padding: '6px 14px',
                  cursor: 'pointer',
                }
              : {
                  font: "600 11.5px 'Public Sans'",
                  color: '#6B655B',
                  background: '#F6F3EC',
                  border: '1px solid rgba(0,0,0,.14)',
                  borderRadius: 20,
                  padding: '6px 14px',
                  cursor: 'pointer',
                }
          }
        >
          {f.label}
        </button>
      ))}
    </div>
  );
}

export function RecordsPage({
  vm,
  dispatch,
}: {
  vm: NonNullable<VouchViewModel['records']>;
  dispatch: (cmd: Command) => void;
}) {
  return (
    <div style={{ padding: '24px 30px 60px', maxWidth: 1180, margin: '0 auto' }}>
      <div style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: '#8A8478' }}>
        DECISION LEDGER
      </div>
      <h2
        style={{
          margin: '5px 0 0',
          font: "800 24px 'Public Sans'",
          letterSpacing: '-.02em',
          color: '#211F1B',
        }}
      >
        All lots and dispositions
      </h2>

      <div style={{ marginTop: 16, display: 'flex', alignItems: 'center', gap: 12 }}>
        <SearchField
          placeholder="Search by lot, material, supplier, order or spec"
          fontSize={13}
          style={{ flex: 1, background: '#F6F3EC', borderColor: 'rgba(0,0,0,.14)' }}
        />
        <div style={{ font: "400 12px 'IBM Plex Mono'", color: '#8A8478', whiteSpace: 'nowrap' }}>
          {vm.total} records
        </div>
      </div>

      <Filters filters={vm.filters} />

      <div
        style={{
          marginTop: 16,
          background: '#F6F3EC',
          border: '1px solid rgba(0,0,0,.1)',
          borderRadius: 13,
          overflowX: 'auto',
        }}
      >
        <div style={{ minWidth: 900 }}>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: GRID,
              gap: 12,
              padding: '11px 20px',
              borderBottom: '1px solid rgba(0,0,0,.1)',
              font: "600 10px 'IBM Plex Mono'",
              letterSpacing: '.08em',
              color: '#8A8478',
            }}
          >
            <div>LOT</div>
            <div>MATERIAL</div>
            <div>SUPPLIER</div>
            <div>DISPOSITION</div>
            <div>ORDER</div>
            <div>STATE</div>
            <div style={{ textAlign: 'right' }}>DATE</div>
          </div>

          {vm.rows.map((r) => (
            <div
              key={r.lotId}
              className="tr"
              role="button"
              tabIndex={0}
              onClick={() => dispatch({ type: 'OPEN_LOT', lotId: r.lotId })}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  dispatch({ type: 'OPEN_LOT', lotId: r.lotId });
                }
              }}
              style={{
                display: 'grid',
                gridTemplateColumns: GRID,
                gap: 12,
                padding: '12px 20px',
                borderBottom: '1px solid rgba(0,0,0,.06)',
                alignItems: 'center',
                cursor: 'pointer',
              }}
            >
              <div style={{ font: "700 12.5px 'IBM Plex Mono'", color: '#211F1B' }}>{r.lotId}</div>
              <div style={{ font: "400 12px 'IBM Plex Mono'", color: '#57534A' }}>{r.material}</div>
              <div style={{ font: "400 12px 'Public Sans'", color: '#6B655B' }}>{r.supplier}</div>
              <div>
                <span
                  style={{
                    display: 'inline-block',
                    font: "700 10px 'IBM Plex Mono'",
                    letterSpacing: '.04em',
                    color: SEM[r.tone].fg,
                    background: SEM[r.tone].bg,
                    border: `1px solid ${SEM[r.tone].br}`,
                    borderRadius: 6,
                    padding: '3px 8px',
                  }}
                >
                  {r.disposition}
                </span>
              </div>
              <div style={{ font: "600 12px 'IBM Plex Mono'", color: '#4A463E' }}>{r.order}</div>
              <div style={{ font: "400 11.5px 'Public Sans'", color: STATE_COLOR[r.stateTone] }}>
                {r.state}
              </div>
              <div
                style={{ textAlign: 'right', font: "400 11px 'IBM Plex Mono'", color: '#9A9384' }}
              >
                {r.date}
              </div>
            </div>
          ))}

          <div
            style={{
              padding: '11px 20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              font: "400 11.5px 'IBM Plex Mono'",
              color: '#8A8478',
            }}
          >
            <span>
              1–{vm.rows.length} of {vm.total}
            </span>
            <span style={{ display: 'flex', gap: 6 }}>
              {['‹', '1', '2', '3', '›'].map((p, i) => (
                <span
                  key={p}
                  style={{
                    padding: '4px 10px',
                    border: '1px solid rgba(0,0,0,.14)',
                    borderRadius: 6,
                    background: p === '1' ? '#EFEBE2' : undefined,
                    color: i === 0 ? '#B7B0A2' : p === '1' || p === '›' ? '#4A463E' : '#6B655B',
                  }}
                >
                  {p}
                </span>
              ))}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
