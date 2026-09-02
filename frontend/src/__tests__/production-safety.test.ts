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
    // `adapter/client.ts` is the ONE sanctioned transport seam. It exists so no
    // component has to reach for the network itself; keeping the ban on every
    // other file is what makes that true rather than aspirational.
    const CLIENT = join('src', 'adapter', 'client.ts');
    for (const f of productFiles.filter((p) => !p.endsWith(CLIENT))) {
      const src = readFileSync(f, 'utf8');
      expect(src, f).not.toMatch(/\bfetch\s*\(/);
      expect(src, f).not.toMatch(/XMLHttpRequest|EventSource|new WebSocket/);
    }
  });

  it('the transport seam reaches only the same-origin BFF', () => {
    const src = readFileSync(join(SRC, 'adapter', 'client.ts'), 'utf8');
    // No absolute origin: an absolute URL would be a second backend, and a
    // cross-origin one would need credentials the browser must never hold.
    expect(src).not.toMatch(/https?:\/\//);
    expect(src).not.toMatch(/amazonaws\.com|bedrock-agentcore/);
    expect(src).toMatch(/'\/api'/);
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
