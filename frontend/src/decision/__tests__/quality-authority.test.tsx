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
  lotId: 'LOT-1003',
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

  it('names the real objects on the option that relies on each', () => {
    // The QUESTION asks which result controls and the SUBHEAD says why a human
    // is here. The methods, the routes and the equivalence live on the option
    // cards, because that is where each one applies.
    expect(panel.question).toContain('viscosity');
    expect(panel.disputed).toContain('Investigator');
    expect(panel.disputed).toContain('Independent Verifier');

    const cards = panel.options
      .map((o) => `${o.value} ${o.methodLine} ${o.routeLabel}`)
      .join(' | ');
    expect(cards).toContain('ASTM-D2196');
    expect(cards).toContain('ASTM-D445');
    expect(cards).toContain('25C');
    expect(cards).toContain('VIA EQV-1');
    expect(cards).toContain('DIRECT METHOD');
  });

  it('uses the canonical role name for the second read', () => {
    // "Verifier" alone reads as a generic checker. The architecture's claim is
    // that the second read is INDEPENDENT, and the label is where an operator
    // learns it.
    const labels = panel.options.map((o) => o.agentLabel);
    expect(labels).toContain('Investigator');
    expect(labels).toContain('Independent Verifier');
    for (const l of labels) expect(l).not.toMatch(/auditor|reviewer|checker/i);
  });

  it('never asks the human to decide the lot', () => {
    const forbidden = /approve|deny|override|reject/i;
    expect(panel.question).not.toMatch(forbidden);
    for (const o of panel.options) expect(o.actionLabel).not.toMatch(forbidden);
    expect(panel.holdActionLabel).toBe('Keep held');
    // The verb is "establish": the human names the controlling measurement,
    // and the engine still decides what it means.
    // The SAME verb on both cards: the choice is between the measurements,
    // not between two differently-worded buttons.
    for (const o of panel.options) {
      expect(o.actionLabel).toBe('Establish this evidence');
    }
  });

  it('asks WHICH result controls, not whether one is acceptable', () => {
    expect(panel.question).toBe(
      'Which viscosity result should control this decision?',
    );
  });

  it('states the consequence of each path, because they differ', () => {
    const direct = panel.options.find((o) => o.routeLabel === 'DIRECT METHOD')!;
    const alternate = panel.options.find((o) => o.routeLabel.startsWith('VIA '))!;

    // The consequence NAMES the disposition. "FAIL" is the arithmetic; the
    // operator is choosing between two outcomes and the card says which.
    expect(direct.passes).toBe(false);
    expect(direct.consequence).toContain('QUARANTINE');
    expect(alternate.passes).toBe(true);
    expect(alternate.consequence).toContain('RELEASE');
    for (const o of panel.options) {
      expect(o.consequence).not.toMatch(/cannot be computed/);
    }
  });

  it('states both positions as selections, with their real measurements', () => {
    expect(panel.options).toHaveLength(2);
    const measurements = panel.options
      .map((o) => `${o.value} ${o.methodLine}`)
      .join(' | ');
    expect(measurements).toContain('178 cP');
    expect(measurements).toContain('312 cP');
    expect(measurements).toContain('ASTM-D2196');
    expect(measurements).toContain('ASTM-D445');
    // The equivalence path is labelled as authorized, not as wrong.
    expect(panel.options.map((o) => o.routeLabel).join(' ')).toContain('EQV-1');
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
    expect(rendered).toContain('QUARANTINE');
    expect(rendered).toContain('RELEASE');
    expect(rendered).toContain('DIRECT METHOD');
    expect(rendered).toContain('VIA EQV-1');
    expect(rendered).toContain('INDEPENDENT VERIFIER');
    expect(screen.getByTestId('quality-authority-question').textContent).toMatch(
      /Which viscosity result/,
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

describe('run 2 reads as a continuation, not a fresh decision', () => {
  it('marks the resumed run and says what caused it', () => {
    const vm = project(capture(run2));

    expect(vm.runBanner).toBe('Run 2 · resumed after Quality authority');
  });

  it('shows no run banner on a first run', () => {
    // A decision that has only ever run once needs no run label; adding one
    // would imply a history it does not have.
    expect(project(capture(run1)).runBanner).toBeNull();
  });

  it('keeps run 1 in the activity rail after run 2 begins', () => {
    // The rail is the proof of the whole story: disagreement, human authority,
    // resume, deterministic outcome, in one continuous history. Clearing it on
    // resume would destroy exactly the evidence it exists to carry.
    const labels = project(capture(run2)).activity.map((a) => a.shortLabel);

    expect(labels).toContain('Applicability question raised');
    expect(labels).toContain('Quality decision required');
    expect(labels).toContain('Controlling evidence established');
    expect(labels).toContain('Decision resumed');
    expect(labels).toContain('Disposition computed');
  });

  it('orders the rail so the human act sits between the two runs', () => {
    // Newest first, so reading upward is chronological.
    const rail = project(capture(run2)).activity;
    const at = (label: string) => rail.findIndex((a) => a.shortLabel === label);

    expect(at('Quality decision required')).toBeGreaterThan(
      at('Controlling evidence established'),
    );
    expect(at('Controlling evidence established')).toBeGreaterThan(
      at('Decision resumed'),
    );
  });

  it('names what Quality established in the released outcome', () => {
    const vm = project(capture(run2));

    expect(vm.outcome.kind).toBe('released');
    expect(vm.outcome.context).toContain('312 cP');
    expect(vm.outcome.context).toContain('ASTM-D445');
    expect(vm.outcome.context).toContain('EQV-1');
    expect(vm.outcome.context).toMatch(/^Quality established/);
  });
});

describe('the disagreement never reads as a service error', () => {
  it('explains the hold in words, not in an event code', () => {
    const vm = project(capture(run1));

    expect(vm.outcome.kind).toBe('quality_decision_required');
    expect(vm.outcome.headline).toBe('Quality decision required');
    expect(vm.outcome.lines.join(' ')).toContain('different controlling evidence');
    // The raw code must not surface as prose.
    expect(vm.outcome.lines.join(' ')).not.toBe('DISAGREEMENT');
    expect(vm.outcome.lines.join(' ')).not.toMatch(/technical failure/i);
  });

  it('keeps the disposition surface visible while a human is owed an answer', () => {
    // TECHNICAL_FAILURE suppresses the disposition panel. A disagreement must
    // not, because that panel is what explains why the lot is being held.
    expect(project(capture(run1)).failure?.suppressesDisposition).not.toBe(true);
  });
});
