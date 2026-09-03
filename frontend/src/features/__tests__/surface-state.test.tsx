/**
 * Surface loading states.
 *
 * These exist because of a real defect found only in a browser: three of the
 * four surfaces sat on "Loading…" forever against a live backend while every
 * unit test passed. The cause was the interaction between React StrictMode's
 * mount/cleanup/remount and a request the browser served once, and the fix
 * (sharing the in-flight promise, keyed per hook INSTANCE rather than per
 * dependency list) is subtle enough to deserve a guard.
 *
 * The instance keying matters specifically because Suppliers and Records both
 * read `list_decisions` with no arguments: keyed on dependencies alone, the
 * second surface attaches to the first's already-settled promise and never
 * renders.
 */

import { StrictMode } from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { classifyRead, useSurfaceData } from '../useSurfaceData';
import { TransportError } from '../../adapter/client';

function Probe({
  load,
  label,
}: {
  load: () => Promise<Record<string, unknown>>;
  label: string;
}) {
  const { status, data, detail } = useSurfaceData(
    load as never,
    (e) => (e as { value?: string }).value ?? '',
  );
  return (
    <div>
      <span data-testid={`${label}-status`}>{status}</span>
      <span data-testid={`${label}-data`}>{String(data ?? '')}</span>
      <span data-testid={`${label}-detail`}>{detail}</span>
    </div>
  );
}

afterEach(() => vi.restoreAllMocks());

describe('classifying a read', () => {
  it('treats an ok envelope as an answer', () => {
    expect(classifyRead({ ok: true })).toEqual({ status: 'ready', detail: '' });
  });

  it('treats a persistence failure as a capability gap, not a fault', () => {
    // The deployed runtime returns exactly this when the recency index grant
    // is missing. It is "this deployment cannot answer", not "it broke".
    const { status } = classifyRead({
      ok: false,
      failure_category: 'PERSISTENCE_FAILURE',
      error: 'dynamodb:Query denied',
    });
    expect(status).toBe('blocked');
  });

  it('treats every other typed failure as a technical failure', () => {
    expect(classifyRead({ ok: false, failure_category: 'TOOL_FAILURE' }).status).toBe('failed');
    expect(classifyRead({ ok: false }).status).toBe('failed');
  });

  it('never turns a failure into a disposition', () => {
    const result = classifyRead({ ok: false, failure_category: 'PERSISTENCE_FAILURE' });
    expect(result).not.toHaveProperty('disposition');
  });
});

describe('a surface settles under StrictMode', () => {
  it('renders its answer rather than staying on loading', async () => {
    // The regression: StrictMode double-invokes the effect while one request
    // is in flight. A guard that cancels or supersedes the run holding that
    // request leaves the surface on `loading` forever.
    const load = vi.fn().mockResolvedValue({ ok: true, value: 'settled' });

    render(
      <StrictMode>
        <Probe load={load} label="a" />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByTestId('a-status').textContent).toBe('ready'));
    expect(screen.getByTestId('a-data').textContent).toBe('settled');
  });

  it('settles two surfaces that make the SAME request', async () => {
    // Suppliers and Records both call `list_decisions()` with no arguments.
    // Keyed on dependencies alone they collide and the second never renders.
    const load = vi.fn().mockResolvedValue({ ok: true, value: 'shared' });

    render(
      <StrictMode>
        <Probe load={load} label="one" />
        <Probe load={load} label="two" />
      </StrictMode>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('one-status').textContent).toBe('ready');
      expect(screen.getByTestId('two-status').textContent).toBe('ready');
    });
    expect(screen.getByTestId('two-data').textContent).toBe('shared');
  });

  it('reports a blocked read with its reason and no data', async () => {
    const load = vi.fn().mockResolvedValue({
      ok: false,
      failure_category: 'PERSISTENCE_FAILURE',
      error: 'no identity-based policy allows the dynamodb:Query action',
    });

    render(
      <StrictMode>
        <Probe load={load} label="b" />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByTestId('b-status').textContent).toBe('blocked'));
    expect(screen.getByTestId('b-data').textContent).toBe('');
    expect(screen.getByTestId('b-detail').textContent).toContain('dynamodb:Query');
  });

  it('reports a transport failure without inventing an outcome', async () => {
    const load = vi.fn().mockRejectedValue(new TransportError('could not reach', 0));

    render(
      <StrictMode>
        <Probe load={load} label="c" />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByTestId('c-status').textContent).toBe('failed'));
    expect(screen.getByTestId('c-data').textContent).toBe('');
  });

  it('issues exactly one request per surface despite the double mount', async () => {
    const load = vi.fn().mockResolvedValue({ ok: true, value: 'once' });

    render(
      <StrictMode>
        <Probe load={load} label="d" />
      </StrictMode>,
    );

    await waitFor(() => expect(screen.getByTestId('d-status').textContent).toBe('ready'));
    // The remount attaches to the request already in flight.
    expect(load).toHaveBeenCalledTimes(1);
  });
});
