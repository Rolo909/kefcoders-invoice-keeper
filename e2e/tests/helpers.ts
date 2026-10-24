import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const ADMIN = { login: process.env.E2E_ADMIN_LOGIN ?? 'admin', password: process.env.E2E_ADMIN_PASSWORD ?? 'change-me' };
export const ANNA = { login: 'anna', password: 'anna12345' };

type Account = { login: string; password: string };

/** Вход через форму панели. */
export async function loginUi(page: Page, account: Account) {
  await page.goto('/login');
  await page.getByLabel('Логин').fill(account.login);
  await page.getByLabel('Пароль', { exact: true }).fill(account.password);
  await page.getByRole('button', { name: 'Войти' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Клиент API с токеном — для подготовки данных и проверок, которых не видно в интерфейсе. */
export async function apiAs(request: APIRequestContext, account: Account) {
  const response = await request.post('/api/v1/auth/login', { data: account });
  expect(response.ok(), await response.text()).toBeTruthy();
  const { access_token: token } = await response.json();
  const headers = { Authorization: `Bearer ${token}` };
  return {
    get: async (path: string) => {
      const r = await request.get(`/api/v1${path}`, { headers });
      expect(r.ok(), `${path}: ${await r.text()}`).toBeTruthy();
      return r.json();
    },
    post: async (path: string, data: unknown) => {
      const r = await request.post(`/api/v1${path}`, { headers, data });
      expect(r.ok(), `${path}: ${await r.text()}`).toBeTruthy();
      return r.json();
    },
    patch: async (path: string, data: unknown) => {
      const r = await request.patch(`/api/v1${path}`, { headers, data });
      expect(r.ok(), `${path}: ${await r.text()}`).toBeTruthy();
      return r.json();
    },
    raw: { headers },
  };
}

export type Api = Awaited<ReturnType<typeof apiAs>>;

/** «Сегодня» сервера (часовой пояс APP_TIMEZONE), ± дни, в формате ГГГГ-ММ-ДД. */
export async function serverDay(api: Api, shiftDays = 0) {
  const { server_today: today } = await api.get('/auth/me');
  const date = new Date(`${today}T12:00:00Z`);
  date.setUTCDate(date.getUTCDate() + shiftDays);
  return date.toISOString().slice(0, 10);
}

/** 2026-10-26 → 26.10.2026, как в подписях кнопок панели. */
export const ru = (iso: string) => iso.split('-').reverse().join('.');

export const uniqueName = (prefix: string) => `${prefix} ${Date.now().toString(36)}`;

/** Команда пользователя: платёж для неё виден и оплачивается только её участниками. */
export async function teamIdOf(request: APIRequestContext, account: Account) {
  const { user } = await (await apiAs(request, account)).get('/auth/me');
  return user.team.id as string;
}
