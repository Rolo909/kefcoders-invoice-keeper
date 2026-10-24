import { useEffect, useState, type KeyboardEvent } from 'react';
import { Button, NativeSelect, TextInput } from '@mantine/core';
import { Link } from 'react-router-dom';
import { useAuditLogs, useNotificationLog, useTestNotification, useUsers } from '../api/hooks';
import { useAuth } from '../auth/context';
import { RequireAdmin } from '../auth/guards';
import { toast } from '../components/dialogs/actions';
import { ACTION_LABEL, describeAudit } from '../lib/audit';
import { date, dateTime } from '../lib/format';

const PER = 25;
const CHANNEL: Record<string, string> = { telegram: 'Telegram', email: 'Почта', webhook: 'Webhook', inapp: 'В панели' };

function Pager({ total, page, setPage }: { total: number; page: number; setPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / PER));
  return (
    <nav className="pager" aria-label="Страницы">
      <span>{total ? `${page * PER + 1}–${Math.min((page + 1) * PER, total)} из ${total}` : ''}</span>
      <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Button size="xs" variant="subtle" disabled={page === 0} onClick={() => setPage(page - 1)}>‹ Новее</Button>
        <span>Страница {page + 1} из {pages}</span>
        <Button size="xs" variant="subtle" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Старше ›</Button>
      </span>
    </nav>
  );
}

function Actions() {
  const users = useUsers();
  const [f, setF] = useState({ action: '', actor_id: '', date_from: '', date_to: '' });
  const [page, setPage] = useState(0);
  const logs = useAuditLogs({ ...f, limit: PER, offset: page * PER });
  const set = (patch: Partial<typeof f>) => { setF((x) => ({ ...x, ...patch })); setPage(0); };
  return (
    <>
      <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Фильтры журнала">
        <NativeSelect label="Действие" w={240} value={f.action} onChange={(e) => set({ action: e.currentTarget.value })} data={[
          { value: '', label: 'Все действия' }, { value: 'auth', label: 'Входы и выходы' }, { value: 'auth.login_failed', label: 'Только неудачные входы' },
          { value: 'occurrence', label: 'Отметки и даты оплаты' }, { value: 'telegram.mark_paid', label: 'Оплаты из Telegram' }, { value: 'attachment', label: 'Вложения' },
          { value: 'payment', label: 'Платежи' }, { value: 'user', label: 'Пользователи' }, { value: 'budget', label: 'Бюджеты' },
        ]} />
        <NativeSelect label="Кто" w={220} value={f.actor_id} onChange={(e) => set({ actor_id: e.currentTarget.value })}
          data={[{ value: '', label: 'Все' }, ...(users.data?.items ?? []).map((u) => ({ value: u.id, label: u.full_name ? `${u.login} — ${u.full_name}` : u.login }))]} />
        <TextInput type="date" label="С" w={150} value={f.date_from} onChange={(e) => set({ date_from: e.currentTarget.value })} classNames={{ input: 'mono' }} />
        <TextInput type="date" label="по" w={150} value={f.date_to} onChange={(e) => set({ date_to: e.currentTarget.value })} classNames={{ input: 'mono' }} />
      </form>
      {logs.isSuccess && !logs.data.items.length ? (
        <div className="empty"><h2>Записей нет</h2><p>По этим фильтрам событий не нашлось.</p><Button variant="outline" onClick={() => set({ action: '', actor_id: '', date_from: '', date_to: '' })}>Сбросить фильтры</Button></div>
      ) : (
        <>
          <table className="ledger stack">
            <caption className="sr-only">Действия и входы</caption>
            <thead><tr><th scope="col">Время</th><th scope="col">Кто</th><th scope="col">Действие</th><th scope="col">Подробности</th><th scope="col">IP</th></tr></thead>
            <tbody>
              {(logs.data?.items ?? []).map((a) => (
                <tr key={a.id}>
                  <td className="date" data-k="date" style={{ width: 120 }}>{dateTime(a.at)}</td>
                  <td className="mono" data-k="name">{a.actor_login}</td>
                  <td data-k="sum" className={a.action === 'auth.login_failed' ? 'red' : undefined} style={a.action === 'auth.login_failed' ? { fontWeight: 700 } : undefined}>{ACTION_LABEL[a.action] ?? a.action}</td>
                  <td data-k="mark">{describeAudit(a)}{a.entity_type === 'occurrence' && a.entity_id && <> <Link className="small" to={`/occurrences/${a.entity_id}`}>период</Link></>}</td>
                  <td className="mono muted" data-k="hide-sm">{a.ip ?? 'Telegram'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Pager total={logs.data?.total ?? 0} page={page} setPage={setPage} />
        </>
      )}
    </>
  );
}

function Notifications() {
  const [f, setF] = useState({ channel: '', status: '' });
  const [page, setPage] = useState(0);
  const log = useNotificationLog({ ...f, limit: PER, offset: page * PER });
  return (
    <>
      <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Фильтры уведомлений">
        <NativeSelect label="Канал" w={180} value={f.channel} onChange={(e) => { setF({ ...f, channel: e.currentTarget.value }); setPage(0); }}
          data={[{ value: '', label: 'Все каналы' }, { value: 'telegram', label: 'Telegram' }, { value: 'email', label: 'Почта' }, { value: 'webhook', label: 'Webhook' }, { value: 'inapp', label: 'В панели' }]} />
        <NativeSelect label="Статус" w={180} value={f.status} onChange={(e) => { setF({ ...f, status: e.currentTarget.value }); setPage(0); }}
          data={[{ value: '', label: 'Все' }, { value: 'sent', label: 'Доставлено' }, { value: 'failed', label: 'Не доставлено' }, { value: 'pending', label: 'Отправляется' }]} />
        <p className="small muted" style={{ alignSelf: 'center', maxWidth: 420 }}>Каждое напоминание уходит один раз на период и канал. Неудачные отправки повторяются до 5 раз.</p>
      </form>
      <table className="ledger stack">
        <caption className="sr-only">Уведомления</caption>
        <thead><tr><th scope="col">Время</th><th scope="col">Канал</th><th scope="col">Платёж и период</th><th scope="col">Тип</th><th scope="col">Статус</th><th scope="col" className="r">Попыток</th></tr></thead>
        <tbody>
          {(log.data?.items ?? []).map((n) => (
            <tr key={n.id}>
              <td className="date" data-k="date" style={{ width: 120 }}>{dateTime(n.created_at)}</td>
              <td data-k="sum">{CHANNEL[n.channel]}</td>
              <td data-k="name"><Link to={`/occurrences/${n.occurrence_id}`}>{n.payment_name}</Link><span className="name-sub mono">{date(n.due_date)}{n.team ? ` · ${n.team.name}` : ''}</span></td>
              <td data-k="hide-sm">{n.kind === 'overdue' ? 'О просрочке' : 'За 3 дня'}</td>
              <td data-k="mark">
                <span className={`st ${n.status === 'sent' ? 'paid' : n.status === 'failed' ? 'overdue' : 'upcoming'}`}>{n.status === 'sent' ? 'Доставлено' : n.status === 'failed' ? 'Не доставлено' : 'Отправляется'}</span>
                {n.last_error && <span className={`name-sub${n.status === 'failed' ? ' red' : ''}`}>{n.last_error}</span>}
              </td>
              <td className="sum" data-k="hide-sm">{n.attempts}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <Pager total={log.data?.total ?? 0} page={page} setPage={setPage} />
    </>
  );
}

function Journal() {
  const [tab, setTab] = useState<'audit' | 'notify'>('audit');
  const test = useTestNotification();
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
      e.preventDefault();
      const next = tab === 'audit' ? 'notify' : 'audit';
      setTab(next);
      requestAnimationFrame(() => document.getElementById(`t-${next}`)?.focus());
    }
  };
  return (
    <>
      <div className="page-head">
        <h1>Журнал</h1>
        {tab === 'notify' && (
          <div className="actions">
            <Button variant="outline" loading={test.isPending} onClick={async () => {
              const r = await test.mutateAsync();
              const ok = r.channels.filter((c) => c.ok).map((c) => CHANNEL[c.channel]);
              const bad = r.channels.filter((c) => !c.ok).map((c) => `${CHANNEL[c.channel]} — ${c.error}`);
              toast(`Тестовое сообщение: доставлено — ${ok.join(', ') || 'никуда'}.${bad.length ? ` Не доставлено: ${bad.join('; ')}.` : ''}`);
            }}>Отправить тестовое уведомление</Button>
          </div>
        )}
      </div>
      <div className="journal-tabs" role="tablist" aria-label="Журнал" onKeyDown={onKey}>
        <button type="button" role="tab" id="t-audit" aria-controls="p-audit" aria-selected={tab === 'audit'} tabIndex={tab === 'audit' ? 0 : -1} onClick={() => setTab('audit')}>Действия и входы</button>
        <button type="button" role="tab" id="t-notify" aria-controls="p-notify" aria-selected={tab === 'notify'} tabIndex={tab === 'notify' ? 0 : -1} onClick={() => setTab('notify')}>Уведомления</button>
      </div>
      <section id={`p-${tab}`} role="tabpanel" aria-labelledby={`t-${tab}`}>{tab === 'audit' ? <Actions /> : <Notifications />}</section>
    </>
  );
}

export function AuditPage() {
  const { isAdmin } = useAuth();
  useEffect(() => {
    document.title = isAdmin ? 'Журнал — Invoice Keeper' : 'Нет доступа — Invoice Keeper';
  }, [isAdmin]);
  return <RequireAdmin back="/occurrences"><Journal /></RequireAdmin>;
}
