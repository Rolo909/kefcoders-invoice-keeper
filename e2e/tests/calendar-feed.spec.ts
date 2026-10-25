/**
 * Подписка на календарь: ссылка из профиля отдаёт сроки в формате iCalendar без входа в панель,
 * а после отключения перестаёт работать.
 */
import { expect, test } from '@playwright/test';
import { ANNA, loginUi } from './helpers';

test('ссылка на календарь из профиля отдаёт сроки и отключается', async ({ page, playwright, baseURL }) => {
  await loginUi(page, ANNA);
  await page.goto('/settings');
  await page.getByRole('button', { name: 'Получить ссылку' }).click();

  const link = page.getByLabel('Ссылка для подписки');
  await expect(link).toHaveValue(/\/api\/v1\/calendar\/[\w-]+\.ics$/);
  const url = new URL(await link.inputValue());
  await expect(page.getByRole('link', { name: 'Открыть в приложении календаря' })).toHaveAttribute('href', /^webcal:\/\//);

  // Календарный сервис приходит без cookie — отдельный клиент без входа.
  const calendarApp = await playwright.request.newContext({ baseURL, ignoreHTTPSErrors: true });
  const feed = await calendarApp.get(url.pathname);
  expect(feed.status()).toBe(200);
  expect(feed.headers()['content-type']).toContain('text/calendar');
  const body = await feed.text();
  expect(body.startsWith('BEGIN:VCALENDAR')).toBeTruthy();
  expect(body).toContain('BEGIN:VEVENT');
  expect(body).toContain('DTSTART;VALUE=DATE:');

  await page.getByRole('button', { name: 'Отключить ссылку' }).click();
  await expect(page.getByRole('button', { name: 'Получить ссылку' })).toBeVisible();
  expect((await calendarApp.get(url.pathname)).status()).toBe(404);
  await calendarApp.dispose();
});
