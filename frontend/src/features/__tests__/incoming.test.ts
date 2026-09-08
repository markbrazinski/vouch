/**
 * Incoming and Suppliers.
 *
 * Two different kinds of verification live here, and they are labelled so the
 * gate report cannot blur them:
 *
 *   CONTRACT_VERIFIED  — the mapping obeys the frozen §4 shape.
 *   AWS_LIVE_VERIFIED  — the deployed runtime actually answered.
 *
 * `list_decisions` is currently the second kind's opposite: the deployed
 * runtime returns a PERSISTENCE_FAILURE because the runtime role lacks
 * `dynamodb:Query` on the recency index. That real failure envelope is
 * committed as a capture, so the blocked path is tested against what AWS truly
 * returns rather than against a guess about it.
 */

import { describe, expect, it } from 'vitest';
import blocked from '../../decision/__tests__/list-decisions-blocked-capture.json';
import {
  toCurrentArrivals,
  toIncoming,
  toIncomingRow,
  type IncomingRowDTO,
  type ListDecisionsDTO,
} from '../incoming/model';
import { toSuppliers } from '../suppliers/model';

/**
 * A §4-shaped row. Every field is server-provided, which is the point: the
 * browser never derives `row_state`, `attention_required` or a display name.
 */
const row = (over: Partial<IncomingRowDTO> = {}): IncomingRowDTO => ({
  decision_record_id: 'DR-aaaaaaaaaaaa',
  lot_id: 'LOT-1002',
  material_id: 'MAT-ALLOY-7',
  material_name: 'Alloy 7 billet',
  supplier_id: 'SUP-EAST',
  supplier_name: 'Eastern Metals',
  supplier_site: 'SITE-E1',
  received_at: '2026-03-02',
  quantity: 400,
  units: 'kg',
  lot_status: 'QUARANTINED',
  disposition: 'QUARANTINE',
  failure_category: '',
  row_state: 'QUARANTINED',
  attention_required: false,
  decided_at: '2026-09-03T04:32:26Z',
  ...over,
});

describe('CONTRACT_VERIFIED — §4 row mapping', () => {
  it('reads rows from `rows`, never a guessed `decisions` key', () => {
    const vm = toIncoming({ ok: true, rows: [row()] } as ListDecisionsDTO);
    expect(vm.rows).toHaveLength(1);
    expect(toIncoming({ ok: true, decisions: [row()] } as ListDecisionsDTO).rows).toHaveLength(0);
  });

  it('carries every server-provided field through', () => {
    const r = toIncomingRow(row());
    expect(r).toMatchObject({
      decisionRecordId: 'DR-aaaaaaaaaaaa',
      lotId: 'LOT-1002',
      materialId: 'MAT-ALLOY-7',
      materialName: 'Alloy 7 billet',
      supplierName: 'Eastern Metals',
      supplierSite: 'SITE-E1',
      lotStatus: 'QUARANTINED',
      disposition: 'QUARANTINE',
      rowState: 'QUARANTINED',
    });
    expect(r.quantity).toBe('400 kg');
  });

  it('uses the SERVER row_state rather than deriving one from the disposition', () => {
    // A row whose disposition and row_state disagree must render the
    // row_state: the server owns that classification on purpose.
    const r = toIncomingRow(row({ disposition: 'RELEASE', row_state: 'SECURITY_HOLD' }));
    expect(r.rowState).toBe('SECURITY_HOLD');
    expect(r.stateLabel).toBe('SECURITY HOLD');
  });

  it('partitions on the server flag, not on a browser rule', () => {
    const vm = toIncoming({
      ok: true,
      rows: [
        row({ decision_record_id: 'DR-1', attention_required: true }),
        row({ decision_record_id: 'DR-2', attention_required: false }),
      ],
    } as ListDecisionsDTO);
    expect(vm.needsAttention.map((r) => r.decisionRecordId)).toEqual(['DR-1']);
    expect(vm.settled.map((r) => r.decisionRecordId)).toEqual(['DR-2']);
  });

  it('falls back to an id rather than inventing a display name', () => {
    const r = toIncomingRow(row({ material_name: '', supplier_name: '' }));
    expect(r.materialName).toBe('MAT-ALLOY-7');
    expect(r.supplierName).toBe('SUP-EAST');
  });

  it('shows a missing quantity as unknown rather than zero', () => {
    expect(toIncomingRow(row({ quantity: null })).quantity).toBe('—');
  });

  it('reports only counters that have a meaning', () => {
    const vm = toIncoming({ ok: true, rows: [row()], counts: { returned: 1 } } as ListDecisionsDTO);
    expect(vm.returned).toBe(1);
    // The rejected fictional metrics must not come back.
    expect(vm).not.toHaveProperty('inProgress');
    expect(vm).not.toHaveProperty('completedByVouch');
  });
});

describe('the blocked live path is stated, never faked', () => {
  it('is a real AccessDenied envelope captured from the deployed runtime', () => {
    expect(blocked.ok).toBe(false);
    expect(blocked.failure_category).toBe('PERSISTENCE_FAILURE');
    expect(blocked.error).toContain('dynamodb:Query');
  });

  it('carries no disposition — a persistence failure is not a verdict', () => {
    expect(blocked).not.toHaveProperty('disposition');
    expect(blocked.mutation).toEqual({});
  });

  it('yields no rows rather than substituting invented ones', () => {
    const vm = toIncoming(blocked as unknown as ListDecisionsDTO);
    expect(vm.rows).toEqual([]);
    expect(vm.needsAttention).toEqual([]);
    expect(vm.returned).toBe(0);
  });
});

describe('Suppliers stays inside what the backend owns', () => {
  const rows = [
    row({ decision_record_id: 'DR-1', lot_id: 'LOT-1002' }),
    row({
      decision_record_id: 'DR-2',
      lot_id: 'LOT-1003',
      supplier_id: 'SUP-WEST',
      supplier_name: 'Western Resins',
      supplier_site: 'SITE-W1',
      material_id: 'MAT-RESIN-3',
      material_name: 'Resin 3',
      row_state: 'QUALITY_DECISION_REQUIRED',
      attention_required: true,
    }),
  ].map(toIncomingRow);

  it('groups the decisions in view by supplier', () => {
    const vm = toSuppliers(rows);
    expect(vm.suppliers.map((s) => s.supplierName)).toEqual([
      'Eastern Metals',
      'Western Resins',
    ]);
    expect(vm.suppliers[0].sites).toEqual(['SITE-E1']);
    expect(vm.suppliers[0].materials[0].materialName).toBe('Alloy 7 billet');
  });

  it('counts attention from the server flag', () => {
    const vm = toSuppliers(rows);
    expect(vm.suppliers.find((s) => s.supplierName === 'Western Resins')!.attentionCount).toBe(1);
    expect(vm.suppliers.find((s) => s.supplierName === 'Eastern Metals')!.attentionCount).toBe(0);
  });

  it('describes what it counted instead of implying a plant-wide total', () => {
    // The rejected "5 of 214" pattern: 214 was never counted by anything.
    expect(toSuppliers(rows).sourceDescription).toBe(
      '2 suppliers across the decisions currently loaded.',
    );
    expect(toSuppliers([]).sourceDescription).toBe(
      'No supplier appears in the decisions currently loaded.',
    );
  });

  it('invents no qualification, score or risk field', () => {
    // Qualification status is read by an agent tool but never serialized into
    // any browser-reachable response, so this surface must not show one.
    const json = JSON.stringify(toSuppliers(rows));
    for (const absent of ['qualification', 'score', 'risk', 'WATCH', 'REQUAL']) {
      expect(json).not.toContain(absent);
    }
  });
});

/**
 * Incoming's unit is the LOT; Records' unit is the DECISION.
 *
 * The qualification corpus holds ~30 LOT-1002 records, so rendering the ledger
 * as arrivals showed thirty arrivals where four exist and made "open LOT-1002"
 * ambiguous. Grouping is a projection over rows the server already returned —
 * it must collapse duplicates without inventing or losing a lot.
 */
describe('CONTRACT_VERIFIED — current arrivals collapse to one row per lot', () => {
  const at = (lot: string, id: string, decided: string, over: Partial<IncomingRowDTO> = {}) =>
    row({ lot_id: lot, decision_record_id: id, decided_at: decided, ...over });

  it('keeps exactly one row per lot, and it is the newest', () => {
    const vm = toCurrentArrivals({
      ok: true,
      rows: [
        at('LOT-1002', 'DR-old', '2026-09-01T00:00:00Z'),
        at('LOT-1002', 'DR-new', '2026-09-08T00:00:00Z', { row_state: 'QUARANTINED' }),
        at('LOT-1002', 'DR-mid', '2026-09-04T00:00:00Z'),
        at('LOT-1001', 'DR-a', '2026-09-02T00:00:00Z'),
      ],
    } as ListDecisionsDTO);

    expect(vm.rows.map((r) => r.lotId)).toEqual(['LOT-1001', 'LOT-1002']);
    expect(vm.rows.find((r) => r.lotId === 'LOT-1002')!.decisionRecordId).toBe('DR-new');
    // The count an operator acts on is lots, not ledger entries behind them.
    expect(vm.returned).toBe(2);
  });

  it('never drops a lot, however many records it has', () => {
    const rows = ['LOT-1001', 'LOT-1002', 'LOT-1003', 'LOT-1004'].flatMap((lot, i) =>
      Array.from({ length: i + 1 }, (_, n) =>
        at(lot, `DR-${lot}-${n}`, `2026-09-0${n + 1}T00:00:00Z`),
      ),
    );
    const vm = toCurrentArrivals({ ok: true, rows } as ListDecisionsDTO);
    expect(vm.rows.map((r) => r.lotId)).toEqual(['LOT-1001', 'LOT-1002', 'LOT-1003', 'LOT-1004']);
  });

  it('a row with no timestamp never displaces one that has a real one', () => {
    const vm = toCurrentArrivals({
      ok: true,
      rows: [
        at('LOT-1002', 'DR-real', '2026-09-08T00:00:00Z'),
        at('LOT-1002', 'DR-blank', ''),
      ],
    } as ListDecisionsDTO);
    expect(vm.rows[0].decisionRecordId).toBe('DR-real');
  });

  it('leaves the ungrouped ledger alone — Records still sees every record', () => {
    const rows = [
      at('LOT-1002', 'DR-1', '2026-09-01T00:00:00Z'),
      at('LOT-1002', 'DR-2', '2026-09-02T00:00:00Z'),
    ];
    expect(toIncoming({ ok: true, rows } as ListDecisionsDTO).rows).toHaveLength(2);
    expect(toCurrentArrivals({ ok: true, rows } as ListDecisionsDTO).rows).toHaveLength(1);
  });
});
