/**
 * Команды в имитации API — то же поведение должен дать бэкенд (docs/teams-api.md).
 * Запросы идут через fetch, как из панели; данные — тестовые из db.ts.
 */
import { setupServer } from 'msw/node';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Occurrence, Page, RecurringPayment, Team } from '../api/types';

const store = new Map<string, string>();
vi.stubGlobal('localStorage', {
  getItem: (k: string) => store.get(k) ?? null,
  setItem: (k: string, v: string) => void store.set(k, String(v)),
  removeItem: (k: string) => void store.delete(k),
});
vi.stubGlobal('location', new URL('http://localhost/'));

const { handlers } = await import('./handlers');
const { today } = await import('./db');
const server = setupServer(...handlers);
const API = 'http://localhost/api/v1';

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterAll(() => server.close());
beforeEach(() => store.clear()); // заново тестовые данные и без сессии

type Res<T = unknown> = { status: number; body: T };
async function call<T = unknown>(method: string, path: string, data?: unknown): Promise<Res<T>> {
  const r = await fetch(`${API}${path}`, {
    method, headers: data === undefined ? undefined : { 'Content-Type': 'application/json' }, body: data === undefined ? undefined : JSON.stringify(data),
  });
  return { status: r.status, body: r.status === 204 ? (null as T) : await r.json() };
}
const get = <T,>(path: string) => call<T>('GET', path);

const ACCOUNTS = { admin: 'admin12345', anna: 'anna12345', oleg: 'oleg12345' } as const;
async function loginAs(login: keyof typeof ACCOUNTS) {
  const r = await call('POST', '/auth/login', { login, password: ACCOUNTS[login] });
  expect(r.status).toBe(200);
}

async function teams() {
  await loginAs('admin');
  const { body } = await get<Page<Team>>('/teams');
  const byName = (name: string) => body.items.find((t) => t.name === name)!;
  return { kef: byName('Kefcoders'), studio: byName('Студия дизайна') };
}

describe('пользователь видит только свою команду', () => {
  it('платежи — своей команды и общие, периоды — только своей команды', async () => {
    await loginAs('anna');
    const payments = await get<Page<RecurringPayment>>('/recurring-payments?include_deleted=true');
    const occurrences = await get<Page<Occurrence>>('/payment-occurrences?limit=500');

    const names = payments.body.items.map((p) => p.name);
    expect(names).toContain('Аренда офиса');
    expect(names).toContain('Бухгалтерское сопровождение');
    expect(names).not.toContain('Аренда студии');
    expect(payments.body.items.every((p) => p.team === null || p.team.name === 'Kefcoders')).toBe(true);
    expect(occurrences.body.total).toBeGreaterThan(0);
    expect(occurrences.body.items.every((o) => o.team.name === 'Kefcoders')).toBe(true);
  });

  it('период чужой команды — 404 на чтение, отметку оплаты и вложения', async () => {
    const { studio } = await teams();
    const { body } = await get<Page<Occurrence>>(`/payment-occurrences?team_id=${studio.id}&status=unpaid&limit=500`);
    const foreign = body.items.find((o) => o.recurring_payment.name === 'Adobe Creative Cloud')!; // платёж только Студии

    await loginAs('anna');
    expect((await get(`/payment-occurrences/${foreign.id}`)).status).toBe(404);
    expect((await call('PATCH', `/payment-occurrences/${foreign.id}`, { status: 'paid' })).status).toBe(404);
    expect((await get(`/payment-occurrences/${foreign.id}/attachments`)).status).toBe(404);
    expect((await call('POST', `/payment-occurrences/${foreign.id}/attachments`, { url: 'https://bank.ru/r/1' })).status).toBe(404);
    expect((await get(`/recurring-payments/${foreign.recurring_payment_id}`)).status).toBe(404);
  });

  it('чужая команда в фильтре — 403', async () => {
    const { studio } = await teams();
    await loginAs('anna');
    for (const path of ['/payment-occurrences', '/recurring-payments', '/payments/summary', '/payments/calendar', '/budgets']) {
      expect((await get(`${path}?team_id=${studio.id}`)).status, path).toBe(403);
    }
  });

  it('колокольчик и бюджеты — только своей команды', async () => {
    const { kef } = await teams();
    await loginAs('anna');
    const inbox = await get<{ items: { team: { name: string } }[] }>('/inbox');
    const budgets = await get<{ team_id: string }[]>('/budgets');

    expect(inbox.body.items.length).toBeGreaterThan(0);
    expect(inbox.body.items.every((i) => i.team.name === 'Kefcoders')).toBe(true);
    expect(budgets.body.length).toBeGreaterThan(0);
    expect(budgets.body.every((b) => b.team_id === kef.id)).toBe(true);
  });

  it('командами управляет только администратор', async () => {
    await loginAs('anna');
    expect((await get('/teams')).status).toBe(403);
    expect((await call('POST', '/teams', { name: 'Своя команда', telegram_chat_id: null })).status).toBe(403);
  });
});

describe('общий платёж', () => {
  it('у каждой команды свой период; оплата одной не меняет период другой', async () => {
    await loginAs('admin');
    const created = await call<RecurringPayment>('POST', '/recurring-payments', {
      name: 'Общий сервис', amount: '1000', currency: 'RUB', period: 'monthly', next_due_date: today(), team_id: null,
    });
    expect(created.status).toBe(201);
    expect(created.body.team).toBeNull();
    const due = `/payment-occurrences?recurring_payment_id=${created.body.id}&date_from=${today()}&date_to=${today()}`;
    const all = await get<Page<Occurrence>>(due);
    expect(all.body.items.map((o) => o.team.name).sort()).toEqual(['Kefcoders', 'Студия дизайна']);

    await loginAs('anna');
    const [mine] = (await get<Page<Occurrence>>(due)).body.items;
    expect((await call('PATCH', `/payment-occurrences/${mine.id}`, { status: 'paid' })).status).toBe(200);

    await loginAs('oleg');
    const theirs = (await get<Page<Occurrence>>(due)).body.items;
    expect(theirs).toHaveLength(1);
    expect(theirs[0].team.name).toBe('Студия дизайна');
    expect(theirs[0].status).toBe('unpaid');
  });

  it('без team_id платёж общий — API кейса без команд работает как раньше', async () => {
    await loginAs('admin');
    const created = await call<RecurringPayment>('POST', '/recurring-payments', {
      name: 'Без команды', amount: '10', currency: 'USD', next_due_date: today(), period: 'monthly',
    });
    expect(created.status).toBe(201);
    expect(created.body.team).toBeNull();
  });

  it('платёж команды видит и оплачивает только она', async () => {
    const { studio } = await teams();
    const created = await call<RecurringPayment>('POST', '/recurring-payments', {
      name: 'Только студии', amount: '10', currency: 'EUR', period: 'monthly', next_due_date: today(), team_id: studio.id,
    });
    expect(created.body.team?.name).toBe('Студия дизайна');

    await loginAs('anna');
    expect((await get(`/recurring-payments/${created.body.id}`)).status).toBe(404);
    await loginAs('oleg');
    expect((await get(`/recurring-payments/${created.body.id}`)).status).toBe(200);
  });

  it('администратор открывает платёж команды по ссылке при любой выбранной команде', async () => {
    const { kef, studio } = await teams();
    const { body } = await get<Page<RecurringPayment>>(`/recurring-payments?team_id=${studio.id}`);
    const rent = body.items.find((p) => p.name === 'Аренда студии')!;
    const detail = await get<{ occurrences: Occurrence[] }>(`/recurring-payments/${rent.id}?team_id=${kef.id}`);

    expect(detail.status).toBe(200);
    expect(detail.body.occurrences.length).toBeGreaterThan(0);
    expect(detail.body.occurrences.every((o) => o.team.name === 'Студия дизайна')).toBe(true);
  });

  it('неизвестная команда — 422', async () => {
    await loginAs('admin');
    const r = await call('POST', '/recurring-payments', {
      name: 'X', amount: '10', currency: 'EUR', period: 'monthly', next_due_date: today(), team_id: '00000000-0000-0000-0000-000000000000',
    });
    expect(r.status).toBe(422);
  });
});

describe('команды', () => {
  it('новая команда получает общие платежи с ближайшего срока, без просрочек', async () => {
    await loginAs('admin');
    const created = await call<Team>('POST', '/teams', { name: 'Отдел продаж', telegram_chat_id: '-1001234567890' });
    expect(created.status).toBe(201);
    expect(created.body).toMatchObject({ name: 'Отдел продаж', telegram_chat_id: '-1001234567890', members_count: 0 });

    const { body } = await get<Page<Occurrence>>(`/payment-occurrences?team_id=${created.body.id}&limit=500`);
    const names = new Set(body.items.map((o) => o.recurring_payment.name));
    expect(names).toEqual(new Set(['Бухгалтерское сопровождение', 'Яндекс 360 для бизнеса']));
    expect(body.items.every((o) => o.due_date >= today() && o.state !== 'overdue')).toBe(true);
  });

  it('название уникально без учёта регистра — 409', async () => {
    await loginAs('admin');
    const r = await call<{ code: string }>('POST', '/teams', { name: 'kefcoders', telegram_chat_id: null });
    expect(r.status).toBe(409);
    expect(r.body.code).toBe('team_name_taken');
  });

  it('удалить можно только пустую команду', async () => {
    const { studio } = await teams();
    const busy = await call<{ code: string }>('DELETE', `/teams/${studio.id}`);
    expect(busy.status).toBe(409);
    expect(busy.body.code).toBe('team_not_empty');

    const empty = await call<Team>('POST', '/teams', { name: 'По ошибке', telegram_chat_id: null });
    expect((await call('DELETE', `/teams/${empty.body.id}`)).status).toBe(204);
    expect((await get(`/payment-occurrences?team_id=${empty.body.id}`)).status).toBe(404);
  });

  it('пользователь создаётся только в команде', async () => {
    const { studio } = await teams();
    const without = await call('POST', '/users', { login: 'no.team', password: 'long-enough' });
    const within = await call<{ team: { name: string } }>('POST', '/users', { login: 'vera', password: 'long-enough', team_id: studio.id });

    expect(without.status).toBe(422);
    expect(within.status).toBe(201);
    expect(within.body.team.name).toBe('Студия дизайна');
  });

  it('итоги всех команд — сумма итогов каждой команды', async () => {
    const { kef, studio } = await teams();
    type Summary = { totals: { currency: string; planned: string; paid: string }[] };
    const [all, a, b] = await Promise.all(['', `&team_id=${kef.id}`, `&team_id=${studio.id}`]
      .map((q) => get<Summary>(`/payments/summary?date_from=${today().slice(0, 8)}01&date_to=${today()}${q}`)));
    for (const [i, t] of all.body.totals.entries()) {
      expect(Number(t.planned)).toBeCloseTo(Number(a.body.totals[i].planned) + Number(b.body.totals[i].planned));
      expect(Number(t.paid)).toBeCloseTo(Number(a.body.totals[i].paid) + Number(b.body.totals[i].paid));
    }
  });

  it('бюджет сохраняется только для команды', async () => {
    await loginAs('admin');
    const r = await call('PUT', '/budgets', [{ currency: 'RUB', period_type: 'month', year: 2026, month: 10, amount: '100.00' }]);
    expect(r.status).toBe(422);
  });
});
