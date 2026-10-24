import { delay, http, HttpResponse } from 'msw';
import { addDays, monthRange, parseISO, type ISODate } from '../lib/dates';
import type {
  Attachment, AuditLog, Budget, CalendarDay, CurrencyTotal, InboxItem, NotificationLog, Occurrence, RecurringPayment, User, UserBrief,
} from '../api/types';
import {
  audit, daysOverdue, isOverdue, load, nowIso, plannedInRange, refresh, save, stateOf, today, uid, ensureOccurrences, dispatchReminders,
  type Db, type DbAttachment, type DbOccurrence, type DbPayment, type DbUser,
} from './db';

const API = '/api/v1';
const SESSION_KEY = 'ik-mock-session';
const CURRENCIES = ['RUB', 'USD', 'EUR'] as const;
const PERIODS = ['weekly', 'monthly', 'quarterly', 'yearly'] as const;
const files = new Map<string, Blob>();
const loginAttempts = new Map<string, number[]>();

let db: Db = load();

const json = (data: unknown, status = 200) => HttpResponse.json(data as never, { status });
const fail = (status: number, detail: string, code: string) => HttpResponse.json({ detail, code }, { status });
const noContent = () => new HttpResponse(null, { status: 204 });

function session(): DbUser | null {
  let id: string | null = null;
  try {
    id = localStorage.getItem(SESSION_KEY);
  } catch {
    id = null;
  }
  return db.users.find((u) => u.id === id) ?? null;
}

type Ctx = { me: DbUser; t: ISODate; url: URL };
type Handler = (ctx: Ctx, req: Request, params: Record<string, string>) => Promise<Response> | Response;

function guarded(handler: Handler, adminOnly = false) {
  return async ({ request, params }: { request: Request; params: Record<string, string | readonly string[] | undefined> }) => {
    await delay(120);
    db = load();
    const me = session();
    if (!me) return fail(401, 'Войдите в систему', 'unauthorized');
    if (adminOnly && me.role !== 'admin') return fail(403, 'Недостаточно прав: действие доступно только администратору', 'forbidden');
    refresh(db);
    const res = await handler({ me, t: today(), url: new URL(request.url) }, request, params as Record<string, string>);
    save(db);
    return res;
  };
}

// ---------- serializers ----------

const brief = (id: string | null): UserBrief | null => {
  const u = db.users.find((x) => x.id === id);
  return u ? { id: u.id, login: u.login, full_name: u.full_name } : null;
};

const userOut = (u: DbUser): User => ({
  id: u.id, login: u.login, full_name: u.full_name, email: u.email, role: u.role, is_system: u.is_system,
  telegram_linked: u.telegram_linked, notify_email: u.notify_email, created_at: u.created_at,
});

const paymentOf = (o: DbOccurrence) => db.payments.find((p) => p.id === o.recurring_payment_id)!;

function occOut(o: DbOccurrence, t: ISODate): Occurrence {
  const p = paymentOf(o);
  const reminder = db.notifications
    .filter((n) => n.occurrence_id === o.id && n.channel === 'telegram' && n.kind === 'before_due' && n.status === 'sent')
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
  return {
    id: o.id, recurring_payment_id: p.id, recurring_payment: { id: p.id, name: p.name, period: p.period, is_deleted: !!p.deleted_at },
    seq: o.seq, due_date: o.due_date, amount: o.amount, currency: o.currency, status: o.status, paid_date: o.paid_date,
    paid_by: brief(o.paid_by), paid_marked_at: o.paid_marked_at, note: o.note, is_overdue: isOverdue(o, t), state: stateOf(o, t),
    days_overdue: daysOverdue(o, t), attachments_count: db.attachments.filter((a) => a.occurrence_id === o.id).length,
    last_reminder_at: reminder?.sent_at ?? null,
  };
}

function nextOccurrence(p: DbPayment, t: ISODate) {
  const list = db.occurrences.filter((o) => o.recurring_payment_id === p.id).sort((a, b) => a.due_date.localeCompare(b.due_date));
  const next = list.find((o) => o.status === 'unpaid') ?? list.find((o) => o.due_date >= t) ?? null;
  return next ? occOut(next, t) : null;
}

const paymentOut = (p: DbPayment, t: ISODate): RecurringPayment => ({
  id: p.id, name: p.name, description: p.description, amount: p.amount, currency: p.currency, period: p.period,
  first_due_date: p.first_due_date, end_date: p.end_date, is_active: p.is_active, deleted_at: p.deleted_at,
  created_by: brief(p.created_by)!, created_at: p.created_at, next_occurrence: nextOccurrence(p, t),
});

const auditOut = (a: Db['audit'][number]): AuditLog => ({ ...a, actor: brief(a.actor_id) });

function notifOut(n: Db['notifications'][number]): NotificationLog {
  const o = db.occurrences.find((x) => x.id === n.occurrence_id);
  return {
    id: n.id, occurrence_id: n.occurrence_id, payment_name: o ? paymentOf(o).name : 'Период удалён', due_date: o?.due_date ?? '',
    channel: n.channel, kind: n.kind, status: n.status, attempts: n.attempts, last_error: n.last_error, sent_at: n.sent_at, created_at: n.created_at,
  };
}

const attachmentOut = (a: DbAttachment): Attachment => ({ ...a, uploaded_by: brief(a.uploaded_by)! });

const occDetails = (o: DbOccurrence, extra: Record<string, string | null> = {}) => ({ payment_name: paymentOf(o).name, due_date: o.due_date, ...extra });

function page<T>(items: T[], url: URL, defLimit = 50) {
  const limit = Math.min(500, Math.max(1, Number(url.searchParams.get('limit') ?? defLimit)));
  const offset = Math.max(0, Number(url.searchParams.get('offset') ?? 0));
  return { items: items.slice(offset, offset + limit), total: items.length, limit, offset };
}

async function body<T>(req: Request): Promise<T | null> {
  try {
    return (await req.json()) as T;
  } catch {
    return null;
  }
}

const isDate = (s: unknown): s is ISODate => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s);
const money2 = (s: unknown) => typeof s === 'string' && /^\d+(\.\d{1,2})?$/.test(s) && Number(s) > 0;
const fixed = (n: number) => n.toFixed(2);

// ---------- totals (§4.7) ----------

function totals(from: ISODate, to: ISODate, asOf: ISODate): CurrencyTotal[] {
  const { y: fy, m: fm } = parseISO(from);
  const wholeMonth = from === monthRange(from.slice(0, 7))[0] && to === monthRange(from.slice(0, 7))[1];
  const wholeYear = from === `${fy}-01-01` && to === `${fy}-12-31`;
  const planned = plannedInRange(db, from, to);
  return CURRENCIES.map((c) => {
    const list = db.occurrences.filter((o) => o.currency === c && o.due_date >= from && o.due_date <= to);
    const paidAt = (o: DbOccurrence) => o.status === 'paid' && !!o.paid_date && o.paid_date <= asOf;
    const sum = (f: (o: DbOccurrence) => boolean) => list.filter(f).reduce((s, o) => s + Number(o.amount), 0);
    const plannedSum = sum(() => true) + planned.filter((x) => x.payment.currency === c).reduce((s, x) => s + Number(x.payment.amount), 0);
    const paid = sum(paidAt);
    const budget = db.budgets.find((b) => b.currency === c && b.year === fy &&
      ((wholeMonth && b.period_type === 'month' && b.month === fm) || (wholeYear && b.period_type === 'year')));
    return {
      currency: c, planned: fixed(plannedSum), paid: fixed(paid), unpaid: fixed(plannedSum - paid),
      overdue: fixed(sum((o) => !paidAt(o) && o.due_date < asOf)), paid_late: fixed(sum((o) => paidAt(o) && o.paid_date! > o.due_date)),
      count_total: list.length + planned.filter((x) => x.payment.currency === c).length, count_paid: list.filter(paidAt).length,
      count_overdue: list.filter((o) => !paidAt(o) && o.due_date < asOf).length,
      budget: budget ? budget.amount : null, budget_left: budget ? fixed(Number(budget.amount) - plannedSum) : null,
    };
  });
}

// ---------- handlers ----------

export const handlers = [
  http.get(`${API}/health`, () => json({ status: 'ok', db: 'ok' })),

  http.post(`${API}/auth/login`, async ({ request }) => {
    await delay(250);
    db = load();
    const b = await body<{ login?: string; password?: string }>(request);
    const login = (b?.login ?? '').trim().toLowerCase();
    const now = Date.now();
    const recent = (loginAttempts.get(login) ?? []).filter((t) => now - t < 60_000);
    if (recent.length >= 5) return fail(429, 'Слишком много попыток входа. Попробуйте снова через минуту.', 'rate_limited');
    const u = db.users.find((x) => x.login.toLowerCase() === login);
    if (!u || u.password !== b?.password) {
      loginAttempts.set(login, [...recent, now]);
      audit(db, null, 'auth.login_failed', null, { login });
      save(db);
      return fail(401, 'Неверный логин или пароль', 'invalid_credentials');
    }
    loginAttempts.delete(login);
    localStorage.setItem(SESSION_KEY, u.id);
    audit(db, u, 'auth.login', ['user', u.id], {});
    save(db);
    return json({ access_token: uid(), token_type: 'bearer', expires_at: addDays(today(), 7), user: userOut(u) });
  }),

  http.get(`${API}/auth/me`, guarded(({ me, t }) => json({ user: userOut(me), server_today: t, timezone: 'Europe/Moscow' }))),

  http.patch(`${API}/auth/me`, guarded(async ({ me }, req) => {
    if (me.is_system) return fail(403, 'Учётная запись администратора задаётся в .env и не меняется через панель', 'system_user');
    const b = await body<{ email?: string | null; notify_email?: boolean }>(req);
    const email = b?.email?.trim() || null;
    if (email && !/^\S+@\S+\.\S+$/.test(email)) return fail(422, 'Введите адрес почты целиком, например name@kefcoders.ru', 'validation_error');
    if (b?.notify_email && !email) return fail(422, 'Укажите почту, чтобы получать на неё напоминания', 'validation_error');
    me.email = email;
    me.notify_email = !!b?.notify_email;
    return json(userOut(me));
  })),

  http.post(`${API}/auth/logout`, guarded(({ me }) => {
    audit(db, me, 'auth.logout', ['user', me.id], {});
    localStorage.removeItem(SESSION_KEY);
    return noContent();
  })),

  // ----- recurring payments -----
  http.get(`${API}/recurring-payments`, guarded(({ t, url }) => {
    const q = (url.searchParams.get('q') ?? '').trim().toLowerCase();
    const currency = url.searchParams.get('currency');
    const includeDeleted = url.searchParams.get('include_deleted') === 'true';
    const list = db.payments
      .filter((p) => (includeDeleted || !p.deleted_at) && (!q || p.name.toLowerCase().includes(q)) && (!currency || p.currency === currency))
      .map((p) => paymentOut(p, t))
      .sort((a, b) => Number(!!a.deleted_at) - Number(!!b.deleted_at) || (a.next_occurrence?.due_date ?? '9').localeCompare(b.next_occurrence?.due_date ?? '9'));
    return json(page(list, url, 200));
  })),

  http.get(`${API}/recurring-payments/:id`, guarded(({ t }, _req, { id }) => {
    const p = db.payments.find((x) => x.id === id);
    if (!p) return fail(404, 'Платёж не найден', 'not_found');
    const occurrences = db.occurrences.filter((o) => o.recurring_payment_id === id).sort((a, b) => b.due_date.localeCompare(a.due_date)).map((o) => occOut(o, t));
    return json({ ...paymentOut(p, t), occurrences });
  })),

  http.post(`${API}/recurring-payments`, guarded(async ({ me, t }, req) => {
    const b = await body<Record<string, unknown>>(req);
    const errors: string[] = [];
    const name = typeof b?.name === 'string' ? b.name.trim() : '';
    if (!name || name.length > 200) errors.push('Название — от 1 до 200 символов');
    if (!money2(b?.amount)) errors.push('Сумма — больше нуля, не больше двух знаков после запятой');
    if (!CURRENCIES.includes(b?.currency as never)) errors.push('Валюта — RUB, USD или EUR');
    if (!PERIODS.includes(b?.period as never)) errors.push('Периодичность — weekly, monthly, quarterly или yearly');
    if (!isDate(b?.next_due_date)) errors.push('Укажите дату ближайшей оплаты');
    if (b?.end_date && (!isDate(b.end_date) || (isDate(b?.next_due_date) && b.end_date < b.next_due_date))) errors.push('Дата окончания — не раньше даты ближайшей оплаты');
    if (errors.length) return fail(422, errors.join('. '), 'validation_error');
    const p: DbPayment = {
      id: uid(), name, description: typeof b!.description === 'string' && b!.description.trim() ? b!.description.trim() : null,
      amount: fixed(Number(b!.amount)), currency: b!.currency as DbPayment['currency'], period: b!.period as DbPayment['period'],
      first_due_date: b!.next_due_date as ISODate, end_date: (b!.end_date as ISODate) || null, is_active: true, deleted_at: null,
      created_by: me.id, created_at: nowIso(),
    };
    db.payments.push(p);
    ensureOccurrences(db, p, t);
    dispatchReminders(db, t);
    audit(db, me, 'payment.create', ['recurring_payment', p.id], { payment_name: p.name, amount: p.amount, currency: p.currency, period: p.period, first_due_date: p.first_due_date });
    return json(paymentOut(p, t), 201);
  }, true)),

  http.delete(`${API}/recurring-payments/:id`, guarded(({ me, t }, _req, { id }) => {
    const p = db.payments.find((x) => x.id === id);
    if (!p) return fail(404, 'Платёж не найден', 'not_found');
    if (p.deleted_at) return noContent();
    p.deleted_at = nowIso();
    p.is_active = false;
    const removed = new Set(db.occurrences.filter((o) => o.recurring_payment_id === id && o.due_date > t && o.status === 'unpaid').map((o) => o.id));
    db.occurrences = db.occurrences.filter((o) => !removed.has(o.id));
    db.notifications = db.notifications.filter((n) => !removed.has(n.occurrence_id) || n.status === 'sent');
    audit(db, me, 'payment.delete', ['recurring_payment', p.id], { payment_name: p.name, removed_periods: removed.size });
    return noContent();
  }, true)),

  // ----- occurrences -----
  http.get(`${API}/payment-occurrences`, guarded(({ t, url }) => {
    const sp = url.searchParams;
    const status = sp.get('status');
    const overdue = sp.get('overdue');
    const currencies = sp.getAll('currency');
    const from = sp.get('date_from');
    const to = sp.get('date_to');
    const pid = sp.get('recurring_payment_id');
    const state = sp.get('state');
    const sort = sp.get('sort') ?? 'due_date';
    const dir = sort.startsWith('-') ? -1 : 1;
    const key = sort.replace('-', '');
    const value = (o: DbOccurrence) => (key === 'amount' ? Number(o.amount) : key === 'days_overdue' ? daysOverdue(o, t) : o.due_date);
    const list = db.occurrences
      .filter((o) => (!status || o.status === status) && (overdue === null || isOverdue(o, t) === (overdue === 'true')) &&
        (!currencies.length || currencies.includes(o.currency)) && (!from || o.due_date >= from) && (!to || o.due_date <= to) &&
        (!pid || o.recurring_payment_id === pid) && (!state || stateOf(o, t) === state))
      .sort((a, b) => {
        const va = value(a), vb = value(b);
        return (va > vb ? 1 : va < vb ? -1 : paymentOf(a).name.localeCompare(paymentOf(b).name)) * dir;
      })
      .map((o) => occOut(o, t));
    return json(page(list, url));
  })),

  http.get(`${API}/payment-occurrences/:id`, guarded(({ t }, _req, { id }) => {
    const o = db.occurrences.find((x) => x.id === id);
    if (!o) return fail(404, 'Период не найден', 'not_found');
    return json({
      ...occOut(o, t),
      history: db.audit.filter((a) => a.entity_type === 'occurrence' && a.entity_id === id).map(auditOut),
      reminders: db.notifications.filter((n) => n.occurrence_id === id).sort((a, b) => b.created_at.localeCompare(a.created_at)).map(notifOut),
    });
  })),

  http.patch(`${API}/payment-occurrences/:id`, guarded(async ({ me, t }, req, { id }) => {
    const o = db.occurrences.find((x) => x.id === id);
    if (!o) return fail(404, 'Период не найден', 'not_found');
    const b = (await body<Record<string, unknown>>(req)) ?? {};
    const extra = Object.keys(b).filter((k) => k !== 'status' && k !== 'paid_date');
    if (extra.length) return fail(422, `Поля ${extra.join(', ')} менять нельзя: срок, сумма и валюта периода фиксированы`, 'validation_error');
    if (b.paid_date !== undefined && b.paid_date !== null && !isDate(b.paid_date)) return fail(422, 'Дата оплаты — в формате ГГГГ-ММ-ДД', 'validation_error');
    if (isDate(b.paid_date) && b.paid_date > t) return fail(422, 'Дата оплаты не может быть позже сегодняшней', 'validation_error');
    if (b.status === "unpaid") {
      const was = o.paid_date;
      Object.assign(o, { status: 'unpaid', paid_date: null, paid_by: null, paid_marked_at: null });
      audit(db, me, 'occurrence.mark_unpaid', ['occurrence', o.id], occDetails(o, { old_paid_date: was }));
    } else if (b.status === 'paid') {
      const date = isDate(b.paid_date) ? b.paid_date : t;
      if (o.status === 'paid') {
        const was = o.paid_date;
        o.paid_date = date;
        if (was !== date) audit(db, me, 'occurrence.change_paid_date', ['occurrence', o.id], occDetails(o, { old_paid_date: was, new_paid_date: date }));
      } else {
        Object.assign(o, { status: 'paid', paid_date: date, paid_by: me.id, paid_marked_at: nowIso() });
        audit(db, me, 'occurrence.mark_paid', ['occurrence', o.id], occDetails(o, { paid_date: date }));
      }
    } else if (b.status === undefined && isDate(b.paid_date)) {
      if (o.status !== 'paid') return fail(409, 'Сначала отметьте оплату, потом меняйте дату', 'not_paid');
      const was = o.paid_date;
      o.paid_date = b.paid_date;
      audit(db, me, 'occurrence.change_paid_date', ['occurrence', o.id], occDetails(o, { old_paid_date: was, new_paid_date: b.paid_date }));
    } else {
      return fail(422, 'Передайте status или paid_date', 'validation_error');
    }
    return json(occOut(o, t));
  })),

  // ----- attachments -----
  http.get(`${API}/payment-occurrences/:id/attachments`, guarded((_ctx, _req, { id }) =>
    json(db.attachments.filter((a) => a.occurrence_id === id).sort((a, b) => a.created_at.localeCompare(b.created_at)).map(attachmentOut)))),

  http.post(`${API}/payment-occurrences/:id/attachments`, guarded(async ({ me }, req, { id }) => {
    const o = db.occurrences.find((x) => x.id === id);
    if (!o) return fail(404, 'Период не найден', 'not_found');
    const type = req.headers.get('content-type') ?? '';
    let a: DbAttachment;
    if (type.includes('multipart/form-data')) {
      const form = await req.formData();
      const file = form.get('file');
      if (!(file instanceof File)) return fail(422, 'Выберите файл чека', 'validation_error');
      if (!/\.(pdf|png|jpe?g|webp)$/i.test(file.name)) return fail(422, 'Подходят PDF, PNG, JPG и WebP', 'unsupported_type');
      if (file.size > 10 * 1024 * 1024) return fail(422, 'Файл больше 10 МБ. Сожмите его или прикрепите ссылку', 'too_large');
      a = { id: uid(), occurrence_id: id, kind: 'file', url: null, original_name: file.name, content_type: file.type || null, size: file.size, uploaded_by: me.id, created_at: nowIso() };
      files.set(a.id, file);
    } else {
      const b = await body<{ url?: string }>(req);
      if (!b?.url || !/^https?:\/\/\S+\.\S+/.test(b.url)) return fail(422, 'Вставьте ссылку целиком, начиная с https://', 'validation_error');
      a = { id: uid(), occurrence_id: id, kind: 'link', url: b.url, original_name: b.url.replace(/^https?:\/\//, '').slice(0, 60), content_type: null, size: null, uploaded_by: me.id, created_at: nowIso() };
    }
    db.attachments.push(a);
    audit(db, me, 'attachment.add', ['occurrence', id], occDetails(o, { name: a.original_name }));
    return json(attachmentOut(a), 201);
  })),

  http.get(`${API}/attachments/:id/download`, guarded((_ctx, _req, { id }) => {
    const a = db.attachments.find((x) => x.id === id);
    if (!a) return fail(404, 'Вложение не найдено', 'not_found');
    const blob = files.get(id) ?? new Blob([`Демо-файл «${a.original_name}». В имитации сервера содержимое не хранится.`], { type: 'text/plain;charset=utf-8' });
    return new HttpResponse(blob, { headers: { 'Content-Type': blob.type || 'application/octet-stream', 'Content-Disposition': `inline; filename="${encodeURIComponent(a.original_name)}"` } });
  })),

  http.delete(`${API}/attachments/:id`, guarded(({ me }, _req, { id }) => {
    const a = db.attachments.find((x) => x.id === id);
    if (!a) return fail(404, 'Вложение не найдено', 'not_found');
    if (a.uploaded_by !== me.id && me.role !== 'admin') return fail(403, 'Удалить вложение может только автор или администратор', 'forbidden');
    db.attachments = db.attachments.filter((x) => x.id !== id);
    files.delete(id);
    const o = db.occurrences.find((x) => x.id === a.occurrence_id);
    audit(db, me, 'attachment.delete', ['occurrence', a.occurrence_id], o ? occDetails(o, { name: a.original_name }) : { name: a.original_name });
    return noContent();
  })),

  // ----- summary, calendar, budgets -----
  http.get(`${API}/payments/summary`, guarded(({ t, url }) => {
    const [mFrom, mTo] = monthRange(t.slice(0, 7));
    const from = url.searchParams.get('date_from') ?? mFrom;
    const to = url.searchParams.get('date_to') ?? mTo;
    const asOf = url.searchParams.get('as_of') ?? t;
    if (!isDate(from) || !isDate(to) || !isDate(asOf) || from > to) return fail(422, 'Неверный период', 'validation_error');
    return json({ period: { from, to }, as_of: asOf, totals: totals(from, to, asOf) });
  })),

  http.get(`${API}/payments/calendar`, guarded(({ t, url }) => {
    const month = url.searchParams.get('month') ?? t.slice(0, 7);
    if (!/^\d{4}-\d{2}$/.test(month)) return fail(422, 'Месяц — в формате ГГГГ-ММ', 'validation_error');
    const [from, to] = monthRange(month);
    const byDay = new Map<string, CalendarDay>();
    const day = (d: string) => byDay.get(d) ?? byDay.set(d, { date: d, occurrences: [], planned: [] }).get(d)!;
    db.occurrences.filter((o) => o.due_date >= from && o.due_date <= to).forEach((o) => day(o.due_date).occurrences.push(occOut(o, t)));
    plannedInRange(db, from, to).forEach(({ payment, due }) =>
      day(due).planned.push({ recurring_payment_id: payment.id, name: payment.name, due_date: due, amount: payment.amount, currency: payment.currency }));
    return json({ month, days: [...byDay.values()].sort((a, b) => a.date.localeCompare(b.date)) });
  })),

  http.get(`${API}/budgets`, guarded(({ t, url }) => {
    const year = Number(url.searchParams.get('year') ?? t.slice(0, 4));
    const month = Number(url.searchParams.get('month') ?? t.slice(5, 7));
    return json(db.budgets.filter((b) => b.year === year && (b.period_type === 'year' || b.month === month)));
  })),

  http.put(`${API}/budgets`, guarded(async ({ me }, req) => {
    const list = await body<Budget[]>(req);
    if (!Array.isArray(list) || list.some((b) => !CURRENCIES.includes(b.currency) || !money2(b.amount))) {
      return fail(422, 'Бюджет — сумма больше нуля для каждой валюты', 'validation_error');
    }
    for (const b of list) {
      const existing = db.budgets.find((x) => x.currency === b.currency && x.period_type === b.period_type && x.year === b.year && x.month === b.month);
      if (existing) existing.amount = fixed(Number(b.amount));
      else db.budgets.push({ ...b, amount: fixed(Number(b.amount)) });
    }
    audit(db, me, 'budget.update', null, { items: list.length });
    return json(list);
  }, true)),

  // ----- users -----
  http.get(`${API}/users`, guarded(({ url }) => json(page(db.users.map(userOut), url, 200)), true)),

  http.post(`${API}/users`, guarded(async ({ me }, req) => {
    const b = (await body<Record<string, unknown>>(req)) ?? {};
    const login = typeof b.login === 'string' ? b.login.trim() : '';
    if (!/^[a-z0-9._-]{3,64}$/i.test(login)) return fail(422, 'Логин — от 3 до 64 латинских букв, цифр, точек, дефисов или подчёркиваний', 'validation_error');
    if (db.users.some((u) => u.login.toLowerCase() === login.toLowerCase())) return fail(409, `Логин «${login}» уже занят`, 'login_taken');
    if (typeof b.password !== 'string' || b.password.length < 8) return fail(422, 'Пароль — не короче 8 символов', 'validation_error');
    const u: DbUser = {
      id: uid(), login, password: b.password, full_name: (b.full_name as string)?.trim() || null, email: (b.email as string)?.trim() || null,
      role: 'user', is_system: false, telegram_linked: false, notify_email: !!b.notify_email, created_at: nowIso(),
    };
    db.users.push(u);
    audit(db, me, 'user.create', ['user', u.id], { login: u.login, full_name: u.full_name });
    return json(userOut(u), 201);
  }, true)),

  http.patch(`${API}/users/:id`, guarded(async ({ me }, req, { id }) => {
    const u = db.users.find((x) => x.id === id);
    if (!u) return fail(404, 'Пользователь не найден', 'not_found');
    if (u.is_system) return fail(403, 'Администратор задаётся в .env и не меняется через панель', 'system_user');
    const b = (await body<Record<string, unknown>>(req)) ?? {};
    if (b.login !== undefined) {
      const login = String(b.login).trim();
      if (!/^[a-z0-9._-]{3,64}$/i.test(login)) return fail(422, 'Логин — от 3 до 64 латинских букв, цифр, точек, дефисов или подчёркиваний', 'validation_error');
      if (db.users.some((x) => x.id !== id && x.login.toLowerCase() === login.toLowerCase())) return fail(409, `Логин «${login}» уже занят`, 'login_taken');
      u.login = login;
    }
    if (b.password) {
      if (String(b.password).length < 8) return fail(422, 'Пароль — не короче 8 символов', 'validation_error');
      u.password = String(b.password);
    }
    if (b.full_name !== undefined) u.full_name = (b.full_name as string)?.trim() || null;
    if (b.email !== undefined) u.email = (b.email as string)?.trim() || null;
    if (b.notify_email !== undefined) u.notify_email = !!b.notify_email;
    audit(db, me, 'user.update', ['user', u.id], { login: u.login, password_changed: !!b.password });
    return json(userOut(u));
  }, true)),

  http.delete(`${API}/users/:id`, guarded(({ me }, _req, { id }) => {
    const u = db.users.find((x) => x.id === id);
    if (!u) return fail(404, 'Пользователь не найден', 'not_found');
    if (u.is_system) return fail(403, 'Администратора из .env удалить нельзя', 'system_user');
    if (u.id === me.id) return fail(403, 'Нельзя удалить самого себя', 'forbidden');
    db.users = db.users.filter((x) => x.id !== id);
    audit(db, me, 'user.delete', ['user', id], { login: u.login });
    return noContent();
  }, true)),

  // ----- logs -----
  http.get(`${API}/audit-logs`, guarded(({ url }) => {
    const sp = url.searchParams;
    const action = sp.get('action');
    const actor = sp.get('actor_id');
    const from = sp.get('date_from');
    const to = sp.get('date_to');
    const list = db.audit
      .filter((a) => (!action || a.action === action || a.action.startsWith(`${action}.`)) && (!actor || a.actor_id === actor) &&
        (!from || a.at.slice(0, 10) >= from) && (!to || a.at.slice(0, 10) <= to))
      .map(auditOut);
    return json(page(list, url));
  }, true)),

  http.get(`${API}/notifications`, guarded(({ url }) => {
    const channel = url.searchParams.get('channel');
    const status = url.searchParams.get('status');
    const list = db.notifications
      .filter((n) => (!channel || n.channel === channel) && (!status || n.status === status))
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .map(notifOut);
    return json(page(list, url));
  }, true)),

  http.post(`${API}/notifications/test`, guarded(() => {
    const emailOn = db.users.some((u) => u.notify_email && u.email);
    return json({ channels: [
      { channel: 'telegram', ok: true, error: null },
      { channel: 'email', ok: emailOn, error: emailOn ? null : 'Нет получателей с включёнными письмами' },
      { channel: 'webhook', ok: false, error: 'WEBHOOK_URL не задан' },
      { channel: 'inapp', ok: true, error: null },
    ] });
  }, true)),

  // ----- inbox (канал inapp) -----
  http.get(`${API}/inbox`, guarded(({ me, t, url }) => {
    const unreadOnly = url.searchParams.get('unread_only') === 'true';
    const items: InboxItem[] = db.notifications
      .filter((n) => n.channel === 'inapp')
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .flatMap((n) => {
        const o = db.occurrences.find((x) => x.id === n.occurrence_id);
        if (!o) return [];
        const p = paymentOf(o);
        const read = db.reads.some((r) => r.user_id === me.id && r.notification_id === n.id);
        return [{ id: n.id, occurrence_id: o.id, kind: n.kind, created_at: n.created_at, read, payment_name: p.name, amount: o.amount,
          currency: o.currency, due_date: o.due_date, occurrence_state: stateOf(o, t), paid_date: o.paid_date, payment_deleted: !!p.deleted_at }];
      })
      .filter((i) => !unreadOnly || !i.read);
    return json({ items: items.slice(0, 30), unread_count: items.filter((i) => !i.read).length });
  })),

  http.post(`${API}/inbox/read-all`, guarded(({ me }) => {
    db.notifications.filter((n) => n.channel === 'inapp').forEach((n) => {
      if (!db.reads.some((r) => r.user_id === me.id && r.notification_id === n.id)) db.reads.push({ user_id: me.id, notification_id: n.id });
    });
    return noContent();
  })),

  http.post(`${API}/inbox/:id/read`, guarded(({ me }, _req, { id }) => {
    if (!db.reads.some((r) => r.user_id === me.id && r.notification_id === id)) db.reads.push({ user_id: me.id, notification_id: id });
    return noContent();
  })),

  http.post(`${API}/telegram/link-code`, guarded(() => {
    const code = String(Math.floor(100000 + Math.random() * 900000));
    return json({ code, expires_at: new Date(Date.now() + 10 * 60_000).toISOString() });
  })),
];
