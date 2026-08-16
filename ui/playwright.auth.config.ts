import path from 'path';

import { defineConfig, devices } from '@playwright/test';

export const DATA_DIR = '/tmp/meowdb-auth-e2e-data';
const REPO_ROOT = path.resolve(__dirname, '..');

export default defineConfig({
  testMatch: 'auth.spec.ts',
  use: {
    baseURL: 'http://127.0.0.1:8002',
  },
  webServer: {
    command: `rm -rf ${DATA_DIR} && uv run python ui/seed.py && uv run meowdb serve --port 8002`,
    cwd: REPO_ROOT,
    env: {
      MEOWDB_DATA_DIR: DATA_DIR,
      MEOWDB_HOST: '127.0.0.1',
      MEOWDB_SESSION_SECRET: 'e2e-secret',
      MEOWDB_PASSWORD_HASH: '$2b$12$TuUAb7C.FlDDPEGXqTuQsuahVv93eMOtBbyDKXl60SWeAs1nm9bKS',
    },
    url: 'http://127.0.0.1:8002',
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
  ],
});
