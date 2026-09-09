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
import { QualityAuthorityPanel } from '../Stages';
import type { QualityAuthorityDTO } from '../dto';
import run1 from './quality-run1-capture.json';
import run2 from './quality-run2-capture.json';
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

  it('asks the narrow applicability question and names the real objects', () => {
    expect(panel.question).toContain('EQV-1');
    expect(panel.question).toContain('ASTM-D445');
    expect(panel.question).toContain('ASTM-D2196');
    expect(panel.question).toContain('25C');
    expect(panel.question).toContain('viscosity');
    expect(panel.question.startsWith('Does Quality authorize')).toBe(true);
  });

  it('never asks the human to decide the lot', () => {
    const forbidden = /approve|deny|release|quarantine|override|reject/i;
    expect(panel.question).not.toMatch(forbidden);
    expect(panel.primaryActionLabel).not.toMatch(forbidden);
    expect(panel.secondaryActionLabel).not.toMatch(forbidden);
    expect(panel.primaryActionLabel).toBe('Authorize applicability');
    expect(panel.secondaryActionLabel).toBe('Keep held');
  });

  it('states both positions as selections, with their real measurements', () => {
    expect(panel.options).toHaveLength(2);
    expect(panel.investigatorPosition).toContain('285 cP');
    expect(panel.investigatorPosition).toContain('ASTM-D2196');
    expect(panel.verifierPosition).toContain('312 cP');
    expect(panel.verifierPosition).toContain('ASTM-D445');
    // The equivalence path is labelled as authorized, not as wrong.
    expect(panel.verifierPosition).toContain('EQV-1');
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

    expect(vm.decision).toBe('AUTHORIZE_APPLICABILITY');
    expect(vm.headline).toBe('Applicability authorized');
    expect(vm.accountableActor).toBe('QA-LEAD');
    expect(vm.authoritySource).toBe('Plant Quality Authority');
    expect(vm.timestamp).toBeTruthy();
    expect(vm.snapshotBinding).toBeTruthy();
    // The question it answered stays legible after the fact.
    expect(vm.question).toContain('EQV-1');
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

    expect(labels).toContain('Applicability authorized');
    expect(labels).toContain('Decision resumed');

    const authority = vm.activity.find((a) => a.shortLabel === 'Applicability authorized')!;
    expect(authority.actorType).toBe('human');
    expect(authority.resultSummary).toContain('EQV-1');
    expect(authority.resultSummary).toContain('QA-LEAD');
  });

  it('files the authority act in run 1, where it was made', () => {
    const vm = project(capture(run2));
    const authority = vm.activity.find((a) => a.shortLabel === 'Applicability authorized')!;

    // The human answered the question run 1 raised; the resume is what opens
    // run 2. Filing the act under run 2 would date it after its own effect.
    expect(authority.runNumber).toBe(1);
  });
});

describe('the panel component', () => {
  const panel = qualityPanelFrom(authorityOf(run1))!;

  it('offers exactly two actions and reports which was chosen', async () => {
    const onDecide = vi.fn();
    render(<QualityAuthorityPanel vm={panel} onDecide={onDecide} />);

    await userEvent.click(screen.getByTestId('quality-authorize'));
    expect(onDecide).toHaveBeenCalledWith('AUTHORIZE_APPLICABILITY');

    await userEvent.click(screen.getByTestId('quality-keep-held'));
    expect(onDecide).toHaveBeenCalledWith('KEEP_HELD');
    expect(onDecide).toHaveBeenCalledTimes(2);
  });

  it('shows both agent positions', () => {
    render(<QualityAuthorityPanel vm={panel} />);

    expect(screen.getByTestId('quality-option-investigator').textContent).toContain('285 cP');
    expect(screen.getByTestId('quality-option-verifier').textContent).toContain('312 cP');
    expect(screen.getByTestId('quality-authority-question').textContent).toMatch(
      /Does Quality authorize/,
    );
  });

  it('does not accept a second click while one is in flight', async () => {
    const onDecide = vi.fn();
    render(<QualityAuthorityPanel vm={panel} onDecide={onDecide} submitting />);

    await userEvent.click(screen.getByTestId('quality-authorize'));
    expect(onDecide).not.toHaveBeenCalled();
  });
});
