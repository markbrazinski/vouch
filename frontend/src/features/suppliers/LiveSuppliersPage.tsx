/**
 * Suppliers — who shipped what, and what Vouch concluded.
 *
 * Intentionally shallow. It shows no qualification standing, no score and no
 * trend, because the backend exposes none of those to a browser and a surface
 * that invented them would be asserting supplier facts nothing established.
 */

import type { SupplierVM, SuppliersVM } from './model';
import { T } from '../../components/tokens';
import { StatusPill } from '../../components/StatusPill';
import { SurfaceState } from '../../components/SurfaceState';

function SupplierCard({
  supplier,
  onOpen,
}: {
  supplier: SupplierVM;
  onOpen?: (decisionRecordId: string) => void;
}) {
  return (
    <section
      data-supplier={supplier.supplierName}
      style={{
        background: T.panel,
        border: `1px solid ${T.hairline}`,
        borderRadius: 12,
        padding: '15px 18px',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h3 style={{ margin: 0, font: "700 15px 'Public Sans'", color: T.ink }}>
          {supplier.supplierName}
        </h3>
        {supplier.sites.length > 0 && (
          <span style={{ font: "400 10.5px 'IBM Plex Mono'", color: T.faint }}>
            {supplier.sites.length === 1 ? 'site' : 'sites'} {supplier.sites.join(', ')}
          </span>
        )}
        {supplier.attentionCount > 0 && (
          <span style={{ marginLeft: 'auto' }}>
            <StatusPill
              tone="decision"
              label={`${supplier.attentionCount} NEEDS QUALITY`}
              size="sm"
            />
          </span>
        )}
      </div>

      {supplier.materials.length > 0 && (
        <div style={{ font: "400 11.5px 'Public Sans'", color: T.muted, marginTop: 6 }}>
          Supplies:{' '}
          {supplier.materials.map((m) => m.materialName || m.materialId).join(' · ')}
        </div>
      )}

      <div style={{ marginTop: 11, display: 'flex', flexDirection: 'column', gap: 6 }}>
        {supplier.decisions.map((d) => (
          <div
            key={d.decisionRecordId}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 10,
              padding: '7px 10px',
              background: '#FCFBF7',
              border: `1px solid ${T.hairline}`,
              borderRadius: 8,
              flexWrap: 'wrap',
            }}
          >
            <span style={{ font: "700 11.5px 'IBM Plex Mono'", color: T.ink }}>{d.lotId}</span>
            <span style={{ font: "400 11.5px 'Public Sans'", color: T.muted }}>
              {d.materialName}
            </span>
            <StatusPill tone={d.tone} label={d.stateLabel} size="sm" />
            {onOpen && (
              <button
                onClick={() => onOpen(d.decisionRecordId)}
                style={{
                  marginLeft: 'auto',
                  padding: '4px 10px',
                  background: 'transparent',
                  border: '1px solid rgba(0,0,0,.18)',
                  borderRadius: 6,
                  font: "600 10.5px 'Public Sans'",
                  color: T.ink70,
                  cursor: 'pointer',
                }}
              >
                Record →
              </button>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

export function LiveSuppliersPage({
  vm,
  onOpen,
}: {
  vm: SuppliersVM;
  onOpen?: (decisionRecordId: string) => void;
}) {
  return (
    <div
      data-testid="suppliers-page"
      style={{ padding: '20px 30px 60px', maxWidth: 1120, margin: '0 auto' }}
    >
      <div style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}>
        SUPPLIERS
      </div>
      <h2
        style={{
          margin: '5px 0 0',
          font: "800 24px 'Public Sans'",
          letterSpacing: '-.02em',
          color: T.ink,
        }}
      >
        Sources in this plant’s decisions
      </h2>
      <div style={{ font: "400 12px 'Public Sans'", color: T.muted, marginTop: 6 }}>
        {vm.sourceDescription}
      </div>

      {vm.suppliers.length === 0 ? (
        <SurfaceState
          kind="empty"
          headline="No supplier context yet."
          detail="Suppliers appear here once their material has been through a decision."
        />
      ) : (
        <div style={{ marginTop: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {vm.suppliers.map((s) => (
            <SupplierCard key={s.supplierId} supplier={s} onOpen={onOpen} />
          ))}
        </div>
      )}

      {/* Says what this surface deliberately does NOT know. */}
      <div
        style={{
          marginTop: 16,
          font: "400 11px/1.6 'Public Sans'",
          color: T.faint,
          maxWidth: 660,
        }}
      >
        Qualification standing is evaluated inside each decision against the authoritative
        corpus. It is not summarised here, because a supplier-level standing is not something
        this surface can establish on its own.
      </div>
    </div>
  );
}
