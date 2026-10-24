import { describe, expect, it } from 'vitest';
import { daysOverdue, ensureOccurrences, isOverdue, plannedInRange, stateOf, type Db, type DbOccurrence, type DbPayment } from './db';

const occ = (patch: Partial<DbOccurrence>): DbOccurrence => ({
  id: 'o1', recurring_payment_id: 'p1', seq: 0, due_date: '2026-10-24', amount: '10.00', currency: 'RUB',
  status: 'unpaid', paid_date: null, paid_by: null, paid_marked_at: null, note: null, ...patch,
});

const emptyDb = (): Db => ({ version: 1, users: [], payments: [], occurrences: [], notifications: [], reads: [], attachments: [], audit: [], budgets: [] });
const payment = (patch: Partial<DbPayment> = {}): DbPayment => ({
  id: 'p1', name: 'Аренда офиса', description: null, amount: '50000.00', currency: 'RUB', period: 'monthly', first_due_date: '2026-10-26',
  end_date: null, is_active: true, deleted_at: null, created_by: 'u1', created_at: '2026-10-01T00:00:00Z', ...patch,
});

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
    const dues = db.occurrences.map((o) => o.due_date);
    expect(dues).toEqual(['2026-08-26', '2026-09-26', '2026-10-26', '2026-11-26']);
    ensureOccurrences(db, p, '2026-10-24');
    expect(db.occurrences).toHaveLength(4);
  });
  it('годовой платёж: один будущий период даже за горизонтом', () => {
    const db = emptyDb();
    const p = payment({ period: 'yearly', first_due_date: '2027-06-01' });
    db.payments.push(p);
    ensureOccurrences(db, p, '2026-10-24');
    expect(db.occurrences.map((o) => o.due_date)).toEqual(['2027-06-01']);
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
    expect(db.occurrences.map((o) => o.due_date)).toEqual(['2026-10-26', '2026-11-26']);
    expect(planned).toEqual(['2026-12-26', '2027-01-26']);
  });
});
