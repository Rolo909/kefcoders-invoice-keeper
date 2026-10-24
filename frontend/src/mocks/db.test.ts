import { describe, expect, it } from 'vitest';
import {
  daysOverdue, dispatchReminders, ensureOccurrences, isOverdue, plannedInRange, stateOf,
  type Db, type DbOccurrence, type DbPayment, type DbTeam, type DbUser,
} from './db';

const occ = (patch: Partial<DbOccurrence>): DbOccurrence => ({
  id: 'o1', recurring_payment_id: 'p1', team_id: 't1', seq: 0, due_date: '2026-10-24', amount: '10.00', currency: 'RUB',
  status: 'unpaid', paid_date: null, paid_by: null, paid_marked_at: null, note: null, ...patch,
});

const team = (id: string, created_at = '2026-01-01T07:00:00Z'): DbTeam => ({ id, name: `Команда ${id}`, telegram_chat_id: null, created_at });
const emptyDb = (teams: DbTeam[] = [team('t1')]): Db => ({
  version: 2, teams, users: [], payments: [], occurrences: [], notifications: [], reads: [], attachments: [], audit: [], budgets: [],
});
const payment = (patch: Partial<DbPayment> = {}): DbPayment => ({
  id: 'p1', name: 'Аренда офиса', description: null, amount: '50000.00', currency: 'RUB', period: 'monthly', first_due_date: '2026-10-26',
  end_date: null, team_id: 't1', is_active: true, deleted_at: null, created_by: 'u1', created_at: '2026-10-01T00:00:00Z', ...patch,
});
const dues = (db: Db, teamId: string) => db.occurrences.filter((o) => o.team_id === teamId).map((o) => o.due_date);

describe('статус периода (TASK_PLAN §4.3)', () => {
  const T = '2026-10-24';
  it('оплата в день срока — вовремя', () => {
    const o = occ({ status: 'paid', paid_date: '2026-10-24' });
    expect(stateOf(o, T)).toBe('paid');
    expect(isOverdue(o, T)).toBe(false);
  });
  it('просрочка со следующего дня', () => {
    expect(stateOf(occ({ due_date: '2026-10-24' }), T)).toBe('due_soon');
    expect(stateOf(occ({ due_date: '2026-10-23' }), T)).toBe('overdue');
    expect(daysOverdue(occ({ due_date: '2026-10-14' }), T)).toBe(10);
  });
  it('за 3 дня — «скоро», за 4 — «ожидает»', () => {
    expect(stateOf(occ({ due_date: '2026-10-27' }), T)).toBe('due_soon');
    expect(stateOf(occ({ due_date: '2026-10-28' }), T)).toBe('upcoming');
  });
  it('исправление даты убирает просрочку, срок не меняется', () => {
    const o = occ({ due_date: '2026-10-05', status: 'paid', paid_date: '2026-10-06' });
    expect(stateOf(o, T)).toBe('paid_late');
    o.paid_date = '2026-10-05';
    expect(stateOf(o, T)).toBe('paid');
    expect(o.due_date).toBe('2026-10-05');
  });
});

describe('периоды (TASK_PLAN §4.2, §4.6)', () => {
  it('создаются до горизонта 60 дней и минимум один будущий', () => {
    const db = emptyDb();
    const p = payment({ first_due_date: '2026-08-26' });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(dues(db, 't1')).toEqual(['2026-08-26', '2026-09-26', '2026-10-26', '2026-11-26']);
    ensureOccurrences(db, p, '2026-10-24');
    expect(db.occurrences).toHaveLength(4);
  });
  it('годовой платёж: один будущий период даже за горизонтом', () => {
    const db = emptyDb();
    const p = payment({ period: 'yearly', first_due_date: '2027-06-01' });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(dues(db, 't1')).toEqual(['2027-06-01']);
  });
  it('прекращённый платёж не создаёт новых периодов и не входит в план', () => {
    const db = emptyDb();
    const p = payment({ deleted_at: '2026-10-01T00:00:00Z', is_active: false });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(db.occurrences).toHaveLength(0);
    expect(plannedInRange(db, '2026-11-01', '2027-03-31')).toHaveLength(0);
  });
  it('плановые даты не дублируют созданные периоды', () => {
    const db = emptyDb();
    const p = payment();
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    const planned = plannedInRange(db, '2026-10-01', '2027-01-31').map((x) => x.due);
    expect(dues(db, 't1')).toEqual(['2026-10-26', '2026-11-26']);
    expect(planned).toEqual(['2026-12-26', '2027-01-26']);
  });
});

describe('команды и общие платежи', () => {
  it('платёж команды создаёт периоды только у неё', () => {
    const db = emptyDb([team('t1'), team('t2')]);
    const p = payment({ team_id: 't2' });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(dues(db, 't1')).toEqual([]);
    expect(dues(db, 't2')).toEqual(['2026-10-26', '2026-11-26']);
  });

  it('общий платёж: у каждой команды свои периоды с теми же сроками', () => {
    const db = emptyDb([team('t1'), team('t2')]);
    const p = payment({ team_id: null });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(dues(db, 't1')).toEqual(['2026-10-26', '2026-11-26']);
    expect(dues(db, 't2')).toEqual(['2026-10-26', '2026-11-26']);
    expect(new Set(db.occurrences.map((o) => o.id)).size).toBe(4);
  });

  it('оплата одной команды не меняет период другой', () => {
    const db = emptyDb([team('t1'), team('t2')]);
    const p = payment({ team_id: null, first_due_date: '2026-10-20' });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    const [first, second] = db.occurrences.filter((o) => o.due_date === '2026-10-20');
    Object.assign(first, { status: 'paid', paid_date: '2026-10-19' });
    expect(stateOf(first, '2026-10-24')).toBe('paid');
    expect(stateOf(second, '2026-10-24')).toBe('overdue');
  });

  it('команда, созданная позже платежа, получает его с ближайшего срока — без долгов', () => {
    const db = emptyDb([team('old'), team('new', '2026-10-10T09:00:00Z')]);
    const p = payment({ team_id: null, first_due_date: '2026-08-26', created_at: '2026-08-01T00:00:00Z' });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(dues(db, 'old')).toEqual(['2026-08-26', '2026-09-26', '2026-10-26', '2026-11-26']);
    expect(dues(db, 'new')).toEqual(['2026-10-26', '2026-11-26']);
    // Номер периода общий для всех команд: тот же срок — тот же seq.
    expect(db.occurrences.filter((o) => o.due_date === '2026-10-26').map((o) => o.seq)).toEqual([2, 2]);
  });

  it('плановые даты общего платежа — у каждой команды', () => {
    const db = emptyDb([team('t1'), team('t2')]);
    const p = payment({ team_id: null });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    const planned = plannedInRange(db, '2026-12-01', '2026-12-31');
    expect(planned.map((x) => [x.team.id, x.due])).toEqual([['t1', '2026-12-26'], ['t2', '2026-12-26']]);
  });

  it('напоминание у каждой команды своё, письма — только участникам команды периода', () => {
    const db = emptyDb([team('t1'), team('t2')]);
    db.users.push({
      id: 'u1', login: 'anna', password: 'x', full_name: null, email: 'anna@kefcoders.ru', role: 'user', is_system: false, team_id: 't1',
      telegram_linked: false, notify_email: true, created_at: '2026-01-01T00:00:00Z',
    } satisfies DbUser);
    const p = payment({ team_id: null });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    dispatchReminders(db, '2026-10-24');
    dispatchReminders(db, '2026-10-24');
    const sent = (teamId: string) => db.notifications
      .filter((n) => db.occurrences.find((o) => o.id === n.occurrence_id)?.team_id === teamId)
      .map((n) => n.channel)
      .sort();
    expect(sent('t1')).toEqual(['email', 'inapp', 'telegram']);
    expect(sent('t2')).toEqual(['inapp', 'telegram']);
  });
});
