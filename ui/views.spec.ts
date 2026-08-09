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
    await page.waitForSelector('.ingest-idle .upload-zone', { state: 'visible' });
    await screenshot(page, testInfo, '04-ingest.png');

    if (isDesktop(page)) {
      // Upload zone and record section are side-by-side: different x positions
      const uploadBox = await page.locator('.ingest-idle .upload-zone').boundingBox();
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
    await page.waitForSelector('.ingest-idle .upload-zone', { state: 'visible' });

    const fileInput = page.locator('input[type="file"]:not([accept^="image"])');
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

  test('about panel', async ({ page }, testInfo) => {
    await page.goto('/', GOTO_OPTS);

    // Desktop opens About from the sidebar brand; mobile from the Play view's
    // floating control, since the brand row is hidden below 768px.
    const trigger = isDesktop(page)
      ? page.locator('.nav-brand')
      : page.locator('.play-auth-mobile .btn-icon');
    await trigger.click();

    await page.waitForSelector('.modal-sheet .about-row', { state: 'visible' });
    // Let the slide-in animation settle before measuring or capturing.
    await page.waitForTimeout(400);
    await expect(page.locator('.about-row').first().locator('.about-value')).toHaveText(
      /^v\d+\.\d+\.\d+/,
    );
    // Every Build and Runtime field renders.
    await expect(page.locator('.about-row')).toHaveCount(7);
    await screenshot(page, testInfo, '07-about.png');

    if (isDesktop(page)) {
      const vp = page.viewportSize()!;
      // Right-pinned full-height 420px panel, not a bottom sheet
      const panel = await page.locator('.modal-backdrop:visible').boundingBox();
      expect(panel!.width).toBe(420);
      expect(panel!.x + panel!.width).toBeCloseTo(vp.width, 0);
      expect(panel!.height).toBe(vp.height);
    }

    await page.keyboard.press('Escape');
    await expect(page.locator('.modal-sheet .about-row').first()).toBeHidden();
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

  test('profiles list', async ({ page }, testInfo) => {
    await page.goto('/profiles', GOTO_OPTS);
    // Scope to the profiles view: other views stay in the DOM (x-show) and the
    // hidden play-view bio also contains "Squishy".
    const view = page.locator('.profiles-view');
    await expect(view.getByText('Squishy')).toBeVisible();
    await screenshot(page, testInfo, '08-profiles.png');

    // All three seeded animals render with names.
    await expect(view.getByText('Thrasher')).toBeVisible();
    await expect(view.getByText('Slushie')).toBeVisible();

    // Species labels are visible alongside animal names.
    await expect(view.getByText('Cat').first()).toBeVisible();
    await expect(view.getByText('Dog').first()).toBeVisible();

    // Clicking an animal opens a photo pane with a back button.
    await view.getByText('Squishy').first().click();
    await expect(view.getByRole('button', { name: /back/i })).toBeVisible();
    await screenshot(page, testInfo, '07b-profiles-detail.png');
  });

  test('play view null-photo state after MEOW press', async ({ page }, testInfo) => {
    // Seed has no photos for any animal, so pressing MEOW always yields a null photo
    // regardless of which random sound is selected.
    await page.goto('/', GOTO_OPTS);

    // Scope all selectors to the play view so hidden views (x-show) are not matched.
    const playView = page.locator('.play-view');
    await playView.waitFor({ state: 'visible' });

    const meowBtn = playView.locator('.meow-btn');
    await meowBtn.waitFor({ state: 'visible' });

    await meowBtn.click();

    // The replay button (x-show="currentSound") becomes visible once the sound
    // response is processed — at that point currentPhoto is already settled.
    await expect(playView.locator('.replay-btn')).toBeVisible({ timeout: 10000 });

    // Null-photo state: no has-photo class and no background-image inline style.
    await expect(meowBtn).not.toHaveClass(/has-photo/);
    const style = await meowBtn.getAttribute('style');
    expect(style ?? '').not.toContain('background-image');

    await screenshot(page, testInfo, '09-play-null-photo.png');
  });

  test('ingest animal selector', async ({ page }) => {
    await page.goto('/upload', GOTO_OPTS);
    await page.waitForSelector('.upload-zone', { state: 'visible' });

    // Animal selector is present and populated with all seeded animals.
    const select = page.locator('select[x-model="selectedAnimalId"]');
    await expect(select).toBeVisible();
    await expect(select.locator('option', { hasText: 'Squishy' })).toHaveCount(1);
    await expect(select.locator('option', { hasText: 'Thrasher' })).toHaveCount(1);
    await expect(select.locator('option', { hasText: 'Slushie' })).toHaveCount(1);
  });

  test('upload hub tabs', async ({ page }, testInfo) => {
    await page.goto('/upload', GOTO_OPTS);
    await page.waitForSelector('.ingest-tabs', { state: 'visible' });
    const tabs = page.locator('.ingest-tabs');
    await expect(tabs.locator('.chip-filter', { hasText: 'Sounds' })).toBeVisible();
    await expect(tabs.locator('.chip-filter', { hasText: 'Photos' })).toBeVisible();
    await expect(tabs.locator('.chip-filter.active')).toHaveText('Sounds');

    await tabs.locator('.chip-filter', { hasText: 'Photos' }).click();
    await expect(tabs.locator('.chip-filter.active')).toHaveText('Photos');
    await expect(page.locator('.ingest-idle .upload-zone')).toBeHidden();
    const photoZone = page.locator('.upload-zone').last();
    await expect(photoZone).toBeVisible();

    await screenshot(page, testInfo, '11-upload-photos-tab.png');
  });

  test('upload hub photos deep link', async ({ page }) => {
    await page.goto('/upload/photos', GOTO_OPTS);
    await page.waitForSelector('.ingest-tabs', { state: 'visible' });
    await expect(page.locator('.ingest-tabs .chip-filter.active')).toHaveText('Photos');
    await expect(page.locator('.ingest-idle')).toBeHidden();
  });

  test('library animal filter chips', async ({ page }) => {
    await page.goto('/library', GOTO_OPTS);
    await page.waitForSelector('.list-row', { state: 'visible' });

    // Filter chips render for All + each seeded animal (scoped: the hidden
    // play-view bio also contains "Squishy").
    const chips = page.locator('.library-filters');
    await expect(chips.getByText('All')).toBeVisible();
    await expect(chips.getByText('Squishy')).toBeVisible();
    await expect(chips.getByText('Thrasher')).toBeVisible();
    await expect(chips.getByText('Slushie')).toBeVisible();
  });
});
