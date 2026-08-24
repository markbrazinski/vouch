import type { DecisionRow } from '../../view-models/types';

/** The six individual Quality decisions. Locked copy. */
export const DECISIONS: DecisionRow[] = [
  {
    lotId: 'L-2262',
    material: 'Resin R-17',
    disposition: 'QUALITY DECISION',
    tone: 'decision',
    hot: true,
    impact: 'C-419 · runs 13:30',
    clock: '3h 42m',
    reason:
      'COA reports tensile by Method M-12; Spec S-88 requires M-17. No approved equivalence on file.',
    question:
      'Does approved evidence establish Method M-12 as equivalent to required Method M-17 for this test?',
    governingBasis: {
      label: 'Spec S-88 · tensile determination',
      body: 'The result must be obtained by Method M-17 for this material and condition.',
    },
    suppliedEvidence: {
      label: 'Supplier certificate of analysis',
      body: 'Reports the tensile result by Method M-12.',
    },
    gap: 'No approved M-12 to M-17 equivalence is on file for this condition.',
    consequence: {
      tag: 'C-419 AT RISK',
      line: 'Runs 13:30 today · 3h 42m to slot. Line 2 coverage depends on this lot.',
    },
    order: 'C-419 · Line 2',
    primaryAction: {
      label: 'Provide approved equivalence',
      sub: 'Attach the equivalence and the accountable authority. Vouch captures the basis, then reassesses.',
    },
  },
  {
    lotId: 'L-2251',
    material: 'Solvent X-9',
    disposition: 'QUALITY DECISION',
    tone: 'decision',
    hot: true,
    impact: 'C-421 · runs 15:00',
    clock: '5h 12m',
    reason:
      'COA covers a blended shipment; single-lot traceability to the tested sample is not established.',
    question: 'Which single lot does the supplied certificate actually certify?',
    governingBasis: {
      label: 'Single-lot traceability',
      body: 'The tested sample must trace to one identified lot.',
    },
    suppliedEvidence: {
      label: 'Supplier certificate of analysis',
      body: 'Covers a blended shipment of three lots.',
    },
    gap: 'The tested sample cannot be traced to this specific lot.',
    consequence: { tag: 'C-421 AT RISK', line: 'Runs 15:00 today · 5h 12m to slot.' },
    order: 'C-421 · Line 4',
    primaryAction: {
      label: 'Provide single-lot traceability',
      sub: 'Attach lot-level identity linking the tested sample to this lot.',
    },
  },
  {
    lotId: 'L-2258',
    material: 'Hardener H-4',
    disposition: 'QUARANTINE · REVIEW',
    tone: 'quarantine',
    hot: false,
    impact: 'C-424 · tmrw 06:00',
    reason:
      'Viscosity is 0.8% above the Spec S-42 band. Verified. A use-as-is override needs a Quality decision.',
    question: 'Should the 0.8% viscosity exceedance be dispositioned use-as-is?',
    governingBasis: {
      label: 'Spec S-42 · viscosity upper band',
      body: 'Result must sit within the specified upper band.',
    },
    suppliedEvidence: {
      label: 'Independently verified result',
      body: '0.8% above the upper band, confirmed by a second path.',
    },
    gap: 'A use-as-is override requires a named Quality decision.',
    consequence: { tag: 'C-424 TOMORROW', line: 'Runs tomorrow 06:00 · not time-critical today.' },
    order: 'C-424 · Line 6',
    primaryAction: {
      label: 'Disposition use-as-is',
      sub: 'Record the accountable Quality decision and rationale for the exceedance.',
    },
  },
  {
    lotId: 'L-2244',
    material: 'Pigment P-2',
    disposition: 'QUALITY DECISION',
    tone: 'decision',
    hot: false,
    impact: 'No near-term order',
    reason:
      'Supplier changed its manufacturing site; no requalification evidence on file for this source.',
    question: 'Is this manufacturing site qualified to supply Pigment P-2?',
    governingBasis: {
      label: 'Approved site qualification',
      body: 'The producing site must be qualified on file.',
    },
    suppliedEvidence: {
      label: 'Shipment origin',
      body: 'Produced at a manufacturing site not previously qualified.',
    },
    gap: 'No requalification evidence is on file for the new site.',
    consequence: { tag: 'NO NEAR-TERM ORDER', line: 'No production waiting on this lot.' },
    order: '—',
    primaryAction: {
      label: 'Attach requalification evidence',
      sub: 'Provide the site qualification for this source.',
    },
  },
  {
    lotId: 'L-2249',
    material: 'Resin R-11',
    disposition: 'QUALITY DECISION',
    tone: 'decision',
    hot: false,
    impact: 'No near-term order',
    reason:
      'Certificate signed by an authority not on the approved signatory list for this supplier.',
    question: 'Is the certifying authority approved to sign for this supplier?',
    governingBasis: {
      label: 'Approved signatory list',
      body: 'The certificate must be signed by a listed authority.',
    },
    suppliedEvidence: {
      label: 'Supplier certificate of analysis',
      body: 'Signed by an authority not on the approved list.',
    },
    gap: 'The signatory is not on the approved list for this supplier.',
    consequence: { tag: 'NO NEAR-TERM ORDER', line: 'No production waiting on this lot.' },
    order: '—',
    primaryAction: {
      label: 'Confirm signatory authorisation',
      sub: 'Attach the approval adding this signatory, or reject.',
    },
  },
  {
    lotId: 'L-2237',
    material: 'Filler F-7',
    disposition: 'QUARANTINE · REVIEW',
    tone: 'quarantine',
    hot: false,
    impact: 'No near-term order',
    reason: 'Moisture result absent from the COA; requirement coverage cannot be confirmed.',
    question: 'Can requirement coverage be confirmed without the moisture result?',
    governingBasis: {
      label: 'Spec · moisture requirement',
      body: 'A moisture result is required to confirm coverage.',
    },
    suppliedEvidence: {
      label: 'Supplier certificate of analysis',
      body: 'The moisture result is absent.',
    },
    gap: 'Coverage cannot be confirmed from the supplied evidence.',
    consequence: { tag: 'NO NEAR-TERM ORDER', line: 'No production waiting on this lot.' },
    order: '—',
    primaryAction: {
      label: 'Request the moisture result',
      sub: 'Ask the supplier to certify the missing result.',
    },
  },
];

/**
 * The Halden incident is ONE bounded decision covering 18 lots — a single row,
 * never exploded into 18 cards. 18 grouped + 6 individual = 24.
 */
export const HALDEN_GROUPED: DecisionRow = {
  lotId: '18 lots',
  material: 'Halden Chemical incident',
  disposition: 'ONE DECISION · 18 LOTS',
  tone: 'quarantine',
  hot: true,
  impact: 'Solvent X-9, Hardener H-4',
  clock: 'grouped',
  groupedCount: 18,
  reason:
    'Same governing gap across 18 re-held lots: the reported deviation scope is unconfirmed. Decide once, applies to all.',
  question:
    'Does the reported manufacturing deviation affect material already accepted from these 18 lots?',
  governingBasis: {
    label: 'Deviation containment',
    body: 'Affected material must be identified and contained before release.',
  },
  suppliedEvidence: {
    label: 'Supplier incident notice',
    body: 'Deviation reported 08:20; scope not yet bounded by the supplier.',
  },
  gap: 'The deviation scope is unconfirmed, so equivalence to accepted material cannot be established.',
  consequence: { tag: '18 LOTS RE-HELD', line: 'All 18 lots held pending one governing decision.' },
  order: 'multiple',
  primaryAction: {
    label: 'Hold all · request bounded scope',
    sub: 'Keep all 18 held and require the supplier to bound the deviation. Applies to every lot at once.',
  },
};
