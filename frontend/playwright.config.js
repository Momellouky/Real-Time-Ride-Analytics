import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  workers: 1,
  timeout: 60000,
  use: { baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    browserName: 'chromium', viewport: { width: 1360, height: 1000 },
    screenshot: 'only-on-failure', trace: 'retain-on-failure' },
});
