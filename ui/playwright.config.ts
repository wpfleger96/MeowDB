import { defineConfig, devices } from '@playwright/test';

export const DATA_DIR = '/tmp/meowdb-screenshot-data';

export default defineConfig({
  testMatch: 'views.spec.ts',
  globalSetup: './global-setup.ts',
  use: {
    baseURL: 'http://127.0.0.1:8001',
  },
  webServer: {
    command: 'uv run meowdb serve --port 8001',
    env: {
      MEOWDB_DATA_DIR: DATA_DIR,
      MEOWDB_HOST: '127.0.0.1',
    },
    url: 'http://127.0.0.1:8001',
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
  projects: [
    {
      name: 'e2e',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'screenshots',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1440, height: 900 },
      },
    },
    {
      name: 'screenshots-mobile',
      use: {
        ...devices['Pixel 5'],
        viewport: { width: 390, height: 844 },
      },
    },
  ],
});
