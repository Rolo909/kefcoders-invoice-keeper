import { defineConfig, devices } from '@playwright/test';

// Тесты идут против уже запущенного стека (`docker compose up -d`) с тестовыми данными.
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  workers: 1, // сценарий меняет общие данные — по очереди
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://localhost:8080',
    // Только для проверки с самоподписанным сертификатом; настоящий сертификат сервера не требует этого.
    ignoreHTTPSErrors: process.env.E2E_IGNORE_HTTPS_ERRORS === '1',
    locale: 'ru-RU',
    timezoneId: 'Europe/Moscow',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
