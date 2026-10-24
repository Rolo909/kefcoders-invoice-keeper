/**
 * Двое одновременно открыли «Отметить оплату» одного периода: второй не должен оплатить повторно
 * и должен увидеть, кто и когда уже оплатил.
 */
import { expect, test, type Browser, type Page } from '@playwright/test';
import { ADMIN, ANNA, apiAs, loginUi, ru, serverDay, uniqueName } from './helpers';

async function openMarkDialog(browser: Browser, account: typeof ADMIN, payment: string, due: string): Promise<Page> {
  const page = await (await browser.newContext()).newPage();
  await loginUi(page, account);
  await page.goto('/occurrences');
  await page.getByLabel('Платёж').selectOption({ label: payment });
  await page.getByRole('button', { name: `Отметить оплату: ${payment}, срок ${ru(due)}` }).click();
  await expect(page.getByRole('dialog').getByLabel('Фактическая дата оплаты')).toBeVisible();
  return page;
}

test('второй плательщик видит «уже оплачено», оплата не повторяется', async ({ browser, request }) => {
  const admin = await apiAs(request, ADMIN);
  const name = uniqueName('E2E Двойная оплата');
  const due = await serverDay(admin, 5);
  const today = await serverDay(admin);
  const payment = await admin.post('/recurring-payments', {
    name, amount: '1500', currency: 'RUB', period: 'monthly', next_due_date: due,
  });

  const annaPage = await openMarkDialog(browser, ANNA, name, due);
  const adminPage = await openMarkDialog(browser, ADMIN, name, due);

  await annaPage.getByRole('dialog').locator('button[type="submit"]').click();
  await expect(annaPage.getByText(`Оплата отмечена: «${name}»`)).toBeVisible();

  await adminPage.getByRole('dialog').locator('button[type="submit"]').click();
  await expect(adminPage.getByRole('dialog').getByText(`Уже оплачено: Анна Ковалёва, ${ru(today)}. Обновите страницу.`)).toBeVisible();

  const period = await admin.get(`/payment-occurrences/${payment.next_occurrence.id}`);
  expect(period.paid_by.login).toBe(ANNA.login);
  expect(period.history.map((h: { action: string }) => h.action)).toEqual(['occurrence.mark_paid']);
});
