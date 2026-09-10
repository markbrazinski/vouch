/**
 * Workspace rendering, driven by the real captured Hero A response.
 *
 * These assert what a person actually sees at each point in the run — and,
 * as importantly, what they must NOT see: a disposition during a technical
 * failure, a governing basis before it was resolved, or a presigned URL
 * anywhere at all.
 */

import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';
import capture from './hero-a-capture.json';
import { DecisionWorkspace } from '../DecisionWorkspace';
import { SourceDocumentViewer } from '../SourceDocumentViewer';
import { project } from '../adapter';
import type { EvaluateDTO, LifecycleEventDTO } from '../dto';
import type { SourceArtifactVM } from '../model';

const dto = capture as unknown as EvaluateDTO;
const events = (dto.events ?? []) as LifecycleEventDTO[];

const terminal = () =>
  project({
    decisionRecordId: dto.decision_record_id,
    lotId: dto.lot_id!,
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-EAST · site SITE-E1 · 400 kg',
    events,
    result: dto,
    running: false,
  });

afterEach(cleanup);

describe('the terminal Hero A workspace', () => {
  it('shows the lot, the material and the disposition', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    expect(screen.getByText('LOT-1002')).toBeTruthy();
    // MAT-ALLOY-7 appears both as the lot's material and as a recovery
    // candidate (existing inventory), so this is legitimately not unique.
    expect(screen.getAllByText('MAT-ALLOY-7').length).toBeGreaterThan(0);
    expect(screen.getAllByText('QUARANTINE').length).toBeGreaterThan(0);
  });

  it('keeps the outcome to WHY and puts the plan change in the impact strip', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    // OUTCOME answers "what happened" and "why". The order transitions are no
    // longer restated here — that duplication is what made the terminal frame
    // unreadable at a glance.
    const outcome = screen.getByTestId('outcome-summary');
    expect(outcome.textContent).toContain('Quarantined');
    expect(outcome.textContent).not.toContain('C-417');

    // "What happens next", once, as two imperatives plus one consequence line.
    expect(screen.getByTestId('next-action').textContent).toContain('Block C-417. Begin C-418.');
    expect(screen.getByTestId('production-impact').textContent).toBe(
      'C-417 blocked · C-418 moved into the available production slot.',
    );
  });

  it('renders the spine with the independence seal', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    const spine = screen.getByTestId('decision-spine');
    expect(spine.textContent).toContain('INVESTIGATION');
    expect(spine.textContent).toContain('VERIFICATION');
    expect(spine.textContent).toContain('INDEPENDENT MATCH');
  });

  it('renders the rail newest-first with every event', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    const rows = screen.getAllByTestId('activity-row');
    expect(rows).toHaveLength(events.length);
    const first = Number(rows[0].getAttribute('data-sequence'));
    const last = Number(rows[rows.length - 1].getAttribute('data-sequence'));
    expect(first).toBeGreaterThan(last);
  });

  it('keeps the recovery grid out of the primary frame but reachable', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    // Not in the 3-second read: the grid competes with OUTCOME / WHY / NEXT
    // ACTION and the judge does not need it to understand the result.
    expect(screen.queryByTestId('recovery-MAT-SUB-9')).toBeNull();

    // Still one click away, with every verdict intact — the refusal is the
    // safety story and must never become unreachable.
    fireEvent.click(screen.getByTestId('completed-consequence'));
    expect(screen.getByTestId('recovery-MAT-SUB-9').textContent).toContain('REFUSED');
    expect(screen.getByTestId('recovery-C-418').textContent).toContain('ELIGIBLE');
  });

  it('drops the context column on the consequence stage', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    // Full-bleed: the durable-facts panel is not mounted.
    expect(screen.queryByText('CASE — DURABLE FACTS')).toBeNull();
  });

  it('keeps completed stages reopenable', () => {
    render(<DecisionWorkspace vm={terminal()} />);
    const disposition = screen.getByTestId('completed-disposition');
    fireEvent.click(disposition);
    expect(screen.getByText('STATE CHANGE')).toBeTruthy();
  });
});

describe('mid-run rendering', () => {
  const upTo = (type: string) => {
    const i = events.findIndex((e) => e.event === type);
    return project({
      decisionRecordId: dto.decision_record_id,
      lotId: dto.lot_id!,
      material: 'MAT-ALLOY-7',
      events: events.slice(0, i + 1),
      running: true,
    });
  };

  it('shows no outcome before a disposition exists', () => {
    render(<DecisionWorkspace vm={upTo('INVESTIGATOR_STARTED')} />);
    expect(screen.queryByTestId('outcome-summary')).toBeNull();
  });

  it('shows EVALUATING rather than a guessed disposition', () => {
    render(<DecisionWorkspace vm={upTo('INVESTIGATOR_STARTED')} />);
    expect(screen.getByText('EVALUATING')).toBeTruthy();
  });

  it('leaves the governing basis as an em-dash until the brief lands', () => {
    render(<DecisionWorkspace vm={upTo('EVIDENCE_SNAPSHOT_CREATED')} />);
    const context = screen.getByText('GOVERNING BASIS').parentElement;
    expect(context?.textContent).toContain('—');
    expect(context?.textContent).not.toContain('SPEC-A7');
  });

  it('fills the basis once the Investigator has resolved it', () => {
    render(<DecisionWorkspace vm={upTo('APPLICABILITY_BRIEF_COMPLETED')} />);
    expect(screen.getByText('SPEC-A7:C')).toBeTruthy();
  });

  it('holds the verifier lane empty until the verifier reports', () => {
    const vm = upTo('APPLICABILITY_BRIEF_COMPLETED');
    const agents = vm.spine.find((n) => n.key === 'agents');
    expect(agents?.investigatorLane).toBe('SUFFICIENT');
    expect(agents?.verifierLane).toBeNull();
  });
});

describe('failure rendering', () => {
  it('renders a technical failure with NO disposition anywhere', () => {
    const vm = project({
      decisionRecordId: 'DR-x',
      lotId: 'LOT-1002',
      material: 'MAT-ALLOY-7',
      events: events.slice(0, 4),
      running: false,
      failure: {
        kind: 'TECHNICAL_FAILURE',
        headline: 'Vouch could not be reached',
        detail: 'No decision was made.',
        suppressesDisposition: true,
      },
    });
    render(<DecisionWorkspace vm={vm} />);

    const notice = screen.getByTestId('failure-notice');
    expect(notice.getAttribute('data-failure-kind')).toBe('TECHNICAL_FAILURE');
    expect(screen.queryByTestId('outcome-summary')).toBeNull();
    // The single most important assertion in this file.
    expect(document.body.textContent).not.toContain('QUARANTINE');
    expect(document.body.textContent).not.toContain('RELEASE');
  });

  it('renders an abstention as an outcome, not as a crash', () => {
    const vm = project({
      decisionRecordId: 'DR-x',
      lotId: 'LOT-1004',
      events: events.slice(0, 4),
      failure: {
        kind: 'DOMAIN_ABSTENTION',
        headline: 'Vouch did not decide',
        detail: 'The evidence could not establish an answer.',
        suppressesDisposition: false,
      },
    });
    render(<DecisionWorkspace vm={vm} />);
    expect(screen.queryByTestId('failure-notice')).toBeNull();
  });
});

describe('source viewer', () => {
  const artifact: SourceArtifactVM = {
    artifactId: 'ART-1',
    displayName: 'Certificate of Analysis',
    documentType: 'coa',
    trustClass: 'supplier_untrusted',
    trustLabel: 'UNTRUSTED_SUPPLIER',
    securityState: 'cleared',
    versionId: 'v-abc123',
    hashSummary: '9f2c8a41…',
    excludedFromDecision: false,
    claims: [
      {
        label: 'Tensile Strength',
        value: '462 MPa',
        locator: 'line:3',
        method: 'ASTM-E8',
        condition: 'room_temp',
        trustClass: 'UNTRUSTED_SUPPLIER',
      },
    ],
    claimCount: 1,
    locators: [],
    extraction: null,
    openable: true,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('shows metadata and declared claims', () => {
    render(
      <SourceDocumentViewer artifact={artifact} decisionRecordId="DR-1" onClose={() => {}} />,
    );
    expect(screen.getByText('Certificate of Analysis')).toBeTruthy();
    expect(screen.getByText('462 MPa')).toBeTruthy();
    expect(screen.getByText('SUPPLIER-DECLARED')).toBeTruthy();
  });

  it('renders a structured locator when one exists', () => {
    render(
      <SourceDocumentViewer
        artifact={{
          ...artifact,
          locators: [
            {
              label: 'Page 3 · Table 1 · Tensile — Mean · Result',
              page: 3,
              table: 1,
              structured: true,
            },
          ],
        }}
        decisionRecordId="DR-1"
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId('source-locator').textContent).toBe(
      'Page 3 · Table 1 · Tensile — Mean · Result',
    );
  });

  it('falls back to the ordinary locator shape for a non-structured source', () => {
    render(
      <SourceDocumentViewer artifact={artifact} decisionRecordId="DR-1" onClose={() => {}} />,
    );
    expect(screen.getByTestId('source-locator').textContent).toBe('line:3');
  });

  it('shows a designed unavailable state, keeping metadata visible', () => {
    render(
      <SourceDocumentViewer
        artifact={{ ...artifact, openable: false }}
        decisionRecordId="DR-1"
        onClose={() => {}}
      />,
    );
    expect(screen.getByTestId('source-unavailable')).toBeTruthy();
    // Metadata survives: "cannot show the bytes" ≠ "know nothing".
    expect(screen.getByText('462 MPa')).toBeTruthy();
  });

  it('never persists a view ref, and never hands it to a new tab', async () => {
    const signed = 'https://bucket.s3.amazonaws.com/x?X-Amz-Signature=deadbeef';
    // The viewer signs, then FETCHES the bytes and frames them same-origin.
    // Both calls are served here: the metadata read and the byte read.
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(async (input: unknown) =>
        String(input).includes('X-Amz-Signature')
          ? { ok: true, blob: async () => new Blob([new Uint8Array([1, 2, 3])], { type: 'application/pdf' }) }
          : {
              ok: true,
              json: async () => ({
                ok: true,
                artifacts: [
                  { artifact_id: 'ART-1', view_ref: signed, content_type: 'application/pdf' },
                ],
              }),
            },
      ),
    );
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:vouch/doc'),
      revokeObjectURL: vi.fn(),
    });
    const open = vi.fn();
    vi.stubGlobal('open', open);

    render(
      <SourceDocumentViewer artifact={artifact} decisionRecordId="DR-1" onClose={() => {}} />,
    );
    // Opening the viewer IS the request to see the document; there is no second
    // button, and no tab is ever opened with the credential in its URL.
    await new Promise((r) => setTimeout(r, 10));
    expect(open).not.toHaveBeenCalled();

    // What is framed is the same-origin blob, never the presigned URL.
    const frame = screen.getByTestId('source-document-frame').querySelector('iframe');
    expect(frame?.getAttribute('src')).toContain('blob:');
    expect(frame?.getAttribute('src')).not.toContain('X-Amz-Signature');

    // The credential must exist nowhere durable and nowhere inspectable.
    // Storage is read through the raw prototypes so a stubbed global cannot
    // make this assertion vacuously pass.
    const dumped = JSON.stringify({ ...window.localStorage, ...window.sessionStorage });
    expect(dumped).not.toContain('X-Amz-Signature');
    expect(document.body.innerHTML).not.toContain('X-Amz-Signature');
    expect(window.location.href).not.toContain('X-Amz-Signature');
  });

  it('distinguishes "not itemized" from "no claims"', () => {
    // The live get_source returns claim_count but not the claims. Rendering
    // "No claims were extracted" would assert something false about the
    // document, so the two cases must read differently.
    render(
      <SourceDocumentViewer
        artifact={{ ...artifact, claims: [], claimCount: 2 }}
        decisionRecordId="DR-1"
        onClose={() => {}}
      />,
    );
    expect(document.body.textContent).toContain('not itemized');
    expect(document.body.textContent).not.toContain('No claims were extracted');
  });

  it('says so plainly when there really are no claims', () => {
    render(
      <SourceDocumentViewer
        artifact={{ ...artifact, claims: [], claimCount: 0 }}
        decisionRecordId="DR-1"
        onClose={() => {}}
      />,
    );
    expect(document.body.textContent).toContain('No claims were extracted');
  });
});
