import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

const ROOT = join(import.meta.dirname, '..', '..');
const DIST = join(ROOT, 'dist-harness-check');

/**
 * Runs the real production build and asserts the shipped bundle carries no
 * fixture control. Slow by design — it is the only proof that matters.
 */
describe('production build excludes the dev fixture harness', () => {
  let bundle = '';

  beforeAll(() => {
    rmSync(DIST, { recursive: true, force: true });
    // --mode production is explicit: the test runner's own env must not leak in
    // and leave import.meta.env.DEV unreplaced.
    execFileSync(
      'npx',
      ['vite', 'build', '--mode', 'production', '--outDir', 'dist-harness-check', '--emptyOutDir'],
      { cwd: ROOT, stdio: 'pipe', env: { ...process.env, NODE_ENV: 'production' } },
    );
    const assets = join(DIST, 'assets');
    bundle = readdirSync(assets)
      .filter((f) => f.endsWith('.js'))
      .map((f) => readFileSync(join(assets, f), 'utf8'))
      .join('\n');
  }, 180_000);

  it('emits a bundle', () => {
    expect(existsSync(DIST)).toBe(true);
    expect(bundle.length).toBeGreaterThan(0);
  });

  it('exposes no prototype state bar or fold overlay', () => {
    expect(bundle).not.toMatch(/PROTOTYPE STATES/);
    expect(bundle).not.toMatch(/1440 × 900 FOLD/);
    expect(bundle).not.toMatch(/vouch-state-harness/);
  });

  it('ships the product surface', () => {
    expect(bundle).toMatch(/ÅBY/);
    expect(bundle).toMatch(/need a Quality decision/);
  });
});
