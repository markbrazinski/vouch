import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync, readdirSync, rmSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { join } from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

const ROOT = join(import.meta.dirname, '..', '..');
const DIST = join(ROOT, 'dist-harness-check');

/**
 * Runs the real production build and asserts the shipped bundle carries no
 * fixture control. Slow by design — it is the only proof that matters.
 */
/**
 * Which emitted chunks are REPLAY data, and which are the product.
 *
 * `/film/:lotId` plays back captured runs, so those chunks legitimately contain
 * real dispositions — that is what a recording IS. They must never load on the
 * live path, which is enforced two ways: the assertions below run against the
 * PRODUCT chunks only, and a separate describe block proves the recorded data is
 * confined to lazy chunks nothing on the live path imports.
 *
 * Identified by the golden DecisionRecord ids they carry, not by filename: a
 * chunk name is a bundler detail and would silently stop matching.
 */
const REPLAY_RECORD_IDS = [
  'DR-90b55b1f5890',
  'DR-f46415ec0641',
  'DR-aafc8009407b',
  'DR-8f59b0e6f7d2',
  'DR-01a822d82a0c',
];

const isReplayChunk = (source: string): boolean =>
  REPLAY_RECORD_IDS.some((id) => source.includes(id));

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
    // PRODUCT chunks only. A replay chunk carries a real recorded outcome by
    // design; asserting "no disposition anywhere" over it would be asserting
    // that recordings contain no recordings.
    bundle = readdirSync(assets)
      .filter((f) => f.endsWith('.js'))
      .map((f) => readFileSync(join(assets, f), 'utf8'))
      .filter((source) => !isReplayChunk(source))
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
    // The Incoming entry point, and the decision spine's independence label.
    // Both are product copy, not fixture data.
    //
    // This was "AWAITING A QUALITY DECISION", the heading of a special LOT-1002
    // arrival card pinned above the list. That card was the only way to launch
    // a canonical run while the rows beneath it opened historical records, so
    // "open LOT-1002" meant two different things. It is gone; the ordinary
    // Incoming row now owns that behaviour, and this is its heading.
    expect(bundle).toMatch(/Material awaiting disposition/);
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
    // The COA is no longer inlined as a JS string: Hero A now submits the
    // CANONICAL tracked PDF, which Vite emits as a separate fingerprinted
    // asset. So the input is proven by the asset's bytes (below), not by
    // finding its text in the bundle — a stronger check, because it pins the
    // exact qualified document rather than a transcription of it.
    // Five canonical certificates, one per arrival Incoming lists. Vite
    // fingerprints each, so they are matched by CONTENT rather than by name.
    const pdfs = readdirSync(join(DIST, 'assets')).filter((f) => f.endsWith('.pdf'));
    expect(pdfs.length, 'every canonical certificate must ship as an asset').toBe(5);
    const shipped = pdfs.map((f) =>
      createHash('sha256').update(readFileSync(join(DIST, 'assets', f))).digest('hex'),
    );
    // Frozen in demo/evidence/MANIFEST.md and re-checked by
    // tests/v2/test_canonical_pdf_assets.py. If any differs, the UI is
    // submitting bytes that were never qualified.
    expect(shipped.sort()).toEqual(
      [
        '765839cc6520c58e454622ee280b5bea2498d24e7629298a26d32a3b10dee181', // 1001
        'bf3e80258af52dd098bc5a76e18b3603e024c3276bb56bdf9816f64fd5f459be', // 1002
        '326b4463ab1bf4222ea8466cc0997508a0f5e4bd0bec51180888054cc8721242', // 1004 binding · batch WP-26-0317-B
        'bb73e789f5e8e43b886e28011a763ffce40124093913f15269f9dd9f43b0a061', // 1005 injection
        'a23b91795ff0a9f3650db6a11ad55e8e29537007f204545920b5eae3abfcf8a8', // 1003 disagreement
      ].sort(),
    );

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

/**
 * The replay data is CONFINED.
 *
 * `/film/:lotId` is deliberately not dev-gated — filming happens against a real
 * build — so the usual "it isn't in the bundle" proof does not apply. The
 * property that replaces it: a captured outcome must live only in chunks that
 * nothing on the live path loads, so an operator evaluating their own material
 * can never be served a recorded decision instead.
 *
 * This is the test that makes shipping film view safe. If it fails, a recorded
 * disposition has leaked onto the live path.
 */
describe('captured golden runs stay out of the product surface', () => {
  let chunks: { name: string; source: string }[] = [];

  beforeAll(() => {
    const assets = join(DIST, 'assets');
    chunks = readdirSync(assets)
      .filter((f) => f.endsWith('.js'))
      .map((f) => ({ name: f, source: readFileSync(join(assets, f), 'utf8') }));
  });

  it('emits the replay data as its own lazy chunks', () => {
    const replay = chunks.filter((c) => isReplayChunk(c.source));
    expect(replay.length, 'the golden packages must ship as separate chunks').toBeGreaterThan(0);
  });

  it('keeps every recorded outcome out of the entry chunk', () => {
    // The entry chunk is the largest product chunk — what every visitor loads.
    const product = chunks.filter((c) => !isReplayChunk(c.source));
    const entry = product.sort((a, b) => b.source.length - a.source.length)[0];
    for (const id of REPLAY_RECORD_IDS) {
      expect(entry.source, `${entry.name} carries recorded run ${id}`).not.toContain(id);
    }
  });

  it('never mixes a recorded run into a chunk carrying product chrome', () => {
    // A chunk holding both the nav and a captured disposition would mean the
    // replay data loads for everyone, which is exactly what must not happen.
    for (const chunk of chunks.filter((c) => isReplayChunk(c.source))) {
      expect(chunk.source, `${chunk.name} mixes replay data into product chrome`).not.toMatch(
        /ÅBY/,
      );
    }
  });

  it('ships no replay badge or watermark in any chunk', () => {
    // Film view renders the product, unmarked, because the footage is of a real
    // decision and an overlay would both spoil the shot and mislabel it. A
    // badge appearing here means someone added demo chrome to the frame.
    const all = chunks.map((c) => c.source).join('\n');
    expect(all).not.toMatch(/data-testid="replay-banner"/);
    expect(all).not.toMatch(/Recorded run ·/);
  });
});
