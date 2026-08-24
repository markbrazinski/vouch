import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const SRC = join(import.meta.dirname, '..');

function sourceFiles(dir: string, acc: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) {
      if (name === '__tests__') continue;
      sourceFiles(p, acc);
    } else if (/\.tsx?$/.test(name)) {
      acc.push(p);
    }
  }
  return acc;
}

/** Everything shipped to a judge, i.e. every source file that is not the dev harness. */
const productFiles = sourceFiles(SRC).filter((p) => !p.includes(`${join('src', 'dev')}`));

describe('the product surface carries no demo apparatus', () => {
  it('no page fetches or invents a backend route', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/\bfetch\s*\(/);
      expect(src, f).not.toMatch(/XMLHttpRequest|EventSource|new WebSocket/);
    }
  });

  it('no fake timer manufactures product state', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/setTimeout|setInterval/);
    }
  });

  it('no prototype bar, judge control, or AI activity feed in product chrome', () => {
    for (const f of productFiles) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/PROTOTYPE STATES|Cleared by Vouch|no run lost|thought feed/i);
    }
  });

  it('the fixture harness is imported only behind import.meta.env.DEV', () => {
    const main = readFileSync(join(SRC, 'main.tsx'), 'utf8');
    expect(main).toMatch(/import\.meta\.env\.DEV/);
    // The only reference to the harness module is the dynamic, dev-guarded import.
    const refs = productFiles.filter((f) => /VouchStateHarness/.test(readFileSync(f, 'utf8')));
    expect(refs.map((f) => f.replace(SRC, ''))).toEqual([join('/', 'main.tsx')]);
  });
});
