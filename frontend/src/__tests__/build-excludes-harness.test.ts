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
