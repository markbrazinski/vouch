/**
 * Incoming — arrivals, and what Vouch has already concluded about them.
 *
 * The surface reads `list_decisions`. Every row is served whole: `row_state`,
 * the display names and `attention_required` are computed server-side, so this
 * page sorts and renders but classifies nothing.
 *
 * It is deliberately not an "Analyze" console. Rows arrive already decided or
 * already flagged, because the decision runs when evidence lands, not when a
 * person presses a button. Where a row needs a person it says which person
 * decision it needs — not that Vouch is waiting for permission.
 */

import type { IncomingRowVM, IncomingVM } from './model';
import { T } from '../../components/tokens';
import { StatusPill } from '../../components/StatusPill';
import { SurfaceState } from '../../components/SurfaceState';

const GRID = '128px 1.25fr 1.35fr 110px 150px 96px';

function HeaderRow() {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: GRID,
        gap: 14,
        padding: '11px 18px',
        borderBottom: `1px solid ${T.hairline}`,
        font: "600 9.5px 'IBM Plex Mono'",
        letterSpacing: '.09em',
        color: T.faint,
      }}
    >
      <div>LOT</div>
      <div>MATERIAL</div>
      <div>SUPPLIER</div>
      <div style={{ textAlign: 'right' }}>QUANTITY</div>
      <div>STATE</div>
      <div />
    </div>
  );
}

function Row({
  row,
  onOpen,
}: {
  row: IncomingRowVM;
  onOpen?: (decisionRecordId: string) => void;
}) {
  return (
    <div
      data-lot={row.lotId}
      data-row-state={row.rowState}
      style={{
        display: 'grid',
        gridTemplateColumns: GRID,
        gap: 14,
        padding: '13px 18px',
        borderBottom: `1px solid rgba(0,0,0,.06)`,
        alignItems: 'center',
        background: row.attentionRequired ? '#FCF7F2' : 'transparent',
      }}
    >
      <div style={{ font: "700 12.5px 'IBM Plex Mono'", color: T.ink }}>{row.lotId}</div>
      <div>
        <div style={{ font: "500 12.5px 'Public Sans'", color: T.ink70 }}>{row.materialName}</div>
        <div style={{ font: "400 10px 'IBM Plex Mono'", color: T.faint }}>{row.materialId}</div>
      </div>
      <div>
        <div style={{ font: "500 12.5px 'Public Sans'", color: T.ink70 }}>{row.supplierName}</div>
        {row.supplierSite && (
          <div style={{ font: "400 10px 'IBM Plex Mono'", color: T.faint }}>
            site {row.supplierSite}
          </div>
        )}
      </div>
      <div style={{ textAlign: 'right', font: "400 11.5px 'IBM Plex Mono'", color: T.muted }}>
        {row.quantity}
      </div>
      <div>
        <StatusPill tone={row.tone} label={row.stateLabel} size="sm" />
      </div>
      <div style={{ textAlign: 'right' }}>
        {onOpen && (
          <button
            onClick={() => onOpen(row.decisionRecordId)}
            style={{
              padding: '5px 10px',
              background: 'transparent',
              border: '1px solid rgba(0,0,0,.18)',
              borderRadius: 7,
              font: "600 11px 'Public Sans'",
              color: T.ink70,
              cursor: 'pointer',
            }}
          >
            Open →
          </button>
        )}
      </div>
    </div>
  );
}

export function LiveIncomingPage({
  vm,
  onOpen,
}: {
  vm: IncomingVM;
  onOpen?: (decisionRecordId: string) => void;
}) {
  const attention = vm.needsAttention.length;
  return (
    <div data-testid="incoming-page" style={{ padding: '20px 30px 60px', maxWidth: 1220, margin: '0 auto' }}>
      <div style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}>
        INCOMING
      </div>
      <h2
        style={{
          margin: '5px 0 0',
          font: "800 24px 'Public Sans'",
          letterSpacing: '-.02em',
          color: T.ink,
        }}
      >
        Arrivals and their dispositions
      </h2>
      <div style={{ font: "400 12px 'Public Sans'", color: T.muted, marginTop: 6 }}>
        {/* Counters with authoritative meaning only: what was returned, and how
            many the SERVER flagged for a person. No "in progress" — invocation
            is synchronous, so nothing is ever persisted mid-flight. */}
        {vm.returned} {vm.returned === 1 ? 'decision' : 'decisions'}
        {attention > 0 && (
          <>
            {' · '}
            <strong style={{ color: '#9A5A2A' }}>
              {attention} {attention === 1 ? 'needs' : 'need'} a Quality decision
            </strong>
          </>
        )}
      </div>

      {vm.rows.length === 0 ? (
        <SurfaceState
          kind="empty"
          headline="No arrivals have been decided yet."
          detail="When evidence for a lot lands, Vouch evaluates it and the result appears here."
        />
      ) : (
        <div
          style={{
            marginTop: 18,
            background: T.panel,
            border: `1px solid ${T.hairline}`,
            borderRadius: 13,
            overflow: 'hidden',
          }}
        >
          <HeaderRow />
          {/* Rows needing a person come first — the server decided which. */}
          {[...vm.needsAttention, ...vm.settled].map((row) => (
            <Row key={row.decisionRecordId} row={row} onOpen={onOpen} />
          ))}
        </div>
      )}

      {vm.hasMore && (
        <div style={{ font: "400 11px 'IBM Plex Mono'", color: T.faint, marginTop: 12 }}>
          More decisions exist beyond this page.
        </div>
      )}
    </div>
  );
}

/**
 * Incoming when the deployed read path cannot answer.
 *
 * `list_decisions` needs the `decisions-by-recency` GSI and the runtime's
 * `dynamodb:Query` grant on it. Both are pending an admin step this identity
 * cannot perform. That is a missing GRANT, not a missing fact, and it is stated
 * as such: fabricating rows here would put invented lots in front of an
 * operator, which is the one thing this surface must never do.
 */
export function IncomingUnavailable({ detail }: { detail?: string }) {
  return (
    <div data-testid="incoming-blocked" style={{ padding: '20px 30px', maxWidth: 1220, margin: '0 auto' }}>
      <div style={{ font: "400 11px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}>
        INCOMING
      </div>
      <SurfaceState
        kind="blocked"
        headline="The arrivals list cannot be read in this deployment."
        detail={
          detail ??
          'Listing decisions requires a recency index and a query grant that this ' +
            'environment has not been given. Nothing is wrong with any lot — the ' +
            'decisions exist and each one can still be opened directly.'
        }
      />
    </div>
  );
}
