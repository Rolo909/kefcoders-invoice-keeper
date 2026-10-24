import { describe, expect, it } from 'vitest';
import { days, money, plural, relative, statusLine } from './format';

describe('склонения и формат', () => {
  it('plural для 1, 2–4, 5–20, 21', () => {
    expect([1, 2, 5, 11, 21, 22, 25].map((n) => plural(n, 'платёж', 'платежа', 'платежей'))).toEqual(['платёж', 'платежа', 'платежей', 'платежей', 'платёж', 'платежа', 'платежей']);
    expect(days(10)).toBe('10 дней');
  });
  it('деньги в формате ru-RU с валютой', () => {
    expect(money('50000.00', 'RUB').replace(/\s/g, ' ')).toBe('50 000,00 ₽');
  });
  it('относительные сроки и строка статуса', () => {
    const base = { paid_date: null, days_overdue: 0 };
    expect(relative({ ...base, state: 'due_soon', due_date: '2026-10-25' }, '2026-10-24')).toBe('завтра');
    expect(relative({ ...base, state: 'due_soon', due_date: '2026-10-24' }, '2026-10-24')).toBe('сегодня');
    expect(relative({ ...base, state: 'upcoming', due_date: '2026-10-31' }, '2026-10-24')).toBe('через 7 дней');
    expect(statusLine({ ...base, state: 'overdue', due_date: '2026-10-14', days_overdue: 10 }, '2026-10-24')).toBe('Просрочено на 10 дней');
  });
});
