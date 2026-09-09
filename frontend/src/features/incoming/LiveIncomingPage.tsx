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

/**
 * Incoming's column track.
 *
 * Sized for the 1600x900 the demo is filmed at, where the previous 1220px cap
 * left ~380px of empty gutter and squeezed supplier and material names into
 * two-line wraps. Material and supplier take the extra room because they are
 * the columns that actually carry long real-world values.
 */
const GRID = '150px 1.4fr 1.5fr 130px 190px 116px';

function HeaderRow() {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: GRID,
        gap: 14,
        padding: '13px 20px',
        borderBottom: `1px solid ${T.hairline}`,
        font: "600 11px 'IBM Plex Mono'",
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
  onEvaluate,
}: {
  row: IncomingRowVM;
  onOpen?: (decisionRecordId: string) => void;
  /**
   * Start a FRESH decision for this lot. Present only on Incoming, where a row
   * is a current arrival; Records passes no handler, so its rows keep opening
   * the historical DecisionRecord they actually are.
   */
  onEvaluate?: (lotId: string) => void;
}) {
  const evaluates = !!onEvaluate;
  return (
    <div
      data-lot={row.lotId}
      data-row-state={row.rowState}
      style={{
        display: 'grid',
        gridTemplateColumns: GRID,
        gap: 16,
        padding: '18px 20px',
        borderBottom: `1px solid rgba(0,0,0,.06)`,
        alignItems: 'center',
        background: row.attentionRequired ? '#FCF7F2' : 'transparent',
      }}
    >
      <div style={{ font: "700 14.5px 'IBM Plex Mono'", color: T.ink }}>{row.lotId}</div>
      <div>
        <div style={{ font: "500 14.5px 'Public Sans'", color: T.ink70 }}>{row.materialName}</div>
        <div style={{ font: "400 11.5px 'IBM Plex Mono'", color: T.faint }}>{row.materialId}</div>
      </div>
      <div>
        <div style={{ font: "500 14.5px 'Public Sans'", color: T.ink70 }}>{row.supplierName}</div>
        {row.supplierSite && (
          <div style={{ font: "400 11.5px 'IBM Plex Mono'", color: T.faint }}>
            site {row.supplierSite}
          </div>
        )}
      </div>
      <div style={{ textAlign: 'right', font: "400 13.5px 'IBM Plex Mono'", color: T.muted }}>
        {row.quantity}
      </div>
      <div>
        <StatusPill tone={row.tone} label={row.stateLabel} />
      </div>
      <div style={{ textAlign: 'right' }}>
        {/* On Incoming this starts a decision, because the row is a lot that
            has arrived. On Records it opens the record, because the row IS a
            record. One row component, two surfaces, no third meaning. */}
        {evaluates ? (
          <button
            data-testid="incoming-row"
            data-evaluate-lot={row.lotId}
            onClick={() => onEvaluate!(row.lotId)}
            style={{
              padding: '7px 13px',
              background: 'transparent',
              border: '1px solid rgba(0,0,0,.18)',
              borderRadius: 7,
              font: "600 12.5px 'Public Sans'",
              color: T.ink70,
              cursor: 'pointer',
            }}
          >
            Open →
          </button>
        ) : (
          onOpen && (
            <button
              onClick={() => onOpen(row.decisionRecordId)}
              style={{
                padding: '7px 13px',
                background: 'transparent',
                border: '1px solid rgba(0,0,0,.18)',
                borderRadius: 7,
                font: "600 12.5px 'Public Sans'",
                color: T.ink70,
                cursor: 'pointer',
              }}
            >
              Open →
            </button>
          )
        )}
      </div>
    </div>
  );
}

/**
 * Records — a row whose identity is the DECISION, not the lot.
 *
 * Incoming's row leads with the lot because the operator is asking "what
 * arrived". Records is an audit trail, so it leads with what makes a row unique
 * in that trail: the DecisionRecord id, when it was decided, and what it
 * concluded. Repeated lot ids are then legible rather than confusing — the same
 * lot evaluated three times is three records, and the id and timestamp say so.
 *
 * `failure_category` is shown because it is the most informative field the
 * ledger already carries and the table never surfaced: POLICY_REFUSAL,
 * MATERIAL_DISAGREEMENT and SECURITY_QUARANTINE are different kinds of "no".
 */
const LEDGER_GRID = '168px 150px 1.1fr 1.25fr 172px 108px';

function LedgerHeaderRow() {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: LEDGER_GRID,
        gap: 14,
        padding: '13px 20px',
        borderBottom: `1px solid ${T.hairline}`,
        font: "600 11px 'IBM Plex Mono'",
        letterSpacing: '.09em',
        color: T.faint,
      }}
    >
      <div>DECISION</div>
      <div>DECIDED</div>
      <div>OUTCOME</div>
      <div>LOT · SUPPLIER</div>
      <div>STATE</div>
      <div />
    </div>
  );
}

/** ISO-8601 from the server, rendered without inventing a timezone claim. */
function decidedAtLabel(iso: string): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso || '—';
  return at.toISOString().replace('T', ' ').slice(0, 16) + 'Z';
}

function LedgerRow({
  row,
  onOpen,
}: {
  row: IncomingRowVM;
  onOpen?: (decisionRecordId: string) => void;
}) {
  return (
    <div
      data-lot={row.lotId}
      data-decision-record={row.decisionRecordId}
      style={{
        display: 'grid',
        gridTemplateColumns: LEDGER_GRID,
        gap: 16,
        padding: '18px 20px',
        borderBottom: `1px solid rgba(0,0,0,.06)`,
        alignItems: 'center',
      }}
    >
      <div style={{ font: "700 14px 'IBM Plex Mono'", color: T.ink }}>{row.decisionRecordId}</div>
      <div style={{ font: "400 12.5px 'IBM Plex Mono'", color: T.muted }}>
        {decidedAtLabel(row.decidedAt)}
      </div>
      <div>
        <div style={{ font: "600 14px 'Public Sans'", color: T.ink70 }}>
          {row.disposition || '—'}
        </div>
        {row.failureCategory && (
          <div style={{ font: "400 11px 'IBM Plex Mono'", color: '#9A5A2A' }}>
            {row.failureCategory}
          </div>
        )}
      </div>
      <div>
        <div style={{ font: "500 14px 'IBM Plex Mono'", color: T.ink70 }}>{row.lotId}</div>
        <div style={{ font: "400 11.5px 'Public Sans'", color: T.faint }}>
          {row.supplierName} · {row.materialId}
        </div>
      </div>
      <div>
        <StatusPill tone={row.tone} label={row.stateLabel} />
      </div>
      <div style={{ textAlign: 'right' }}>
        {onOpen && (
          <button
            onClick={() => onOpen(row.decisionRecordId)}
            style={{
              padding: '7px 13px',
              background: 'transparent',
              border: '1px solid rgba(0,0,0,.18)',
              borderRadius: 7,
              font: "600 12.5px 'Public Sans'",
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

/** Records: the durable ledger, newest first, one row per DecisionRecord. */
export function LedgerPage({
  vm,
  onOpen,
}: {
  vm: IncomingVM;
  onOpen?: (decisionRecordId: string) => void;
}) {
  const rows = [...vm.rows].sort((a, b) => b.decidedAt.localeCompare(a.decidedAt));
  return (
    <div data-testid="records-page" style={{ padding: '20px 34px 60px', maxWidth: 1560, margin: '0 auto' }}>
      <div style={{ font: "400 12.5px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}>
        RECORDS
      </div>
      <h2
        style={{
          margin: '5px 0 0',
          font: "800 29px 'Public Sans'",
          letterSpacing: '-.02em',
          color: T.ink,
        }}
      >
        Decision audit trail
      </h2>
      <div style={{ font: "400 14px 'Public Sans'", color: T.muted, marginTop: 7 }}>
        {rows.length} {rows.length === 1 ? 'decision record' : 'decision records'} · newest first
      </div>

      <div
        style={{
          marginTop: 18,
          background: T.panel,
          border: `1px solid ${T.hairline}`,
          borderRadius: 13,
          overflow: 'hidden',
        }}
      >
        <LedgerHeaderRow />
        {rows.map((row) => (
          <LedgerRow key={row.decisionRecordId} row={row} onOpen={onOpen} />
        ))}
      </div>
    </div>
  );
}

export function LiveIncomingPage({
  vm,
  onOpen,
  onEvaluate,
  heading = 'Arrivals and their dispositions',
  eyebrow = 'INCOMING',
  unit = 'decision',
}: {
  vm: IncomingVM;
  onOpen?: (decisionRecordId: string) => void;
  /** Incoming only. Its presence is what makes a row an arrival. */
  onEvaluate?: (lotId: string) => void;
  heading?: string;
  eyebrow?: string;
  /** "lot" on Incoming, "decision" on Records — the row means a different thing. */
  unit?: string;
}) {
  const attention = vm.needsAttention.length;
  return (
    <div data-testid="incoming-page" style={{ padding: '20px 34px 60px', maxWidth: 1560, margin: '0 auto' }}>
      <div style={{ font: "400 12.5px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}>
        {eyebrow}
      </div>
      <h2
        style={{
          margin: '5px 0 0',
          font: "800 29px 'Public Sans'",
          letterSpacing: '-.02em',
          color: T.ink,
        }}
      >
        {heading}
      </h2>
      <div style={{ font: "400 14px 'Public Sans'", color: T.muted, marginTop: 7 }}>
        {/* Counters with authoritative meaning only: what was returned, and how
            many the SERVER flagged for a person. No "in progress" — invocation
            is synchronous, so nothing is ever persisted mid-flight. */}
        {vm.returned} {vm.returned === 1 ? unit : `${unit}s`}
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
            <Row
              key={row.decisionRecordId}
              row={row}
              onOpen={onOpen}
              onEvaluate={onEvaluate}
            />
          ))}
        </div>
      )}

      {vm.hasMore && (
        <div style={{ font: "400 12.5px 'IBM Plex Mono'", color: T.faint, marginTop: 12 }}>
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
    <div data-testid="incoming-blocked" style={{ padding: '20px 34px', maxWidth: 1560, margin: '0 auto' }}>
      <div style={{ font: "400 12.5px 'IBM Plex Mono'", letterSpacing: '.12em', color: T.faint }}>
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
