import { useEffect, useState } from 'react';
import { ActionIcon, Button, Checkbox, Menu, TextInput } from '@mantine/core';
import { Link } from 'react-router-dom';
import { usePayments, useSummary } from '../api/hooks';
import { useAuth } from '../auth/context';
import { StatusText } from '../components/Marks';
import { useDialogs } from '../components/dialogs/context';
import { amountWithSign, date, money, PERIOD_LABEL, plural } from '../lib/format';
import { monthOf, monthRange } from '../lib/dates';

export function PaymentsPage() {
  const { isAdmin, today } = useAuth();
  const { open } = useDialogs();
  const [q, setQ] = useState('');
  const [showStopped, setShowStopped] = useState(false);
  const all = usePayments({ include_deleted: true });
  const [from, to] = monthRange(monthOf(today));
  const month = useSummary({ date_from: from, date_to: to });

  useEffect(() => {
    document.title = 'Регулярные платежи — Invoice Keeper';
  }, []);

  const items = (all.data?.items ?? []).filter((p) => (showStopped || !p.deleted_at) && (!q.trim() || p.name.toLowerCase().includes(q.trim().toLowerCase())));
  const active = (all.data?.items ?? []).filter((p) => !p.deleted_at);
  const stopped = (all.data?.items ?? []).length - active.length;
  const planned = (month.data?.totals ?? []).filter((t) => Number(t.planned) > 0).map((t) => money(t.planned, t.currency)).join(' · ');

  return (
    <>
      <div className="page-head"><h1>Регулярные платежи</h1></div>
      <p className="lead">
        {all.isPending ? <span className="sk" style={{ width: '50%', height: 18 }} /> : (
          <>Действует {active.length} {plural(active.length, 'платёж', 'платежа', 'платежей')}.{planned && <> В этом месяце по плану: <span className="mono">{planned}</span>.</>}</>
        )}
      </p>
      <div className="filters">
        <TextInput type="search" label="Поиск по названию" placeholder="Сервер" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={260} />
        <Checkbox label={`Показать прекращённые (${stopped})`} checked={showStopped} onChange={(e) => setShowStopped(e.currentTarget.checked)} style={{ alignSelf: 'center' }} />
      </div>

      {all.isSuccess && !items.length ? (
        q ? (
          <div className="empty"><h2>Ничего не нашлось по «{q}»</h2><Button variant="outline" onClick={() => setQ('')}>Очистить поиск</Button></div>
        ) : (
          <div className="empty">
            <h2>Регулярных платежей пока нет</h2>
            <p>Добавьте аренду, подписки и серверы — книга сама заведёт периоды и напомнит о сроках в Telegram за 3 дня.</p>
            {isAdmin ? <Button variant="outline" onClick={() => open({ type: 'newPayment' })}>Добавить первый платёж</Button> : <p>Платежи добавляет администратор.</p>}
          </div>
        )
      ) : (
        <>
          <table className="ledger stack">
            <caption className="sr-only">Регулярные платежи</caption>
            <thead>
              <tr>
                <th scope="col">Платёж</th><th scope="col" className="r">Сумма</th><th scope="col">Периодичность</th>
                <th scope="col">Ближайший срок</th><th scope="col">Состояние</th>{isAdmin && <th scope="col"><span className="sr-only">Действия</span></th>}
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className={p.deleted_at ? 'stopped' : undefined}>
                  <td data-k="name" style={{ maxWidth: 440 }}>
                    <Link className="name" to={`/recurring-payments/${p.id}`}>{p.name}</Link>
                    {p.description && <span className="name-sub">{p.description}</span>}
                  </td>
                  <td className="sum" data-k="sum">{amountWithSign(p.amount, p.currency)}</td>
                  <td data-k="hide-sm">{PERIOD_LABEL[p.period]}</td>
                  <td className="date" data-k="date">{p.next_occurrence ? date(p.next_occurrence.due_date) : '—'}</td>
                  <td data-k="mark">
                    {p.deleted_at ? <span className="st stopped">Прекращён {date(p.deleted_at.slice(0, 10))}</span> : p.next_occurrence ? <StatusText occ={p.next_occurrence} /> : <span className="muted">Новых сроков нет</span>}
                  </td>
                  {isAdmin && (
                    <td className="acts" data-k="more">
                      {!p.deleted_at && (
                        <Menu>
                          <Menu.Target><ActionIcon variant="subtle" color="gray" aria-label={`Действия с платежом ${p.name}`}>⋯</ActionIcon></Menu.Target>
                          <Menu.Dropdown>
                            <Menu.Item component={Link} to={`/recurring-payments/${p.id}`}>Открыть платёж</Menu.Item>
                            <Menu.Item c="var(--red)" onClick={() => open({ type: 'stopPayment', payment: p })}>Прекратить платёж</Menu.Item>
                          </Menu.Dropdown>
                        </Menu>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
          <p className="small muted" style={{ marginTop: 14 }}>Чтобы изменить сумму или срок, прекратите платёж и создайте новый. История оплат сохранится.</p>
        </>
      )}
    </>
  );
}
