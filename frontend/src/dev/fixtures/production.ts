import type {
  ProductionLine,
  ProductionOrder,
  ProductionReadiness,
  RecoveryVerdictVM,
  SequenceCell,
} from '../../view-models/types';

const o = (
  time: string,
  id: string,
  material: string,
  readiness: ProductionReadiness = 'READY',
): ProductionOrder => ({ time, id, material, readiness });

/** 8 lines · 43 orders. Every order is represented. */
export const LINES: Omit<ProductionLine, 'note'>[] = [
  {
    name: 'Line 1 · Mixing',
    orders: [
      o('07:00', 'C-401', 'Resin R-17'),
      o('09:30', 'C-402', 'Compound B-2'),
      o('12:00', 'C-403', 'Filler F-3'),
      o('14:00', 'C-404', 'Resin R-11'),
      o('16:00', 'C-405', 'Solvent X-9', 'AT_RISK'),
      o('18:00', 'C-406', 'Compound B-2'),
    ],
  },
  {
    name: 'Line 2 · Extrusion',
    orders: [
      o('09:30', 'C-417', 'Resin R-17'),
      o('12:00', 'C-418', 'Compound B-2'),
      o('13:30', 'C-419', 'Resin R-17', 'AT_RISK'),
      o('15:30', 'C-420', 'Filler F-3'),
    ],
  },
  {
    name: 'Line 3 · Molding',
    orders: [
      o('07:00', 'C-431', 'Compound B-2'),
      o('09:00', 'C-432', 'Compound B-2'),
      o('11:00', 'C-433', 'Pigment P-2'),
      o('13:00', 'C-434', 'Compound B-2'),
      o('15:00', 'C-435', 'Filler F-3'),
      o('17:00', 'C-436', 'Compound B-2'),
    ],
  },
  {
    name: 'Line 4 · Coating',
    orders: [
      o('08:00', 'C-441', 'Solvent X-9'),
      o('10:30', 'C-442', 'Pigment P-2'),
      o('13:00', 'C-443', 'Solvent X-9', 'AT_RISK'),
      o('15:30', 'C-444', 'Hardener H-4'),
      o('17:30', 'C-445', 'Solvent X-9'),
    ],
  },
  {
    name: 'Line 5 · Assembly',
    orders: [
      o('07:30', 'C-451', 'Compound B-2'),
      o('09:30', 'C-452', 'Filler F-3'),
      o('11:30', 'C-453', 'Resin R-17'),
      o('13:30', 'C-454', 'Compound B-2'),
      o('15:30', 'C-455', 'Filler F-7'),
      o('17:30', 'C-456', 'Compound B-2'),
    ],
  },
  {
    name: 'Line 6 · Curing',
    orders: [
      o('06:00', 'C-461', 'Hardener H-4'),
      o('08:30', 'C-462', 'Resin R-11'),
      o('11:00', 'C-463', 'Hardener H-4'),
      o('14:00', 'C-464', 'Compound B-2'),
      o('16:30', 'C-465', 'Hardener H-4'),
    ],
  },
  {
    name: 'Line 7 · Packaging',
    orders: [
      o('07:00', 'C-471', 'Filler F-3'),
      o('09:00', 'C-472', 'Filler F-3'),
      o('11:00', 'C-473', 'Pigment P-2'),
      o('13:00', 'C-474', 'Filler F-3'),
      o('15:00', 'C-475', 'Filler F-3'),
      o('17:00', 'C-476', 'Filler F-3'),
    ],
  },
  {
    name: 'Line 8 · Finishing',
    orders: [
      o('08:00', 'C-481', 'Solvent X-9'),
      o('10:00', 'C-482', 'Pigment P-2'),
      o('12:00', 'C-483', 'Solvent X-9'),
      o('14:30', 'C-484', 'Hardener H-4'),
      o('16:30', 'C-485', 'Solvent X-9'),
    ],
  },
];

/** Line 2 after the quarantine: C-418 moved up, C-417 stays blocked. */
export const L2_SEQUENCE: SequenceCell[] = [
  { time: '09:30', id: 'C-418', readiness: 'READY', tag: 'MOVED UP' },
  { time: '12:00', id: 'C-417', readiness: 'BLOCKED' },
  { time: '13:30', id: 'C-419', readiness: 'AT_RISK' },
  { time: '15:30', id: 'C-420', readiness: 'READY' },
];

export const RECOVERY: RecoveryVerdictVM[] = [
  {
    kind: 'EXISTING INVENTORY',
    title: 'Released R-17 on hand',
    detail: '420 kg available against 900 kg required — 480 kg short.',
    verdict: 'NOT FEASIBLE',
    tone: 'blocked',
  },
  {
    kind: 'SUBSTITUTE',
    title: 'Lot L-2240',
    detail: 'Chemically close, not on the approved list for Spec S-88. No equivalence basis.',
    verdict: '✕ REFUSED',
    tone: 'refused',
  },
  {
    kind: 'RESEQUENCE',
    title: 'Pull C-418 forward',
    detail: 'All materials released and Line 2 feasible in the 09:30 slot.',
    verdict: 'ELIGIBLE',
    tone: 'released',
  },
];
