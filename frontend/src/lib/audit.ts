import type { AuditLog } from '../api/types';
import { date } from './format';

export const ACTION_LABEL: Record<string, string> = {
  'auth.login': 'Вход',
  'auth.login_failed': 'Неудачный вход',
  'auth.logout': 'Выход',
  'payment.create': 'Новый платёж',
  'payment.delete': 'Прекращение платежа',
  'occurrence.mark_paid': 'Отметка оплаты',
  'occurrence.mark_unpaid': 'Снятие отметки',
  'occurrence.change_paid_date': 'Изменение даты оплаты',
  'user.create': 'Новый пользователь',
  'user.update': 'Изменение пользователя',
  'user.delete': 'Удаление пользователя',
  'attachment.add': 'Вложение',
  'attachment.delete': 'Удаление вложения',
  'telegram.mark_paid': 'Оплата из Telegram',
  'budget.update': 'Изменение бюджетов',
  'team.create': 'Новая команда',
  'team.update': 'Изменение команды',
  'team.delete': 'Удаление команды',
};

const s = (v: unknown) => (v === null || v === undefined ? '' : String(v));

export function describeAudit(a: AuditLog) {
  const d = a.details ?? {};
  const pay = d.payment_name ? `«${s(d.payment_name)}»` : '';
  const period = d.due_date ? ` за ${date(s(d.due_date))}` : '';
  switch (a.action) {
    case 'auth.login': return 'Вход в панель';
    case 'auth.logout': return 'Выход из панели';
    case 'auth.login_failed': return `Неверный логин или пароль${d.login ? ` для «${s(d.login)}»` : ''}`;
    case 'payment.create': return `Создан платёж ${pay}${d.team_name ? ` для команды «${s(d.team_name)}»` : ''}: ${s(d.amount)} ${s(d.currency)}, первый срок ${date(s(d.first_due_date))}`;
    case 'payment.delete': return `Платёж ${pay} прекращён. История сохранена`;
    case 'occurrence.mark_paid': return `Оплата ${pay}${period}, дата ${date(s(d.paid_date))}`;
    case 'telegram.mark_paid': return `Оплата ${pay}${period} отмечена кнопкой в Telegram`;
    case 'occurrence.mark_unpaid': return `Снята отметка об оплате ${pay}${period}${d.old_paid_date ? ` (была ${date(s(d.old_paid_date))})` : ''}`;
    case 'occurrence.change_paid_date': return `Дата оплаты ${pay}${period}: ${date(s(d.old_paid_date))} → ${date(s(d.new_paid_date))}`;
    case 'attachment.add': return `Вложение «${s(d.name)}» к ${pay}${period}`;
    case 'attachment.delete': return `Удалено вложение «${s(d.name)}»`;
    case 'user.create': return `Создан пользователь ${s(d.login)}${d.full_name ? ` (${s(d.full_name)})` : ''}${d.team_name ? `, команда «${s(d.team_name)}»` : ''}`;
    case 'user.update': return `Пользователь ${s(d.login)}: изменены данные${d.password_changed ? ', пароль сменён' : ''}`;
    case 'user.delete': return `Удалён пользователь ${s(d.login)}`;
    case 'budget.update': return `Изменены бюджеты${d.team_name ? ` команды «${s(d.team_name)}»` : ''}`;
    case 'team.create': return `Создана команда «${s(d.name)}»`;
    case 'team.update': return `Команда «${s(d.name)}»: изменены данные`;
    case 'team.delete': return `Удалена команда «${s(d.name)}»`;
    default: return Object.entries(d).map(([k, v]) => `${k}: ${s(v)}`).join(', ');
  }
}
