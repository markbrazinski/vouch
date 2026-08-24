import type { BasisChainLink, BasisStep, ResumeStep } from '../../view-models/types';

export const BASIS_CHAIN: BasisChainLink[] = [
  { label: 'SUPPLIER COA', value: 'CONFORMS', tone: 'released' },
  { label: 'GOVERNING BASIS', value: 'Plant Spec S-88 · Rev 4', tone: 'ink' },
  { label: 'REQUIREMENT', value: 'Tensile ≥ 480 MPa', tone: 'ink' },
  { label: 'SUPPLIED RESULT', value: '462 MPa', tone: 'ink' },
  { label: 'RESULT', value: '⊘ QUARANTINED', tone: 'quarantine' },
];

/**
 * Eight-step decision basis. Step 2 — resolving which requirement governs — is
 * the load-bearing agentic judgment. Never reduce this to 462 < 480 → QUARANTINE.
 */
export const RECORD_STEPS: BasisStep[] = [
  {
    n: '1',
    kind: 'EVIDENCE',
    head: 'Supplier certificate of analysis',
    body: 'Resin R-17 · shipment 88-4471. Declares the lot conforms and attaches the mill test report.',
    pill: 'COA: CONFORMS',
    tone: 'released',
  },
  {
    n: '2',
    kind: 'GOVERNING BASIS',
    head: 'Vouch resolved which requirement governs',
    body: 'The supplier certifies against its own limits. For this material the governing basis is the current plant specification — Vouch establishes that S-88 Rev 4 applies before any value is compared.',
    pill: 'Plant Spec S-88 · Rev 4 · Tensile ≥ 480 MPa',
    tone: 'ink',
    loadBearing: true,
  },
  {
    n: '3',
    kind: 'OBSERVED RESULT',
    head: 'Result read from the supplied data',
    body: 'Under the governing method, the reported tensile value sits below the required minimum.',
    pill: '462 MPa · −18 vs required',
    tone: 'quarantine',
  },
  {
    n: '4',
    kind: 'DISPOSITION',
    head: 'Quarantined',
    body: 'Measured against S-88 Rev 4, the supplier’s CONFORMS claim does not hold. Vouch dispositions on the governing basis, not the certificate’s conclusion.',
    pill: '⊘ QUARANTINED',
    tone: 'quarantine',
    loadBearing: true,
  },
  {
    n: '5',
    kind: 'INDEPENDENT VERIFICATION',
    head: 'Independent verification · VERIFIED',
    body: 'A separate path checked the proposed disposition against the applicable evidence and governing basis — not a re-run of the arithmetic. Basis and disposition confirmed.',
    pill: 'VERIFIED',
    tone: 'released',
  },
  {
    n: '6',
    kind: 'INVENTORY STATE CHANGE',
    head: 'Lot moved out of available stock',
    body: 'Physical inventory state changes with the disposition: the lot is no longer available to production.',
    pill: 'Pending release → Quarantined · 900 kg',
    tone: 'quarantine',
  },
  {
    n: '7',
    kind: 'REQUIREMENT COVERAGE',
    head: 'C-417 loses its coverage',
    body: 'C-417 requires 900 kg of R-17. With this lot held, that requirement is fully uncovered.',
    pill: '900 kg uncovered',
    tone: 'quarantine',
  },
  {
    n: '8',
    kind: 'PRODUCTION CONSEQUENCE',
    head: 'C-417 blocked, then recovered',
    body: 'The order can no longer run in its slot. Vouch evaluated recovery options and resequenced C-418 into the 09:30 slot, preserving Line 2 capacity while C-417 remains blocked.',
    pill: 'C-417 BLOCKED · C-418 resequenced',
    tone: 'blocked',
    loadBearing: true,
  },
];

/** Same record resumes after evidence. No new case is created. */
export const RESUME_STEPS: ResumeStep[] = [
  {
    head: 'Evidence added',
    body: 'Approved equivalence and its accountable authority are attached to this record.',
  },
  {
    head: 'Evaluation resumed',
    body: 'On the resolved basis, Vouch re-evaluates the result against the governing spec.',
  },
  {
    head: 'Independent verification · VERIFIED',
    body: 'The disposition is checked against the applicable evidence and basis, and confirmed.',
  },
  {
    head: 'Released',
    body: 'Inventory state moves Pending release → Released. Material becomes available.',
  },
];
