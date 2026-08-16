import { test, expect } from '@playwright/test';

const GOTO_OPTS = { waitUntil: 'domcontentloaded' as const };

const loginModal = '[aria-label="Login"]';
const passwordInput = '[aria-label="Login"] input[type="password"]';
const loginSubmit = '[aria-label="Login"] button[type="submit"]';
const loginCancel = '[aria-label="Login"] button.btn-secondary';

test.describe('auth gating', () => {
  test('homepage stays modal-free when logged out', async ({ page }) => {
    await page.goto('/', GOTO_OPTS);
    await page.waitForSelector('.meow-btn', { state: 'visible' });
    await expect(page.locator(loginModal)).toBeHidden();

    await page.locator('.meow-btn').click();
    await expect(page.locator(loginModal)).toBeHidden();
  });

  test('deep-link to /upload prompts login', async ({ page }) => {
    await page.goto('/upload', GOTO_OPTS);
    await expect(page.locator(loginModal)).toBeVisible();
  });

  test('runtime nav to /upload prompts login', async ({ page }) => {
    await page.goto('/', GOTO_OPTS);
    await page.waitForSelector('.meow-btn', { state: 'visible' });

    await page.evaluate(() => (window as unknown as { navigateTo: (p: string) => void }).navigateTo('/upload'));
    await expect(page.locator(loginModal)).toBeVisible();
  });

  test('login on /upload unlocks the upload view', async ({ page }) => {
    await page.goto('/upload', GOTO_OPTS);
    await page.locator(passwordInput).fill('test');
    await page.locator(loginSubmit).click();

    await expect(page.locator(loginModal)).toBeHidden();
    await expect(page.locator('.ingest-idle .upload-zone')).toBeVisible();
    await expect(page.locator('nav button[aria-label="Upload"]')).toBeVisible();
  });

  test('cancelling login on /upload returns to homepage', async ({ page }) => {
    await page.goto('/upload', GOTO_OPTS);
    await expect(page.locator(loginModal)).toBeVisible();

    await page.locator(loginCancel).click();
    await expect(page).toHaveURL('/');
    await expect(page.locator(loginModal)).toBeHidden();
  });
});
