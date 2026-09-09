/**
 * The human-resolvable identity case, projected and rendered.
 *
 * Both captures are REAL runtime payloads (`app/Gatehouse/main.py`, local
 * mode), not hand-written fixtures: the whole risk in this case is the
 * frontend describing a backend state it does not actually produce.
 *
 * What is being defended: this screen must never read as an OCR failure. The
 * document parsed, the measurements extracted, security passed — and Vouch
 * still refused, because it could not prove whose lot the results describe.
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import run1 from './binding-run1-capture.json';
import run2 from './binding-run2-capture.json';
import { DecisionWorkspace } from '../DecisionWorkspace';
import { project } from '../adapter';
import { classifyFailure } from '../useDecisionRun';
import type { EvaluateDTO, LifecycleEventDTO } from '../dto';

/**
 * The real client accumulates events across a resumption by cursor — it never
 * discards what it has already seen — so run 2 is projected from run 1's
 * events PLUS its own. Projecting run 2 alone would be testing a rail the
 * product never renders, and would prove the opposite of the continuity this
 * case is about.
 */
const vmOf = (capture: unknown, prior: unknown[] = []) => {
  const dto = capture as EvaluateDTO;
  const earlier = prior.flatMap(
    (p) => ((p as EvaluateDTO).events ?? []) as LifecycleEventDTO[],
  );
  return project({
    decisionRecordId: dto.decision_record_id,
    lotId: 'LOT-1003',
    material: 'MAT-ALLOY-7',
    receiptMeta: 'SUP-NORTH · site SITE-N1 · 450 kg',
    events: [...earlier, ...((dto.events ?? []) as LifecycleEventDTO[])],
    result: dto,
    record: dto.decision_record as Record<string, unknown>,
    running: false,
  });
};

const show = (capture: unknown, prior: unknown[] = []) =>
  render(<DecisionWorkspace vm={vmOf(capture, prior)} />);

describe('run 1 asks an identity question, not an extraction one', () => {
  it('projects the identity panel and not the applicability panel', () => {
    const vm = vmOf(run1);
    expect(vm.identityBindingPanel).not.toBeNull();
    expect(vm.qualityAuthorityPanel).toBeNull();
  });

  it('asks the exact question, naming both identifiers', () => {
    const vm = vmOf(run1);
    expect(vm.identityBindingPanel!.question).toBe(
      'Does supplier batch WP-26-0317-B correspond to internal LOT-1003 for this evidence?',
    );
  });

  it('states parse, extraction and security as things that SUCCEEDED', () => {
    const facts = vmOf(run1).identityBindingPanel!.verified;
    expect(facts.map((f) => f.label)).toEqual(['Document', 'Measurements', 'Security']);
    expect(facts[0].value).toMatch(/parsed successfully/i);
    expect(facts[1].value).toMatch(/2 extracted/);
    expect(facts[2].value).toMatch(/passed/i);
  });

  it('shows the unresolved pair side by side and says the mapping is missing', () => {
    show(run1);
    expect(screen.getByTestId('identity-side-supplier').textContent).toContain(
      'WP-26-0317-B',
    );
    expect(screen.getByTestId('identity-side-vouch').textContent).toContain('LOT-1003');
    expect(screen.getByTestId('identity-mapping-status').textContent).toMatch(
      /MAPPING NOT ESTABLISHED/,
    );
  });

  it('offers identity actions, never a disposition verb', () => {
    show(run1);
    const confirm = screen.getByTestId('identity-confirm-binding').textContent ?? '';
    const keep = screen.getByTestId('identity-keep-unbound').textContent ?? '';
    expect(confirm).toBe('Confirm binding');
    expect(keep).toBe('Keep unbound');
    for (const word of ['Approve', 'Release', 'Accept evidence']) {
      expect(confirm + keep).not.toContain(word);
    }
  });

  it('classifies the failure as identity confirmation, not abstention', () => {
    const failure = classifyFailure(run1 as Record<string, unknown>);
    expect(failure.kind).toBe('IDENTITY_CONFIRMATION_REQUIRED');
    expect(failure.headline).toBe('Identity confirmation required');
    // The abstention copy would be a lie here: the evidence DOES establish an
    // answer, and only its owner is unknown.
    expect(failure.detail).not.toMatch(/could not establish an answer/i);
    expect(failure.suppressesDisposition).toBe(false);
  });

  it('reached no disposition and shows no completed authority stage', () => {
    const vm = vmOf(run1);
    // The stage projects, but empty: no disposition was computed, so there is
    // nothing for it to report.
    expect(vm.disposition?.disposition ?? '').toBe('');
    expect(vm.qualityAuthority).toBeNull();
  });

  it('does not describe the halt as a successful binding', () => {
    const rail = vmOf(run1).activity.map((e) => e.shortLabel);
    expect(rail).toContain('Identity not established');
    expect(rail).not.toContain('Identity bound');
  });

  it('names the halt in the rail as an identity question', () => {
    const raised = vmOf(run1).activity.find(
      (e) => e.shortLabel === 'Identity confirmation required',
    );
    expect(raised).toBeDefined();
    expect(raised!.resultSummary).toContain('WP-26-0317-B');
    expect(raised!.resultSummary).toContain('LOT-1003');
  });
});

describe('run 2 is the same record continuing', () => {
  it('replaces the controls with a completed Identity authority stage', () => {
    const vm = vmOf(run2, [run1]);
    expect(vm.identityBindingPanel).toBeNull();
    expect(vm.qualityAuthority).not.toBeNull();
    expect(vm.qualityAuthority!.headline).toBe('Identity authority');
    expect(vm.qualityAuthority!.answer).toBe(
      'Supplier batch WP-26-0317-B confirmed as LOT-1003',
    );
    expect(vm.qualityAuthority!.stageLabel).toBe('Identity authority');
  });

  it('attributes the authority to an accountable actor', () => {
    show(run2, [run1]);
    const stage = screen.getByTestId('quality-authority-stage').textContent ?? '';
    expect(stage).toContain('QA-LEAD');
    expect(stage).toContain('Plant Quality Authority');
    // Bound to the ARTIFACT, because that is what the human was shown.
    expect(stage).toContain('Source artifact');
  });

  it('marks the run as resumed after identity confirmation', () => {
    expect(vmOf(run2, [run1]).runBanner).toBe('Run 2 · resumed after identity confirmation');
  });

  it('reaches RELEASE deterministically', () => {
    const vm = vmOf(run2, [run1]);
    expect(vm.disposition?.disposition).toBe('RELEASE');
    show(run2, [run1]);
    expect(screen.getAllByText(/RELEASE/i).length).toBeGreaterThan(0);
  });

  it('keeps run 1 in the rail rather than resetting it', () => {
    const rail = vmOf(run2, [run1]).activity.map((e) => e.shortLabel);
    // The pre-authority history is still inspectable...
    expect(rail).toContain('Identity confirmation required');
    // ...followed by the human answer, the resumption, and the agents.
    expect(rail).toContain('Batch-to-lot mapping confirmed');
    expect(rail).toContain('Evidence binding resumed');
    expect(rail).toContain('Identity established');
    expect(rail).toContain('Disposition computed');
  });

  it('orders the rail: question, human answer, resumption, then agents', () => {
    // The rail renders newest-first, so chronology reads backwards down the
    // array. Asserted on chronological position so the expectation says what
    // it means rather than mirroring a layout decision.
    const rail = vmOf(run2, [run1]).activity.map((e) => e.shortLabel);
    const when = (label: string) => rail.length - 1 - rail.indexOf(label);
    expect(when('Identity confirmation required')).toBeLessThan(
      when('Batch-to-lot mapping confirmed'),
    );
    expect(when('Batch-to-lot mapping confirmed')).toBeLessThan(
      when('Evidence binding resumed'),
    );
    expect(when('Evidence binding resumed')).toBeLessThan(when('Investigator started'));
  });

  it('files the human answer and everything after it as run 2', () => {
    const rail = vmOf(run2, [run1]).activity;
    const runOf = (label: string) =>
      rail.find((e) => e.shortLabel === label)?.runNumber;
    // Run 1 ends at the question it could not answer.
    expect(runOf('Identity confirmation required')).toBe(1);
    // The confirmation is what OPENS run 2, not something run 1 did.
    expect(runOf('Batch-to-lot mapping confirmed')).toBe(2);
    expect(runOf('Identity established')).toBe(2);
    expect(runOf('Investigator started')).toBe(2);
  });

  it('no longer reports an open quality decision', () => {
    expect(vmOf(run2, [run1]).outcome.kind).not.toBe('quality_decision_required');
  });
});
