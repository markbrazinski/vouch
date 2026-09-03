/**
 * Visual baselines for the journeys that are NOT Hero A.
 *
 * Same contract as `visual-baseline.mjs`, extended to the two journeys this
 * gate had to prove: the Hero B continuation and the hostile security halt.
 * Every fixture is a verbatim deployed-runtime response replayed through the
 * SAME Decision Workspace, so a difference here is a rendering difference.
 *
 *   npm run dev
 *   node e2e/journey-baselines.mjs
 */

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.VOUCH_UI ?? 'http://localhost:5173';
const OUT = join(dirname(fileURLToPath(import.meta.url)), 'baseline');
mkdirSync(OUT, { recursive: true });

/** What each route must render for the journey to be considered proven. */
const ROUTES = [
  {
    path: '/dev/baseline/hero-b-run1',
    shot: 'hero-b-run1',
    state: 'QUALITY_DECISION_REQUIRED',
    // Run 1 abstained: Vouch asked a human rather than answering.
    mustNotShow: ['RELEASED'],
  },
  {
    path: '/dev/baseline/hero-b-run2',
    shot: 'hero-b-run2',
    state: 'RELEASE',
    mustNotShow: [],
  },
  {
    path: '/dev/baseline/hostile',
    shot: 'hostile',
    state: 'SECURITY_QUARANTINE',
    // Invariant 6: no agent placeholders on a security halt.
    mustNotShow: ['Independently reconciled', 'Material disagreement'],
  },
];

const run = async () => {
  const browser = await chromium.launch();
  const report = { kind: 'JOURNEY_BASELINES', routes: [] };
  let ok = true;

  for (const route of ROUTES) {
    const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    const errors = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));

    await page.goto(`${BASE}${route.path}`, { waitUntil: 'networkidle' });
    await page.waitForSelector('[data-testid="visual-baseline"]');

    const state = await page
      .locator('[data-testid="visual-baseline"]')
      .getAttribute('data-baseline-state');
    const body = (await page.locator('body').textContent()) ?? '';
    const leaked = route.mustNotShow.filter((s) => body.includes(s));
    const horizontalScroll = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
    );

    await page.screenshot({ path: join(OUT, `${route.shot}.png`), fullPage: true });

    const pass = state === route.state && !leaked.length && !horizontalScroll && !errors.length;
    if (!pass) ok = false;
    report.routes.push({
      path: route.path,
      state,
      events: await page.locator('[data-testid="activity-row"]').count(),
      leaked,
      horizontalScroll,
      errors,
      pass,
    });
    await page.close();
  }

  writeFileSync(join(OUT, 'journey-baselines.json'), JSON.stringify(report, null, 1));
  await browser.close();

  console.log('\n=== JOURNEY BASELINES ===');
  for (const r of report.routes) {
    console.log(
      `${r.pass ? 'PASS' : 'FAIL'}  ${r.path.padEnd(30)} ${String(r.state).padEnd(26)} ` +
        `events=${String(r.events).padEnd(3)} ` +
        `${r.leaked.length ? `leaked=${r.leaked.join(',')} ` : ''}` +
        `${r.horizontalScroll ? 'H-SCROLL ' : ''}` +
        `${r.errors.length ? `errors=${r.errors.length}` : ''}`,
    );
  }
  return ok;
};

run()
  .then((ok) => {
    if (!ok) {
      console.error('\nFAIL: a journey baseline did not render its declared state.');
      process.exit(1);
    }
  })
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
