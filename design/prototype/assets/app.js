(function () {
  const D = window.IKD;
  const params = new URLSearchParams(location.search);
  const PAGE = document.body.dataset.page || '';

  const ss = {
    get(k) { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { sessionStorage.setItem(k, v); } catch (e) { } },
    del(k) { try { sessionStorage.removeItem(k); } catch (e) { } },
  };
  if (params.get('reset') === '1') ss.del('ik-state');
  if (params.get('role')) ss.set('ik-role', params.get('role') === 'user' ? 'user' : 'admin');
  if (params.get('theme')) ss.set('ik-theme', params.get('theme') === 'dark' ? 'dark' : 'light');
  const ROLE = ss.get('ik-role') || 'admin';
  const THEME = ss.get('ik-theme') || 'light';
  document.documentElement.dataset.theme = THEME;

  const MONTHS = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];
  const MONTHS_GEN = ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'];
  const WEEKDAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'];
  const plural = (n, one, few, many) => {
    const a = Math.abs(n) % 100, b = a % 10;
    if (a > 10 && a < 20) return many;
    if (b === 1) return one;
    if (b >= 2 && b <= 4) return few;
    return many;
  };
  const F = {
    money: (v, c) => new Intl.NumberFormat('ru-RU', { style: 'currency', currency: c }).format(v),
    num: (v) => new Intl.NumberFormat('ru-RU', { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(v),
    sign: (c) => D.SIGN[c],
    date: (s) => s ? s.slice(8, 10) + '.' + s.slice(5, 7) + '.' + s.slice(0, 4) : '',
    short: (s) => s ? s.slice(8, 10) + '.' + s.slice(5, 7) : '',
    long: (s) => +s.slice(8, 10) + ' ' + MONTHS_GEN[+s.slice(5, 7) - 1],
    weekday: (s) => WEEKDAYS[new Date(s + 'T12:00:00').getDay()],
    month: (ym) => { const m = MONTHS[+ym.slice(5, 7) - 1]; return m[0].toUpperCase() + m.slice(1) + ' ' + ym.slice(0, 4); },
    monthOnly: (ym) => { const m = MONTHS[+ym.slice(5, 7) - 1]; return m[0].toUpperCase() + m.slice(1); },
    days: (n) => n + ' ' + plural(n, 'день', 'дня', 'дней'),
    plural,
    period: (p) => D.PERIODS[p],
    time: (s) => s.slice(8, 10) + '.' + s.slice(5, 7) + ', ' + s.slice(11, 16),
    channel: (c) => D.CHANNELS[c],
    action: (a) => D.ACTIONS[a] || a,
  };
  window.F = F;

  const hash = (s) => { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0; return Math.abs(h); };
  F.stamp = (o) => {
    const h = hash(o.id), rot = -1.5 - (h % 30) / 10, dx = h % 7, my = (h >> 3) % 40;
    const fresh = o.hit || D.diff(o.paid, D.TODAY) <= 3 || o.paid > o.due;
    return 'transform:translateX(' + dx + 'px) rotate(' + rot.toFixed(1) + 'deg);-webkit-mask-position:' + (h % 60) + 'px ' + my + 'px;mask-position:' + (h % 60) + 'px ' + my + 'px;opacity:' + (fresh ? 1 : .8);
  };

  const clone = (x) => JSON.parse(JSON.stringify(x));
  function seed() {
    return { v: 3, payments: clone(D.payments), occurrences: clone(D.occurrences), users: clone(D.users),
      inbox: clone(D.inbox), audit: clone(D.audit), reminders: clone(D.reminders), budgets: clone(D.budgets) };
  }
  let saved = null;
  try { saved = JSON.parse(ss.get('ik-state') || 'null'); } catch (e) { saved = null; }
  const initial = saved && saved.v === 3 ? saved : seed();

  const nowStamp = () => D.TODAY + ' ' + new Date().toTimeString().slice(0, 5);

  document.addEventListener('alpine:init', () => {
    const Alpine = window.Alpine;

    Alpine.directive('num', (el, { expression }, { evaluateLater, effect }) => {
      const get = evaluateLater(expression);
      let cur = null, raf = 0;
      effect(() => get((v) => {
        const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (cur === null || reduce || v === cur) { cur = v; el.textContent = F.num(v); return; }
        const from = cur, t0 = performance.now() + 260;
        cur = v; cancelAnimationFrame(raf);
        el.classList.add('num-changed');
        const step = (t) => {
          const k = Math.min(1, Math.max(0, (t - t0) / 520)), e = 1 - Math.pow(1 - k, 3);
          el.textContent = F.num(from + (v - from) * e);
          if (k < 1) raf = requestAnimationFrame(step); else setTimeout(() => el.classList.remove('num-changed'), 600);
        };
        raf = requestAnimationFrame(step);
      }));
    });

    Alpine.store('ik', {
      today: D.TODAY,
      role: ROLE,
      theme: THEME,
      remindDays: D.REMIND_DAYS,
      ...initial,
      toasts: [],
      changed: null,

      get me() { return this.users.find((u) => u.login === (this.role === 'admin' ? 'admin' : 'anna')); },
      get isAdmin() { return this.role === 'admin'; },
      get unread() { return this.inbox.filter((i) => !i.read).length; },

      save() {
        ss.set('ik-state', JSON.stringify({ v: 3, payments: this.payments, occurrences: this.occurrences, users: this.users,
          inbox: this.inbox, audit: this.audit, reminders: this.reminders, budgets: this.budgets }));
      },

      occ(id) { return this.occurrences.find((o) => o.id === id); },
      pay(id) { return this.payments.find((p) => p.id === id); },
      user(login) { return this.users.find((u) => u.login === login); },
      userName(login) { const u = this.user(login); return u ? u.name : login; },
      payOf(o) { return this.pay(o.pid); },

      state(o) {
        if (o.paid) return o.paid > o.due ? 'paid_late' : 'paid';
        const left = D.diff(this.today, o.due);
        if (left < 0) return 'overdue';
        if (left <= D.REMIND_DAYS) return 'due_soon';
        return 'upcoming';
      },
      daysOverdue(o) {
        const s = this.state(o);
        if (s === 'overdue') return D.diff(o.due, this.today);
        if (s === 'paid_late') return D.diff(o.due, o.paid);
        return 0;
      },
      daysLeft(o) { return D.diff(this.today, o.due); },
      stateLabel(o) {
        const s = this.state(o);
        return { paid: 'Оплачено', paid_late: 'Оплачено с опозданием', due_soon: 'Скоро', overdue: 'Просрочено', upcoming: 'Ожидает' }[s];
      },
      rel(o) {
        const s = this.state(o), left = this.daysLeft(o);
        if (s === 'overdue') return 'просрочено на ' + F.days(this.daysOverdue(o));
        if (s === 'paid_late') return 'с опозданием на ' + F.days(this.daysOverdue(o));
        if (o.paid) return 'оплачено ' + F.date(o.paid);
        if (left === 0) return 'сегодня';
        if (left === 1) return 'завтра';
        return 'через ' + F.days(left);
      },
      statusLine(o) {
        const s = this.state(o);
        if (s === 'overdue') return 'Просрочено на ' + F.days(this.daysOverdue(o));
        if (s === 'paid_late') return 'Оплачено с опозданием на ' + F.days(this.daysOverdue(o));
        if (s === 'paid') return 'Оплачено ' + F.date(o.paid);
        return (s === 'due_soon' ? 'Скоро · ' : 'Ожидает · ') + this.rel(o);
      },
      lastReminder(o) {
        const r = this.reminders.filter((x) => x.oid === o.id && x.channel === 'telegram' && x.status === 'sent');
        return r.length ? r[0] : null;
      },
      month(ym) {
        return this.occurrences.filter((o) => o.due.slice(0, 7) === ym && this.visible(o))
          .sort((a, b) => a.due.localeCompare(b.due) || a.pid.localeCompare(b.pid));
      },
      visible(o) { const p = this.payOf(o); return !!p; },
      overdueList() { return this.occurrences.filter((o) => this.state(o) === 'overdue').sort((a, b) => a.due.localeCompare(b.due)); },
      nextDays(n) { return this.occurrences.filter((o) => !o.paid && this.daysLeft(o) >= 0 && this.daysLeft(o) <= n).sort((a, b) => a.due.localeCompare(b.due)); },

      totals(from, to, asOf) {
        const at = asOf || this.today;
        return D.CURRENCIES.map((c) => {
          const list = this.occurrences.filter((o) => o.currency === c && o.due >= from && o.due <= to);
          const paidAt = (o) => o.paid && o.paid <= at;
          const sum = (f) => list.filter(f).reduce((s, o) => s + o.amount, 0);
          const planned = sum(() => true), paid = sum(paidAt);
          const overdue = sum((o) => !paidAt(o) && o.due < at);
          const late = sum((o) => paidAt(o) && o.paid > o.due);
          return { currency: c, name: D.CUR_NAME[c], planned, paid, unpaid: planned - paid, overdue, late,
            count: list.length, countPaid: list.filter(paidAt).length,
            countOverdue: list.filter((o) => !paidAt(o) && o.due < at).length };
        });
      },

      log(action, text, oid) { this.audit.unshift({ at: nowStamp(), actor: this.me.login, action, text, ip: '85.140.12.7', oid }); },
      toast(text, undo) {
        const t = { id: Math.random().toString(36).slice(2), text, undo };
        this.toasts = [...this.toasts.slice(-2), t];
        if (!undo) setTimeout(() => this.dismiss(t.id), 6000);
      },
      dismiss(id) { this.toasts = this.toasts.filter((t) => t.id !== id); },

      markPaid(id, date, silent) {
        const o = this.occ(id), p = this.payOf(o);
        o.paid = date; o.paidBy = this.me.login; o.hit = Date.now(); this.changed = { currency: o.currency, at: Date.now() };
        this.log('occurrence.mark_paid', 'Оплата «' + p.name + '» за ' + F.date(o.due) + ', дата ' + F.date(date), id);
        this.save();
        const inCard = window.Alpine.store('dlg').name === 'period' || document.body.dataset.page === 'period';
        if (!silent) this.toast(inCard ? 'Оплата отмечена: ' + F.date(date) + '.' : 'Оплата отмечена: «' + p.name + '», ' + F.date(date) + '. Исправить дату или снять отметку можно в карточке периода.', inCard ? null : () => this.unmark(id, true));
      },
      unmark(id, fromUndo) {
        const o = this.occ(id), p = this.payOf(o), was = o.paid;
        o.paid = null; o.paidBy = null; o.hit = 0; this.changed = { currency: o.currency, at: Date.now() };
        this.log('occurrence.mark_unpaid', 'Снята отметка об оплате «' + p.name + '» за ' + F.date(o.due) + ' (была ' + F.date(was) + ')', id);
        this.save();
        const inCard = window.Alpine.store('dlg').name === 'period' || document.body.dataset.page === 'period';
        this.toast(fromUndo ? 'Отметка снята.' : 'Отметка об оплате «' + p.name + '» снята.', fromUndo || inCard ? null : () => this.markPaid(id, was, true));
      },
      changeDate(id, date) {
        const o = this.occ(id), p = this.payOf(o), was = o.paid;
        const wasLate = was > o.due;
        o.paid = date;
        const nowLate = date > o.due;
        this.log('occurrence.change_paid_date', 'Дата оплаты «' + p.name + '» за ' + F.date(o.due) + ': ' + F.date(was) + ' → ' + F.date(date) + (wasLate && !nowLate ? ', просрочка снята' : ''), id);
        this.save();
        this.toast('Дата оплаты: ' + F.date(date) + '. ' + (wasLate && !nowLate ? 'Просрочка снята.' : nowLate ? 'Оплачено с опозданием на ' + F.days(D.diff(o.due, date)) + '.' : 'Оплачено вовремя.'));
      },
      addFile(id, file) {
        const o = this.occ(id), p = this.payOf(o);
        o.files.push({ id: 'f' + Date.now(), by: this.me.login, at: nowStamp(), ...file });
        this.log('attachment.add', (file.kind === 'link' ? 'Ссылка' : 'Чек ' + file.name) + ' к периоду «' + p.name + '» за ' + F.date(o.due), id);
        this.save();
        this.toast(file.kind === 'link' ? 'Ссылка прикреплена.' : 'Чек ' + file.name + ' прикреплён.');
      },
      removeFile(id, fid) {
        const o = this.occ(id), f = o.files.find((x) => x.id === fid);
        o.files = o.files.filter((x) => x.id !== fid);
        this.log('attachment.delete', 'Удалено вложение «' + f.name + '»', id);
        this.save();
        this.toast('Вложение «' + f.name + '» удалено.');
      },
      createPayment(d) {
        const id = 'p' + Date.now().toString(36);
        const p = { id, name: d.name.trim(), desc: d.desc.trim(), amount: +d.amount, currency: d.currency, period: d.period, first: d.due, end: d.end || null, created: this.today, createdBy: this.me.login, paid: {} };
        this.payments.push(p);
        const limit = D.addDays(this.today, D.HORIZON_DAYS);
        for (let n = 0; n < 60; n++) {
          const due = D.dueDate(p.first, p.period, n);
          if (p.end && due > p.end) break;
          if (due > limit && this.occurrences.some((o) => o.pid === id && o.due > this.today)) break;
          this.occurrences.push({ id: id + '-' + n, pid: id, seq: n, due, amount: p.amount, currency: p.currency, paid: null, paidBy: null, files: [] });
        }
        this.log('payment.create', 'Создан регулярный платёж «' + p.name + '»: ' + F.money(p.amount, p.currency) + ', ' + F.period(p.period).toLowerCase() + ', первый срок ' + F.date(p.first));
        const first = this.occurrences.find((o) => o.pid === id && o.due >= this.today);
        let msg = 'Платёж «' + p.name + '» создан. Первый срок — ' + F.date(p.first) + '.';
        if (first && this.daysLeft(first) <= D.REMIND_DAYS) {
          this.reminders.unshift({ id: 'n' + Date.now(), oid: first.id, channel: 'telegram', kind: 'before_due', status: 'sent', at: nowStamp(), attempts: 1 });
          msg += ' До срока меньше 3 дней — напоминание уже ушло в Telegram.';
        }
        this.save();
        this.toast(msg);
        return id;
      },
      stopPayment(id) {
        const p = this.pay(id);
        p.deleted = this.today;
        const removed = this.occurrences.filter((o) => o.pid === id && o.due > this.today && !o.paid);
        this.occurrences = this.occurrences.filter((o) => !removed.includes(o));
        this.log('payment.delete', 'Платёж «' + p.name + '» прекращён. Удалено будущих периодов: ' + removed.length + '. История сохранена');
        this.save();
        this.toast('Платёж «' + p.name + '» прекращён. История оплат сохранена.');
      },
      saveUser(d) {
        if (d.id) {
          const u = this.users.find((x) => x.id === d.id);
          Object.assign(u, { login: d.login.trim(), name: d.name.trim(), email: d.email.trim(), notifyEmail: d.notifyEmail });
          this.log('user.update', 'Пользователь ' + u.login + ': изменены данные' + (d.password ? ', пароль сменён, сессии завершены' : ''));
          this.toast('Изменения пользователя ' + u.login + ' сохранены.');
        } else {
          this.users.push({ id: 'u' + Date.now(), login: d.login.trim(), name: d.name.trim(), email: d.email.trim(), role: 'user', system: false, telegram: '', notifyEmail: d.notifyEmail, created: this.today });
          this.log('user.create', 'Создан пользователь ' + d.login.trim() + (d.name ? ' (' + d.name.trim() + ')' : ''));
          this.toast('Пользователь ' + d.login.trim() + ' создан. Передайте ему логин и пароль.');
        }
        this.save();
      },
      deleteUser(id) {
        const u = this.users.find((x) => x.id === id);
        this.users = this.users.filter((x) => x.id !== id);
        this.log('user.delete', 'Удалён пользователь ' + u.login);
        this.save();
        this.toast('Пользователь ' + u.login + ' удалён.');
      },
      read(id) { const i = this.inbox.find((x) => x.id === id); if (i) i.read = true; this.save(); },
      readAll() { this.inbox.forEach((i) => { i.read = true; }); this.save(); },
      setTheme(t) { this.theme = t; document.documentElement.dataset.theme = t; ss.set('ik-theme', t); },
    });

    Alpine.store('dlg', {
      name: null, sub: null, ctx: {}, opener: null, subOpener: null,
      open(name, ctx, ev) {
        if (this.name === 'period' && name !== 'period') {
          this.subOpener = ev && ev.currentTarget ? ev.currentTarget : document.activeElement;
          this.ctx = Object.assign({}, this.ctx, ctx || {});
          window.dispatchEvent(new CustomEvent('ik-dlg-open', { detail: { name } }));
          this.sub = name;
          return;
        }
        this.opener = ev && ev.currentTarget ? ev.currentTarget : document.activeElement;
        this.ctx = ctx || {};
        window.dispatchEvent(new CustomEvent('ik-dlg-open', { detail: { name } }));
        this.name = name;
      },
      close() { if (this.sub) this.subClosed(); else this.closed(); },
      subClosed() {
        this.sub = null;
        const el = this.subOpener;
        setTimeout(() => {
          if (el && document.body.contains(el) && el.offsetParent !== null) return el.focus();
          const f = document.querySelector('dialog.drawer-dlg[open] .pay-box button, dialog.drawer-dlg[open] .pay-box input');
          if (f) f.focus();
        }, 0);
      },
      closed() {
        this.name = null;
        const el = this.opener, ctx = this.ctx;
        setTimeout(() => {
          if (el && document.body.contains(el) && el.offsetParent !== null) el.focus();
          else if (ctx.oid) { const n = document.querySelector('[data-oid="' + ctx.oid + '"] .name-btn'); if (n) n.focus(); }
        }, 0);
      },
    });

    Alpine.data('period', (fixedId) => ({
      fixedId,
      payDate: D.TODAY,
      payErr: '',
      init() { if (!this.fixedId) window.addEventListener('ik-dlg-open', () => { this.payDate = D.TODAY; this.payErr = ''; }); },
      get o() { return this.$store.ik.occ(this.fixedId || this.$store.dlg.ctx.oid); },
      get p() { return this.o ? this.$store.ik.payOf(this.o) : null; },
      get siblings() { return this.o ? this.$store.ik.occurrences.filter((x) => x.pid === this.o.pid).sort((a, b) => b.due.localeCompare(a.due)) : []; },
      get history() { return this.o ? this.$store.ik.audit.filter((a) => a.oid === this.o.id) : []; },
      get reminders() { return this.o ? this.$store.ik.reminders.filter((r) => r.oid === this.o.id) : []; },
      canRemove(f) { return this.$store.ik.isAdmin || f.by === this.$store.ik.me.login; },
      submitPay() {
        if (!this.payDate) { this.payErr = 'Укажите дату оплаты.'; return this.$refs.payDate.focus(); }
        if (this.payDate > this.$store.ik.today) { this.payErr = 'Укажите дату не позже сегодняшней — ' + F.date(this.$store.ik.today) + '.'; return this.$refs.payDate.focus(); }
        this.payErr = '';
        this.$store.ik.markPaid(this.o.id, this.payDate);
        const root = this.$root;
        this.$nextTick(() => { const b = root.querySelector('.pay-box .btn'); if (b) b.focus(); });
      },
    }));

    Alpine.data('dlgForms', () => ({
      date: D.TODAY, err: '',
      np: { name: '', desc: '', amount: '', currency: 'RUB', period: 'monthly', due: '', end: '' }, npErr: {},
      at: { kind: 'file', file: null, url: '' }, atErr: '',
      uf: { id: null, login: '', name: '', email: '', password: '', notifyEmail: false }, ufErr: {},
      get o() { return this.$store.ik.occ(this.$store.dlg.ctx.oid); },
      get p() { return this.$store.dlg.ctx.pid ? this.$store.ik.pay(this.$store.dlg.ctx.pid) : (this.o ? this.$store.ik.payOf(this.o) : null); },
      get u() { return this.$store.ik.users.find((x) => x.id === this.$store.dlg.ctx.uid); },
      reset() {
        const c = this.$store.dlg.ctx;
        this.err = ''; this.atErr = ''; this.npErr = {}; this.ufErr = {};
        this.date = this.o && this.o.paid ? this.o.paid : D.TODAY;
        this.np = { name: '', desc: '', amount: '', currency: 'RUB', period: 'monthly', due: '', end: '' };
        this.at = { kind: 'file', file: null, url: '' };
        const u = this.u;
        this.uf = u ? { id: u.id, login: u.login, name: u.name, email: u.email, password: '', notifyEmail: u.notifyEmail }
          : { id: null, login: '', name: '', email: '', password: '', notifyEmail: false };
        if (c.prefill) Object.assign(this.np, c.prefill);
      },
      preview() {
        if (!this.o || !this.date) return '';
        if (this.date > this.$store.ik.today) return '';
        const late = D.diff(this.o.due, this.date);
        return late > 0 ? 'Будет: оплачено с опозданием на ' + F.days(late) + '.' : 'Будет: оплачено вовремя.';
      },
      submitDate(kind) {
        if (!this.date) { this.err = 'Укажите дату оплаты.'; return this.$el.querySelector('input[type=date]').focus(); }
        if (this.date > this.$store.ik.today) { this.err = 'Укажите дату не позже сегодняшней — ' + F.date(this.$store.ik.today) + '.'; return this.$el.querySelector('input[type=date]').focus(); }
        if (kind === 'mark') this.$store.ik.markPaid(this.o.id, this.date); else this.$store.ik.changeDate(this.o.id, this.date);
        this.$store.dlg.close();
      },
      submitPayment() {
        const e = {}, n = this.np;
        if (!n.name.trim()) e.name = 'Введите название, например «Аренда офиса».';
        const amt = String(n.amount).replace(/\s/g, '').replace(',', '.');
        if (!/^\d+(\.\d{1,2})?$/.test(amt) || +amt <= 0) e.amount = 'Введите сумму больше нуля, не больше двух знаков после запятой: 50000 или 20,50.';
        if (!n.due) e.due = 'Укажите дату ближайшей оплаты.';
        if (n.end && n.due && n.end < n.due) e.end = 'Дата окончания должна быть не раньше даты ближайшей оплаты.';
        this.npErr = e;
        const first = Object.keys(e)[0];
        if (first) return this.$el.querySelector('[name="np-' + first + '"]').focus();
        n.amount = amt;
        this.$store.ik.createPayment(n);
        this.$store.dlg.close();
      },
      confirmDeleteFile() {
        const f = this.o && this.o.files.find((x) => x.id === this.$store.dlg.ctx.fid);
        if (f) this.$store.ik.removeFile(this.o.id, f.id);
        this.$store.dlg.close();
      },
      get file() { return this.o ? this.o.files.find((x) => x.id === this.$store.dlg.ctx.fid) : null; },
      submitAttach() {
        if (this.at.kind === 'link') {
          if (!/^https?:\/\/\S+\.\S+/.test(this.at.url)) { this.atErr = 'Вставьте ссылку целиком, начиная с https://'; return this.$el.querySelector('[name=at-url]').focus(); }
          this.$store.ik.addFile(this.o.id, { kind: 'link', name: this.at.url.replace(/^https?:\/\//, '').slice(0, 48), url: this.at.url });
        } else {
          const f = this.at.file;
          if (!f) { this.atErr = 'Выберите файл чека: PDF, PNG, JPG или WebP до 10 МБ.'; return this.$el.querySelector('[name=at-file]').focus(); }
          if (!/\.(pdf|png|jpe?g|webp)$/i.test(f.name)) { this.atErr = 'Подходят PDF, PNG, JPG и WebP. Сохраните чек в одном из этих форматов.'; return; }
          if (f.size > 10 * 1024 * 1024) { this.atErr = 'Файл больше 10 МБ. Сожмите его или прикрепите ссылку на чек.'; return; }
          this.$store.ik.addFile(this.o.id, { kind: 'file', name: f.name, size: Math.max(1, Math.round(f.size / 1024)) + ' КБ' });
        }
        this.$store.dlg.close();
      },
      submitUser() {
        const e = {}, u = this.uf;
        if (!/^[a-z0-9._-]{3,64}$/i.test(u.login.trim())) e.login = 'Логин — от 3 до 64 латинских букв, цифр, точек, дефисов или подчёркиваний.';
        else if (this.$store.ik.users.some((x) => x.login.toLowerCase() === u.login.trim().toLowerCase() && x.id !== u.id)) e.login = 'Логин «' + u.login.trim() + '» уже занят. Выберите другой.';
        if (u.email && !/^\S+@\S+\.\S+$/.test(u.email)) e.email = 'Введите адрес целиком, например name@kefcoders.ru.';
        if (!u.id && u.password.length < 8) e.password = 'Пароль — не короче 8 символов.';
        if (u.id && u.password && u.password.length < 8) e.password = 'Новый пароль — не короче 8 символов. Оставьте поле пустым, чтобы не менять.';
        if (u.notifyEmail && !u.email) e.email = 'Укажите почту, чтобы присылать на неё напоминания.';
        this.ufErr = e;
        const first = Object.keys(e)[0];
        if (first) return this.$el.querySelector('[name="uf-' + first + '"]').focus();
        this.$store.ik.saveUser(u);
        this.$store.dlg.close();
      },
    }));

    Alpine.data('bell', () => ({
      open: false,
      get items() { return this.$store.ik.inbox.slice().sort((a, b) => b.at.localeCompare(a.at)); },
      line(i) {
        const ik = this.$store.ik, o = ik.occ(i.oid);
        if (!o) return { t: 'Период удалён', s: '' };
        const p = ik.payOf(o);
        if (o.paid) return { t: p.name, s: 'Уже оплачено ' + F.date(o.paid), red: false };
        if (p.deleted) return { t: p.name, s: 'Платёж прекращён', red: false };
        if (i.kind === 'overdue' || ik.state(o) === 'overdue') return { t: p.name, s: 'Просрочено: ' + F.money(o.amount, o.currency) + ', срок был ' + F.date(o.due), red: true };
        return { t: p.name, s: F.money(o.amount, o.currency) + ' · срок ' + F.date(o.due) + ', ' + ik.rel(o), red: false };
      },
    }));
  });

  const ICON = {
    bell: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 16V11a6 6 0 0 1 12 0v5l1.5 2h-15z"/><path d="M10 20.5a2 2 0 0 0 4 0"/></svg>',
    x: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    clip: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.5l-7.8 7.8a5 5 0 0 1-7-7L13 4.5a3.3 3.3 0 0 1 4.7 4.7l-7.6 7.6a1.7 1.7 0 0 1-2.4-2.4l7-7"/></svg>',
    tg: '<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M21 4L3 11l6 2 2 6 3-4 5 4z"/><path d="M9 13l8-6"/></svg>',
  };
  window.ICON = ICON;

  const NAV = [
    ['index', 'index.html', 'Сводка'], ['periods', 'periods.html', 'Периоды'], ['payments', 'payments.html', 'Платежи'],
    ['calendar', 'calendar.html', 'Календарь'], ['summary', 'summary.html', 'Итоги'],
    ['users', 'users.html', 'Пользователи', true], ['journal', 'journal.html', 'Журнал', true], ['profile', 'profile.html', 'Профиль'],
  ];
  const MOBILE = ['index', 'periods', 'payments', 'calendar'];
  const cur = (k) => (k === PAGE || (PAGE === 'period' && k === 'periods') || (PAGE === 'payment' && k === 'payments') ? ' aria-current="page"' : '');

  const shell = `
  <a class="skip" href="#main">Перейти к содержимому</a>
  <header class="mast" x-data>
    <a class="brand" href="index.html"><b>Invoice Keeper</b></a>
    <span class="today">${F.weekday(D.TODAY)}, ${F.long(D.TODAY)} 2026</span>
    <div style="position:relative" x-data="bell" @keydown.escape="if(open){open=false;$refs.b.focus()}" @click.outside="open=false" @focusout="if (!$el.contains($event.relatedTarget)) open = false">
      <button class="icon-btn" x-ref="b" type="button" @click="open=!open" :aria-expanded="open" aria-controls="inbox"
        :aria-label="'Уведомления' + ($store.ik.unread ? ', непрочитанных: ' + $store.ik.unread : '')">${ICON.bell}<span class="count" x-show="$store.ik.unread" x-text="$store.ik.unread" aria-hidden="true"></span></button>
      <div class="menu" id="inbox" x-show="open" x-cloak x-transition.opacity>
        <div class="menu-head"><b>Уведомления</b><button class="link small" type="button" @click="$store.ik.readAll()" x-show="$store.ik.unread">Прочитать все</button></div>
        <template x-for="i in items" :key="i.id">
          <a class="menu-item" :class="i.read && 'read'" :href="'period.html?id=' + i.oid" @click="$store.ik.read(i.id)" style="text-decoration:none;color:inherit">
            <span class="dot" aria-hidden="true"></span>
            <span><span class="t" x-text="line(i).t"></span><span class="s" :class="line(i).red && 'red'" x-text="line(i).s"></span>
            <span class="s" x-text="'В панели · ' + F.time(i.at) + (i.read ? '' : ' · не прочитано')"></span></span>
          </a>
        </template>
      </div>
    </div>
    <div class="who"><b x-text="$store.ik.me.name"></b><small x-text="$store.ik.isAdmin ? 'логин admin' : $store.ik.me.login + ' · пользователь'"></small></div>
    <button class="btn primary" type="button" x-show="$store.ik.isAdmin" @click="$store.dlg.open('newPayment', {}, $event)">Новый платёж</button>
  </header>
  <nav class="index" aria-label="Разделы" x-data>
    ${NAV.map(([k, href, label, admin]) => `<a href="${href}"${cur(k)}${admin ? ' x-show="$store.ik.isAdmin"' : ''}>${label}</a>`).join('')}
  </nav>
  <nav class="bottom-nav" aria-label="Разделы" x-data>
    ${NAV.filter(([k]) => MOBILE.includes(k)).map(([k, href, label]) => `<a href="${href}"${cur(k)}>${label}</a>`).join('')}
    <div style="position:relative" x-data="{ open: false }" @keydown.escape="if (open) { open = false; $refs.more.focus() }" @click.outside="open = false">
      <button type="button" x-ref="more" :aria-expanded="open" aria-controls="more-nav" @click="open = !open"${NAV.some(([k]) => !MOBILE.includes(k) && cur(k)) ? ' style="color:var(--ink);font-weight:700;box-shadow:inset 0 3px 0 var(--violet)"' : ''}>Ещё</button>
      <div class="more" id="more-nav" x-show="open" x-cloak x-transition.opacity>
        ${NAV.filter(([k]) => !MOBILE.includes(k)).map(([k, href, label, admin]) => `<a href="${href}"${cur(k)}${admin ? ' x-show="$store.ik.isAdmin"' : ''}>${label}</a>`).join('')}
      </div>
    </div>
  </nav>`;

  const toasts = `
  <div class="toast-region" role="status" aria-live="polite" x-data>
    <template x-for="t in $store.ik.toasts" :key="t.id">
      <div class="toast"><span class="grow" x-text="t.text"></span>
        <button class="btn sm" type="button" x-show="typeof t.undo === 'function'" @click="t.undo(); $store.ik.dismiss(t.id)">Отменить</button>
        <button class="icon-btn" type="button" style="border-color:transparent;color:inherit" aria-label="Закрыть уведомление" @click="$store.ik.dismiss(t.id)">${ICON.x}</button>
      </div>
    </template>
  </div>`;

  const top = document.getElementById('shell');
  if (top) top.outerHTML = shell;
  window.IK_TOASTS = toasts;
})();
