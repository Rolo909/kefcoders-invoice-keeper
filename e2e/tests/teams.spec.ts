/**
 * Команды: один администратор, у каждой команды свои платежи, общий платёж каждая команда оплачивает сама.
 * Всё готовится через интерфейс в одной сессии браузера, поэтому сценарий идёт и на стеке, и на имитации API.
 */
import { expect, test, type Page } from '@playwright/test';
import { ADMIN, ANNA, loginUi, ru, uniqueName } from './helpers';

const stamp = Date.now().toString(36);
const TEAM = `E2E Команда ${stamp}`;
const MEMBER = { login: `e2e.${stamp}`, password: 'e2e-pass-123' };
const TEAM_PAYMENT = uniqueName('E2E Платёж команды');
const COMMON_PAYMENT = uniqueName('E2E Общий платёж');

/** «Сегодня» в часовом поясе приложения (APP_TIMEZONE, по умолчанию Europe/Moscow) ± дни. */
function day(shift: number) {
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/Moscow' }).format(new Date());
  const d = new Date(`${today}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + shift);
  return d.toISOString().slice(0, 10);
}
const DUE = day(5);

async function logout(page: Page) {
  await page.goto('/settings');
  await page.getByRole('button', { name: 'Выйти' }).click();
  await expect(page).toHaveURL(/\/login/);
}

async function createPayment(page: Page, name: string, whom: string) {
  await page.getByRole('button', { name: 'Новый платёж' }).click();
  const dialog = page.getByRole('dialog', { name: 'Новый регулярный платёж' });
  await dialog.getByLabel('Название').fill(name);
  await dialog.getByLabel('Для кого').selectOption({ label: whom });
  await dialog.getByLabel('Сумма').fill('500');
  await dialog.getByLabel('Дата ближайшей оплаты').fill(DUE);
  await dialog.getByRole('button', { name: 'Создать платёж' }).click();
  await expect(dialog).toBeHidden();
}

async function pickTeam(page: Page, name: string) {
  await page.getByRole('button', { name: /^Команда: .*Сменить$/ }).click();
  await page.getByRole('menuitem', { name, exact: true }).click();
  await expect(page.getByRole('button', { name: /^Команда: .*Сменить$/ })).toContainText(name);
}

test('команды разделены, общий платёж каждая команда оплачивает сама', async ({ page }) => {
  let memberPeriodUrl = '';

  await test.step('администратор создаёт команду и пользователя в ней', async () => {
    await loginUi(page, ADMIN);
    await page.goto('/teams');
    await page.getByRole('button', { name: 'Новая команда' }).click();
    const team = page.getByRole('dialog', { name: 'Новая команда' });
    await team.getByLabel('Название').fill(TEAM);
    await team.getByRole('button', { name: 'Создать команду' }).click();
    await expect(team).toBeHidden();
    await expect(page.getByRole('row').filter({ hasText: TEAM })).toBeVisible();

    await page.goto('/users');
    await page.getByRole('button', { name: 'Новый пользователь' }).click();
    const user = page.getByRole('dialog', { name: 'Новый пользователь' });
    await user.getByLabel('Логин').fill(MEMBER.login);
    await user.getByLabel('Пароль', { exact: true }).fill(MEMBER.password);
    await user.getByLabel('Команда').selectOption({ label: TEAM });
    await user.getByRole('button', { name: 'Создать пользователя' }).click();
    await expect(user).toBeHidden();
    await expect(page.getByRole('row').filter({ hasText: MEMBER.login })).toContainText(TEAM);
  });

  await test.step('администратор добавляет платёж команды и общий платёж', async () => {
    await createPayment(page, TEAM_PAYMENT, TEAM);
    await createPayment(page, COMMON_PAYMENT, 'Все команды — общий платёж');

    await pickTeam(page, TEAM);
    await page.goto('/recurring-payments');
    await expect(page.getByRole('link', { name: TEAM_PAYMENT })).toBeVisible();
    await expect(page.getByRole('row').filter({ hasText: COMMON_PAYMENT })).toContainText('общий');
    await pickTeam(page, 'Все команды');
    await logout(page);
  });

  await test.step('участник команды видит свои и общие платежи и оплачивает общий', async () => {
    await loginUi(page, MEMBER);
    await expect(page.getByRole('link', { name: new RegExp(`команда ${TEAM}`) })).toBeVisible();
    await page.goto('/recurring-payments');
    await expect(page.getByRole('link', { name: TEAM_PAYMENT })).toBeVisible();
    await expect(page.getByRole('link', { name: COMMON_PAYMENT })).toBeVisible();

    await page.goto('/occurrences');
    await page.getByLabel('Платёж').selectOption({ label: COMMON_PAYMENT });
    await page.getByRole('button', { name: `Отметить оплату: ${COMMON_PAYMENT}, срок ${ru(DUE)}` }).click();
    await page.getByRole('dialog').locator('button[type="submit"]').click();
    await expect(page.getByText(`Оплата отмечена: «${COMMON_PAYMENT}»`)).toBeVisible();

    // В списке два периода (этот месяц и следующий) — открываем оплаченный.
    await page.getByRole('row').filter({ hasText: 'Оплачено' }).getByRole('button', { name: COMMON_PAYMENT, exact: true }).click();
    memberPeriodUrl = (await page.getByRole('link', { name: 'Открыть страницу периода' }).getAttribute('href')) ?? '';
    expect(memberPeriodUrl).toMatch(/^\/occurrences\/.+/);
    await logout(page);
  });

  await test.step('другая команда не видит чужой платёж, а свой период общего платежа у неё не оплачен', async () => {
    await loginUi(page, ANNA);
    await page.goto('/recurring-payments');
    await expect(page.getByRole('link', { name: COMMON_PAYMENT })).toBeVisible();
    await expect(page.getByRole('link', { name: TEAM_PAYMENT })).toHaveCount(0);

    await page.goto('/occurrences');
    await page.getByLabel('Платёж').selectOption({ label: COMMON_PAYMENT });
    await expect(page.getByRole('button', { name: `Отметить оплату: ${COMMON_PAYMENT}, срок ${ru(DUE)}` })).toBeVisible();

    await page.goto(memberPeriodUrl);
    await expect(page.getByRole('heading', { name: 'Период не найден' })).toBeVisible();
    await logout(page);
  });

  await test.step('администратор видит отметку по каждой команде на странице общего платежа', async () => {
    await loginUi(page, ADMIN);
    await page.goto('/recurring-payments');
    await page.getByRole('link', { name: COMMON_PAYMENT }).click();
    await expect(page.getByRole('columnheader', { name: 'Команда' })).toBeVisible();
    await expect(page.getByRole('row').filter({ hasText: TEAM }).filter({ hasText: ru(DUE) })).toContainText('Оплачено');
  });
});
