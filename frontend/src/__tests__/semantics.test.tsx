import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { fixtureState, selectView } from '../view-models/fixture-adapter';
import { VouchApp } from '../app/VouchApp';

describe('semantic state never relies on color alone', () => {
  it('a BLOCKED order carries the textual label BLOCKED', () => {
    render(<VouchApp initialState={fixtureState('today-disrupted')} />);
    expect(screen.getAllByText('BLOCKED').length).toBeGreaterThan(0);
  });

  it('AT_RISK carries the textual label AT RISK', () => {
    render(<VouchApp initialState={fixtureState('today-normal')} />);
    expect(screen.getAllByText('AT RISK').length).toBeGreaterThan(0);
  });

  it('QUARANTINED and REJECTED/REFUSED are distinct labels', () => {
    render(<VouchApp initialState={fixtureState('records')} />);
    expect(screen.getAllByText('⊘ QUARANTINED').length).toBeGreaterThan(0);
    expect(screen.getByText('✕ REFUSED')).toBeDefined();
  });

  it('C-417 remains BLOCKED after C-418 resequences — never implied to have run', () => {
    render(<VouchApp initialState={fixtureState('today-disrupted')} />);
    expect(screen.getByText('C-418')).toBeDefined();
    expect(screen.getByText('MOVED UP')).toBeDefined();
    expect(screen.getByText('C-417 remains blocked')).toBeDefined();

    const { today } = selectView(fixtureState('today-disrupted'));
    const c417 = today!.disruption!.sequence.find((s) => s.id === 'C-417');
    expect(c417!.readiness).toBe('BLOCKED');
    // No copy anywhere claims the blocked order ran or that nothing was lost.
    expect(screen.queryByText(/C-417 ran/i)).toBeNull();
    expect(screen.queryByText(/no run lost/i)).toBeNull();
  });

  it('unsafe substitute is REFUSED, not silently substituted', () => {
    const { today } = selectView(fixtureState('today-disrupted'));
    const sub = today!.disruption!.recovery.find((r) => r.kind === 'SUBSTITUTE');
    expect(sub!.verdict).toBe('✕ REFUSED');
    expect(sub!.tone).toBe('refused');
  });
});

describe('the abstain state does not imply released material', () => {
  it('a Quality decision drawer shows the unresolved question and no release', () => {
    render(<VouchApp initialState={fixtureState('quality-decision')} />);
    const drawer = screen.getByRole('dialog');
    expect(within(drawer).getByText('UNRESOLVED')).toBeDefined();
    expect(
      within(drawer).getByText(/Method M-12 as equivalent to required Method M-17/),
    ).toBeDefined();
    expect(within(drawer).getByText('THE GAP')).toBeDefined();
    expect(within(drawer).queryByText('RELEASED')).toBeNull();
    // Absence of evidence is an escalation, never a defect finding.
    expect(within(drawer).queryByText(/defect/i)).toBeNull();
  });

  it('the human provides evidence; the drawer never offers to release the lot', () => {
    render(<VouchApp initialState={fixtureState('quality-decision')} />);
    const drawer = screen.getByRole('dialog');
    expect(within(drawer).getByText('Provide approved equivalence')).toBeDefined();
    expect(within(drawer).queryByRole('button', { name: /^Release/ })).toBeNull();
  });
});

describe('evidence resolves the same record in place', () => {
  it('providing evidence turns the header RELEASED and shows resume history', async () => {
    const user = userEvent.setup();
    render(<VouchApp initialState={fixtureState('quality-decision')} />);
    const drawer = screen.getByRole('dialog');
    await user.click(within(drawer).getByText('Provide approved equivalence'));

    expect(within(drawer).getAllByText('RELEASED').length).toBeGreaterThan(0);
    expect(within(drawer).getByText('Evidence added')).toBeDefined();
    expect(within(drawer).getByText('Evaluation resumed')).toBeDefined();
    expect(within(drawer).getByText('Independent verification · VERIFIED')).toBeDefined();
    expect(within(drawer).getByText('READINESS UPDATED IN PLACE')).toBeDefined();
    expect(within(drawer).getByText(/AT RISK → READY/)).toBeDefined();
    // Same record updates — no new case is created.
    expect(within(drawer).getByText('L-2262')).toBeDefined();
    expect(within(drawer).queryByText(/case/i)).toBeNull();
  });

  it('the drawer is keyboard-dismissable', async () => {
    const user = userEvent.setup();
    render(<VouchApp initialState={fixtureState('quality-decision')} />);
    expect(screen.getByRole('dialog')).toBeDefined();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});

describe('the three state axes stay independent', () => {
  it('the view model keeps inventory, disposition and readiness separate', () => {
    const vm = selectView(fixtureState('today-disrupted'));
    // Readiness lives on orders; disposition lives on decision rows. Neither is derived.
    expect(vm.today!.disruption!.sequence.every((s) => 'readiness' in s)).toBe(true);
    expect(vm.incoming!.needsYou.every((r) => 'disposition' in r && 'tone' in r)).toBe(true);
  });
});
