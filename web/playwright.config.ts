import { defineConfig, devices } from '@playwright/test'

/**
 * Browser suite — blueprint/wp/WP14-quality.md §2.3-2.4. It runs against the compose stack
 * (`scripts/e2e.sh`), which serves a frozen demo database; nothing here mocks the network.
 */
export default defineConfig({
  testDir: './e2e',
  testMatch: '*.e2e.ts',
  fullyParallel: false, // the favorite journey writes to the one demo database
  workers: 1,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5199',
    trace: 'retain-on-failure',
  },
  expect: {
    toHaveScreenshot: { maxDiffPixelRatio: 0.01 },
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } }],
})
