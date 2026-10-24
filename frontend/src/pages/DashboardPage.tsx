import { useEffect, useMemo, useState } from 'react';
import { Button } from '@mantine/core';
import { useOccurrences, useSummary } from '../api/hooks';
import type { Currency, Occurrence } from '../api/types';
import { useAuth } from '../auth/context';
import { MarkCell } from '../components/Marks';
import { MonthTotals } from '../components/MonthTotals';
import { useDialogs } from '../components/dialogs/context';
import { monthOf, monthRange, shiftMonth } from '../lib/dates';
import { amountShort, CURRENCIES, longDate, monthName, monthTitle, plural, shortDate } from '../lib/format';

function sums(list: Occurrence[]) {
  return CURRENCIES.map((c: Currency) => [c, list.filter((o) => o.currency === c).reduce((s, o) => s + Number(o.amount), 0)] as const)
    .filter(([, v]) => v > 0)
    .map(([c, v]) => amountShort(v, c))
    .join(', ');
}

function Row({ o }: { o: Occurrence }) {
  const { openPeriod } = useDialogs();
  return (
    <tr className={o.state} data-oid={o.id}>
      <td className="date" data-k="date">{shortDate(o.due_date)}</td>
      <td data-k="name">
        <button type="button" className="link name" onClick={() => openPeriod(o.id)}>{o.recurring_payment.name}</button>
        {o.recurring_payment.is_deleted && <span className="name-sub">платёж прекращён</span>}
      </td>
      <td className="sum ruled" data-k="sum">{amountShort(o.amount, o.currency)}</td>
      <td className="mark" data-k="mark"><MarkCell occ={o} /></td>
    </tr>
  );
}

export function DashboardPage() {
  const { today, isAdmin } = useAuth();
  const { open } = useDialogs();
  const [ym, setYm] = useState(monthOf(today));
  const [from, to] = monthRange(ym);
  const list = useOccurrences({ date_from: from, date_to: to, sort: 'due_date', limit: 500 });
  const summary = useSummary({ date_from: from, date_to: to });
  const isNow = ym === monthOf(today);

  useEffect(() => {
    document.title = `${monthTitle(ym)} — Сводка — Invoice Keeper`;
  }, [ym]);

  const rows = useMemo(() => list.data?.items ?? [], [list.data]);
  const past = rows.filter((o) => o.due_date < today);
  const future = rows.filter((o) => o.due_date >= today);
  const empty = list.isSuccess && rows.length === 0;
  const allDone = isNow && rows.length > 0 && rows.every((o) => o.paid_date);

  const lead = (() => {
    const od = rows.filter((o) => o.state === 'overdue');
    const paid = rows.filter((o) => o.paid_date).length;
    if (ym < monthOf(today)) {
      return <>Оплачено {paid} из {rows.length}.{od.length ? <span className="red"> Не оплачено {od.length} — строки на красной подложке.</span> : ' Месяц закрыт.'}</>;
    }
    if (ym > monthOf(today)) return <>Запланировано {rows.length} {plural(rows.length, 'платёж', 'платежа', 'платежей')}: {sums(rows) || 'нет сумм'}.</>;
    const left = rows.filter((o) => !o.paid_date && o.due_date >= today).length;
    return (
      <>
        {od.length ? <span className="red">{plural(od.length, 'Просрочен', 'Просрочено', 'Просрочено')} {od.length} {plural(od.length, 'платёж', 'платежа', 'платежей')} на {sums(od)}. </span> : 'Просроченных платежей нет. '}
        {left ? `До конца месяца оплатить ещё ${left}.` : 'Остальное в этом месяце оплачено.'}
      </>
    );
  })();

  const next = rows.concat().filter((o) => !o.paid_date && o.due_date > today)[0];

  return (
    <section aria-labelledby="month-t">
      <div className="page-head">
        <h1 id="month-t">{monthTitle(ym)}</h1>
        <div className="actions month-nav">
          <Button variant="subtle" size="xs" onClick={() => setYm(shiftMonth(ym, -1))}>‹ {monthName(shiftMonth(ym, -1))}</Button>
          {!isNow && <Button variant="subtle" size="xs" onClick={() => setYm(monthOf(today))}>Текущий месяц</Button>}
          <Button variant="subtle" size="xs" onClick={() => setYm(shiftMonth(ym, 1))}>{monthName(shiftMonth(ym, 1))} ›</Button>
        </div>
      </div>

      {empty ? (
        <div className="empty">
          <span className="stamp big" aria-hidden="true">Пусто</span>
          <h2>{isNow ? 'Книга пока пуста' : 'В этом месяце платежей нет'}</h2>
          <p>Здесь появятся сроки регулярных платежей — аренды, подписок, серверов — и отметки об оплате.</p>
          {isAdmin ? <Button variant="outline" onClick={() => open({ type: 'newPayment' })}>Добавить платёж</Button> : <p>Платежи добавляет администратор. Когда они появятся, напоминания придут в Telegram.</p>}
        </div>
      ) : (
        <>
          <p className="lead">{list.isPending ? <span className="sk" style={{ width: '60%', height: 18 }} /> : lead}</p>
          <MonthTotals totals={summary.data?.totals} loading={summary.isPending} />

          <table className="ledger stack attn" aria-describedby="month-t">
            <thead>
              <tr><th scope="col">Срок</th><th scope="col">Платёж</th><th scope="col" className="r ruled" style={{ paddingRight: 24 }}>Сумма</th><th scope="col" className="mark">Отметка</th></tr>
            </thead>
            {list.isPending ? (
              <tbody>
                {Array.from({ length: 8 }, (_, i) => (
                  <tr key={i}><td><span className="sk" style={{ width: 44 }} /></td><td><span className="sk" style={{ width: '60%' }} /></td><td className="sum ruled"><span className="sk" style={{ width: 90, marginLeft: 'auto' }} /></td><td className="mark"><span className="sk" style={{ width: 120 }} /></td></tr>
                ))}
              </tbody>
            ) : (
              <>
                <tbody className="enter">{past.map((o) => <Row key={o.id} o={o} />)}</tbody>
                {isNow && (
                  <tbody>
                    <tr className="today-row"><td colSpan={4}><div className="today-line"><span>сегодня, {longDate(today)}</span></div></td></tr>
                  </tbody>
                )}
                <tbody className="enter">{future.map((o) => <Row key={o.id} o={o} />)}</tbody>
              </>
            )}
          </table>
          {allDone && (
            <div className="done">
              <span className="stamp big">Всё оплачено</span>
              <p>{next ? `Следующий срок — ${shortDate(next.due_date)}: «${next.recurring_payment.name}».` : 'Новых сроков в этом месяце нет.'}</p>
            </div>
          )}
        </>
      )}
    </section>
  );
}
