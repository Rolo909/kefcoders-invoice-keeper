window.IKD = (function () {
  const TODAY = '2026-10-24';
  const TIMEZONE = 'Europe/Moscow';
  const REMIND_DAYS = 3;
  const HORIZON_DAYS = 60;

  const pad = (n) => String(n).padStart(2, '0');
  const iso = (y, m, d) => y + '-' + pad(m) + '-' + pad(d);
  const parse = (s) => { const [y, m, d] = s.split('-').map(Number); return { y, m, d }; };
  const toDate = (s) => { const p = parse(s); return new Date(Date.UTC(p.y, p.m - 1, p.d)); };
  const fromDate = (dt) => iso(dt.getUTCFullYear(), dt.getUTCMonth() + 1, dt.getUTCDate());
  const addDays = (s, n) => { const dt = toDate(s); dt.setUTCDate(dt.getUTCDate() + n); return fromDate(dt); };
  const diff = (a, b) => Math.round((toDate(b) - toDate(a)) / 86400000);
  const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();

  function dueDate(first, period, n) {
    if (period === 'weekly') return addDays(first, 7 * n);
    const months = { monthly: 1, quarterly: 3, yearly: 12 }[period] * n;
    const f = parse(first);
    const total = f.m - 1 + months;
    const y = f.y + Math.floor(total / 12), m = (total % 12) + 1;
    return iso(y, m, Math.min(f.d, lastDay(y, m)));
  }

  const CURRENCIES = ['RUB', 'USD', 'EUR'];
  const CUR_NAME = { RUB: 'Рубли', USD: 'Доллары', EUR: 'Евро' };
  const SIGN = { RUB: '₽', USD: '$', EUR: '€' };
  const PERIODS = { weekly: 'Еженедельно', monthly: 'Ежемесячно', quarterly: 'Раз в квартал', yearly: 'Раз в год' };

  const users = [
    { id: 'u-admin', login: 'admin', name: 'Администратор', email: '', role: 'admin', system: true, telegram: '', notifyEmail: false, created: '2026-06-01' },
    { id: 'u-anna', login: 'anna', name: 'Анна Ковалёва', email: 'anna@kefcoders.ru', role: 'user', system: false, telegram: '@anna_kov', notifyEmail: true, created: '2026-06-01' },
    { id: 'u-maria', login: 'maria', name: 'Мария Лебедева', email: 'maria@kefcoders.ru', role: 'user', system: false, telegram: '@mlebedeva', notifyEmail: false, created: '2026-06-03' },
    { id: 'u-user', login: 'user', name: 'Дмитрий Орлов', email: '', role: 'user', system: false, telegram: '', notifyEmail: false, created: '2026-07-14' },
  ];

  const payments = [
    { id: 'rent', name: 'Аренда офиса', desc: 'Офис на Пушкинской, 12. Договор № 14/2025, оплата до 26-го числа.', amount: 50000, currency: 'RUB', period: 'monthly', first: '2026-06-26', created: '2026-06-01', createdBy: 'admin',
      paid: { 0: ['2026-06-25', 'anna'], 1: ['2026-07-24', 'anna'], 2: ['2026-08-26', 'maria'], 3: ['2026-09-25', 'anna'] } },
    { id: 'accounting', name: 'Бухгалтерское сопровождение', desc: 'ООО «Баланс-Сервис», ежемесячный счёт.', amount: 25000, currency: 'RUB', period: 'monthly', first: '2026-06-25', created: '2026-06-01', createdBy: 'admin',
      paid: { 0: ['2026-06-24', 'anna'], 1: ['2026-07-25', 'anna'], 2: ['2026-08-25', 'anna'], 3: ['2026-09-24', 'anna'] } },
    { id: 'mts', name: 'МТС Бизнес, интернет', desc: 'Лицевой счёт 7712 0045 8810.', amount: 3900, currency: 'RUB', period: 'monthly', first: '2026-06-20', created: '2026-06-01', createdBy: 'admin',
      paid: { 0: ['2026-06-19', 'maria'], 1: ['2026-07-20', 'maria'], 2: ['2026-08-18', 'anna'], 3: ['2026-09-20', 'anna'], 4: ['2026-10-19', 'anna'] } },
    { id: 'yandex', name: 'Яндекс 360 для бизнеса', desc: 'Почта и диск, 8 пользователей.', amount: 2400, currency: 'RUB', period: 'monthly', first: '2026-07-01', created: '2026-06-02', createdBy: 'admin',
      paid: { 0: ['2026-07-01', 'anna'], 1: ['2026-08-01', 'anna'], 2: ['2026-09-01', 'maria'], 3: ['2026-10-01', 'anna'] } },
    { id: 'insurance', name: 'Страхование офиса', desc: 'Полис «Ингосстрах» № 0471-2026.', amount: 38000, currency: 'RUB', period: 'quarterly', first: '2026-03-01', created: '2026-06-01', createdBy: 'admin',
      paid: { 0: ['2026-02-27', 'anna'], 1: ['2026-06-01', 'anna'], 2: ['2026-08-29', 'anna'] } },
    { id: 'domain', name: 'Домен invoicekeeper.ru', desc: 'Продление у регистратора REG.RU.', amount: 1500, currency: 'RUB', period: 'yearly', first: '2026-11-13', created: '2026-06-02', createdBy: 'admin', paid: {} },
    { id: 'do', name: 'Сервер DigitalOcean', desc: 'Droplet 4 vCPU / 8 GB, продакшен.', amount: 20, currency: 'USD', period: 'monthly', first: '2026-07-14', created: '2026-06-20', createdBy: 'admin',
      paid: { 0: ['2026-07-14', 'maria'], 1: ['2026-08-14', 'maria'], 2: ['2026-09-14', 'maria'] } },
    { id: 'sentry', name: 'Sentry Team', desc: 'Мониторинг ошибок, 50 тыс. событий.', amount: 26, currency: 'USD', period: 'monthly', first: '2026-07-18', created: '2026-06-20', createdBy: 'admin',
      paid: { 0: ['2026-07-18', 'maria'], 1: ['2026-08-17', 'maria'], 2: ['2026-09-17', 'maria'] } },
    { id: 'github', name: 'GitHub Team', desc: '11 мест, организация kefcoders.', amount: 44, currency: 'USD', period: 'monthly', first: '2026-07-22', created: '2026-06-20', createdBy: 'admin',
      paid: { 0: ['2026-07-22', 'maria'], 1: ['2026-08-21', 'maria'], 2: ['2026-09-22', 'maria'], 3: ['2026-10-22', 'maria'] } },
    { id: 'aws', name: 'AWS', desc: 'S3 и CloudFront для файлов клиентов.', amount: 134.2, currency: 'USD', period: 'monthly', first: '2026-10-28', created: '2026-10-23', createdBy: 'admin', paid: {} },
    { id: 'jetbrains', name: 'JetBrains All Products', desc: 'Лицензия на команду, 3 места.', amount: 28.9, currency: 'EUR', period: 'monthly', first: '2026-07-05', created: '2026-06-20', createdBy: 'admin',
      paid: { 0: ['2026-07-05', 'anna'], 1: ['2026-08-05', 'anna'], 2: ['2026-09-04', 'anna'], 3: ['2026-10-05', 'anna'] } },
    { id: 'figma', name: 'Figma Professional', desc: 'Оплата 31-го; в коротких месяцах — в последний день.', amount: 15, currency: 'EUR', period: 'monthly', first: '2026-07-31', created: '2026-06-20', createdBy: 'admin',
      paid: { 0: ['2026-07-31', 'maria'], 1: ['2026-08-31', 'maria'], 2: ['2026-10-03', 'maria'] } },
    { id: 'timeweb', name: 'Хостинг Timeweb', desc: 'Старый сервер, переехали на DigitalOcean.', amount: 1290, currency: 'RUB', period: 'monthly', first: '2026-04-10', created: '2026-04-01', createdBy: 'admin', deleted: '2026-08-15',
      paid: { 0: ['2026-04-10', 'anna'], 1: ['2026-05-08', 'anna'], 2: ['2026-06-10', 'anna'], 3: ['2026-07-10', 'anna'], 4: ['2026-08-10', 'anna'] } },
  ];

  function materialize(p) {
    const out = [];
    const limit = addDays(TODAY, HORIZON_DAYS);
    for (let n = 0; n < 60; n++) {
      const due = dueDate(p.first, p.period, n);
      if (p.deleted && due > p.deleted && !p.paid[n]) break;
      const hasFuture = out.some((o) => o.due > TODAY);
      if (due > limit && hasFuture) break;
      const pm = p.paid[n];
      out.push({ id: p.id + '-' + n, pid: p.id, seq: n, due, amount: p.amount, currency: p.currency,
        paid: pm ? pm[0] : null, paidBy: pm ? pm[1] : null, files: [] });
    }
    return out;
  }

  const occurrences = payments.flatMap(materialize);
  const occ = (id) => occurrences.find((o) => o.id === id);

  const reminders = [
    { id: 'n1', oid: 'rent-4', channel: 'telegram', kind: 'before_due', status: 'sent', at: '2026-10-23 09:00', attempts: 1 },
    { id: 'n2', oid: 'rent-4', channel: 'email', kind: 'before_due', status: 'sent', at: '2026-10-23 09:00', attempts: 1, to: 'anna@kefcoders.ru' },
    { id: 'n3', oid: 'rent-4', channel: 'inapp', kind: 'before_due', status: 'sent', at: '2026-10-23 09:00', attempts: 1 },
    { id: 'n4', oid: 'accounting-4', channel: 'telegram', kind: 'before_due', status: 'sent', at: '2026-10-22 09:00', attempts: 1 },
    { id: 'n5', oid: 'accounting-4', channel: 'webhook', kind: 'before_due', status: 'sent', at: '2026-10-22 09:05', attempts: 2, error: 'Первая попытка: нет ответа за 5 с' },
    { id: 'n6', oid: 'accounting-4', channel: 'inapp', kind: 'before_due', status: 'sent', at: '2026-10-22 09:00', attempts: 1 },
    { id: 'n7', oid: 'github-3', channel: 'telegram', kind: 'before_due', status: 'sent', at: '2026-10-19 09:00', attempts: 1 },
    { id: 'n8', oid: 'sentry-3', channel: 'telegram', kind: 'overdue', status: 'sent', at: '2026-10-19 09:00', attempts: 1 },
    { id: 'n9', oid: 'sentry-3', channel: 'inapp', kind: 'overdue', status: 'sent', at: '2026-10-19 09:00', attempts: 1 },
    { id: 'n10', oid: 'sentry-3', channel: 'telegram', kind: 'before_due', status: 'sent', at: '2026-10-15 09:00', attempts: 1 },
    { id: 'n11', oid: 'do-3', channel: 'telegram', kind: 'overdue', status: 'sent', at: '2026-10-15 09:00', attempts: 1 },
    { id: 'n12', oid: 'do-3', channel: 'inapp', kind: 'overdue', status: 'sent', at: '2026-10-15 09:00', attempts: 1 },
    { id: 'n13', oid: 'do-3', channel: 'telegram', kind: 'before_due', status: 'sent', at: '2026-10-11 09:00', attempts: 1 },
    { id: 'n14', oid: 'do-3', channel: 'email', kind: 'before_due', status: 'failed', at: '2026-10-11 09:00', attempts: 5, error: 'SMTP 550: адрес получателя не найден' },
    { id: 'n15', oid: 'mts-4', channel: 'telegram', kind: 'before_due', status: 'sent', at: '2026-10-17 09:00', attempts: 1 },
  ];

  const inbox = [
    { id: 'i1', oid: 'rent-4', kind: 'before_due', at: '2026-10-23 09:00', read: false },
    { id: 'i2', oid: 'accounting-4', kind: 'before_due', at: '2026-10-22 09:00', read: false },
    { id: 'i3', oid: 'sentry-3', kind: 'overdue', at: '2026-10-19 09:00', read: false },
    { id: 'i4', oid: 'github-3', kind: 'before_due', at: '2026-10-19 09:00', read: true },
    { id: 'i5', oid: 'do-3', kind: 'overdue', at: '2026-10-15 09:00', read: true },
  ];

  occ('mts-4').files.push({ id: 'f1', kind: 'file', name: 'mts-oktyabr-2026.pdf', size: '184 КБ', by: 'anna', at: '2026-10-19 13:06' });
  occ('github-3').files.push({ id: 'f2', kind: 'link', name: 'Счёт GitHub за октябрь', url: 'https://github.com/organizations/kefcoders/settings/billing', by: 'maria', at: '2026-10-22 11:48' });
  occ('rent-3').files.push({ id: 'f3', kind: 'file', name: 'platezhka-arenda-sentyabr.pdf', size: '96 КБ', by: 'anna', at: '2026-09-25 15:20' });
  occ('jetbrains-3').files.push({ id: 'f4', kind: 'file', name: 'jetbrains-invoice-oct.png', size: '412 КБ', by: 'anna', at: '2026-10-06 12:01' });

  const audit = [
    { at: '2026-10-24 09:12', actor: 'anna', action: 'auth.login', text: 'Вход в панель', ip: '85.140.12.7' },
    { at: '2026-10-23 18:02', actor: 'admin', action: 'payment.create', text: 'Создан регулярный платёж «AWS»: 134,20 $, ежемесячно, первый срок 28.10.2026', ip: '85.140.12.3' },
    { at: '2026-10-22 11:48', actor: 'maria', action: 'attachment.add', text: 'Ссылка на счёт к периоду «GitHub Team» за 22.10.2026', ip: '93.80.41.15', oid: 'github-3' },
    { at: '2026-10-22 11:47', actor: 'maria', action: 'telegram.mark_paid', text: 'Оплата «GitHub Team» за 22.10.2026 отмечена кнопкой в Telegram', ip: '', oid: 'github-3' },
    { at: '2026-10-21 16:20', actor: 'user', action: 'auth.login_failed', text: 'Неверный пароль', ip: '176.59.33.201' },
    { at: '2026-10-19 13:06', actor: 'anna', action: 'attachment.add', text: 'Чек mts-oktyabr-2026.pdf к периоду «МТС Бизнес, интернет» за 20.10.2026', ip: '85.140.12.7', oid: 'mts-4' },
    { at: '2026-10-19 13:05', actor: 'anna', action: 'occurrence.mark_paid', text: 'Оплата «МТС Бизнес, интернет» за 20.10.2026, дата 19.10.2026', ip: '85.140.12.7', oid: 'mts-4' },
    { at: '2026-10-15 10:31', actor: 'admin', action: 'user.update', text: 'Пользователь maria: изменён email', ip: '85.140.12.3' },
    { at: '2026-10-06 12:04', actor: 'anna', action: 'occurrence.change_paid_date', text: 'Дата оплаты «JetBrains All Products» за 05.10.2026: 06.10.2026 → 05.10.2026, просрочка снята', ip: '85.140.12.7', oid: 'jetbrains-3' },
    { at: '2026-10-06 12:01', actor: 'anna', action: 'occurrence.mark_paid', text: 'Оплата «JetBrains All Products» за 05.10.2026, дата 06.10.2026', ip: '85.140.12.7', oid: 'jetbrains-3' },
    { at: '2026-10-03 17:44', actor: 'maria', action: 'occurrence.mark_paid', text: 'Оплата «Figma Professional» за 30.09.2026, дата 03.10.2026', ip: '93.80.41.15', oid: 'figma-2' },
    { at: '2026-10-01 09:30', actor: 'anna', action: 'occurrence.mark_paid', text: 'Оплата «Яндекс 360 для бизнеса» за 01.10.2026, дата 01.10.2026', ip: '85.140.12.7', oid: 'yandex-3' },
    { at: '2026-08-15 11:00', actor: 'admin', action: 'payment.delete', text: 'Платёж «Хостинг Timeweb» прекращён. История сохранена', ip: '85.140.12.3' },
    { at: '2026-07-14 10:15', actor: 'admin', action: 'user.create', text: 'Создан пользователь user (Дмитрий Орлов)', ip: '85.140.12.3' },
  ];

  const ACTIONS = {
    'auth.login': 'Вход', 'auth.login_failed': 'Неудачный вход', 'auth.logout': 'Выход',
    'payment.create': 'Новый платёж', 'payment.delete': 'Прекращение платежа',
    'occurrence.mark_paid': 'Отметка оплаты', 'occurrence.mark_unpaid': 'Снятие отметки', 'occurrence.change_paid_date': 'Изменение даты оплаты',
    'user.create': 'Новый пользователь', 'user.update': 'Изменение пользователя', 'user.delete': 'Удаление пользователя',
    'attachment.add': 'Вложение', 'attachment.delete': 'Удаление вложения', 'telegram.mark_paid': 'Оплата из Telegram',
  };
  const CHANNELS = { telegram: 'Telegram', email: 'Почта', webhook: 'Webhook', inapp: 'В панели' };

  const budgets = {
    month: { RUB: 90000, USD: 250, EUR: 60 },
    year: { RUB: 1100000, USD: 3000, EUR: 700 },
  };

  return {
    TODAY, TIMEZONE, REMIND_DAYS, HORIZON_DAYS, CURRENCIES, CUR_NAME, SIGN, PERIODS, ACTIONS, CHANNELS,
    users, payments, occurrences, reminders, inbox, audit, budgets,
    dueDate, addDays, diff, lastDay, pad, iso,
  };
})();
