/**
 * Shift+R, the film/dev reset shortcut.
 *
 * The two properties worth testing are the ones a filming operator would
 * discover the hard way: that the key does not fire while they are typing, and
 * that it never shadows the browser's own reload.
 */

import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useFilmReset } from '../useFilmReset';

function Harness({ onReset }: { onReset?: () => void }) {
  const { toast } = useFilmReset(onReset);
  return (
    <div>
      <input data-testid="text-input" />
      <textarea data-testid="textarea" />
      <select data-testid="select">
        <option>a</option>
      </select>
      <div data-testid="editable" contentEditable suppressContentEditableWarning />
      <div data-testid="plain" />
      {toast && <span data-testid="toast">{toast}</span>}
    </div>
  );
}

const ok = (_url?: unknown, _init?: RequestInit) =>
  Promise.resolve({
    ok: true,
    json: () => Promise.resolve({ ok: true, lot_id: 'LOT-1003', lot_status: 'RECEIVED' }),
  } as Response);

function press(target: Element | Window, init: Partial<KeyboardEventInit> = {}) {
  const event = new KeyboardEvent('keydown', {
    key: 'R',
    shiftKey: true,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  target.dispatchEvent(event);
  return event;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('the shortcut fires on Shift+R', () => {
  it('calls the bounded dev reset route for LOT-1003', async () => {
    const fetchMock = vi.fn(ok);
    vi.stubGlobal('fetch', fetchMock);
    render(<Harness />);

    press(screen.getByTestId('plain'));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/dev/reset-lot');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toEqual({ lot_id: 'LOT-1003' });
  });

  it('shows the transient confirmation', async () => {
    vi.stubGlobal('fetch', vi.fn(ok));
    render(<Harness />);
    press(screen.getByTestId('plain'));
    expect((await screen.findByTestId('toast')).textContent).toBe(
      'LOT-1003 reset · ready for another run',
    );
  });

  it('notifies the shell so it can re-read authoritative state', async () => {
    vi.stubGlobal('fetch', vi.fn(ok));
    const onReset = vi.fn();
    render(<Harness onReset={onReset} />);
    press(screen.getByTestId('plain'));
    await waitFor(() => expect(onReset).toHaveBeenCalledTimes(1));
  });

  it('reports a failure rather than silently doing nothing', async () => {
    // A silent no-op mid-shoot is worse than an ugly toast: the next take
    // would film stale state without anyone noticing.
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 400,
          json: () => Promise.resolve({ ok: false, error: 'nope' }),
        } as Response),
      ),
    );
    render(<Harness />);
    press(screen.getByTestId('plain'));
    expect((await screen.findByTestId('toast')).textContent).toContain('reset failed');
  });
});

describe('the shortcut is suppressed while typing', () => {
  it.each(['text-input', 'textarea', 'select', 'editable'])(
    'ignores Shift+R inside %s',
    async (testid) => {
      const fetchMock = vi.fn(ok);
      vi.stubGlobal('fetch', fetchMock);
      render(<Harness />);

      press(screen.getByTestId(testid));

      await new Promise((r) => setTimeout(r, 20));
      expect(fetchMock).not.toHaveBeenCalled();
      expect(screen.queryByTestId('toast')).toBeNull();
    },
  );
});

describe('the shortcut never shadows a browser or OS binding', () => {
  it.each([
    ['metaKey', { metaKey: true }],
    ['ctrlKey', { ctrlKey: true }],
    ['altKey', { altKey: true }],
  ])('ignores Shift+R with %s held', async (_name, mods) => {
    const fetchMock = vi.fn(ok);
    vi.stubGlobal('fetch', fetchMock);
    render(<Harness />);

    press(screen.getByTestId('plain'), mods);

    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('ignores a plain lowercase r', async () => {
    const fetchMock = vi.fn(ok);
    vi.stubGlobal('fetch', fetchMock);
    render(<Harness />);
    press(screen.getByTestId('plain'), { key: 'r', shiftKey: false });
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('ignores an auto-repeating held key', async () => {
    const fetchMock = vi.fn(ok);
    vi.stubGlobal('fetch', fetchMock);
    render(<Harness />);
    press(screen.getByTestId('plain'), { repeat: true });
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
