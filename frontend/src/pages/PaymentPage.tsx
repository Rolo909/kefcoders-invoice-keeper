import { useEffect } from 'react';
import { Button } from '@mantine/core';
import { Link, useParams } from 'react-router-dom';
import { usePayment } from '../api/hooks';
import { useAuth } from '../auth/context';
import { useTeamScope } from '../auth/team';
import { MarkCell } from '../components/Marks';
import { useDialogs } from '../components/dialogs/context';
import { amountShort, date, dateTime, PERIOD_LABEL, plural } from '../lib/format';

export function PaymentPage() {
  const { id = '' } = useParams();
  const { isAdmin } = useAuth();
  const { showTeams, current } = useTeamScope();
  const { open, openPeriod } = useDialogs();
  const q = usePayment(id);

  useEffect(() => {
    if (q.data) document.title = `${q.data.name} — Invoice Keeper`;
  }, [q.data]);

  if (q.isPending) return <div aria-busy="true"><span className="sk" style={{ width: '40%', height: 36 }} /></div>;
  if (q.isError || !q.data) return <div className="empty"><h2>Платёж не найден</h2><Link to="/recurring-payments">Все регулярные платежи</Link></div>;

  const p = q.data;
  const paid = p.occurrences.filter((o) => o.paid_date);
  const paidSum = paid.reduce((s, o) => s + Number(o.amount), 0);
  const overdue = p.occurrences.filter((o) => o.state === 'overdue').length;
  const day31 = p.period === 'monthly' && Number(p.first_due_date.slice(8)) > 28;
  // Общий платёж у всех команд сразу: у каждой команды свои строки периодов.
  const byTeam = !p.team && showTeams;

  return (
    <>
      <p className="crumbs"><Link to="/recurring-payments">Регулярные платежи</Link> ›</p>
      <div className="page-head">
        <h1>{p.name}</h1>
        {isAdmin && !p.deleted_at && <div className="actions"><Button variant="outline" color="red" onClick={() => open({ type: 'stopPayment', payment: p })}>Прекратить платёж</Button></div>}
      </div>
      <p className="lead">
        Оплачено {paid.length} из {p.occurrences.length} {plural(p.occurrences.length, 'периода', 'периодов', 'периодов')} на {amountShort(paidSum, p.currency)}.
        {overdue > 0 && <span className="red"> Просрочено: {overdue}.</span>}
      </p>
      <div className="split" style={{ gridTemplateColumns: 'minmax(0, 340px) minmax(0, 1fr)' }}>
        <section className="params" aria-label="Параметры">
          <dl className="kv">
            <dt>Для кого</dt>
            <dd>
              {p.team ? p.team.name : 'Все команды'}
              <span className="name-sub">{p.team ? 'Платёж видит и оплачивает только эта команда' : `Общий платёж: каждая команда оплачивает свой период${current ? `. Здесь — периоды команды «${current.name}»` : ''}`}</span>
            </dd>
            <dt>Сумма</dt><dd>{amountShort(p.amount, p.currency)}</dd>
            <dt>Периодичность</dt><dd>{PERIOD_LABEL[p.period]}</dd>
            <dt>Первый срок</dt><dd><span className="mono">{date(p.first_due_date)}</span><span className="name-sub">{day31 ? `Все сроки — ${Number(p.first_due_date.slice(8))}-го, в коротких месяцах — последний день` : 'От этой даты считаются все сроки'}</span></dd>
            <dt>Окончание</dt><dd>{p.end_date ? date(p.end_date) : 'Не задано'}</dd>
            <dt>Описание</dt><dd style={{ fontWeight: 400 }}>{p.description || "—"}</dd>
            <dt>Создан</dt><dd style={{ fontWeight: 400 }}>{dateTime(p.created_at)}, {p.created_by.full_name ?? p.created_by.login}</dd>
            <dt>Состояние</dt><dd className={p.deleted_at ? 'muted' : undefined}>{p.deleted_at ? `Прекращён ${date(p.deleted_at.slice(0, 10))}. Новых периодов и напоминаний нет` : 'Действует. Напоминание — за 3 дня до срока'}</dd>
          </dl>
          <p className="small muted" style={{ marginTop: 16 }}>Сумму и срок не меняют задним числом: чтобы изменить их, прекратите платёж и создайте новый. Прошлые периоды останутся как были.</p>
        </section>
        <section aria-labelledby="hist-t">
          <h2 id="hist-t" className="section-title" style={{ marginTop: 0 }}>Все периоды</h2>
          <table className="ledger stack attn">
            <thead><tr><th scope="col">Срок</th>{byTeam && <th scope="col">Команда</th>}<th scope="col" className="r ruled" style={{ paddingRight: 24 }}>Сумма</th><th scope="col" className="mark">Отметка</th><th scope="col">Вложения</th></tr></thead>
            <tbody>
              {p.occurrences.map((o) => (
                <tr key={o.id} className={o.state}>
                  <td className="date" data-k="date"><button type="button" className="link mono" onClick={() => openPeriod(o.id)} aria-label={`Период ${date(o.due_date)}${byTeam ? `, команда ${o.team.name}` : ''}`}>{date(o.due_date)}</button></td>
                  {byTeam && <td data-k="name">{o.team.name}</td>}
                  <td className="sum ruled" data-k="sum">{amountShort(o.amount, o.currency)}</td>
                  <td className="mark" data-k="mark"><MarkCell occ={o} /></td>
                  <td data-k="hide-sm" className="muted">{o.attachments_count ? `${o.attachments_count} ${plural(o.attachments_count, 'файл', 'файла', 'файлов')}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </>
  );
}
