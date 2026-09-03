/**
 * The Hero A VISUAL BASELINE. Deterministic, offline, DEV-only.
 *
 * Counterpart to `hero-a.mjs`, and deliberately the opposite kind of check:
 *
 *   hero-a.mjs         live stack, real model, whichever valid outcome occurs.
 *                      Proves the system works. Useless as a screenshot diff,
 *                      because the outcome legitimately varies between runs.
 *
 *   visual-baseline    one pinned state (canonical QUARANTINE), replayed from a
 *                      captured real decision. No network, no model, no timing
 *                      variance — so a screenshot difference means the RENDERING
 *                      changed and nothing else.
 *
 * It talks to no backend. The fixture is a verbatim capture of a real decision
 * record, so the pixels come from production truth rather than invented data,
 * but replaying it costs nothing and gives the same frame every time.
 *
 *   npm run dev            # the route is DEV-only by construction
 *   node e2e/visual-baseline.mjs
 */

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.VOUCH_UI ?? 'http://localhost:5173';
const OUT = join(dirname(fileURLToPath(import.meta.url)), 'baseline');
mkdirSync(OUT, { recursive: true });

const run = async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const report = {
    kind: 'VISUAL_BASELINE',
    note: 'Deterministic replay of a captured real QUARANTINE decision. Not live evidence.',
    errors: [],
  };

  page.on('pageerror', (e) => report.errors.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && report.errors.push(m.text()));

  await page.goto(`${BASE}/dev/visual-baseline`, { waitUntil: 'networkidle' });
  await page.waitForSelector('[data-testid="visual-baseline"]');

  // The baseline is only meaningful if it is the state it claims to be.
  report.state = await page
    .locator('[data-testid="visual-baseline"]')
    .getAttribute('data-baseline-state');
  report.outcome = (await page.locator('[data-testid="outcome-summary"]').count())
    ? (await page.locator('[data-testid="outcome-summary"]').textContent())?.replace(/\s+/g, ' ')
    : null;
  report.events = await page.locator('[data-testid="activity-row"]').count();

  await page.screenshot({ path: join(OUT, 'hero-a-quarantine.png') });

  // Scroll the workspace so the lower stages are captured too.
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForTimeout(200);
  await page.screenshot({ path: join(OUT, 'hero-a-quarantine-lower.png') });

  report.horizontalScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );

  writeFileSync(join(OUT, 'baseline.json'), JSON.stringify(report, null, 1));
  await browser.close();

  console.log('\n=== HERO A VISUAL BASELINE ===');
  console.log(`state            ${report.state}`);
  console.log(`events           ${report.events}`);
  console.log(`horizontal scroll${report.horizontalScroll ? ' YES (FAIL)' : ' none'}`);
  console.log(`page errors      ${report.errors.length}`);
  console.log(`outcome          ${report.outcome?.slice(0, 140)}`);

  // The baseline must be the canonical state, or a diff against it means
  // nothing. This is the one assertion that makes the artifact trustworthy.
  return report.state === 'QUARANTINE' && !report.horizontalScroll;
};

run()
  .then((ok) => {
    if (!ok) {
      console.error('\nFAIL: the baseline did not render the canonical QUARANTINE state.');
      process.exit(1);
    }
  })
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
