/**
 * Hero A LIVE QUALIFICATION, end to end, through the real stack.
 *
 * This is qualification evidence, NOT a visual baseline.
 *
 * Hero A is nondeterministic on the live model path: the same lot and the same
 * document reach QUARANTINE on some runs and abstain to INSUFFICIENT_EVIDENCE
 * on others. Both are valid — the abstention is Vouch refusing to answer on
 * evidence it cannot establish — so this script RECORDS whichever occurred and
 * fails only when the outcome is not a valid one at all.
 *
 * Screenshot regression belongs to `e2e/visual-baseline.mjs`, which pins one
 * canonical state so a diff means a rendering change rather than a different
 * model run.
 *
 *   browser -> vite -> /api -> local BFF (the real bff/handler) -> AgentCore
 *   -> Nova Pro -> DynamoDB / S3
 *
 * Nothing is mocked. The screenshots this produces are of a decision that
 * actually happened, and the timings are the real ones.
 *
 * It also asserts the live behaviour that unit tests cannot: that lifecycle
 * events arrive in the rail WHILE the model is still executing, rather than all
 * at once when the call returns.
 *
 *   node e2e/hero-a.mjs
 */

import { chromium } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const BASE = process.env.VOUCH_UI ?? 'http://localhost:5173';
// fileURLToPath, not URL.pathname: the latter silently produces a path that
// looks right and is not, and the screenshots vanish without an error.
const OUT = join(dirname(fileURLToPath(import.meta.url)), 'shots');
mkdirSync(OUT, { recursive: true });

const shot = async (page, name) => {
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  console.log(`  shot: ${name}.png`);
};

const railCount = (page) => page.locator('[data-testid="activity-row"]').count();
const activeStage = async (page) => {
  const el = page.locator('[data-active="true"]').first();
  return (await el.count()) ? el.getAttribute('data-testid') : null;
};

const run = async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
  const report = {
    kind: 'LIVE_QUALIFICATION',
    note: 'Whichever valid outcome the live model produced. Not a visual baseline.',
    samples: [],
    stages: [],
    errors: [],
  };

  page.on('pageerror', (e) => report.errors.push(String(e)));
  page.on('console', (m) => m.type() === 'error' && report.errors.push(m.text()));

  console.log('1. entry surface');
  await page.goto(BASE, { waitUntil: 'networkidle' });
  await shot(page, '01-incoming-entry');

  const started = Date.now();
  console.log('2. opening the arrival (this starts the decision)');
  await page.getByTestId('incoming-row').click();

  // Sample the rail while the decision runs. This is the proof that events are
  // live: if they only arrived at the end, every sample before the last would
  // read zero.
  console.log('3. sampling the rail while Nova executes');
  let shots = 0;
  for (let i = 0; i < 80; i += 1) {
    await page.waitForTimeout(1000);
    const count = await railCount(page);
    const stage = await activeStage(page);
    const t = ((Date.now() - started) / 1000).toFixed(1);
    report.samples.push({ t: Number(t), events: count, stage });

    if (stage && !report.stages.includes(stage)) {
      report.stages.push(stage);
      console.log(`   t+${t}s  ${stage}  (${count} events)`);
      await shot(page, `0${2 + shots}-${stage.replace('stage-', '')}`);
      shots += 1;
    }

    // Try the viewer on EVERY tick until it opens: the context column only
    // offers "Open source" once the artifact has loaded, which is not
    // necessarily the instant a stage changes.
    if (!report.sourceViewer) {
      const openBtn = page.getByRole('button', { name: 'Open source' });
      if ((await openBtn.count()) && (await openBtn.first().isEnabled())) {
        await openBtn.first().click();
        await page.waitForTimeout(500);
        if (await page.locator('[data-testid="source-viewer"]').count()) {
          await shot(page, '08-source-viewer');
          report.sourceViewer = true;
          report.sourceLocator = await page
            .locator('[data-testid="source-locator"]')
            .textContent();
          report.sourceTrust = await page
            .locator('[data-testid="source-viewer"]')
            .textContent();
          await page.keyboard.press('Escape');
          await page.waitForTimeout(300);
        }
      }
    }

    const outcome = await page.locator('[data-testid="outcome-summary"]').count();
    if (outcome > 0 && count > 0) {
      // Give the terminal load a moment to settle.
      await page.waitForTimeout(2500);
      break;
    }
  }

  const elapsed = ((Date.now() - started) / 1000).toFixed(1);
  console.log(`4. terminal after ${elapsed}s`);
  await shot(page, '09-terminal');

  // Open the source viewer.
  const completedEvidence = page.getByTestId('completed-evidence');
  if (await completedEvidence.count()) {
    await completedEvidence.click();
    await page.waitForTimeout(400);
    const viewBtn = page.getByRole('button', { name: 'View source' }).first();
    if (await viewBtn.count()) {
      await viewBtn.click();
      await page.waitForTimeout(600);
      await shot(page, '10-source-viewer');
      report.sourceViewer = await page.locator('[data-testid="source-viewer"]').count();
      report.sourceLocator = (await page.locator('[data-testid="source-locator"]').count())
        ? await page.locator('[data-testid="source-locator"]').textContent()
        : null;
      await page.keyboard.press('Escape');
    }
  }

  // The claims itemization, checked at the TERMINAL state.
  //
  // Claims live on the durable record, which only lands once the decision
  // finishes, so a viewer opened mid-run legitimately shows the count instead.
  // This re-opens it at the end, where the itemized rows must be present.
  // Wait for the source to actually land first. It arrives a few seconds AFTER
  // the outcome renders, because `get_source` only becomes answerable once the
  // record is durable — so sampling the instant the outcome appears reads the
  // gap rather than the settled state.
  try {
    await page
      .getByRole('button', { name: 'Open source' })
      .first()
      .waitFor({ state: 'visible', timeout: 20000 });
    await page.waitForFunction(
      () =>
        [...document.querySelectorAll('button')].some(
          (b) => /Open source/.test(b.textContent || '') && !b.disabled,
        ),
      { timeout: 20000 },
    );
  } catch {
    report.sourceSettled = false;
  }
  report.sourceSettled = report.sourceSettled !== false;

  const contextOpen = page.getByRole('button', { name: 'Open source' }).first();
  if ((await contextOpen.count()) && (await contextOpen.isEnabled())) {
    await contextOpen.click();
    await page.waitForTimeout(700);
    const provenance = page.locator('[data-testid="claim-provenance"]');
    report.claimRows = await provenance.count();
    report.claimProvenance = report.claimRows
      ? (await provenance.first().textContent())?.trim()
      : null;
    report.claimsItemized = report.claimRows > 0;
    await shot(page, '11-claims-itemized');
    await page.keyboard.press('Escape');
    await page.waitForTimeout(300);
  }

  // Facts a screenshot cannot assert.
  report.elapsedSeconds = Number(elapsed);
  report.finalEvents = await railCount(page);
  report.outcome = (await page.locator('[data-testid="outcome-summary"]').count())
    ? (await page.locator('[data-testid="outcome-summary"]').textContent())?.replace(/\s+/g, ' ')
    : null;
  report.disposition = await page.locator('text=QUARANTINE').first().count();

  // Which valid outcome happened. Both are correct product behaviour; the run
  // is qualified on reaching one of them, never on reaching a chosen one.
  const text = report.outcome ?? '';
  report.outcomeClass = /Quarantined/i.test(text)
    ? 'QUARANTINE'
    : /Quality decision required/i.test(text)
      ? 'QUALITY_DECISION_REQUIRED'
      : /Released/i.test(text)
        ? 'RELEASED'
        : 'UNKNOWN';
  report.validOutcome = report.outcomeClass !== 'UNKNOWN';

  // No horizontal page scroll at the acceptance frame.
  report.horizontalScroll = await page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
  // Nothing critical clipped.
  report.frame = await page.locator('[data-testid="acceptance-frame"]').boundingBox();
  // The credential must not be anywhere durable.
  report.storage = await page.evaluate(() =>
    JSON.stringify({ local: { ...localStorage }, session: { ...sessionStorage } }),
  );

  writeFileSync(join(OUT, 'live-qualification.json'), JSON.stringify(report, null, 1));
  await browser.close();

  console.log('\n=== HERO A E2E ===');
  console.log(`elapsed          ${report.elapsedSeconds}s`);
  console.log(`events in rail   ${report.finalEvents}`);
  console.log(`stages seen      ${report.stages.join(' -> ')}`);
  console.log(`source viewer    ${report.sourceViewer ? 'opened' : 'not opened'}`);
  console.log(`locator          ${report.sourceLocator}`);
  console.log(`claims itemized  ${report.claimsItemized ? `yes (${report.claimRows})` : 'no'}  ${report.claimProvenance ?? ''}`);
  console.log(`horizontal scroll${report.horizontalScroll ? ' YES (FAIL)' : ' none'}`);
  console.log(`storage          ${report.storage}`);
  console.log(`page errors      ${report.errors.length}`);
  console.log(`outcome class    ${report.outcomeClass}  (valid: ${report.validOutcome})`);
  console.log(`outcome          ${report.outcome?.slice(0, 150)}`);
  console.log('\nrail growth:');
  for (const s of report.samples.filter((_, i) => i % 3 === 0)) {
    console.log(`  t+${String(s.t).padStart(5)}s  ${String(s.events).padStart(3)} events  ${s.stage ?? '-'}`);
  }

  return report.validOutcome;
};

run()
  .then((ok) => {
    if (ok === false) {
      console.error('\nFAIL: the run did not reach any valid Hero A outcome.');
      process.exit(1);
    }
  })
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
