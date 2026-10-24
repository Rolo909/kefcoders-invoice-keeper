import { expect, test } from '@playwright/test';
import { ANNA, loginUi } from './helpers';

test('без входа панель и данные недоступны', async ({ page, request }) => {
  await page.goto('/occurrences');

  await expect(page).toHaveURL(/\/login/);
  expect((await request.get('/api/v1/payment-occurrences')).status()).toBe(401);
});

test('пользователь не видит разделов администратора и не может их открыть', async ({ page }) => {
  await loginUi(page, ANNA);

  const nav = page.getByRole('navigation').first();
  await expect(nav.getByRole('link', { name: 'Периоды' })).toBeVisible();
  await expect(nav.getByRole('link', { name: 'Пользователи' })).toHaveCount(0);
  await expect(nav.getByRole('link', { name: 'Журнал' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Новый платёж' })).toHaveCount(0);

  await page.goto('/users');
  await expect(page.getByText('Раздел доступен только администратору')).toBeVisible();
});

test('неверный пароль — понятная ошибка', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Логин').fill('anna');
  await page.getByLabel('Пароль', { exact: true }).fill('wrong-password');
  await page.getByRole('button', { name: 'Войти' }).click();

  await expect(page.getByRole('alert')).toContainText('Неверный логин или пароль');
});
