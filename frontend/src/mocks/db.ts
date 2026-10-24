import {
  addDays, datesInRange, diffDays, dueDate, iso, lastDayOfMonth, parseISO, todayIn,
  type ISODate, type Period,
} from '../lib/dates';
import type { Channel, Currency, NotificationKind, OccurrenceState, Role } from '../api/types';

export const TIMEZONE = 'Europe/Moscow';
export const REMIND_DAYS = 3;
export const HORIZON_DAYS = 60;
const STORAGE_KEY = 'ik-mock-db-v1';

export interface DbUser {
  id: string; login: string; password: string; full_name: string | null; email: string | null; role: Role;
  is_system: boolean; telegram_linked: boolean; notify_email: boolean; created_at: string;
}
export interface DbPayment {
  id: string; name: string; description: string | null; amount: string; currency: Currency; period: Period;
  first_due_date: ISODate; end_date: ISODate | null; is_active: boolean; deleted_at: string | null; created_by: string; created_at: string;
}
export interface DbOccurrence {
  id: string; recurring_payment_id: string; seq: number; due_date: ISODate; amount: string; currency: Currency;
  status: 'paid' | 'unpaid'; paid_date: ISODate | null; paid_by: string | null; paid_marked_at: string | null; note: string | null;
}
export interface DbNotification {
  id: string; occurrence_id: string; channel: Channel; kind: NotificationKind; status: 'pending' | 'sent' | 'failed';
  attempts: number; last_error: string | null; sent_at: string | null; created_at: string;
}
export interface DbAttachment {
  id: string; occurrence_id: string; kind: 'file' | 'link'; url: string | null; original_name: string;
  content_type: string | null; size: number | null; uploaded_by: string; created_at: string;
}
export interface DbAudit {
  id: string; at: string; actor_id: string | null; actor_login: string; action: string;
  entity_type: string | null; entity_id: string | null; details: Record<string, string | number | boolean | null>; ip: string | null;
}
export interface DbBudget { currency: Currency; period_type: 'month' | 'year'; year: number; month: number | null; amount: string }

export interface Db {
  version: 1;
  users: DbUser[];
  payments: DbPayment[];
  occurrences: DbOccurrence[];
  notifications: DbNotification[];
  reads: { user_id: string; notification_id: string }[];
  attachments: DbAttachment[];
  audit: DbAudit[];
  budgets: DbBudget[];
}

export const today = () => todayIn(TIMEZONE);
export const uid = () => crypto.randomUUID();
export const at = (d: ISODate, hhmm = '09:00') => `${d}T${hhmm}:00+03:00`;
export const nowIso = () => new Date().toISOString();

// ---------- domain (TASK_PLAN §4) ----------

export function stateOf(o: DbOccurrence, t: ISODate): OccurrenceState {
  if (o.status === 'paid' && o.paid_date) return o.paid_date > o.due_date ? 'paid_late' : 'paid';
  const left = diffDays(t, o.due_date);
  if (left < 0) return 'overdue';
  if (left <= REMIND_DAYS) return 'due_soon';
  return 'upcoming';
}

export function daysOverdue(o: DbOccurrence, t: ISODate) {
  if (o.status === 'paid' && o.paid_date) return Math.max(0, diffDays(o.due_date, o.paid_date));
  return Math.max(0, diffDays(o.due_date, t));
}

export const isOverdue = (o: DbOccurrence, t: ISODate) =>
  o.status === 'paid' && o.paid_date ? o.paid_date > o.due_date : t > o.due_date;

export function ensureOccurrences(db: Db, p: DbPayment, t: ISODate) {
  if (p.deleted_at || !p.is_active) return;
  const mine = db.occurrences.filter((o) => o.recurring_payment_id === p.id);
  const limit = addDays(t, HORIZON_DAYS);
  for (let n = 0; n < 2000; n++) {
    const due = dueDate(p.first_due_date, p.period, n);
    if (p.end_date && due > p.end_date) break;
    const hasFuture = mine.some((o) => o.due_date > t);
    if (due > limit && hasFuture) break;
    if (!mine.some((o) => o.seq === n)) {
      const occ: DbOccurrence = {
        id: uid(), recurring_payment_id: p.id, seq: n, due_date: due, amount: p.amount, currency: p.currency,
        status: 'unpaid', paid_date: null, paid_by: null, paid_marked_at: null, note: null,
      };
      db.occurrences.push(occ);
      mine.push(occ);
    }
  }
}

function scheduled(time: string) {
  return new Date(time).getTime() <= Date.now() ? time : nowIso();
}

export function dispatchReminders(db: Db, t: ISODate) {
  const emailOn = db.users.some((u) => u.notify_email && u.email);
  const channels: Channel[] = emailOn ? ['telegram', 'email', 'inapp'] : ['telegram', 'inapp'];
  for (const o of db.occurrences) {
    if (o.status === 'paid') continue;
    const p = db.payments.find((x) => x.id === o.recurring_payment_id);
    if (!p || p.deleted_at) continue;
    const left = diffDays(t, o.due_date);
    let kind: NotificationKind | null = null;
    let when = '';
    if (left >= 0 && left <= REMIND_DAYS) {
      kind = 'before_due';
      const ideal = addDays(o.due_date, -REMIND_DAYS);
      const created = p.created_at.slice(0, 10);
      when = at(ideal > created ? ideal : created);
    } else if (left < 0) {
      kind = 'overdue';
      when = at(addDays(o.due_date, 1));
    }
    if (!kind) continue;
    for (const channel of channels) {
      if (db.notifications.some((n) => n.occurrence_id === o.id && n.channel === channel && n.kind === kind)) continue;
      const time = scheduled(when);
      db.notifications.push({ id: uid(), occurrence_id: o.id, channel, kind, status: 'sent', attempts: 1, last_error: null, sent_at: time, created_at: time });
    }
  }
}

export function refresh(db: Db) {
  const t = today();
  db.payments.forEach((p) => ensureOccurrences(db, p, t));
  dispatchReminders(db, t);
}

export function plannedInRange(db: Db, from: ISODate, to: ISODate) {
  const out: { payment: DbPayment; due: ISODate }[] = [];
  for (const p of db.payments) {
    if (p.deleted_at || !p.is_active) continue;
    const materialized = new Set(db.occurrences.filter((o) => o.recurring_payment_id === p.id).map((o) => o.due_date));
    for (const due of datesInRange(p.first_due_date, p.period, from, to, p.end_date)) {
      if (!materialized.has(due)) out.push({ payment: p, due });
    }
  }
  return out;
}

export function audit(db: Db, actor: DbUser | null, action: string, entity: [string, string] | null, details: DbAudit['details']) {
  db.audit.unshift({
    id: uid(), at: nowIso(), actor_id: actor?.id ?? null, actor_login: actor?.login ?? 'system', action,
    entity_type: entity?.[0] ?? null, entity_id: entity?.[1] ?? null, details, ip: '127.0.0.1',
  });
}

// ---------- persistence ----------

export function load(): Db {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const db = JSON.parse(raw) as Db;
      if (db.version === 1) return db;
    }
  } catch {
    // storage unavailable or corrupt: start from seed
  }
  const db = seed();
  save(db);
  return db;
}

export function save(db: Db) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(db));
  } catch {
    // quota or private mode: keep working in memory
  }
}

export function reset() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

// ---------- seed (TASK_PLAN §12, dates relative to today) ----------

function seed(): Db {
  const T = today();
  const db: Db = { version: 1, users: [], payments: [], occurrences: [], notifications: [], reads: [], attachments: [], audit: [], budgets: [] };

  const user = (login: string, password: string, full_name: string | null, extra: Partial<DbUser> = {}): DbUser => {
    const u: DbUser = {
      id: uid(), login, password, full_name, email: null, role: 'user', is_system: false,
      telegram_linked: false, notify_email: false, created_at: at(addDays(T, -140)), ...extra,
    };
    db.users.push(u);
    return u;
  };
  const admin = user('admin', 'admin12345', 'Администратор', { role: 'admin', is_system: true });
  const anna = user('anna', 'anna12345', 'Анна Ковалёва', { email: 'anna@kefcoders.ru', telegram_linked: true, notify_email: true });
  const maria = user('maria', 'maria12345', 'Мария Лебедева', { email: 'maria@kefcoders.ru', telegram_linked: true });
  user('user', 'user12345', 'Дмитрий Орлов', { created_at: at(addDays(T, -100)) });

  type Spec = {
    name: string; description: string; amount: string; currency: Currency; period: Period; first: ISODate;
    paid?: (seq: number, due: ISODate) => [ISODate, DbUser] | null; deletedAt?: ISODate; createdAt?: ISODate;
  };
  const back = (due: ISODate, period: Period, k: number) => dueDate(due, period, -k);
  const monthly = (currentDue: ISODate, past: number) => back(currentDue, 'monthly', past);
  const paidBefore = (shift: number, who: DbUser[]) => (seq: number, due: ISODate): [ISODate, DbUser] | null => {
    const d = addDays(due, shift);
    return d <= T ? [d, who[seq % who.length]] : null;
  };

  const figmaAnchor = (() => {
    let { y, m } = parseISO(T);
    m -= 3;
    for (let i = 0; i < 12; i++) {
      if (m < 1) { m += 12; y -= 1; }
      if (lastDayOfMonth(y, m) === 31) return iso(y, m, 31);
      m -= 1;
    }
    return iso(y, 1, 31);
  })();

  const specs: Spec[] = [
    { name: 'Аренда офиса', description: 'Офис на Пушкинской, 12. Договор № 14/2025, оплата до 26-го числа.', amount: '50000.00', currency: 'RUB', period: 'monthly',
      first: monthly(addDays(T, 2), 4), paid: (seq, due) => (due < addDays(T, 2) ? paidBefore(-1, [anna, maria])(seq, due) : null) },
    { name: 'Бухгалтерское сопровождение', description: 'ООО «Баланс-Сервис», ежемесячный счёт.', amount: '25000.00', currency: 'RUB', period: 'monthly',
      first: monthly(addDays(T, 1), 4), paid: (seq, due) => (due < addDays(T, 1) ? paidBefore(-1, [anna])(seq, due) : null) },
    { name: 'МТС Бизнес, интернет', description: 'Лицевой счёт 7712 0045 8810.', amount: '3900.00', currency: 'RUB', period: 'monthly',
      first: monthly(addDays(T, -4), 4), paid: paidBefore(-1, [maria, anna]) },
    { name: 'Яндекс 360 для бизнеса', description: 'Почта и диск, 8 пользователей.', amount: '2400.00', currency: 'RUB', period: 'monthly',
      first: monthly(addDays(T, -23), 3), paid: paidBefore(0, [anna, maria]) },
    { name: 'Страхование офиса', description: 'Полис «Ингосстрах» № 0471-2026.', amount: '38000.00', currency: 'RUB', period: 'quarterly',
      first: back(addDays(T, 38), 'quarterly', 2), paid: (seq, due) => (due < T ? paidBefore(-2, [anna])(seq, due) : null) },
    { name: 'Домен invoicekeeper.ru', description: 'Продление у регистратора REG.RU.', amount: '1500.00', currency: 'RUB', period: 'yearly', first: addDays(T, 20) },
    { name: 'Сервер DigitalOcean', description: 'Droplet 4 vCPU / 8 GB, продакшен.', amount: '20.00', currency: 'USD', period: 'monthly',
      first: monthly(addDays(T, -10), 3), paid: (seq, due) => (due < addDays(T, -10) ? paidBefore(0, [maria])(seq, due) : null) },
    { name: 'Sentry Team', description: 'Мониторинг ошибок, 50 тыс. событий.', amount: '26.00', currency: 'USD', period: 'monthly',
      first: monthly(addDays(T, -6), 3), paid: (seq, due) => (due < addDays(T, -6) ? paidBefore(-1, [maria])(seq, due) : null) },
    { name: 'GitHub Team', description: '11 мест, организация kefcoders.', amount: '44.00', currency: 'USD', period: 'monthly',
      first: monthly(addDays(T, -2), 3), paid: paidBefore(0, [maria]) },
    { name: 'AWS', description: 'S3 и CloudFront для файлов клиентов.', amount: '134.20', currency: 'USD', period: 'monthly', first: addDays(T, 4), createdAt: addDays(T, -1) },
    { name: 'JetBrains All Products', description: 'Лицензия на команду, 3 места.', amount: '28.90', currency: 'EUR', period: 'monthly',
      first: monthly(addDays(T, -19), 3), paid: paidBefore(0, [anna]) },
    { name: 'Figma Professional', description: 'Оплата 31-го; в коротких месяцах — в последний день.', amount: '15.00', currency: 'EUR', period: 'monthly',
      first: figmaAnchor, paid: (seq, due) => (seq < 2 ? paidBefore(0, [maria])(seq, due) : seq === 2 ? paidBefore(3, [maria])(seq, due) : null) },
    { name: 'Хостинг Timeweb', description: 'Старый сервер, переехали на DigitalOcean.', amount: '1290.00', currency: 'RUB', period: 'monthly',
      first: monthly(addDays(T, -75), 4), paid: paidBefore(0, [anna]), deletedAt: addDays(T, -70) },
  ];

  const byName: Record<string, DbPayment> = {};
  for (const s of specs) {
    const p: DbPayment = {
      id: uid(), name: s.name, description: s.description, amount: s.amount, currency: s.currency, period: s.period,
      first_due_date: s.first, end_date: null, is_active: !s.deletedAt, deleted_at: null, created_by: admin.id,
      created_at: at(s.createdAt ?? addDays(s.first, -25), '11:00'),
    };
    db.payments.push(p);
    byName[s.name] = p;
    if (s.deletedAt) {
      for (let n = 0; n < 60; n++) {
        const due = dueDate(p.first_due_date, p.period, n);
        if (due > s.deletedAt) break;
        db.occurrences.push({ id: uid(), recurring_payment_id: p.id, seq: n, due_date: due, amount: p.amount, currency: p.currency,
          status: 'unpaid', paid_date: null, paid_by: null, paid_marked_at: null, note: null });
      }
      p.deleted_at = at(s.deletedAt, '11:00');
    } else {
      ensureOccurrences(db, p, T);
    }
    for (const o of db.occurrences.filter((x) => x.recurring_payment_id === p.id)) {
      const mark = s.paid?.(o.seq, o.due_date);
      if (mark) {
        o.status = 'paid';
        o.paid_date = mark[0];
        o.paid_by = mark[1].id;
        o.paid_marked_at = at(mark[0], '13:05');
      }
    }
  }

  const occOf = (name: string, pick: (list: DbOccurrence[]) => DbOccurrence | undefined) =>
    pick(db.occurrences.filter((o) => o.recurring_payment_id === byName[name].id).sort((a, b) => a.due_date.localeCompare(b.due_date)));
  const lastPaid = (name: string) => occOf(name, (l) => [...l].reverse().find((o) => o.status === 'paid'));

  const mts = lastPaid('МТС Бизнес, интернет');
  const github = lastPaid('GitHub Team');
  const jet = lastPaid('JetBrains All Products');
  const figmaLate = occOf('Figma Professional', (l) => l.find((o) => o.paid_date && o.paid_date > o.due_date));
  const files: [DbOccurrence | undefined, Partial<DbAttachment>, DbUser][] = [
    [mts, { kind: 'file', original_name: 'mts-chek.pdf', content_type: 'application/pdf', size: 188_416 }, anna],
    [github, { kind: 'link', url: 'https://github.com/organizations/kefcoders/settings/billing', original_name: 'Счёт GitHub' }, maria],
    [jet, { kind: 'file', original_name: 'jetbrains-invoice.png', content_type: 'image/png', size: 421_888 }, anna],
  ];
  for (const [o, a, by] of files) {
    if (!o) continue;
    db.attachments.push({ id: uid(), occurrence_id: o.id, kind: 'file', url: null, original_name: '', content_type: null, size: null,
      uploaded_by: by.id, created_at: at(o.paid_date ?? T, '13:06'), ...a });
  }

  const log = (when: string, actor: DbUser | null, action: string, entity: [string, string] | null, details: DbAudit["details"], ip: string | null = "85.140.12.7") =>
    db.audit.push({ id: uid(), at: when, actor_id: actor?.id ?? null, actor_login: actor?.login ?? 'system', action,
      entity_type: entity?.[0] ?? null, entity_id: entity?.[1] ?? null, details, ip });
  const occDetails = (o: DbOccurrence, extra: DbAudit['details'] = {}) => ({
    payment_name: db.payments.find((p) => p.id === o.recurring_payment_id)?.name ?? '', due_date: o.due_date, ...extra,
  });
  log(at(T, '09:12'), anna, 'auth.login', ['user', anna.id], {});
  log(at(addDays(T, -1), '18:02'), admin, 'payment.create', ['recurring_payment', byName.AWS.id],
    { payment_name: 'AWS', amount: '134.20', currency: 'USD', period: 'monthly', first_due_date: byName.AWS.first_due_date }, '85.140.12.3');
  if (github) {
    log(at(github.paid_date!, '11:47'), maria, 'telegram.mark_paid', ['occurrence', github.id], occDetails(github, { paid_date: github.paid_date }), null);
    log(at(github.paid_date!, '11:48'), maria, 'attachment.add', ['occurrence', github.id], occDetails(github, { name: 'Счёт GitHub' }), '93.80.41.15');
  }
  log(at(addDays(T, -3), '16:20'), null, 'auth.login_failed', null, { login: 'user' }, '176.59.33.201');
  if (mts) {
    log(at(mts.paid_date!, '13:05'), anna, 'occurrence.mark_paid', ['occurrence', mts.id], occDetails(mts, { paid_date: mts.paid_date }));
    log(at(mts.paid_date!, '13:06'), anna, 'attachment.add', ['occurrence', mts.id], occDetails(mts, { name: 'mts-chek.pdf' }));
  }
  if (jet) {
    log(at(addDays(jet.paid_date!, 1), '12:01'), anna, 'occurrence.mark_paid', ['occurrence', jet.id], occDetails(jet, { paid_date: addDays(jet.paid_date!, 1) }));
    log(at(addDays(jet.paid_date!, 1), '12:04'), anna, 'occurrence.change_paid_date', ['occurrence', jet.id],
      occDetails(jet, { old_paid_date: addDays(jet.paid_date!, 1), new_paid_date: jet.paid_date }));
  }
  if (figmaLate) log(at(figmaLate.paid_date!, '17:44'), maria, 'occurrence.mark_paid', ['occurrence', figmaLate.id], occDetails(figmaLate, { paid_date: figmaLate.paid_date }), '93.80.41.15');
  log(byName['Хостинг Timeweb'].deleted_at!, admin, 'payment.delete', ['recurring_payment', byName['Хостинг Timeweb'].id], { payment_name: 'Хостинг Timeweb' }, '85.140.12.3');
  log(at(addDays(T, -100), '10:15'), admin, 'user.create', ['user', db.users[3].id], { login: 'user', full_name: 'Дмитрий Орлов' }, '85.140.12.3');
  db.audit.sort((a, b) => b.at.localeCompare(a.at));

  const { y, m } = parseISO(T);
  const budget = (currency: Currency, monthAmount: string, yearAmount: string) => {
    db.budgets.push({ currency, period_type: 'month', year: y, month: m, amount: monthAmount });
    db.budgets.push({ currency, period_type: 'year', year: y, month: null, amount: yearAmount });
  };
  budget('RUB', '90000.00', '1100000.00');
  budget('USD', '250.00', '3000.00');
  budget('EUR', '60.00', '700.00');

  dispatchReminders(db, T);
  const inapp = db.notifications.filter((n) => n.channel === 'inapp').sort((a, b) => a.created_at.localeCompare(b.created_at));
  inapp.slice(0, Math.max(0, inapp.length - 3)).forEach((n) => db.users.forEach((u) => db.reads.push({ user_id: u.id, notification_id: n.id })));

  return db;
}
