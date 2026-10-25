/**
 * Сценарий демонстрации из кейса — через интерфейс панели, шаг за шагом.
 * Данные для особых случаев готовятся через API, действия выполняются кликами.
 */
import { expect, test, type Page } from '@playwright/test';
import { ADMIN, ANNA, apiAs, loginUi, ru, serverDay, uniqueName } from './helpers';

test.describe.configure({ mode: 'serial' });

const PAYMENT = uniqueName('E2E Облачное хранилище');
let dueDate = '';

async function logout(page: Page) {
  await page.goto('/settings');
  await page.getByRole('button', { name: 'Выйти' }).click();
  await expect(page).toHaveURL(/\/login/);
}

async function openPeriodsOf(page: Page, paymentName: string) {
  await page.goto('/occurrences');
  await page.getByLabel('Платёж').selectOption({ label: paymentName });
}

test('1–2. администратор входит и добавляет регулярный платёж', async ({ page, request }) => {
  const admin = await apiAs(request, ADMIN);
  dueDate = await serverDay(admin, 2);

  await loginUi(page, ADMIN);
  await page.getByRole('button', { name: 'Новый платёж' }).click();
  const dialog = page.getByRole('dialog', { name: 'Новый регулярный платёж' });
  await dialog.getByLabel('Название').fill(PAYMENT);
  await dialog.getByLabel('Сумма').fill('990');
  await dialog.getByLabel('Валюта').selectOption('RUB');
  await dialog.getByLabel('Периодичность').selectOption('monthly');
  await dialog.getByLabel('Дата ближайшей оплаты').fill(dueDate);
  await dialog.getByRole('button', { name: 'Создать платёж' }).click();

  await expect(dialog).toBeHidden();
  const { items } = await admin.get(`/recurring-payments?q=${encodeURIComponent(PAYMENT)}`);
  expect(items).toHaveLength(1);
  expect(items[0].next_occurrence.due_date).toBe(dueDate);
});

test('3. напоминание уходит сразу и без дублей', async ({ request }) => {
  const admin = await apiAs(request, ADMIN);
  const [payment] = (await admin.get(`/recurring-payments?q=${encodeURIComponent(PAYMENT)}`)).items;

  // Повторная проверка worker'а (раз в минуту) не должна создать второе напоминание.
  await expect
    .poll(async () => (await admin.get(`/payment-occurrences/${payment.next_occurrence.id}`)).reminders.length, {
      timeout: 15_000,
    })
    .toBeGreaterThan(0);
  const { reminders } = await admin.get(`/payment-occurrences/${payment.next_occurrence.id}`);
  const channels = reminders.map((r: { channel: string }) => r.channel);
  expect(new Set(channels).size).toBe(channels.length); // по одной записи на канал
  expect(reminders.every((r: { kind: string }) => r.kind === 'before_due')).toBeTruthy();

  // Каналы обрабатываются по очереди (Telegram, почта, колокольчик) — ждём, пока дойдёт до колокольчика.
  await expect
    .poll(async () => (await admin.get('/inbox')).items.some((i: { payment_name: string }) => i.payment_name === PAYMENT), {
      timeout: 30_000,
    })
    .toBeTruthy();
});

test('4. пользователь входит и отмечает оплату', async ({ page, request }) => {
  await loginUi(page, ADMIN);
  await logout(page);
  await loginUi(page, ANNA);

  await openPeriodsOf(page, PAYMENT);
  await page.getByRole('button', { name: `Отметить оплату: ${PAYMENT}, срок ${ru(dueDate)}` }).click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByLabel('Фактическая дата оплаты')).toBeVisible();
  await dialog.locator('button[type="submit"]').click();

  await expect(page.getByText(`Оплата отмечена: «${PAYMENT}»`)).toBeVisible();
  const anna = await apiAs(request, ANNA);
  const [payment] = (await anna.get(`/recurring-payments?q=${encodeURIComponent(PAYMENT)}`)).items;
  const paid = (await anna.get(`/recurring-payments/${payment.id}`)).occurrences.find(
    (o: { due_date: string }) => o.due_date === dueDate,
  );
  expect(paid.status).toBe('paid');
  expect(paid.paid_by.login).toBe('anna');
});

test('5. просроченный платёж виден и находится фильтром', async ({ page }) => {
  await loginUi(page, ANNA);
  await page.goto('/occurrences');

  await page.getByRole('button', { name: 'Просрочено', exact: true }).click();

  await expect(page.getByText(/Найдено \d+ период/)).toBeVisible();
  await expect(page.getByText(/просрочено на \d+ д/).first()).toBeVisible();
  await expect(page.getByText('ОПЛАЧЕНО', { exact: true })).toHaveCount(0);
});

test('6. исправление фактической даты убирает ошибочную просрочку', async ({ page, request }) => {
  // Подготовка: период, оплаченный через 3 дня после срока.
  const admin = await apiAs(request, ADMIN);
  const name = uniqueName('E2E Подписка');
  const due = await serverDay(admin, -10);
  const created = await admin.post('/recurring-payments', { name, amount: '15', currency: 'EUR', next_due_date: due });
  const lateDate = await serverDay(admin, -7);
  const late = await admin.patch(`/payment-occurrences/${created.next_occurrence.id}`, { status: 'paid', paid_date: lateDate });
  expect(late.state).toBe('paid_late');

  await loginUi(page, ANNA);
  await openPeriodsOf(page, name);
  await page.getByRole('button', { name: `Действия с оплатой: ${name}, срок ${ru(due)}` }).click();
  await page.getByText('Изменить дату оплаты', { exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Новая фактическая дата').fill(due);
  await dialog.locator('button[type="submit"]').click();

  const anna = await apiAs(request, ANNA);
  await expect
    .poll(async () => (await anna.get(`/payment-occurrences/${created.next_occurrence.id}`)).state)
    .toBe('paid');
  const fixed = await anna.get(`/payment-occurrences/${created.next_occurrence.id}`);
  expect(fixed.is_overdue).toBe(false);
  expect(fixed.due_date).toBe(due); // срок не изменился
  expect(fixed.history.map((h: { action: string }) => h.action)).toContain('occurrence.change_paid_date');
});

test('7. следующий период — с отдельным статусом', async ({ page, request }) => {
  const anna = await apiAs(request, ANNA);
  const [payment] = (await anna.get(`/recurring-payments?q=${encodeURIComponent(PAYMENT)}`)).items;

  await loginUi(page, ANNA);
  await page.goto(`/recurring-payments/${payment.id}`);

  await expect(page.getByRole('heading', { name: PAYMENT })).toBeVisible();
  const detail = await anna.get(`/recurring-payments/${payment.id}`);
  const next = detail.occurrences.find((o: { due_date: string }) => o.due_date > dueDate);
  expect(next.status).toBe('unpaid');
  await expect(page.getByRole('button', { name: `Отметить оплату: ${PAYMENT}, срок ${ru(next.due_date)}` })).toBeVisible();
});
