/**
 * Suppliers — supporting context, deliberately shallow.
 *
 * WHAT THE BACKEND OWNS AND THE BROWSER CAN REACH:
 *   supplier_id, supplier_site        — `list_decisions` rows and a record's
 *                                       identity segment
 *   supplier_name                     — `list_decisions` rows only (joined
 *                                       server-side from the corpus)
 *   the lots and decisions seen       — the rows themselves
 *
 * WHAT IT DOES NOT: qualification status, effective/expiry dates and site
 * scope exist in the corpus and are read by `get_supplier_qualification`
 * during reasoning, but they are never serialized into a browser-reachable
 * response — `_corpus_objects` records specs, requirements, deviations and
 * equivalences, and no supplier object. So this surface does NOT show
 * qualification standing. Rendering one would mean inventing it.
 *
 * There is no scoring, no risk model and no historical analytics here for the
 * same reason: the backend owns no such concept, so the frontend must not
 * conjure one. This view aggregates decisions that already exist and nothing
 * more.
 */

import type { IncomingRowVM } from '../incoming/model';

export interface SupplierMaterialVM {
  materialId: string;
  materialName: string;
}

export interface SupplierDecisionVM {
  decisionRecordId: string;
  lotId: string;
  materialName: string;
  stateLabel: string;
  rowState: IncomingRowVM['rowState'];
  tone: IncomingRowVM['tone'];
  attentionRequired: boolean;
}

export interface SupplierVM {
  supplierId: string;
  supplierName: string;
  /** Every site this supplier shipped from, among the decisions in view. */
  sites: string[];
  materials: SupplierMaterialVM[];
  decisions: SupplierDecisionVM[];
  /** How many of those decisions the SERVER flagged for a person. */
  attentionCount: number;
}

export interface SuppliersVM {
  suppliers: SupplierVM[];
  /** Stated plainly so the count is never mistaken for a plant-wide total. */
  sourceDescription: string;
}

/**
 * Group the decisions in view by supplier.
 *
 * The result describes THE DECISIONS THIS PAGE CAN SEE — never the supplier
 * base. A page that has ten rows knows about the suppliers on those ten rows,
 * and saying "5 of 214" when nothing counted 214 would be a fabrication.
 */
export function toSuppliers(rows: IncomingRowVM[]): SuppliersVM {
  const byId = new Map<string, SupplierVM>();

  for (const row of rows) {
    const id = row.supplierName || row.lotId;
    let entry = byId.get(id);
    if (!entry) {
      entry = {
        supplierId: id,
        supplierName: row.supplierName,
        sites: [],
        materials: [],
        decisions: [],
        attentionCount: 0,
      };
      byId.set(id, entry);
    }
    if (row.supplierSite && !entry.sites.includes(row.supplierSite)) {
      entry.sites.push(row.supplierSite);
    }
    if (row.materialId && !entry.materials.some((m) => m.materialId === row.materialId)) {
      entry.materials.push({ materialId: row.materialId, materialName: row.materialName });
    }
    entry.decisions.push({
      decisionRecordId: row.decisionRecordId,
      lotId: row.lotId,
      materialName: row.materialName,
      stateLabel: row.stateLabel,
      rowState: row.rowState,
      tone: row.tone,
      attentionRequired: row.attentionRequired,
    });
    if (row.attentionRequired) entry.attentionCount += 1;
  }

  const suppliers = [...byId.values()].sort((a, b) =>
    a.supplierName.localeCompare(b.supplierName),
  );

  return {
    suppliers,
    sourceDescription:
      suppliers.length === 0
        ? 'No supplier appears in the decisions currently loaded.'
        : `${suppliers.length} ${suppliers.length === 1 ? 'supplier' : 'suppliers'} across the decisions currently loaded.`,
  };
}
