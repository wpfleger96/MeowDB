import fs from 'fs';
import path from 'path';

import { test, expect, Page, TestInfo } from '@playwright/test';

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

function isDesktop(page: Page): boolean {
  const vp = page.viewportSize();
  return vp !== null && vp.width >= 768;
}

const GOTO_OPTS = { waitUntil: 'networkidle' as const };

test.describe('MeowDB views', () => {
  test('play view', async ({ page }, testInfo) => {
    await page.goto('/', GOTO_OPTS);
    await page.waitForSelector('.meow-btn', { state: 'visible' });
    await screenshot(page, testInfo, '01-play.png');
  });

  test('navigation layout', async ({ page }) => {
    await page.goto('/', GOTO_OPTS);
    const nav = page.locator('.bottom-nav');
    const box = await nav.boundingBox();
    if (isDesktop(page)) {
      // Sidebar: pinned to left edge, 220px wide, full-height
      expect(box?.x).toBe(0);
      expect(box?.width).toBe(220);
    } else {
      // Bottom bar: full-width, pinned to bottom
      const vp = page.viewportSize()!;
      expect(box?.width).toBe(vp.width);
    }
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

    if (isDesktop(page)) {
      const vp = page.viewportSize()!;
      // Library list shifts to make room for the side panel
      await expect(page.locator('.library-view')).toHaveClass(/detail-open/);
      // Sheet fills full height (not a short bottom sheet)
      const sheet = await page.locator('.modal-sheet:visible').boundingBox();
      expect(sheet!.height).toBeGreaterThan(vp.height / 2);
    }
  });

  test('ingest upload', async ({ page }, testInfo) => {
    await page.goto('/upload', GOTO_OPTS);
    await page.waitForSelector('.upload-zone', { state: 'visible' });
    await screenshot(page, testInfo, '04-ingest.png');

    if (isDesktop(page)) {
      // Upload zone and record section are side-by-side: different x positions
      const uploadBox = await page.locator('.upload-zone').boundingBox();
      const recordBox = await page.locator('.record-section').boundingBox();
      expect(uploadBox!.x).toBeLessThan(recordBox!.x);
      // "or" divider is hidden
      await expect(page.locator('.ingest-or-divider')).toBeHidden();
    }
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

  test('algorithm doc', async ({ page }, testInfo) => {
    await page.goto('/algorithm', GOTO_OPTS);
    // Markdown rendered (headings from the doc) and math typeset by MathJax (SVG).
    await page.waitForSelector('.markdown-body h1', { state: 'visible' });
    await page.waitForSelector('.markdown-body mjx-container svg', { state: 'visible' });
    // The Parameters markdown table rendered.
    await expect(page.locator('.markdown-body table')).toHaveCount(1);
    await screenshot(page, testInfo, '06-algorithm.png');
  });

  test('stats dashboard', async ({ page }, testInfo) => {
    await page.goto('/stats', GOTO_OPTS);
    await page.waitForSelector('.stat-tile', { state: 'visible' });
    await screenshot(page, testInfo, '05-stats.png');

    if (isDesktop(page)) {
      const tiles = await page.locator('.stat-tile').all();
      const boxes = await Promise.all(tiles.map((t) => t.boundingBox()));
      // All 4 tiles should be in the same row (same y, different x)
      expect(boxes[0]!.y).toBeCloseTo(boxes[3]!.y, -1);
      expect(boxes[0]!.x).toBeLessThan(boxes[1]!.x);
      expect(boxes[1]!.x).toBeLessThan(boxes[2]!.x);
      expect(boxes[2]!.x).toBeLessThan(boxes[3]!.x);
    }
  });
});
