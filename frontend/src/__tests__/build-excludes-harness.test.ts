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

  it('ships no deterministic visual baseline', () => {
    // The baseline replays a captured real decision so screenshot diffs mean a
    // rendering change rather than a different model run. It is DEV-only
    // apparatus: shipping it would put a frozen QUARANTINE in the product, and
    // an operator could see a decision that did not happen on their material.
    expect(bundle).not.toMatch(/visual-baseline/);
    expect(bundle).not.toMatch(/data-baseline-state/);
    expect(bundle).not.toMatch(/VISUAL_BASELINE/);
    // The captured record id must not leak either — it names a real decision.
    expect(bundle).not.toMatch(/DR-c127f2c38a8b/);
  });

  it('exposes no prototype state bar or fold overlay', () => {
    expect(bundle).not.toMatch(/PROTOTYPE STATES/);
    expect(bundle).not.toMatch(/1440 × 900 FOLD/);
    expect(bundle).not.toMatch(/vouch-state-harness/);
  });

  it('ships the product surface', () => {
    expect(bundle).toMatch(/ÅBY/);
    // The Hero A entry: an arrival awaiting a decision, and the decision
    // spine's independence label. Both are product copy, not fixture data.
    expect(bundle).toMatch(/AWAITING A QUALITY DECISION/);
    expect(bundle).toMatch(/INVESTIGATION/);
  });

  it('ships no hard-coded decision outcome', () => {
    // Care is needed about what "hard-coded" means here.
    //
    // The bundle legitimately contains the supplier's COA verbatim — including
    // "Specification SPEC-A7 Revision B" and "462 MPa" — because that document
    // is the INPUT Hero A evaluates. A certificate claiming a revision is a
    // supplier claim, not Vouch's answer; whether that revision still governs
    // is precisely what the run determines.
    //
    // What must never be baked in is the OUTCOME: the governing basis Vouch
    // resolved, the disposition it reached, or the consequence it computed.
    const heroDoc = bundle.indexOf('Certificate of Analysis');
    expect(heroDoc).toBeGreaterThan(-1);

    // The resolved basis (revision C) is the Investigator's finding and must
    // come from the backend, never the bundle.
    expect(bundle).not.toMatch(/SPEC-A7:C/);
    // No pre-declared verdict for this lot.
    expect(bundle).not.toMatch(/LOT-1002[^]{0,80}QUARANTINE/);
    // No pre-computed consequence.
    expect(bundle).not.toMatch(/C-417[^]{0,40}BLOCKED/);
    expect(bundle).not.toMatch(/short by 900/);
  });

  it('ships no scripted lifecycle sequence', () => {
    // A poll is permitted — it asks the server what happened. A scripted event
    // sequence is not.
    //
    // Note this cannot be a keyword scan: React DOM itself contains "Playback"
    // and "autoPlay" as media-attribute names, so /playback|autoplay/i matches
    // a bundle with no demo apparatus in it whatsoever. The honest test is for
    // the SHAPE of a fabricated run — a literal array of lifecycle event names,
    // which is what the design reference used and nothing in the product does.
    expect(bundle).not.toMatch(/\["INVESTIGATOR_STARTED"|'INVESTIGATOR_STARTED',/);
    expect(bundle).not.toMatch(/maxStep|stepIndex|seek\(/);
    // No transport controls in the product chrome.
    expect(bundle).not.toMatch(/PROTOTYPE STATES|Restart|▶|⏸/);
  });
});

/**
 * The credential boundary.
 *
 * A browser that could sign an AgentCore request would need AWS credentials,
 * and a credential shipped to a browser is a credential handed to every viewer.
 * The BFF signs server-side precisely so this bundle cannot.
 *
 * Asserted against the real production build rather than the source, because
 * what matters is what actually ships.
 */
describe('the production bundle holds no AWS credentials or signing code', () => {
  let bundle = '';

  beforeAll(() => {
    const assets = join(DIST, 'assets');
    bundle = readdirSync(assets)
      .filter((f) => f.endsWith('.js'))
      .map((f) => readFileSync(join(assets, f), 'utf8'))
      .join('\n');
  });

  it('contains no AWS access key or session credential', () => {
    expect(bundle).not.toMatch(/AKIA[0-9A-Z]{16}/);
    expect(bundle).not.toMatch(/aws_secret_access_key/i);
    expect(bundle).not.toMatch(/aws_session_token/i);
  });

  it('contains no browser-side SigV4 implementation', () => {
    expect(bundle).not.toMatch(/AWS4-HMAC-SHA256/);
    expect(bundle).not.toMatch(/X-Amz-Credential/i);
    expect(bundle).not.toMatch(/getSignatureKey|createSigV4|SignatureV4/);
  });

  it('does not bundle an AWS SDK to invoke AgentCore', () => {
    expect(bundle).not.toMatch(/@aws-sdk\/client-bedrock/);
    expect(bundle).not.toMatch(/invoke_agent_runtime|InvokeAgentRuntime/);
  });

  it('ships no AgentCore runtime ARN', () => {
    expect(bundle).not.toMatch(/arn:aws:bedrock-agentcore/);
  });
});

describe('the frontend declares no AWS SDK dependency', () => {
  it('has no @aws-sdk package in dependencies', () => {
    const pkg = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'));
    const declared = Object.keys({ ...pkg.dependencies, ...pkg.devDependencies });
    expect(declared.filter((name) => name.startsWith('@aws-sdk/'))).toEqual([]);
    expect(declared).not.toContain('aws-sdk');
  });
});
