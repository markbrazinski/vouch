import type { SupplierRow, VouchViewModel } from '../../view-models/types';
import { StatusPill } from '../../components/StatusPill';
import { SearchField } from '../../components/SearchField';
import type { SemanticTone } from '../../view-models/types';

const GRID = '1.5fr 1.7fr 150px 1.7fr 60px 110px';

const QUAL_TONE: Record<SupplierRow['qualification'], SemanticTone> = {
  QUALIFIED: 'released',
  WATCH: 'atrisk',
  'REQUAL PENDING': 'quarantine',
};

export function SupplierTable({ rows }: { rows: SupplierRow[] }) {
  return (
    <div
      style={{
        marginTop: 18,
        background: '#F6F3EC',
        border: '1px solid rgba(0,0,0,.1)',
        borderRadius: 13,
        overflowX: 'auto',
      }}
    >
      <div style={{ minWidth: 860 }}>
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: GRID,
            gap: 14,
            padding: '12px 20px',
            borderBottom: '1px solid rgba(0,0,0,.1)',
            font: "600 10px 'IBM Plex Mono'",
            letterSpacing: '.09em',
            color: '#8A8478',
          }}
        >
          <div>SUPPLIER</div>
          <div>MATERIALS</div>
          <div>QUALIFICATION</div>
          <div>RECENT FLAG</div>
          <div style={{ textAlign: 'right' }}>LOTS</div>
          <div style={{ textAlign: 'right' }}>LAST QUAL</div>
        </div>
        {rows.map((s) => (
          <div
            key={s.name}
            className="tr"
            style={{
              display: 'grid',
              gridTemplateColumns: GRID,
              gap: 14,
              padding: '15px 20px',
              borderBottom: '1px solid rgba(0,0,0,.06)',
              alignItems: 'center',
              cursor: 'pointer',
            }}
          >
            <div style={{ font: "700 14px 'Public Sans'", color: '#211F1B' }}>{s.name}</div>
            <div style={{ font: "400 12px 'IBM Plex Mono'", color: '#6B655B' }}>{s.materials}</div>
            <div>
              <StatusPill tone={QUAL_TONE[s.qualification]} label={s.qualification} />
            </div>
            <div>
              {s.flag ? (
                <span style={{ font: "400 11.5px/1.4 'Public Sans'", color: '#9A5A2A' }}>
                  {s.flag}
                </span>
              ) : (
                <span style={{ font: "400 11.5px 'IBM Plex Mono'", color: '#A39C8D' }}>—</span>
              )}
            </div>
            <div style={{ textAlign: 'right', font: "600 13px 'IBM Plex Mono'", color: '#57534A' }}>
              {s.lots}
            </div>
            <div
              style={{ textAlign: 'right', font: "500 11.5px 'IBM Plex Mono'", color: '#8A8478' }}
            >
              {s.lastQualification}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function SuppliersPage({ vm }: { vm: NonNullable<VouchViewModel['suppliers']> }) {
  return (
    <div style={{ padding: '24px 30px 60px', maxWidth: 1120, margin: '0 auto' }}>
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-end',
          justifyContent: 'space-between',
          gap: 16,
          flexWrap: 'wrap',
        }}
      >
        <div>
          <div
            style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: '#8A8478' }}
          >
            APPROVED SOURCES
          </div>
          <h2
            style={{
              margin: '5px 0 0',
              font: "800 24px 'Public Sans'",
              letterSpacing: '-.02em',
              color: '#211F1B',
            }}
          >
            Supplier standing
          </h2>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <SearchField
            placeholder="Filter suppliers, materials"
            style={{ minWidth: 200, background: '#F6F3EC', borderColor: 'rgba(0,0,0,.12)' }}
          />
          <div
            style={{ font: "400 11.5px 'IBM Plex Mono'", color: '#8A8478', whiteSpace: 'nowrap' }}
          >
            {vm.shown}
          </div>
        </div>
      </div>
      <SupplierTable rows={vm.rows} />
    </div>
  );
}
