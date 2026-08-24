import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { render, screen } from '@testing-library/react';
import { fixtureState } from '../view-models/fixture-adapter';
import { VouchApp } from '../app/VouchApp';

const css = readFileSync(join(import.meta.dirname, '..', 'app', 'global.css'), 'utf8');

describe('motion is guarded and never load-bearing', () => {
  it('prefers-reduced-motion neutralises animation and transition', () => {
    expect(css).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    expect(css).toMatch(/animation-duration:\s*\.001ms\s*!important/);
    expect(css).toMatch(/transition-duration:\s*\.001ms\s*!important/);
  });

  it('every disrupted-state fact is readable as text, with animation ignored', () => {
    render(<VouchApp initialState={fixtureState('today-disrupted')} />);
    // These are the facts the motion decorates; each is legible without it.
    for (const text of [
      'C-418',
      'MOVED UP',
      'C-417 remains blocked',
      '09:30 SLOT RECOVERED',
      'NOT FEASIBLE',
      '✕ REFUSED',
      'ELIGIBLE',
    ]) {
      expect(screen.getAllByText(text).length, text).toBeGreaterThan(0);
    }
    expect(screen.getAllByText('BLOCKED').length).toBeGreaterThan(0);
  });

  it('focus is visible on clickable rows', () => {
    expect(css).toMatch(/focus-visible/);
    expect(css).toMatch(/outline:\s*2px solid/);
  });
});
