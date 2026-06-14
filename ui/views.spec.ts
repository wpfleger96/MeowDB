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

async function waitForApp(page: Page): Promise<void> {
  await page.waitForFunction(() => typeof (window as any).Alpine !== 'undefined');
  await page.waitForLoadState('networkidle');
}

test.describe('MeowDB views', () => {
  test('play view', async ({ page }, testInfo) => {
    await page.goto('/');
    await waitForApp(page);
    await page.waitForSelector('.meow-btn', { state: 'visible' });
    await screenshot(page, testInfo, '01-play.png');
  });

  test('library list', async ({ page }, testInfo) => {
    await page.goto('/library');
    await waitForApp(page);
    await page.waitForSelector('.list-row', { state: 'visible' });
    await screenshot(page, testInfo, '02-library.png');
  });

  test('library detail', async ({ page }, testInfo) => {
    await page.goto('/library');
    await waitForApp(page);
    await page.waitForSelector('.list-row', { state: 'visible' });
    await page.locator('.list-row').first().click();
    await page.waitForSelector('.modal-sheet', { state: 'visible' });
    await page.waitForTimeout(200);
    await screenshot(page, testInfo, '03-library-detail.png');
  });

  test('ingest upload', async ({ page }, testInfo) => {
    await page.goto('/upload');
    await waitForApp(page);
    await page.waitForSelector('.upload-zone', { state: 'visible' });
    await screenshot(page, testInfo, '04-ingest.png');
  });

  test('stats dashboard', async ({ page }, testInfo) => {
    await page.goto('/stats');
    await waitForApp(page);
    await page.waitForSelector('.stat-tile', { state: 'visible' });
    await screenshot(page, testInfo, '05-stats.png');
  });
});
