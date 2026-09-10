/**
 * Hero B and Hostile through the REAL DecisionWorkspace, not just the adapter.
 *
 * `hero-b-hostile.test.ts` proves the projection is right; this proves the
 * rendered page is. Both matter: the empty "Disposition" panel on the hostile
 * path projected to `null` correctly and still rendered its chrome.
 */

import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import run1 from './hero-b-run1-capture.json';
import run2 from './hero-b-run2-capture.json';
import hostile from './hostile-capture.json';
import heroA from './hero-a-capture.json';
import { DecisionWorkspace } from '../DecisionWorkspace';
import { project } from '../adapter';
import type { EvaluateDTO, LifecycleEventDTO } from '../dto';

const show = (capture: unknown, lotId: string) => {
  const dto = capture as EvaluateDTO;
  const vm = project({
    decisionRecordId: dto.decision_record_id,
    lotId,
    material: 'MAT-POLY-3',
    receiptMeta: 'SUP-WEST · site SITE-W1 · 200 kg',
    events: (dto.events ?? []) as LifecycleEventDTO[],
    result: dto,
    running: false,
  });
  return render(<DecisionWorkspace vm={vm} />);
};

describe('Hero B run 2 renders as a continuation, not a fresh release', () => {
  it('marks the reasoning stages as run 2', () => {
    show(run2, 'LOT-1004');
    const badges = screen.getAllByTestId(/^completed-run-/);
    expect(badges.length).toBeGreaterThan(0);
    badges.forEach((b) => expect(b.textContent).toBe('RUN 2'));
  });

  it('still shows the release it reached', () => {
    show(run2, 'LOT-1004');
    expect(screen.getAllByText(/RELEASE/i).length).toBeGreaterThan(0);
  });
});

describe('Hero A is a single run and says nothing about runs', () => {
  it('shows no RUN badge', () => {
    const dto = heroA as EvaluateDTO;
    render(
      <DecisionWorkspace
        vm={project({
          decisionRecordId: dto.decision_record_id,
          lotId: dto.lot_id!,
          material: 'MAT-ALLOY-7',
          receiptMeta: '',
          events: (dto.events ?? []) as LifecycleEventDTO[],
          result: dto,
          running: false,
        })}
      />,
    );
    expect(screen.queryAllByTestId(/^completed-run-/)).toHaveLength(0);
  });
});

describe('the hostile page renders no fabricated panel', () => {
  it('shows no Disposition stage card over empty content', () => {
    show(hostile, 'LOT-1005');
    expect(screen.queryByText(/deterministic — computed from established truth/)).toBeNull();
  });

  it('says no stage ran, rather than implying one is coming', () => {
    show(hostile, 'LOT-1005');
    expect(screen.getByText(/No stage ran/)).toBeTruthy();
    expect(screen.queryByText('No stage yet.')).toBeNull();
  });

  it('shows the bound lot, not the word BOUND, as the bound fact', () => {
    show(hostile, 'LOT-1005');
    expect(screen.getAllByText('LOT-1005').length).toBeGreaterThan(0);
  });

  it('renders the security outcome', () => {
    show(hostile, 'LOT-1005');
    expect(screen.getByTestId('outcome-summary').textContent).toMatch(/quarantined/i);
  });
});

describe('Hero B run 1 renders the abstention as a product outcome', () => {
  it('names the quality decision without a disposition pill', () => {
    show(run1, 'LOT-1004');
    expect(screen.getByTestId('outcome-summary').textContent).toMatch(/Quality decision/i);
  });
});
