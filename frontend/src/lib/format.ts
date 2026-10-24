import { diffDays, type ISODate, type Period } from './dates';
import type { Currency, Occurrence, OccurrenceState } from '../api/types';

const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
const WEEKDAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];

export const CURRENCIES: Currency[] = ['RUB', 'USD', 'EUR'];
export const CURRENCY_SIGN: Record<Currency, string> = { RUB: '₽', USD: '$', EUR: '€' };
export const CURRENCY_NAME: Record<Currency, string> = { RUB: 'Рубли', USD: 'Доллары', EUR: 'Евро' };
export const PERIOD_LABEL: Record<Period, string> = { weekly: 'Еженедельно', monthly: 'Ежемесячно', quarterly: 'Раз в квартал', yearly: 'Раз в год' };
export const PERIOD_SHORT: Record<Period, string> = { weekly: '/нед', monthly: '/мес', quarterly: '/квартал', yearly: '/год' };
export const STATE_LABEL: Record<OccurrenceState, string> = {
  paid: 'Оплачено', paid_late: 'Оплачено с опозданием', due_soon: 'Скоро', overdue: 'Просрочено', upcoming: 'Ожидает',
};

export function plural(n: number, one: string, few: string, many: string) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b >= 2 && b <= 4) return few;
  return many;
}

export const days = (n: number) => `${n} ${plural(n, 'день', 'дня', 'дней')}`;

const toNumber = (v: string | number) => (typeof v === 'number' ? v : Number(v));

export const money = (v: string | number, c: Currency) =>
  new Intl.NumberFormat('ru-RU', { style: 'currency', currency: c }).format(toNumber(v));

export const num = (v: string | number) =>
  new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(toNumber(v));

export const numShort = (v: string | number) => num(v).replace(/,00$/, '');
export const amountShort = (v: string | number, c: Currency) => `${numShort(v)}\u00a0${CURRENCY_SIGN[c]}`;

export const date = (s?: string | null) => (s ? `${s.slice(8, 10)}.${s.slice(5, 7)}.${s.slice(0, 4)}` : '');
export const shortDate = (s?: string | null) => (s ? `${s.slice(8, 10)}.${s.slice(5, 7)}` : '');
export const longDate = (s: ISODate) => `${Number(s.slice(8, 10))} ${MONTHS_GEN[Number(s.slice(5, 7)) - 1]}`;
export const weekday = (s: ISODate) => WEEKDAYS[new Date(`${s}T12:00:00Z`).getUTCDay()];

const cap = (s: string) => s[0].toUpperCase() + s.slice(1);
export const monthName = (ym: string) => cap(MONTHS[Number(ym.slice(5, 7)) - 1]);
export const monthTitle = (ym: string) => `${monthName(ym)} ${ym.slice(0, 4)}`;

export function dateTime(s: string) {
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  return new Intl.DateTimeFormat('ru-RU', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).format(d).replace(',', ',');
}

export function relative(o: Pick<Occurrence, 'state' | 'due_date' | 'paid_date' | 'days_overdue'>, today: ISODate) {
  if (o.state === 'overdue') return `просрочено на ${days(o.days_overdue)}`;
  if (o.state === 'paid_late') return `с опозданием на ${days(o.days_overdue)}`;
  if (o.paid_date) return `оплачено ${date(o.paid_date)}`;
  const left = diffDays(today, o.due_date);
  if (left === 0) return 'сегодня';
  if (left === 1) return 'завтра';
  return `через ${days(left)}`;
}

export function statusLine(o: Pick<Occurrence, 'state' | 'due_date' | 'paid_date' | 'days_overdue'>, today: ISODate) {
  if (o.state === 'overdue') return `Просрочено на ${days(o.days_overdue)}`;
  if (o.state === 'paid_late') return `Оплачено с опозданием на ${days(o.days_overdue)}`;
  if (o.state === 'paid') return `Оплачено ${date(o.paid_date)}`;
  return `${o.state === 'due_soon' ? 'Скоро' : 'Ожидает'} · ${relative(o, today)}`;
}

export function lateBy(due: ISODate, paid: ISODate) {
  return diffDays(due, paid);
}

export function bytes(n: number) {
  if (n < 1024) return `${n} Б`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} КБ`;
  return `${(n / 1024 / 1024).toFixed(1).replace('.', ',')} МБ`;
}
