/**
 * DEMO MODE ACCEPTANCE — a fresh clone, no credentials, all five scenarios.
 *
 * This is the acceptance criterion the commission states, driven as a person
 * would drive it: turn Demo Mode on, click each lot from Incoming, let the run
 * play, press the authority control where it stops to ask, and read Today.
 *
 * The assertion that matters most is the NEGATIVE one. Every request the page
 * makes is recorded, and at the end this fails if any of them reached `/api`.
 * Demo Mode is supposed to need no backend at all; a passing screenshot with a
 * live BFF quietly answering underneath would prove nothing.
 *
 *     npm run dev                       # no BFF, no AWS profile, no credentials
 *     node e2e/demo-mode-acceptance.mjs
 *
 * Exits non-zero on the first failed expectation.
 */

import { chromium } from 'playwright';
import { resolve } from 'node:path';

const BASE = process.env.VOUCH_UI ?? 'http://localhost:5173';
const OUT = resolve(process.argv[2] ?? 'demo-acceptance.png');

/**
 * Each lot, what it must end up saying, and whether it stops for a person.
 *
 * The terminal text is the WORKSPACE's own rendering of the archived outcome —
 * asserted, not screenshotted, so a run that silently stalls fails here instead
 * of producing a plausible-looking image.
 */
const LOTS = [
  { id: 'LOT-1001', playMs: 34000, terminal: /Released into usable inventory/ },
  // The quarantine blocks C-417 — true until LOT-1004 later releases material
  // that covers it again. Asserted here, where the archive says it.
  { id: 'LOT-1002', playMs: 32000, terminal: /Quarantined/, thenToday: /1 BLOCKED/ },
  { id: 'LOT-1003', playMs: 20000, gate: /Establish this evidence/, afterGateMs: 22000, terminal: /Released into usable inventory/, thenToday: /1 READY/ },
  { id: 'LOT-1004', playMs: 8000, gate: /Confirm binding/, afterGateMs: 16000, terminal: /Released into usable inventory/ },
  { id: 'LOT-1005', playMs: 8000, terminal: /Prompt injection detected|Quarantined/ },
];

const log = (...a) => console.log(...a);
const failures = [];
const expect = (ok, what) => {
  log(`    ${ok ? 'PASS' : 'FAIL'}  ${what}`);
  if (!ok) failures.push(what);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

/** Every request the page makes. The proof that nothing reached a backend. */
const apiCalls = [];
page.on('request', (r) => {
  if (r.url().includes('/api/')) apiCalls.push(`${r.method()} ${r.url()}`);
});

log(`opening ${BASE} with demo mode on`);
await page.goto(`${BASE}/incoming?demo=1`, { waitUntil: 'networkidle' });
// `?demo=1` is applied before the first render, so the load that enables the
// mode is the one that must then be repeated with the interceptor installed.
await page.reload({ waitUntil: 'networkidle' });
await page.waitForTimeout(2000);

const body = () => page.locator('body').innerText();

log('\nopening state');
{
  const text = await body();
  expect(/DEMO\s*MODE/i.test(text), 'the demo badge is visible');
  expect(!/\bLIVE\b/.test(text), 'nothing claims to be LIVE during playback');
  for (const lot of LOTS) expect(text.includes(lot.id), `${lot.id} is listed`);
}

/** Click a lot's row, or route to it directly once it has left the list. */
async function openLot(lot) {
  const rows = page.locator('[data-testid="incoming-row"]');
  await rows.first().waitFor({ state: 'visible', timeout: 20000 }).catch(() => {});
  const lots = await rows.evaluateAll((els) =>
    els.map((el) => {
      const found = (el.parentElement?.parentElement?.innerText || '').match(/LOT-\d+/);
      return found ? found[0] : '';
    }),
  );
  const index = lots.indexOf(lot);
  if (index >= 0) {
    await rows.nth(index).click();
    await page.waitForTimeout(800);
    return true;
  }
  // A settled lot leaves the awaiting-disposition list, which is the board
  // behaving correctly. `pushState` rather than `goto`: a reload would discard
  // the outcomes accumulated so far.
  await page.evaluate((target) => {
    window.history.pushState({}, '', target);
    window.dispatchEvent(new PopStateEvent('popstate'));
  }, `/demo/${lot}`);
  await page.waitForTimeout(1200);
  return false;
}

for (const lot of LOTS) {
  log(`\n${lot.id}`);
  await openLot(lot.id);
  await page.waitForTimeout(lot.playMs);

  if (lot.gate) {
    const text = await body();
    expect(lot.gate.test(text), 'playback stopped and asked the human question');
    const before = text;
    // It must WAIT. A timer that advanced past the question would mime the
    // decision — the whole reason the gate exists.
    await page.waitForTimeout(6000);
    expect((await body()) === before, 'nothing advances the run while it waits');

    const button = page.locator('button', { hasText: lot.gate }).first();
    if ((await button.count()) > 0) {
      await button.click();
      log('    pressed the authority control');
      await page.waitForTimeout(lot.afterGateMs);
    } else {
      expect(false, 'an authority control was available to press');
    }
  }

  expect(lot.terminal.test(await body()), `reached its archived terminal state`);

  /**
   * Check the plan at the moment this run's consequence is the latest one.
   *
   * Readiness is last-write-wins across the five runs, exactly as a ledger
   * would be: LOT-1002 moves C-417 to BLOCKED, and LOT-1004's later release of
   * 450kg of the same material moves it back to READY. Both are real recorded
   * consequences, so "C-417 is BLOCKED" is only true BETWEEN those two runs —
   * asserting it at the end would be asserting a story the archive does not
   * tell. This checks each claim where the archive actually makes it.
   */
  if (lot.thenToday) {
    await page.locator('button', { hasText: 'Today' }).first().click();
    await page.waitForTimeout(2500);
    const plan = (await body()).replace(/\s+/g, ' ');
    expect(lot.thenToday.test(plan), `Today reflects ${lot.id}: ${lot.thenToday}`);
    await page.locator('button', { hasText: 'Incoming' }).first().click();
    await page.waitForTimeout(1500);
    continue;
  }

  const back = page.locator('button', { hasText: 'Back to Incoming' }).first();
  if ((await back.count()) > 0) {
    await back.click();
    await page.waitForTimeout(1200);
  }
}

log('\nToday, after all five');
// The NAV BUTTON, not pushState: a synthetic history entry renders the route
// without re-running the surface load.
await page.locator('button', { hasText: 'Today' }).first().click();
await page.waitForTimeout(3000);
{
  const text = (await body()).replace(/\s+/g, ' ');
  log(`    ${text.slice(0, 200)}`);

  /**
   * Read the COUNTS, not just the presence of a word.
   *
   * The first version of this asserted `/BLOCKED/` and `/READY/`, both of which
   * match the header chips whatever their value — so it passed while Today
   * still read "0 READY · 3 AWAITING QUALITY · 0 BLOCKED" after five runs had
   * visibly changed the plan. The board had never re-read. Asserting the
   * numbers is what makes this test able to fail.
   */
  const count = (label) => {
    const found = text.match(new RegExp(`(\\d+)\\s+${label}`));
    return found ? Number(found[1]) : -1;
  };
  log(`    READY=${count('READY')} BLOCKED=${count('BLOCKED')} AWAITING=${count('AWAITING QUALITY')}`);
  //
  // At the END, C-417 is READY again: LOT-1004's release covers it. That is the
  // archive's own arithmetic, and the board agreeing with it is the point.
  expect(count('READY') >= 2, 'the orders the runs cleared read READY');
  expect(count('AWAITING QUALITY') < 3, 'the board is no longer entirely awaiting quality');
}

log('\nReset demo');
await page.locator('button', { hasText: /Reset demo/ }).first().click();
await page.waitForTimeout(400);
await page.locator('button', { hasText: /^Reset demo$/ }).first().click();
await page.waitForTimeout(2500);
await page.locator('button', { hasText: 'Incoming' }).first().click();
await page.waitForTimeout(2000);
{
  const text = await body();
  for (const lot of LOTS) expect(text.includes(lot.id), `${lot.id} is replayable again`);
  expect(!/Released into usable inventory/.test(text), 'no run survived the reset');
}

log('\nno backend was contacted');
expect(apiCalls.length === 0, `zero /api requests (saw ${apiCalls.length})`);
for (const call of apiCalls.slice(0, 10)) log(`      ${call}`);

await page.screenshot({ path: OUT, fullPage: true });
log(`\nscreenshot -> ${OUT}`);
await browser.close();

if (failures.length) {
  log(`\nDEMO_MODE_BLOCKED — ${failures.length} failed:`);
  for (const f of failures) log(`  - ${f}`);
  process.exit(1);
}
log('\nDEMO_MODE_READY — all five scenarios, no backend contacted.');
