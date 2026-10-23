(function () {
  const ICON = window.ICON;
  const sync = (name) => `x-effect="($store.dlg.name === '${name}' || $store.dlg.sub === '${name}') ? ($el.open || $el.showModal()) : ($el.open && $el.close())" @close="$store.dlg.sub === '${name}' ? $store.dlg.subClosed() : ($store.dlg.name === '${name}' && $store.dlg.closed())"`;
  const head = (attrs, text = '') => `<div class="dlg-head"><h2 ${attrs}>${text}</h2><button class="icon-btn x" type="button" aria-label="Закрыть окно" @click="$store.dlg.close()">${ICON.x}</button></div>`;

  const dialogs = `
  <div x-data="dlgForms" @ik-dlg-open.window="reset()">
    <dialog class="dlg side" aria-labelledby="d-mark-t" ${sync('markPaid')}>
      <form method="dialog" @submit.prevent="submitDate('mark')" novalidate x-show="o">
        ${head('id="d-mark-t"', 'Отметить оплату')}
        <div class="dlg-body">
          <p><b x-text="p && p.name"></b><br><span class="muted" x-text="o && ('Срок ' + F.date(o.due) + ' · ' + F.money(o.amount, o.currency))"></span></p>
          <div class="field">
            <label for="d-mark-date">Фактическая дата оплаты</label>
            <input class="input mono" id="d-mark-date" type="date" x-model="date" :max="$store.ik.today" :aria-invalid="!!err" aria-describedby="d-mark-h d-mark-e">
            <span class="hint" id="d-mark-h" x-text="preview() || 'Оплата в день срока считается вовремя.'"></span>
            <span class="err" id="d-mark-e" x-text="err"></span>
          </div>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Отмена</button><button class="btn primary" type="submit">Отметить оплату</button></div>
      </form>
    </dialog>

    <dialog class="dlg side" aria-labelledby="d-date-t" ${sync('changeDate')}>
      <form method="dialog" @submit.prevent="submitDate('change')" novalidate x-show="o">
        ${head('id="d-date-t"', 'Изменить дату оплаты')}
        <div class="dlg-body">
          <p><b x-text="p && p.name"></b><br><span class="muted" x-text="o && ('Срок ' + F.date(o.due) + ' не меняется. Сейчас оплата отмечена ' + F.date(o.paid) + '.')"></span></p>
          <div class="field">
            <label for="d-date-date">Новая фактическая дата</label>
            <input class="input mono" id="d-date-date" type="date" x-model="date" :max="$store.ik.today" :aria-invalid="!!err" aria-describedby="d-date-h d-date-e">
            <span class="hint" id="d-date-h" x-text="preview() || 'Если дата не позже срока, просрочка снимется.'"></span>
            <span class="err" id="d-date-e" x-text="err"></span>
          </div>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Отмена</button><button class="btn primary" type="submit">Сохранить дату</button></div>
      </form>
    </dialog>

    <dialog class="dlg" aria-labelledby="d-un-t" ${sync('unmark')}>
      <div x-show="o">
        ${head(`id="d-un-t" x-text="o && ('Снять отметку об оплате «' + p.name + '» за ' + F.short(o.due) + '?')"`)}
        <div class="dlg-body">
          <p x-text="o && ('Фактическая дата ' + F.date(o.paid) + ' удалится, период снова станет неоплаченным.')"></p>
          <p class="red" x-show="o && o.due < $store.ik.today">Срок прошёл, поэтому период сразу станет просроченным.</p>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Оставить отметку</button><button class="btn danger primary" type="button" @click="$store.ik.unmark(o.id); $store.dlg.close()">Снять отметку</button></div>
      </div>
    </dialog>

    <dialog class="dlg" aria-labelledby="d-at-t" ${sync('attach')}>
      <form method="dialog" @submit.prevent="submitAttach()" novalidate x-show="o">
        ${head('id="d-at-t"', 'Прикрепить чек или ссылку')}
        <div class="dlg-body">
          <p class="muted" x-text="p && o && (p.name + ', период ' + F.date(o.due))"></p>
          <div class="seg" role="group" aria-label="Что прикрепить">
            <button type="button" :aria-pressed="at.kind === 'file'" @click="at.kind = 'file'; atErr = ''">Файл чека</button>
            <button type="button" :aria-pressed="at.kind === 'link'" @click="at.kind = 'link'; atErr = ''">Ссылка</button>
          </div>
          <div class="field" x-show="at.kind === 'file'">
            <label for="d-at-file">Файл</label>
            <input id="d-at-file" name="at-file" type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" @change="at.file = $event.target.files[0]; atErr = ''" aria-describedby="d-at-h d-at-e">
            <span class="hint" id="d-at-h">PDF, PNG, JPG или WebP, до 10 МБ.</span>
          </div>
          <div class="field" x-show="at.kind === 'link'">
            <label for="d-at-url">Ссылка на чек или счёт</label>
            <input class="input" id="d-at-url" name="at-url" type="url" inputmode="url" placeholder="https://lk.mts.ru/bill/2026-10" x-model="at.url" aria-describedby="d-at-e">
          </div>
          <span class="err" id="d-at-e" x-text="atErr" style="color:var(--red);font-size:13px"></span>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Отмена</button><button class="btn primary" type="submit" x-text="at.kind === 'link' ? 'Прикрепить ссылку' : 'Прикрепить чек'"></button></div>
      </form>
    </dialog>

    <dialog class="dlg wide" aria-labelledby="d-np-t" ${sync('newPayment')}>
      <form method="dialog" @submit.prevent="submitPayment()" novalidate>
        ${head('id="d-np-t"', 'Новый регулярный платёж')}
        <div class="dlg-body">
          <div class="form-grid">
            <div class="field wide"><label for="np-name">Название</label>
              <input class="input" id="np-name" name="np-name" maxlength="200" autocomplete="off" placeholder="Аренда офиса" x-model="np.name" :aria-invalid="!!npErr.name" aria-describedby="np-name-e">
              <span class="err" id="np-name-e" x-text="npErr.name"></span></div>
            <div class="field wide"><label for="np-desc">Описание <span class="muted">— необязательно</span></label>
              <textarea class="textarea" id="np-desc" rows="2" placeholder="Договор № 14/2025, оплата до 26-го числа" x-model="np.desc"></textarea></div>
            <div class="field"><label for="np-amount">Сумма</label>
              <input class="input mono" id="np-amount" name="np-amount" inputmode="decimal" autocomplete="off" placeholder="50 000,00" x-model="np.amount" :aria-invalid="!!npErr.amount" aria-describedby="np-amount-e">
              <span class="err" id="np-amount-e" x-text="npErr.amount"></span></div>
            <div class="field"><label for="np-cur">Валюта</label>
              <select class="select" id="np-cur" x-model="np.currency"><option value="RUB">RUB — рубли</option><option value="USD">USD — доллары</option><option value="EUR">EUR — евро</option></select></div>
            <div class="field"><label for="np-period">Периодичность</label>
              <select class="select" id="np-period" x-model="np.period"><option value="monthly">Ежемесячно</option><option value="weekly">Еженедельно</option><option value="quarterly">Раз в квартал</option><option value="yearly">Раз в год</option></select></div>
            <div class="field"><label for="np-due">Дата ближайшей оплаты</label>
              <input class="input mono" id="np-due" name="np-due" type="date" x-model="np.due" :aria-invalid="!!npErr.due" aria-describedby="np-due-h np-due-e">
              <span class="hint" id="np-due-h">Если в месяце нет такого числа, срок — последний день месяца. До срока меньше 3 дней — напоминание уйдёт сразу.</span>
              <span class="err" id="np-due-e" x-text="npErr.due"></span></div>
            <div class="field"><label for="np-end">Окончание <span class="muted">— необязательно</span></label>
              <input class="input mono" id="np-end" name="np-end" type="date" x-model="np.end" :aria-invalid="!!npErr.end" aria-describedby="np-end-e">
              <span class="err" id="np-end-e" x-text="npErr.end"></span></div>
          </div>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Отмена</button><button class="btn primary" type="submit">Создать платёж</button></div>
      </form>
    </dialog>

    <dialog class="dlg" aria-labelledby="d-stop-t" ${sync('stopPayment')}>
      <div x-show="p">
        ${head(`id="d-stop-t" x-text="p && ('Прекратить «' + p.name + '»?')"`)}
        <div class="dlg-body">
          <ul class="list-ruled">
            <li>Новые периоды и напоминания больше не появятся.</li>
            <li x-text="p && (function(){ const f = $store.ik.occurrences.filter(o => o.pid === p.id && o.due > $store.ik.today && !o.paid); return f.length ? 'Будущие неоплаченные периоды удалятся: ' + f.map(o => F.date(o.due)).join(', ') + '.' : 'Будущих неоплаченных периодов нет.'; })()"></li>
            <li x-text="p && ('История сохранится: ' + $store.ik.occurrences.filter(o => o.pid === p.id && (o.due <= $store.ik.today || o.paid)).length + ' ' + F.plural($store.ik.occurrences.filter(o => o.pid === p.id && (o.due <= $store.ik.today || o.paid)).length, 'период', 'периода', 'периодов') + ' с оплатами и вложениями.')"></li>
          </ul>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Не прекращать</button><button class="btn danger primary" type="button" @click="$store.ik.stopPayment(p.id); $store.dlg.close()">Прекратить платёж</button></div>
      </div>
    </dialog>

    <dialog class="dlg wide" aria-labelledby="d-uf-t" ${sync('userForm')}>
      <form method="dialog" @submit.prevent="submitUser()" novalidate>
        ${head(`id="d-uf-t" x-text="uf.id ? 'Изменить пользователя ' + (u && u.login) : 'Новый пользователь'"`)}
        <div class="dlg-body">
          <div class="form-grid">
            <div class="field"><label for="uf-login">Логин</label>
              <input class="input mono" id="uf-login" name="uf-login" autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="ivan.petrov" x-model="uf.login" :aria-invalid="!!ufErr.login" aria-describedby="uf-login-e">
              <span class="err" id="uf-login-e" x-text="ufErr.login"></span></div>
            <div class="field"><label for="uf-name">Имя и фамилия <span class="muted">— необязательно</span></label>
              <input class="input" id="uf-name" name="uf-name" autocomplete="off" placeholder="Иван Петров" x-model="uf.name"></div>
            <div class="field"><label for="uf-email">Почта <span class="muted">— необязательно</span></label>
              <input class="input" id="uf-email" name="uf-email" type="email" inputmode="email" autocomplete="off" placeholder="ivan@kefcoders.ru" x-model="uf.email" :aria-invalid="!!ufErr.email" aria-describedby="uf-email-e">
              <span class="err" id="uf-email-e" x-text="ufErr.email"></span></div>
            <div class="field"><label for="uf-password" x-text="uf.id ? 'Новый пароль — необязательно' : 'Пароль'"></label>
              <input class="input mono" id="uf-password" name="uf-password" type="password" autocomplete="new-password" x-model="uf.password" :aria-invalid="!!ufErr.password" aria-describedby="uf-password-h uf-password-e">
              <span class="hint" id="uf-password-h" x-text="uf.id ? 'Смена пароля завершит все сессии пользователя.' : 'Не короче 8 символов.'"></span>
              <span class="err" id="uf-password-e" x-text="ufErr.password"></span></div>
            <label class="check wide"><input type="checkbox" x-model="uf.notifyEmail"><span>Присылать напоминания на почту</span></label>
            <p class="wide muted small" x-show="!uf.id">Новый пользователь получит роль «пользователь». Администратор задаётся только в файле .env.</p>
          </div>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Отмена</button><button class="btn primary" type="submit" x-text="uf.id ? 'Сохранить изменения' : 'Создать пользователя'"></button></div>
      </form>
    </dialog>

    <dialog class="dlg" aria-labelledby="d-df-t" ${sync('deleteFile')}>
      <div x-show="file">
        ${head(`id="d-df-t" x-text="file && ((file.kind === 'link' ? 'Удалить ссылку «' : 'Удалить чек «') + file.name + '»?')"`)}
        <div class="dlg-body"><p x-text="file && p && o && ((file.kind === 'link' ? 'Ссылка удалится' : 'Файл удалится') + ' из периода «' + p.name + '» за ' + F.date(o.due) + '. Вернуть его будет нельзя — только прикрепить заново.')"></p></div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Оставить</button><button class="btn danger primary" type="button" @click="confirmDeleteFile()" x-text="file && file.kind === 'link' ? 'Удалить ссылку' : 'Удалить чек'"></button></div>
      </div>
    </dialog>

    <dialog class="dlg" aria-labelledby="d-du-t" ${sync('deleteUser')}>
      <div x-show="u">
        ${head(`id="d-du-t" x-text="u && ('Удалить пользователя ' + u.login + '?')"`)}
        <div class="dlg-body">
          <p x-text="u && ((u.name ? u.name + ' — ' : '') + 'доступ пропадёт сразу, все сессии завершатся.')"></p>
          <p class="muted">Отметки об оплате и вложения этого пользователя останутся в истории.</p>
        </div>
        <div class="dlg-foot"><button class="btn quiet" type="button" @click="$store.dlg.close()">Не удалять</button><button class="btn danger primary" type="button" @click="$store.ik.deleteUser(u.id); $store.dlg.close()">Удалить пользователя</button></div>
      </div>
    </dialog>

    <dialog class="dlg drawer-dlg" aria-labelledby="pd-title" ${sync('period')}>
      <div x-data="period(null)">
        <div class="drawer-bar"><a class="link small" :href="o && ('period.html?id=' + o.id)">Открыть страницу периода</a>
          <button class="icon-btn" type="button" aria-label="Закрыть карточку периода" @click="$store.dlg.close()">${ICON.x}</button></div>
        <template x-if="o">${'<div>' + '%%PERIOD%%' + '</div>'}</template>
      </div>
    </dialog>
  </div>`;

  const periodDetail = `
  <div class="period">
    <p class="crumbs"><a :href="'payment.html?id=' + p.id">Регулярный платёж</a><span x-text="' · ' + F.period(p.period).toLowerCase() + (p.deleted ? ' · прекращён ' + F.date(p.deleted) : '')"></span></p>
    <h2 id="pd-title" class="serif" style="font-size:28px;line-height:1.2" x-text="p.name"></h2>
    <p class="st" :class="$store.ik.state(o)" style="margin-top:8px" x-text="$store.ik.statusLine(o)"></p>
    <p class="big-sum"><span x-text="F.num(o.amount)"></span><small x-text="F.sign(o.currency)"></small></p>
    <dl class="facts">
      <div><dt class="sr-only">Срок</dt><dd>Срок <b x-text="F.date(o.due)"></b></dd></div>
      <div><dt class="sr-only">Номер периода</dt><dd>Период <b x-text="'№ ' + (o.seq + 1)"></b></dd></div>
      <div x-show="o.paid"><dt class="sr-only">Отметка</dt><dd>Отметка <b x-text="o.paidBy ? $store.ik.userName(o.paidBy) : ''"></b></dd></div>
    </dl>

    <template x-if="!o.paid">
      <form class="pay-box" @submit.prevent="submitPay()" novalidate>
        <div class="row">
          <div class="field"><label :for="'pay-' + o.id">Фактическая дата оплаты</label>
            <input class="input mono" :id="'pay-' + o.id" x-ref="payDate" type="date" x-model="payDate" :max="$store.ik.today" :aria-invalid="!!payErr" :aria-describedby="'pay-e-' + o.id"></div>
          <button class="btn primary" type="submit">Отметить оплату</button>
        </div>
        <span class="err small red" :id="'pay-e-' + o.id" x-text="payErr"></span>
        <p class="small muted">Срок периода не изменится. Дату можно будет исправить.</p>
      </form>
    </template>
    <template x-if="o.paid">
      <div class="pay-box">
        <div><span class="stamp" :style="F.stamp(o)" :class="{ late: $store.ik.state(o) === 'paid_late', hit: o.hit && (Date.now() - o.hit < 1500) }">Оплачено <em x-text="F.short(o.paid)"></em></span>
          <span class="stamp-late-note" x-show="$store.ik.state(o) === 'paid_late'" x-text="'Позже срока на ' + F.days($store.ik.daysOverdue(o)) + '. Если оплатили раньше, исправьте дату.'"></span></div>
        <div class="btn-row">
          <button class="btn sm" type="button" @click="$store.dlg.open('changeDate', { oid: o.id }, $event)">Изменить дату оплаты</button>
          <button class="btn sm danger" type="button" @click="$store.dlg.open('unmark', { oid: o.id }, $event)">Снять отметку</button>
        </div>
      </div>
    </template>

    <h3 class="section-title" style="font-size:19px;margin-top:28px">Чеки и ссылки</h3>
    <ul class="list-ruled">
      <template x-for="f in o.files" :key="f.id">
        <li><span>${ICON.clip} <a :href="f.url || '#'" x-text="f.name"></a> <span class="small muted" x-text="(f.size ? f.size + ' · ' : '') + $store.ik.userName(f.by) + ', ' + F.time(f.at)"></span></span>
          <button class="btn sm quiet" type="button" style="color:var(--red)" x-show="canRemove(f)" @click="$store.dlg.open('deleteFile', { oid: o.id, fid: f.id }, $event)" :aria-label="'Удалить вложение ' + f.name">Удалить</button></li>
      </template>
      <li x-show="!o.files.length" class="muted">Чеков и ссылок пока нет.</li>
    </ul>
    <button class="btn sm" type="button" style="margin-top:12px" @click="$store.dlg.open('attach', { oid: o.id }, $event)">Прикрепить чек или ссылку</button>

    <div class="cols-2" style="margin-top:8px">
      <section>
        <h3 class="section-title" style="font-size:19px;margin-top:28px">Напоминания</h3>
        <ul class="list-ruled">
          <template x-for="r in reminders" :key="r.id">
            <li><span><b x-text="F.channel(r.channel)"></b><span class="name-sub" x-text="r.kind === 'overdue' ? 'о просрочке' : 'за ' + $store.ik.remindDays + ' дня до срока'"></span></span>
              <span class="small" :class="r.status === 'failed' ? 'red' : 'muted'" style="text-align:right" x-text="F.time(r.at) + ' · ' + (r.status === 'sent' ? 'доставлено' : 'не доставлено: ' + r.error)"></span></li>
          </template>
          <li x-show="!reminders.length" class="muted" x-text="$store.ik.daysLeft(o) > $store.ik.remindDays ? 'Напомним за 3 дня до срока, ' + F.date(window.IKD.addDays(o.due, -3)) + '.' : 'Напоминаний не было.'"></li>
        </ul>
      </section>
      <section>
        <h3 class="section-title" style="font-size:19px;margin-top:28px">История</h3>
        <ul class="list-ruled">
          <template x-for="(a, i) in history" :key="i">
            <li style="display:block"><span x-text="F.action(a.action)" style="font-weight:700"></span> <span class="small muted" x-text="F.time(a.at) + ' · ' + $store.ik.userName(a.actor)"></span>
              <span class="name-sub" x-text="a.text"></span></li>
          </template>
          <li x-show="!history.length" class="muted">Изменений не было.</li>
        </ul>
      </section>
    </div>

    <h3 class="section-title" style="font-size:19px">Все периоды платежа</h3>
    <ul class="list-ruled">
      <template x-for="s in siblings.slice(0, 6)" :key="s.id">
        <li :style="s.id === o.id ? 'font-weight:700' : ''"><a class="mono" :href="'period.html?id=' + s.id" x-text="F.date(s.due)" :aria-current="s.id === o.id ? 'true' : null"></a>
          <span class="st small" :class="$store.ik.state(s)" x-text="$store.ik.stateLabel(s) + (s.paid ? ' ' + F.short(s.paid) : '')"></span></li>
      </template>
    </ul>
  </div>`;
  window.IK_PERIOD_DETAIL = periodDetail;

  const tail = document.createElement('div');
  tail.innerHTML = window.IK_TOASTS + dialogs.replace('%%PERIOD%%', periodDetail);
  while (tail.firstElementChild) document.body.appendChild(tail.firstElementChild);
  const asPage = periodDetail.replace('<h2 id="pd-title" class="serif" style="font-size:28px;line-height:1.2" x-text="p.name"></h2>',
    '<h1 id="pd-title" class="serif" style="font-size:40px;line-height:1.1;letter-spacing:-0.015em" x-text="p.name"></h1>');
  document.querySelectorAll('[data-period-detail]').forEach((el) => { el.innerHTML = asPage; });
})();
