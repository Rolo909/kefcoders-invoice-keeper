export type ISODate = string;
export type Period = 'weekly' | 'monthly' | 'quarterly' | 'yearly';

export const pad = (n: number) => String(n).padStart(2, '0');
export const iso = (y: number, m: number, d: number): ISODate => `${y}-${pad(m)}-${pad(d)}`;

export function parseISO(s: ISODate) {
  const [y, m, d] = s.slice(0, 10).split('-').map(Number);
  return { y, m, d };
}

const toUTC = (s: ISODate) => {
  const p = parseISO(s);
  return Date.UTC(p.y, p.m - 1, p.d);
};

export function addDays(s: ISODate, n: number): ISODate {
  const t = new Date(toUTC(s) + n * 86400000);
  return iso(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate());
}

export const diffDays = (from: ISODate, to: ISODate) => Math.round((toUTC(to) - toUTC(from)) / 86400000);

export const lastDayOfMonth = (y: number, m: number) => new Date(Date.UTC(y, m, 0)).getUTCDate();

export function addMonthsClamped(anchor: ISODate, months: number): ISODate {
  const a = parseISO(anchor);
  const total = a.m - 1 + months;
  const y = a.y + Math.floor(total / 12);
  const m = ((total % 12) + 12) % 12 + 1;
  return iso(y, m, Math.min(a.d, lastDayOfMonth(y, m)));
}

export function dueDate(first: ISODate, period: Period, n: number): ISODate {
  if (period === 'weekly') return addDays(first, 7 * n);
  const step = { monthly: 1, quarterly: 3, yearly: 12 }[period];
  return addMonthsClamped(first, step * n);
}

export function datesInRange(first: ISODate, period: Period, from: ISODate, to: ISODate, end?: ISODate | null): ISODate[] {
  const out: ISODate[] = [];
  for (let n = 0; n < 2000; n++) {
    const d = dueDate(first, period, n);
    if (d > to || (end && d > end)) break;
    if (d >= from) out.push(d);
  }
  return out;
}

export function todayIn(timeZone: string): ISODate {
  return new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
}

export const monthOf = (s: ISODate) => s.slice(0, 7);

export function shiftMonth(ym: string, n: number): string {
  const y = Number(ym.slice(0, 4));
  const m = Number(ym.slice(5, 7)) - 1 + n;
  return `${y + Math.floor(m / 12)}-${pad((((m % 12) + 12) % 12) + 1)}`;
}

export function monthRange(ym: string): [ISODate, ISODate] {
  const y = Number(ym.slice(0, 4));
  const m = Number(ym.slice(5, 7));
  return [`${ym}-01`, `${ym}-${pad(lastDayOfMonth(y, m))}`];
}

export const mondayIndex = (s: ISODate) => (new Date(toUTC(s)).getUTCDay() + 6) % 7;
