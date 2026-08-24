import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { INITIAL_STATE, fixtureState, reduce } from '../view-models/fixture-adapter';
import { VouchApp } from '../app/VouchApp';

describe('state changes only via the command gateway', () => {
  it('NAVIGATE moves screens and closes any open drawer', () => {
    const s = reduce(
      { ...INITIAL_STATE, openLotId: 'L-2262' },
      {
        type: 'NAVIGATE',
        screen: 'today',
      },
    );
    expect(s.screen).toBe('today');
    expect(s.openLotId).toBeNull();
  });

  it('PROVIDE_EVIDENCE is idempotent — replay cannot double-release', () => {
    const cmd = { type: 'PROVIDE_EVIDENCE', lotId: 'L-2262', authority: 'D. Karlsson' } as const;
    const once = reduce(INITIAL_STATE, cmd);
    const twice = reduce(once, cmd);
    expect(once.resolvedLotIds).toEqual(['L-2262']);
    expect(twice.resolvedLotIds).toEqual(['L-2262']);
  });

  it('a records row navigates to its own decision record', () => {
    const s = reduce(
      { ...INITIAL_STATE, screen: 'records' },
      {
        type: 'OPEN_LOT',
        lotId: 'L-2231',
      },
    );
    expect(s.screen).toBe('record');
  });

  it('clicking a needs-you row opens its drawer', async () => {
    const user = userEvent.setup();
    render(<VouchApp initialState={fixtureState('incoming-normal')} />);
    expect(screen.queryByRole('dialog')).toBeNull();
    await user.click(screen.getByText('L-2251'));
    expect(screen.getByRole('dialog', { name: /L-2251/ })).toBeDefined();
  });

  it('navigating between screens works from the nav', async () => {
    const user = userEvent.setup();
    render(<VouchApp initialState={fixtureState('incoming-normal')} />);
    await user.click(screen.getByRole('button', { name: /Today/ }));
    expect(screen.getByText('Production plan · Tue 23 Aug')).toBeDefined();
    await user.click(screen.getByRole('button', { name: /Suppliers/ }));
    expect(screen.getByText('Supplier standing')).toBeDefined();
  });
});
