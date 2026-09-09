/**
 * §8. The human-authority surface, against REAL backend captures.
 *
 * The three fixtures beside this file were produced by running the actual
 * pipeline — run 1 to MATERIAL_DISAGREEMENT, then AUTHORIZE, then KEEP_HELD on
 * a fresh world — and serialized verbatim. Hand-written shapes would prove the
 * adapter agrees with itself; these prove it agrees with the backend.
 *
 * The property that carries the most weight here is the DISAPPEARANCE: once a
 * human answers, the controls must be gone from the projection entirely, not
 * disabled and not hidden by a flag. A stale affordance on an authority
 * surface is how someone authorizes something twice.
 */

import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { project, qualityAuthorityFrom, qualityPanelFrom } from '../adapter';
import { classifyFailure } from '../useDecisionRun';
import { QualityAuthorityPanel } from '../Stages';
import type { QualityAuthorityDTO } from '../dto';
import run1 from './quality-run1-capture.json';
import run2 from './quality-run2-capture.json';
import quarantined from './quality-quarantine-capture.json';
import held from './quality-held-capture.json';

const capture = (c: { record: unknown; events: unknown }) => ({
  decisionRecordId: (c.record as { record_id: string }).record_id,
  lotId: 'LOT-1006',
  events: c.events as never[],
  record: c.record as Record<string, unknown>,
});

/**
 * The captured `quality_authority` segment, typed for the adapter.
 *
 * The fixtures are real serialized backend output, so TypeScript infers wide
 * literal types (`status: string` rather than the union). Going through
 * `unknown` states plainly that the JSON is being trusted as the DTO shape,
 * which is exactly the contract these tests exist to check.
 */
const authorityOf = (c: { record: unknown }): QualityAuthorityDTO =>
  (c.record as { quality_authority: unknown }).quality_authority as QualityAuthorityDTO;

describe('the open applicability question', () => {
  const panel = qualityPanelFrom(authorityOf(run1))!;

  it('is rendered from the backend question, not composed by the frontend', () => {
    expect(panel).not.toBeNull();
    expect(panel.questionId).toBe(
      authorityOf(run1).question!.question_id,
    );
    expect(panel.characteristic).toBe('viscosity');
    expect(panel.equivalenceId).toBe('EQV-1');
  });

  it('names the real objects, on the option that relies on each', () => {
    // The QUESTION asks which determination controls; the OPTIONS carry the
    // methods and the equivalence, because that is where they apply.
    expect(panel.question).toContain('viscosity');
    expect(panel.disputed).toContain('EQV-1');
    expect(panel.disputed).toContain('ASTM-D445');
    expect(panel.disputed).toContain('ASTM-D2196');
    expect(panel.disputed).toContain('25C');
  });

  it('never asks the human to decide the lot', () => {
    const forbidden = /approve|deny|override|reject/i;
    expect(panel.question).not.toMatch(forbidden);
    for (const o of panel.options) expect(o.actionLabel).not.toMatch(forbidden);
    expect(panel.holdActionLabel).toBe('Keep held');
    // The verb is "establish": the human names the controlling measurement,
    // and the engine still decides what it means.
    for (const o of panel.options) expect(o.actionLabel).toMatch(/^Establish /);
  });

  it('asks WHICH determination controls, not whether one is acceptable', () => {
    expect(panel.question).toMatch(/^Which viscosity determination/);
    expect(panel.question).toContain('controlling');
  });

  it('states the consequence of each path, because they differ', () => {
    const direct = panel.options.find((o) => !o.basis.startsWith('applicable via'))!;
    const alternate = panel.options.find((o) => o.basis.startsWith('applicable via'))!;

    expect(direct.passes).toBe(false);
    expect(direct.consequence).toMatch(/will FAIL/);
    expect(alternate.passes).toBe(true);
    expect(alternate.consequence).toMatch(/will PASS/);
  });

  it('states both positions as selections, with their real measurements', () => {
    expect(panel.options).toHaveLength(2);
    const measurements = panel.options.map((o) => o.measurement).join(' | ');
    expect(measurements).toContain('178 cP');
    expect(measurements).toContain('312 cP');
    expect(measurements).toContain('ASTM-D2196');
    expect(measurements).toContain('ASTM-D445');
    // The equivalence path is labelled as authorized, not as wrong.
    expect(panel.options.map((o) => o.basis).join(' ')).toContain('EQV-1');
  });
});

describe('the projection swaps controls for a record', () => {
  it('offers the panel and no record while the question is open', () => {
    const vm = project(capture(run1));

    expect(vm.qualityAuthorityPanel).not.toBeNull();
    expect(vm.qualityAuthority).toBeNull();
  });

  it('REMOVES the panel once a human has answered', () => {
    const vm = project(capture(run2));

    expect(vm.qualityAuthorityPanel).toBeNull();
    expect(vm.qualityAuthority).not.toBeNull();
  });

  it('removes the panel for KEEP_HELD too — no button survives either answer', () => {
    const vm = project(capture(held));

    expect(vm.qualityAuthorityPanel).toBeNull();
    expect(vm.qualityAuthority?.decision).toBe('KEEP_HELD');
  });
});

describe('the durable quality-authority record', () => {
  it('keeps who acted, under what authority, and against which snapshot', () => {
    const vm = qualityAuthorityFrom(authorityOf(run2))!;

    expect(vm.decision).toBe('ESTABLISH_EVIDENCE');
    expect(vm.headline).toBe('Controlling evidence established');
    expect(vm.accountableActor).toBe('QA-LEAD');
    expect(vm.authoritySource).toBe('Plant Quality Authority');
    expect(vm.timestamp).toBeTruthy();
    expect(vm.snapshotBinding).toBeTruthy();
    // What was established, readable without resolving a claim id.
    expect(vm.answer).toContain('312 cP');
    expect(vm.answer).toContain('ASTM-D445');
    expect(vm.answer).toContain('EQV-1');
  });

  it('reads as held, not as a defect, when Quality kept the lot back', () => {
    const vm = qualityAuthorityFrom(authorityOf(held))!;

    expect(vm.decision).toBe('KEEP_HELD');
    expect(vm.headline).toBe('Kept held');
    expect(vm.answer).not.toMatch(/reject|defect|fail/i);
  });
});

describe('run 2 is the same record', () => {
  it('carries the release, the run count and the recovered order', () => {
    const vm = project(capture(run2));

    expect((run2.record as { run_count: number }).run_count).toBe(2);
    expect((run2.record as { record_id: string }).record_id).toBe(
      (run1.record as { record_id: string }).record_id,
    );
    expect((run2.record as { disposition: string }).disposition).toBe('RELEASE');
    expect(vm.qualityAuthority).not.toBeNull();
  });

  it('shows the authority act and the resume in the activity rail', () => {
    const vm = project(capture(run2));
    const labels = vm.activity.map((a) => a.shortLabel);

    expect(labels).toContain('Controlling evidence established');
    expect(labels).toContain('Decision resumed');

    const authority = vm.activity.find(
      (a) => a.shortLabel === 'Controlling evidence established',
    )!;
    expect(authority.actorType).toBe('human');
    expect(authority.resultSummary).toContain('EQV-1');
    expect(authority.resultSummary).toContain('QA-LEAD');
  });

  it('files the authority act in run 1, where it was made', () => {
    const vm = project(capture(run2));
    const authority = vm.activity.find(
      (a) => a.shortLabel === 'Controlling evidence established',
    )!;

    // The human answered the question run 1 raised; the resume is what opens
    // run 2. Filing the act under run 2 would date it after its own effect.
    expect(authority.runNumber).toBe(1);
  });
});

describe('the panel component', () => {
  const panel = qualityPanelFrom(authorityOf(run1))!;

  it('offers one action PER PATH, naming which evidence it establishes', async () => {
    const onEstablish = vi.fn();
    const onHold = vi.fn();
    render(
      <QualityAuthorityPanel vm={panel} onEstablish={onEstablish} onHold={onHold} />,
    );

    // Two establish buttons, one per disputed measurement. A single button
    // would silently pick a side, and the two paths reach opposite
    // dispositions — so it would be deciding the lot for the operator.
    await userEvent.click(screen.getByTestId('quality-establish-investigator'));
    await userEvent.click(screen.getByTestId('quality-establish-verifier'));

    const chosen = onEstablish.mock.calls.map((c) => c[0]);
    expect(new Set(chosen).size).toBe(2);
    for (const claimId of chosen) {
      expect(panel.options.map((o) => o.claimId)).toContain(claimId);
    }

    await userEvent.click(screen.getByTestId('quality-keep-held'));
    expect(onHold).toHaveBeenCalledTimes(1);
  });

  it('shows both measurements and both consequences', () => {
    render(<QualityAuthorityPanel vm={panel} />);

    const rendered = [
      screen.getByTestId('quality-option-investigator').textContent,
      screen.getByTestId('quality-option-verifier').textContent,
    ].join(' | ');
    expect(rendered).toContain('178 cP');
    expect(rendered).toContain('312 cP');
    expect(rendered).toMatch(/will FAIL/);
    expect(rendered).toMatch(/will PASS/);
    expect(screen.getByTestId('quality-authority-question').textContent).toMatch(
      /Which viscosity determination/,
    );
  });

  it('does not accept a second click while one is in flight', async () => {
    const onEstablish = vi.fn();
    render(<QualityAuthorityPanel vm={panel} onEstablish={onEstablish} submitting />);

    await userEvent.click(screen.getByTestId('quality-establish-verifier'));
    expect(onEstablish).not.toHaveBeenCalled();
  });
});

describe('the choice is load-bearing', () => {
  it('establishing the direct path quarantines instead of releasing', () => {
    const vm = qualityAuthorityFrom(authorityOf(quarantined))!;

    expect((quarantined.record as { disposition: string }).disposition).toBe('QUARANTINE');
    expect(vm.decision).toBe('ESTABLISH_EVIDENCE');
    expect(vm.answer).toContain('178 cP');
    expect(vm.answer).toContain('ASTM-D2196');
    expect(vm.answer).toContain('direct method');
  });

  it('renders the disagreement as a quality decision, never a crash', () => {
    const failure = classifyFailure({ failure_category: 'MATERIAL_DISAGREEMENT' });

    // The default branch used to catch this and render "Vouch could not
    // complete this decision · A technical failure occurred", which is untrue
    // and also blanked the disposition surface explaining the hold.
    expect(failure.kind).toBe('DOMAIN_ABSTENTION');
    expect(failure.headline).toBe('Quality decision required');
    expect(failure.suppressesDisposition).toBe(false);
    expect(failure.detail).toMatch(/different controlling evidence/);
  });
});

describe('the agent cards show what actually differs', () => {
  it('states each agent SELECTION rather than shared sufficiency', () => {
    const vm = project(capture(run1));
    const agents = vm.spine.find((n) => n.key === 'agents')!;

    // Both lanes previously read "Evidence covers the requirement" — the one
    // field the two agents agree on — under a banner saying they disagreed.
    expect(agents.investigatorLane).not.toBe(agents.verifierLane);
    const lanes = `${agents.investigatorLane} | ${agents.verifierLane}`;
    expect(lanes).toContain('178 cP');
    expect(lanes).toContain('312 cP');
    expect(lanes).toContain('direct method');
    expect(lanes).toContain('via EQV-1');
  });

  it('does not assume which role took which path', () => {
    // Live Nova has been observed reversing these, so the lane must report
    // whatever its own agent selected rather than a frozen assignment.
    const vm = project(capture(run1));
    const agents = vm.spine.find((n) => n.key === 'agents')!;
    const lanes = [agents.investigatorLane, agents.verifierLane];

    expect(lanes.filter((l) => l?.includes('direct method'))).toHaveLength(1);
    expect(lanes.filter((l) => l?.includes('via EQV-1'))).toHaveLength(1);
  });
});
