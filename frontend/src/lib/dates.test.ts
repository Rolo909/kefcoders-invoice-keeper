import { describe, expect, it } from 'vitest';
import { addDays, datesInRange, diffDays, dueDate, monthRange, shiftMonth } from './dates';

describe('dueDate — от якоря, нет числа → последний день (ARCHITECTURE.md §4.1)', () => {
  it('31 января идёт 28/29 февраля, 31 марта, 30 апреля', () => {
    expect([0, 1, 2, 3].map((n) => dueDate('2026-01-31', 'monthly', n))).toEqual(['2026-01-31', '2026-02-28', '2026-03-31', '2026-04-30']);
    expect(dueDate('2028-01-31', 'monthly', 1)).toBe('2028-02-29');
  });
  it('не «съезжает» на 28-е навсегда', () => {
    expect(dueDate('2026-01-30', 'monthly', 1)).toBe('2026-02-28');
    expect(dueDate('2026-01-30', 'monthly', 2)).toBe('2026-03-30');
  });
  it('29 февраля раз в год: 28 февраля, а через 4 года снова 29', () => {
    expect(dueDate('2028-02-29', 'yearly', 1)).toBe('2029-02-28');
    expect(dueDate('2028-02-29', 'yearly', 4)).toBe('2032-02-29');
  });
  it('еженедельно и раз в квартал', () => {
    expect(dueDate('2026-10-24', 'weekly', 2)).toBe('2026-11-07');
    expect(dueDate('2026-11-30', 'quarterly', 1)).toBe('2027-02-28');
  });
});

describe('вспомогательные даты', () => {
  it('сдвиги и разница', () => {
    expect(addDays('2026-12-31', 1)).toBe('2027-01-01');
    expect(diffDays('2026-10-24', '2026-10-26')).toBe(2);
    expect(shiftMonth('2026-12', 1)).toBe('2027-01');
    expect(shiftMonth('2026-01', -1)).toBe('2025-12');
    expect(monthRange('2026-02')).toEqual(['2026-02-01', '2026-02-28']);
  });
  it('даты в диапазоне без материализации', () => {
    expect(datesInRange('2026-01-31', 'monthly', '2026-02-01', '2026-04-30')).toEqual(['2026-02-28', '2026-03-31', '2026-04-30']);
    expect(datesInRange('2026-01-31', 'monthly', '2026-02-01', '2026-04-30', '2026-03-31')).toEqual(['2026-02-28', '2026-03-31']);
  });
});
