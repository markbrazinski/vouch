import { execFileSync } from 'node:child_process';
import { readFileSync, readdirSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

const ROOT = join(import.meta.dirname, '..', '..');
const DIST = join(ROOT, 'dist-judge-check');

/**
 * The judge deployment must not expose or default to Demo Mode.
 *
 * A runtime flag would leave the playback code in the bundle with a condition
 * in front of it, and a condition in a browser is something a browser can
 * change. `DEMO_AVAILABLE` is a build-time constant instead, so the bundler
 * drops the route, the toggle, the interceptor and the archived packages as
 * dead code — the judge bundle does not contain a demo mode that is switched
 * off, it does not contain demo mode. No stored preference and no `?demo=1`
 * can reach what is not there.
 *
 * NOTE the explicit `VITE_ENABLE_DEMO_MODE=false` below. The repository ships
 * `frontend/.env` with it TRUE, so a cloned repo gets Demo Mode without
 * configuring anything — which means the judge build must OVERRIDE it rather
 * than rely on absence. That asymmetry is the whole reason this test runs the
 * REAL production build: it is the only thing that can prove the claim.
 */
describe('the judge build contains no recorded playback', () => {
  let bundle = '';
  let chunks: string[] = [];

  beforeAll(() => {
    rmSync(DIST, { recursive: true, force: true });
    execFileSync(
      'npx',
      ['vite', 'build', '--mode', 'production', '--outDir', 'dist-judge-check', '--emptyOutDir'],
      {
        cwd: ROOT,
        stdio: 'pipe',
        // Explicitly false, exactly as the judge/live build must set it.
        env: { ...process.env, NODE_ENV: 'production', VITE_ENABLE_DEMO_MODE: 'false' },
      },
    );
    const assets = join(DIST, 'assets');
    chunks = readdirSync(assets).filter((f) => f.endsWith('.js'));
    bundle = chunks.map((f) => readFileSync(join(assets, f), 'utf8')).join('\n');
  }, 180_000);

  it('emits a bundle', () => {
    expect(bundle.length).toBeGreaterThan(1000);
  });

  /**
   * The golden DecisionRecord ids the captured runs carry. Identified by
   * content rather than by chunk name, because a chunk name is a bundler detail
   * that would silently stop matching.
   */
  it.each([
    'DR-90b55b1f5890',
    'DR-f46415ec0641',
    'DR-aafc8009407b',
    'DR-8f59b0e6f7d2',
    'DR-01a822d82a0c',
  ])('carries no recorded run %s', (recordId) => {
    expect(bundle).not.toContain(recordId);
  });

  it.each(['DemoRoute', 'markDecided', 'installDemoBackend', 'DEMO_MODE_REFUSED'])(
    'carries no playback symbol %s',
    (symbol) => {
      expect(bundle).not.toContain(symbol);
    },
  );

  it('registers no /demo route', () => {
    expect(bundle).not.toContain('/demo/');
  });

  it('carries no demo toggle', () => {
    expect(bundle).not.toContain('vouch.demoMode');
  });

  /**
   * The archived opening board is absent too.
   *
   * The packages are the obvious thing to check for, but the board is the one
   * that would let a judge build render arrivals that never came from DynamoDB.
   */
  it('carries no archived opening board', () => {
    expect(bundle).not.toContain('ARCHIVED_GOLDEN_RUN');
  });

  it('carries no dev-only per-lot reset', () => {
    expect(bundle).not.toContain('dev/reset-lot');
  });

  it('keeps the judge reset', () => {
    // The counterpart assertion: proving demo mode is absent is worth nothing
    // if the control judges actually need went missing with it.
    expect(bundle).toContain('reset-demo');
  });
});
