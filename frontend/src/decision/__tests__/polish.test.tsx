/**
 * The Hero A Experience Polish pass — four corrections, each pinned.
 *
 * 1. live qualification is separate from the visual baseline
 * 2. "not persisted yet" no longer renders as "does not exist"
 * 3. source claims are itemized from authoritative truth, with provenance
 * 4. `identityTrusted === false` has a rendering path
 *
 * Where a test can assert against REAL captured backend data it does, because a
 * hand-written fixture agrees with whatever assumption the adapter already
 * makes and therefore cannot falsify it.
 */

import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { claimsByArtifact, project, toSource } from '../adapter';
import { mergeEvents } from '../useDecisionRun';
import { CaseContextColumn } from '../CaseContextColumn';
import { EvidenceStage } from '../Stages';
import { SourceDocumentViewer } from '../SourceDocumentViewer';
import type { SourceArtifactDTO } from '../dto';
import type { EstablishedTruthVM, SourceArtifactVM } from '../model';

const SRC = join(import.meta.dirname, '..', '..');
const E2E = join(SRC, '..', 'e2e');

/** The captured real QUARANTINE decision that backs the visual baseline. */
const CAPTURE = JSON.parse(
  readFileSync(join(SRC, 'dev', 'fixtures', 'hero-a-quarantine.json'), 'utf8'),
) as { decision_record_id: string; record: Record<string, unknown>; events: unknown[] };

const EMPTY_TRUTH: EstablishedTruthVM = {
  lotLine: 'LOT-1002 · MAT-ALLOY-7',
  governingBasis: null,
  boundFact: null,
  holdTruth: null,
};

// ---------------------------------------------------------------------------
// 1. live qualification vs visual baseline
// ---------------------------------------------------------------------------

describe('live qualification is separate from the visual baseline', () => {
  it('the live run accepts every valid outcome, not one chosen outcome', () => {
    const live = readFileSync(join(E2E, 'hero-a.mjs'), 'utf8');

    // It classifies whatever happened...
    expect(live).toMatch(/outcomeClass/);
    expect(live).toMatch(/QUALITY_DECISION_REQUIRED/);
    expect(live).toMatch(/QUARANTINE/);
    // ...and qualifies on reaching A valid outcome, never a specific one.
    expect(live).toMatch(/validOutcome = report\.outcomeClass !== 'UNKNOWN'/);
    // It must not fail merely because the model abstained.
    expect(live).not.toMatch(/outcomeClass !== 'QUARANTINE'/);
  });

  it('the live report is labelled as qualification evidence, not a baseline', () => {
    const live = readFileSync(join(E2E, 'hero-a.mjs'), 'utf8');
    expect(live).toMatch(/kind: 'LIVE_QUALIFICATION'/);
    expect(live).toMatch(/live-qualification\.json/);

    const baseline = readFileSync(join(E2E, 'visual-baseline.mjs'), 'utf8');
    expect(baseline).toMatch(/kind: 'VISUAL_BASELINE'/);
    // The two must not write to the same artifact, or one would overwrite the
    // other and the distinction would be lost on disk.
    expect(baseline).not.toMatch(/live-qualification\.json/);
  });

  it('the live run waits for the source to settle before reading it', () => {
    // The source lands a few seconds AFTER the outcome renders, because
    // `get_source` only becomes answerable once the record is durable. Sampling
    // at the outcome read the gap and reported "no claims" for a document whose
    // claims existed.
    const live = readFileSync(join(E2E, 'hero-a.mjs'), 'utf8');
    expect(live).toMatch(/waitForFunction/);
    expect(live).toMatch(/sourceSettled/);
  });

  it('the baseline pins one canonical state and fails if it drifts', () => {
    const baseline = readFileSync(join(E2E, 'visual-baseline.mjs'), 'utf8');
    expect(baseline).toMatch(/report\.state === 'QUARANTINE'/);
  });

  it('the baseline is built from a real captured decision, not invented data', () => {
    // Real records carry real ids and real event volume. A hand-written fixture
    // would not survive these.
    expect(CAPTURE.decision_record_id).toMatch(/^DR-[0-9a-f]{12}$/);
    expect(CAPTURE.events.length).toBeGreaterThan(30);
    const disposition = CAPTURE.record.disposition as { disposition?: string };
    expect(disposition.disposition).toBe('QUARANTINE');
  });

  it('the baseline route is DEV-only and never authors an outcome in main', () => {
    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8');
    // Guarded by DEV, so Vite drops the branch and the chunk in production.
    expect(main).toMatch(/import\.meta\.env\.DEV && window\.location\.pathname === '\/dev\/visual-baseline'/);
    // And the entry file still names no disposition of its own.
    expect(main).not.toMatch(/QUARANTINE|RELEASE|INSUFFICIENT_EVIDENCE/);
  });

  it('the baseline renders through the real projection, not a parallel one', () => {
    const mod = readFileSync(join(SRC, 'dev', 'HeroAVisualBaseline.tsx'), 'utf8');
    expect(mod).toMatch(/from '\.\.\/decision\/adapter'/);
    expect(mod).toMatch(/project\(/);
    // No network: a baseline that fetched would not be deterministic.
    expect(mod).not.toMatch(/\bfetch\s*\(/);
    // And through the same dedupe, not around it.
    expect(mod).toMatch(/mergeEvents\(\[\], CAPTURED\.events\)/);
  });

  it('the captured stream carries the backend double-write, and dedupes to half', () => {
    // The capture is the RAW durable stream. The backend writes every event
    // twice by design — once live from the sink, once in the terminal batch —
    // with distinct sequences and distinct ids, so neither can be the dedupe
    // key. Rendering the raw rows produced duplicate React keys; this pins the
    // collapse so the baseline cannot silently regress to showing everything
    // twice.
    const raw = CAPTURE.events as { event: string; at: string; sequence: number }[];
    expect(new Set(raw.map((e) => e.sequence)).size).toBe(raw.length);

    const merged = mergeEvents([], raw as never[]);
    expect(merged.length).toBeLessThan(raw.length);
    // Densely renumbered, so every row has a stable unique key.
    expect(new Set(merged.map((e) => e.sequence)).size).toBe(merged.length);
  });
});

// ---------------------------------------------------------------------------
// 2. the pre-source state
// ---------------------------------------------------------------------------

describe('a source that has not persisted yet is not reported as absent', () => {
  const renderColumn = (props: Partial<Parameters<typeof CaseContextColumn>[0]> = {}) =>
    render(
      <CaseContextColumn
        sources={[]}
        selectedId={null}
        truth={EMPTY_TRUTH}
        onSelect={() => {}}
        onOpenSource={() => {}}
        {...props}
      />,
    );

  it('says evidence is arriving while an artifact is known to exist', () => {
    renderColumn({ pending: true });
    expect(screen.getByTestId('source-pending').textContent).toContain(
      'Receiving source evidence',
    );
  });

  it('never claims there is no artifact while one is known to exist', () => {
    renderColumn({ pending: true });
    expect(screen.getByTestId('source-pending').textContent).not.toContain(
      'No source artifact yet',
    );
  });

  it('still reports absence honestly when no artifact is known', () => {
    renderColumn({ pending: false });
    expect(screen.getByTestId('source-pending').textContent).toContain('No source artifact yet');
  });

  it('stays pending after the outcome, until the fetch actually lands', () => {
    // The real defect, found live: the source arrives ~3s AFTER the outcome
    // renders, by which point `running` is already false. Deriving the state
    // from `running` therefore flipped the column back to "No source artifact
    // yet" while the document demonstrably existed.
    const vm = project({
      decisionRecordId: 'DR-x',
      lotId: 'LOT-1002',
      running: false,
      sources: [],
      events: [
        {
          event: 'EVIDENCE_RECEIVED',
          decision_record_id: 'DR-x',
          at: '2026-09-03T00:00:00Z',
          sequence: 1,
          artifact_id: 'ART-1',
        },
      ] as never[],
    });
    expect(vm.sourcesPending).toBe(true);
  });

  it('is not pending when the lifecycle never mentioned an artifact', () => {
    const vm = project({ decisionRecordId: 'DR-x', lotId: 'LOT-1002', events: [] });
    expect(vm.sourcesPending).toBe(false);
  });

  it('stops being pending once the artifact has arrived', () => {
    const vm = project({
      decisionRecordId: 'DR-x',
      lotId: 'LOT-1002',
      sources: [{ artifact_id: 'ART-1' } as never],
      events: [
        {
          event: 'EVIDENCE_RECEIVED',
          decision_record_id: 'DR-x',
          at: '2026-09-03T00:00:00Z',
          sequence: 1,
          artifact_id: 'ART-1',
        },
      ] as never[],
    });
    expect(vm.sourcesPending).toBe(false);
  });

  it('shows the artifact rather than either message once one exists', () => {
    const artifact = toSource({ artifact_id: 'ART-1', document_type: 'COA' } as SourceArtifactDTO);
    renderColumn({ sources: [artifact], pending: true });
    expect(screen.queryByTestId('source-pending')).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 3. itemized claims, joined from authoritative truth
// ---------------------------------------------------------------------------

describe('source claims are itemized from the durable record', () => {
  it('joins the captured record real claims onto their artifact', () => {
    const joined = claimsByArtifact(CAPTURE.record);
    expect(joined.size).toBeGreaterThan(0);

    const [artifactId, claims] = [...joined.entries()][0];
    expect(artifactId).toMatch(/^ART-/);
    expect(claims.length).toBe(2);

    // The real Hero A COA declares exactly these two measurements.
    const characteristics = claims.map((c) => c.characteristic).sort();
    expect(characteristics).toEqual(['hardness', 'tensile_strength']);
  });

  it('carries each claim provenance, not just its value', () => {
    const claims = [...claimsByArtifact(CAPTURE.record).values()][0];
    const tensile = claims.find((c) => c.characteristic === 'tensile_strength')!;
    expect(tensile.value).toBe(462.0);
    expect(tensile.units).toBe('MPa');
    expect(tensile.method).toBe('ASTM-E8');
    // Where in the document it was read. This is what makes it evidence.
    expect(tensile.source_locator).toBeTruthy();
  });

  it('projects the joined claims onto the source view model', () => {
    const joined = claimsByArtifact(CAPTURE.record);
    const [artifactId, claims] = [...joined.entries()][0];
    const vm = toSource({ artifact_id: artifactId } as SourceArtifactDTO, claims);

    expect(vm.claims).toHaveLength(2);
    const tensile = vm.claims.find((c) => c.label === 'Tensile Strength')!;
    expect(tensile.value).toBe('462 MPa');
    expect(tensile.method).toBe('ASTM-E8');
    expect(tensile.locator).toBeTruthy();
  });

  it('itemizes them in the viewer instead of reporting a bare count', () => {
    const joined = claimsByArtifact(CAPTURE.record);
    const [artifactId, claims] = [...joined.entries()][0];
    const vm = toSource(
      { artifact_id: artifactId, claim_count: 2 } as SourceArtifactDTO,
      claims,
    );

    render(
      <SourceDocumentViewer artifact={vm} decisionRecordId="DR-test" onClose={() => {}} />,
    );

    expect(screen.getByText('Tensile Strength')).toBeTruthy();
    expect(screen.getByText('462 MPa')).toBeTruthy();
    // The old admission must be gone now that the claims are actually shown.
    expect(screen.queryByText(/not itemized on this view/)).toBeNull();
    // And each claim shows where it came from.
    expect(screen.getAllByTestId('claim-provenance').length).toBe(2);
  });

  it('still admits a count honestly when no claims can be joined', () => {
    const vm = toSource({ artifact_id: 'ART-x', claim_count: 2 } as SourceArtifactDTO);
    render(
      <SourceDocumentViewer artifact={vm} decisionRecordId="DR-test" onClose={() => {}} />,
    );
    // Two claims exist but are not available here: that is not "no claims".
    expect(screen.getByText(/not itemized on this view/)).toBeTruthy();
  });

  it('is a pure read of published truth, inventing no claim', () => {
    // Nothing is joined from a record that has none, and nothing is fabricated
    // to fill the gap.
    expect(claimsByArtifact({}).size).toBe(0);
    expect(claimsByArtifact(null).size).toBe(0);
    expect(claimsByArtifact({ evidence: {} }).size).toBe(0);
  });

  it('reaches the workspace projection end to end', () => {
    const vm = project({
      decisionRecordId: CAPTURE.decision_record_id,
      lotId: 'LOT-1002',
      events: CAPTURE.events as never[],
      record: CAPTURE.record,
      sources: [
        { artifact_id: [...claimsByArtifact(CAPTURE.record).keys()][0] } as SourceArtifactDTO,
      ],
    });
    expect(vm.sources[0].claims).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// 4. identityTrusted === false
// ---------------------------------------------------------------------------

describe('a document whose identity could not be established', () => {
  /** Readable enough to yield measurements, not readable enough to bind a lot. */
  const untrusted = (): SourceArtifactVM =>
    toSource({
      artifact_id: 'ART-untrusted',
      document_type: 'COA',
      security_state: 'CLEARED',
      structured_extraction: true,
      extraction_method: 'TEXTRACT_TABLES',
      extraction_confidence: 0.82,
      confidence_gate_passed: true,
      identity_trusted: false,
      claim_count: 2,
    } as SourceArtifactDTO);

  it('is modelled as untrusted identity, not as a failure', () => {
    const vm = untrusted();
    expect(vm.extraction?.identityTrusted).toBe(false);
    // Extraction still succeeded. The two facts are independent.
    expect(vm.extraction?.confidenceGatePassed).toBe(true);
  });

  it('keeps the source visible rather than hiding it', () => {
    const vm = untrusted();
    render(<EvidenceStage sources={[vm]} claimCount={2} onOpenSource={() => {}} />);
    expect(screen.getAllByText('COA').length).toBeGreaterThan(0);
  });

  it('shows an evidence-stage caution that identity is not established', () => {
    render(<EvidenceStage sources={[untrusted()]} claimCount={2} onOpenSource={() => {}} />);
    const notice = screen.getByTestId('identity-untrusted');
    expect(notice.textContent).toContain('IDENTITY NOT ESTABLISHED');
    expect(notice.textContent).toMatch(/held unbound/i);
  });

  it('never asserts the evidence was bound to a lot', () => {
    render(<EvidenceStage sources={[untrusted()]} claimCount={2} onOpenSource={() => {}} />);
    // The Identity row is READ, not hard-coded. This was a real defect: the row
    // said "Bound to lot" unconditionally.
    expect(screen.getByText('Not established')).toBeTruthy();
    expect(screen.queryByText('Bound to lot')).toBeNull();
  });

  it('still says bound when the identity genuinely was', () => {
    const ordinary = toSource({
      artifact_id: 'ART-ok',
      security_state: 'CLEARED',
    } as SourceArtifactDTO);
    render(<EvidenceStage sources={[ordinary]} claimCount={2} onOpenSource={() => {}} />);
    expect(screen.getByText('Bound to lot')).toBeTruthy();
    expect(screen.queryByTestId('identity-untrusted')).toBeNull();
  });

  it('implies no mutation and no disposition', () => {
    render(<EvidenceStage sources={[untrusted()]} claimCount={2} onOpenSource={() => {}} />);
    const notice = screen.getByTestId('identity-untrusted');
    expect(notice.textContent).toMatch(/nothing was changed/i);
    expect(notice.textContent).not.toMatch(/QUARANTINE|RELEASE/);
  });

  it('does not populate established truth from an unbound reading', () => {
    // The binding event is what populates boundFact, and an identity-untrusted
    // document never produces a successful one.
    const vm = project({
      decisionRecordId: 'DR-test',
      lotId: 'LOT-1002',
      events: [
        {
          event: 'EVIDENCE_BINDING_COMPLETED',
          decision_record_id: 'DR-test',
          at: '2026-09-03T00:00:00Z',
          sequence: 1,
          bound: false,
          binding_status: 'UNBOUND',
        },
      ],
    });
    expect(vm.truth.boundFact).toBeNull();
    expect(vm.truth.governingBasis).toBeNull();
  });

  it('routes to a human rather than presenting a technical crash', () => {
    render(<EvidenceStage sources={[untrusted()]} claimCount={2} onOpenSource={() => {}} />);
    expect(screen.getByTestId('identity-untrusted').textContent).toMatch(/Routed to Quality/i);
  });
});

// ---------------------------------------------------------------------------
// A refused proposal is not an outcome (found by the live abstain run)
// ---------------------------------------------------------------------------

describe('a refused disposition is never presented as a state change', () => {
  /**
   * The real abstain sequence, observed live: the disposition is COMPUTED as
   * QUARANTINE, the policy gate REFUSES it, and a quality decision is required.
   * Nothing is committed.
   */
  const abstainEvents = [
    {
      event: 'DISPOSITION_COMPUTED',
      decision_record_id: 'DR-abstain',
      at: '2026-09-03T08:00:28Z',
      sequence: 1,
      disposition: 'QUARANTINE',
    },
    {
      event: 'POLICY_EVALUATED',
      decision_record_id: 'DR-abstain',
      at: '2026-09-03T08:00:28Z',
      sequence: 2,
      gate_decision: 'REFUSED',
      policy_version: 'vouch-policy-2.1',
    },
    {
      event: 'QUALITY_DECISION_REQUIRED',
      decision_record_id: 'DR-abstain',
      at: '2026-09-03T08:00:28Z',
      sequence: 3,
      material_differences: [],
    },
  ];

  const abstain = () =>
    project({ decisionRecordId: 'DR-abstain', lotId: 'LOT-1002', events: abstainEvents as never[] });

  it('does not put the refused proposal in the header', () => {
    // The defect this pins: the header read "QUARANTINE" beside an outcome
    // panel reading "Quality decision required · ABSTAIN", asserting a state
    // change the policy gate had explicitly refused.
    expect(abstain().dispositionLabel).not.toBe('QUARANTINE');
  });

  it('states the decision is open instead', () => {
    expect(abstain().dispositionLabel).toBe('QUALITY DECISION');
  });

  it('records no committed mutation', () => {
    expect(abstain().disposition?.stateMutation ?? []).not.toContain('Quarantine Lot');
  });

  it('still reports a genuine disposition when one was committed', () => {
    // The guard must not swallow a real outcome. The captured QUARANTINE run
    // committed its mutation, and its header must say so.
    const vm = project({
      decisionRecordId: CAPTURE.decision_record_id,
      lotId: 'LOT-1002',
      events: mergeEvents([], CAPTURE.events as never[]),
      record: CAPTURE.record,
    });
    expect(vm.dispositionLabel).toBe('QUARANTINE');
  });
});
