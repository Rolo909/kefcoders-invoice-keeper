import { useEffect, useState } from 'react';
import { ActionIcon, Button, Checkbox, Menu, TextInput } from '@mantine/core';
import { Link } from 'react-router-dom';
import { usePayments, useSummary } from '../api/hooks';
import { useAuth } from '../auth/context';
import { StatusText } from '../components/Marks';
import { useDialogs } from '../components/dialogs/context';
import { amountShort, date, PERIOD_LABEL, PERIOD_SHORT, plural, shortDate } from '../lib/format';
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
  const planned = (month.data?.totals ?? []).filter((t) => Number(t.planned) > 0).map((t) => amountShort(t.planned, t.currency)).join(', ');

  return (
    <>
      <div className="page-head"><h1>Регулярные платежи</h1></div>
      <p className="lead">
        {all.isPending ? <span className="sk" style={{ width: '50%', height: 18 }} /> : (
          <>Действует {active.length} {plural(active.length, 'платёж', 'платежа', 'платежей')}.{planned && <> В этом месяце по плану {planned}.</>}</>
        )}
      </p>
      <div className="filters open">
        <TextInput type="search" label="Поиск по названию" value={q} onChange={(e) => setQ(e.currentTarget.value)} w={260} />
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
                <th scope="col">Платёж</th><th scope="col" className="r">Сумма</th>
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
                  <td className="sum" data-k="sum">{amountShort(p.amount, p.currency)}<span className="per" title={PERIOD_LABEL[p.period]}>{PERIOD_SHORT[p.period]}</span></td>
                  <td className="date" data-k="date">{p.next_occurrence ? (p.next_occurrence.due_date.startsWith(today.slice(0, 4)) ? shortDate(p.next_occurrence.due_date) : date(p.next_occurrence.due_date)) : '—'}</td>
                  <td data-k="mark">
                    {p.deleted_at ? <span className="st stopped">прекращён {date(p.deleted_at.slice(0, 10))}</span> : p.next_occurrence ? <StatusText occ={p.next_occurrence} /> : <span className="muted">новых сроков нет</span>}
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
