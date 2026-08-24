import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { FixtureId } from '../view-models/types';
import { fixtureState } from '../view-models/fixture-adapter';
import { VouchApp } from '../app/VouchApp';

const ALL: FixtureId[] = [
  'incoming-normal',
  'incoming-incident',
  'today-normal',
  'today-disrupted',
  'decision-record',
  'quality-decision',
  'resolved',
  'suppliers',
  'records',
];

describe('every locked state renders', () => {
  it.each(ALL)('%s renders without error', (id) => {
    render(<VouchApp initialState={fixtureState(id)} />);
    expect(screen.getByText('Vouch')).toBeDefined();
  });

  it('incoming shows the status rail and needs-you list', () => {
    render(<VouchApp initialState={fixtureState('incoming-normal')} />);
    expect(screen.getByText('187')).toBeDefined();
    expect(screen.getByText('need a Quality decision')).toBeDefined();
    expect(screen.getByRole('heading', { name: 'Needs you' })).toBeDefined();
    expect(screen.getByText('L-2262')).toBeDefined();
  });

  it('incident renders one grouped row, never 18 cards', () => {
    render(<VouchApp initialState={fixtureState('incoming-incident')} />);
    expect(screen.getByText('SUPPLIER INCIDENT')).toBeDefined();
    expect(screen.getAllByText('ONE DECISION · 18 LOTS')).toHaveLength(1);
  });

  it('today disrupted expands Line 2 and shows the recovery trio', () => {
    render(<VouchApp initialState={fixtureState('today-disrupted')} />);
    expect(screen.getByText('RECOVERY EVALUATED BEFORE THE PLAN MOVED')).toBeDefined();
    expect(screen.getByText('NOT FEASIBLE')).toBeDefined();
    expect(screen.getByText('✕ REFUSED')).toBeDefined();
    expect(screen.getByText('ELIGIBLE')).toBeDefined();
  });

  it('decision record shows the load-bearing governing basis, not bare arithmetic', () => {
    render(<VouchApp initialState={fixtureState('decision-record')} />);
    expect(screen.getByText('Vouch resolved which requirement governs')).toBeDefined();
    expect(screen.getByText('Plant Spec S-88 · Rev 4 · Tensile ≥ 480 MPa')).toBeDefined();
    expect(screen.getByText('Independent verification · VERIFIED')).toBeDefined();
  });

  it('suppliers is an operational table with no index or score', () => {
    render(<VouchApp initialState={fixtureState('suppliers')} />);
    expect(screen.getByText('Supplier standing')).toBeDefined();
    expect(screen.getByText('5 of 214')).toBeDefined();
    expect(screen.queryByText(/score/i)).toBeNull();
    expect(screen.queryByText(/index/i)).toBeNull();
  });

  it('records is search-first at 3,481-record scale', () => {
    render(<VouchApp initialState={fixtureState('records')} />);
    expect(screen.getByText('3,481 records')).toBeDefined();
    expect(screen.getByText('1–10 of 3,481')).toBeDefined();
    expect(screen.getByLabelText('Search by lot, material, supplier, order or spec')).toBeDefined();
  });
});
