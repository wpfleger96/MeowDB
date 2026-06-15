import fs from 'fs';
import path from 'path';

import { test, Page, TestInfo } from '@playwright/test';

const SCREENSHOTS_DIR = path.resolve(__dirname, 'screenshots');
const SCREENSHOTS_ENABLED = process.env.SCREENSHOTS === 'true';

test.beforeAll(() => {
  if (SCREENSHOTS_ENABLED) {
    fs.mkdirSync(SCREENSHOTS_DIR, { recursive: true });
  }
});

async function screenshot(page: Page, testInfo: TestInfo, name: string): Promise<void> {
  if (!SCREENSHOTS_ENABLED) return;
  const project = testInfo.project.name;
  await page.screenshot({
    path: path.join(SCREENSHOTS_DIR, `${project}-${name}`),
    fullPage: false,
  });
}

const GOTO_OPTS = { waitUntil: 'networkidle' as const };

test.describe('MeowDB views', () => {
  test('play view', async ({ page }, testInfo) => {
    await page.goto('/', GOTO_OPTS);
    await page.waitForSelector('.meow-btn', { state: 'visible' });
    await screenshot(page, testInfo, '01-play.png');
  });

  test('library list', async ({ page }, testInfo) => {
    await page.goto('/library', GOTO_OPTS);
    await page.waitForSelector('.list-row', { state: 'visible' });
    await screenshot(page, testInfo, '02-library.png');
  });

  test('library detail', async ({ page }, testInfo) => {
    await page.goto('/library', GOTO_OPTS);
    await page.waitForSelector('.list-row', { state: 'visible' });
    await page.locator('.list-row').first().click();
    await page.waitForSelector('.modal-sheet', { state: 'visible' });
    await page.waitForTimeout(200);
    await screenshot(page, testInfo, '03-library-detail.png');
  });

  test('ingest upload', async ({ page }, testInfo) => {
    await page.goto('/upload', GOTO_OPTS);
    await page.waitForSelector('.upload-zone', { state: 'visible' });
    await screenshot(page, testInfo, '04-ingest.png');
  });

  test('ingest waveform clipping', async ({ page }, testInfo) => {
    test.skip(!SCREENSHOTS_ENABLED, 'screenshots disabled');

    const audioFile = path.resolve(__dirname, '..', 'Meow 1.m4a');
    test.skip(!fs.existsSync(audioFile), 'audio fixture not available');

    await page.goto('/upload', GOTO_OPTS);
    await page.waitForSelector('.upload-zone', { state: 'visible' });

    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(audioFile);

    await page.waitForSelector('#clip-waveform-container canvas', { state: 'visible', timeout: 15000 });
    await page.waitForTimeout(1000);
    await screenshot(page, testInfo, '04b-ingest-waveform.png');
  });

  test('stats dashboard', async ({ page }, testInfo) => {
    await page.goto('/stats', GOTO_OPTS);
    await page.waitForSelector('.stat-tile', { state: 'visible' });
    await screenshot(page, testInfo, '05-stats.png');
  });
});
