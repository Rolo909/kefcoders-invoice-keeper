import { useEffect, useMemo, useState } from 'react';
import { ActionIcon, Button, Menu, NativeSelect, TextInput } from '@mantine/core';
import { useOccurrences, usePayments } from '../api/hooks';
import type { Currency, Occurrence, OccurrenceQuery } from '../api/types';
import { MarkButton, PaidMark } from '../components/Marks';
import { ClipIcon } from '../components/icons';
import { useDialogs } from '../components/dialogs/context';
import { useAuth } from '../auth/context';
import { monthOf, monthRange, shiftMonth } from '../lib/dates';
import { amountWithSign, CURRENCIES, date, days, PERIOD_LABEL, plural, relative } from '../lib/format';

type Filters = { status: '' | 'paid' | 'unpaid'; cur: Currency[]; overdue: boolean; from: string; to: string; pid: string };
const PER = 20;

function MarkText({ o }: { o: Occurrence }) {
  const { today } = useAuth();
  if (o.paid_date) return <PaidMark occ={o} />;
  if (o.state === 'overdue') return <span className="note-red">{relative(o, today)}</span>;
  if (o.state === 'due_soon') return <span className="amber" style={{ fontWeight: 700 }}>{relative(o, today)}</span>;
  return <span className="muted">{relative(o, today)}</span>;
}

function SortHeader({ label, k, sort, setSort, className }: { label: string; k: 'due_date' | 'amount' | 'days_overdue'; sort: string; setSort: (s: OccurrenceQuery['sort']) => void; className?: string }) {
  const active = sort.replace('-', '') === k;
  const asc = !sort.startsWith('-');
  return (
    <th scope="col" className={className} aria-sort={active ? (asc ? 'ascending' : 'descending') : undefined}>
      <button type="button" className="sort" onClick={() => setSort((active ? (asc ? `-${k}` : k) : k === 'due_date' ? k : `-${k}`) as OccurrenceQuery['sort'])}>
        {label} <span aria-hidden="true" className={active ? undefined : 'hint'}>{active ? (asc ? '↑' : '↓') : '↕'}</span>
      </button>
    </th>
  );
}

export function OccurrencesPage() {
  const { today } = useAuth();
  const { open, openPeriod } = useDialogs();
  const base = useMemo<Filters>(() => ({ status: '', cur: [], overdue: false, from: monthRange(shiftMonth(monthOf(today), -1))[0], to: monthRange(shiftMonth(monthOf(today), 1))[1], pid: '' }), [today]);
  const [f, setF] = useState<Filters>(base);
  const [sort, setSort] = useState<OccurrenceQuery['sort']>('due_date');
  const [pageNo, setPageNo] = useState(0);
  const [showFilters, setShowFilters] = useState(false);
  const payments = usePayments({ include_deleted: true });

  useEffect(() => {
    document.title = 'Периоды — Invoice Keeper';
  }, []);

  const query: OccurrenceQuery = {
    status: f.status || undefined, overdue: f.overdue || undefined, currency: f.cur.length ? f.cur : undefined,
    date_from: f.from || undefined, date_to: f.to || undefined, recurring_payment_id: f.pid || undefined,
    sort, limit: PER, offset: pageNo * PER,
  };
  const list = useOccurrences(query);
  const set = (patch: Partial<Filters>) => { setF((x) => ({ ...x, ...patch })); setPageNo(0); };
  const dirty = JSON.stringify(f) !== JSON.stringify(base);
  const total = list.data?.total ?? 0;
  const pages = Math.max(1, Math.ceil(total / PER));
  const items = list.data?.items ?? [];

  return (
    <>
      <div className="page-head">
        <h1>Периоды</h1>
        <p className="muted" role="status">{list.isPending ? 'Загружаем…' : `${plural(total, 'Найден', 'Найдено', 'Найдено')} ${total} ${plural(total, 'период', 'периода', 'периодов')}`}</p>
      </div>

      <Button className="filters-toggle" size="xs" variant="outline" aria-expanded={showFilters} aria-controls="flt" onClick={() => setShowFilters((s) => !s)}>
        Фильтры{dirty ? ' · изменены' : ''}
      </Button>
      <form id="flt" className={`filters${showFilters ? ' open' : ''}`} onSubmit={(e) => e.preventDefault()} aria-label="Фильтры">
        <div className="grp"><span id="f-st">Статус</span>
          <div className="seg" role="group" aria-labelledby="f-st">
            {([['', 'Все'], ['unpaid', 'Не оплачено'], ['paid', 'Оплачено']] as const).map(([v, l]) => (
              <button key={v} type="button" aria-pressed={f.status === v} onClick={() => set({ status: v })}>{l}</button>
            ))}
          </div>
        </div>
        <div className="grp"><span id="f-cur">Валюта</span>
          <div role="group" aria-labelledby="f-cur" style={{ display: 'flex', gap: 6 }}>
            {CURRENCIES.map((c) => (
              <button key={c} type="button" className="chip" aria-pressed={f.cur.includes(c)} onClick={() => set({ cur: f.cur.includes(c) ? f.cur.filter((x) => x !== c) : [...f.cur, c] })}>{c}</button>
            ))}
          </div>
        </div>
        <div className="grp"><span id="f-od">Просрочка</span>
          <div role="group" aria-labelledby="f-od"><button type="button" className="chip" aria-pressed={f.overdue} onClick={() => set({ overdue: !f.overdue })}>Только с просрочкой</button></div>
        </div>
        <TextInput type="date" label="Срок с" value={f.from} onChange={(e) => set({ from: e.currentTarget.value })} w={140} classNames={{ input: 'mono' }} />
        <TextInput type="date" label="по" value={f.to} onChange={(e) => set({ to: e.currentTarget.value })} w={140} classNames={{ input: 'mono' }} />
        <NativeSelect label="Платёж" w={210} value={f.pid} onChange={(e) => set({ pid: e.currentTarget.value })}
          data={[{ value: '', label: 'Все платежи' }, ...(payments.data?.items ?? []).map((p) => ({ value: p.id, label: p.name + (p.deleted_at ? ' (прекращён)' : '') }))]} />
        {dirty && <Button size="xs" variant="subtle" style={{ marginLeft: 'auto', alignSelf: 'end' }} onClick={() => { setF(base); setPageNo(0); }}>Сбросить фильтры</Button>}
      </form>

      {list.isSuccess && !items.length ? (
        <div className="empty">
          <h2>Нет периодов по этим фильтрам</h2>
          <p>Срок {date(f.from)}–{date(f.to)}{f.overdue ? ', только с просрочкой' : ''}{f.cur.length ? `, ${f.cur.join(', ')}` : ''}.</p>
          <Button variant="outline" onClick={() => { setF(base); setPageNo(0); }}>Сбросить фильтры</Button>
        </div>
      ) : (
        <>
          <table className="ledger stack attn">
            <caption className="sr-only">Периоды регулярных платежей</caption>
            <thead>
              <tr>
                <SortHeader label="Срок" k="due_date" sort={sort!} setSort={setSort} />
                <th scope="col">Платёж</th>
                <SortHeader label="Сумма" k="amount" sort={sort!} setSort={setSort} className="r" />
                <th scope="col">Отметка</th>
                <SortHeader label="Просрочка" k="days_overdue" sort={sort!} setSort={setSort} />
                <th scope="col"><span className="sr-only">Вложения</span></th>
                <th scope="col"><span className="sr-only">Действия</span></th>
              </tr>
            </thead>
            <tbody>
              {items.map((o) => (
                <tr key={o.id} className={o.state}>
                  <td className="date" data-k="date">{date(o.due_date)}</td>
                  <td data-k="name">
                    <button type="button" className="link name" onClick={() => openPeriod(o.id)}>{o.recurring_payment.name}</button>
                    <span className="name-sub">{PERIOD_LABEL[o.recurring_payment.period]}{o.recurring_payment.is_deleted ? ' · прекращён' : ''}</span>
                  </td>
                  <td className="sum" data-k="sum">{amountWithSign(o.amount, o.currency)}</td>
                  <td data-k="mark" style={{ width: 330 }}><MarkText o={o} /></td>
                  <td data-k="hide-sm" className={o.days_overdue ? 'red' : undefined} style={{ whiteSpace: 'nowrap' }}>{o.days_overdue ? days(o.days_overdue) : '—'}</td>
                  <td data-k="hide-sm">{o.attachments_count > 0 && <span className="muted" aria-label={`Вложений: ${o.attachments_count}`} style={{ display: 'inline-flex', gap: 4 }}><ClipIcon /><span aria-hidden="true">{o.attachments_count}</span></span>}</td>
                  <td className="acts" data-k="more">
                    {!o.paid_date ? (
                      <MarkButton occ={o} />
                    ) : (
                      <Menu>
                        <Menu.Target>
                          <ActionIcon variant="subtle" color="gray" aria-label={`Действия с оплатой: ${o.recurring_payment.name}, срок ${date(o.due_date)}`}>⋯</ActionIcon>
                        </Menu.Target>
                        <Menu.Dropdown>
                          <Menu.Item onClick={() => open({ type: 'changeDate', occ: o })}>Изменить дату оплаты</Menu.Item>
                          <Menu.Item onClick={() => open({ type: 'attach', occ: o })}>Прикрепить чек или ссылку</Menu.Item>
                          <Menu.Item c="var(--red)" onClick={() => open({ type: 'unmark', occ: o })}>Снять отметку</Menu.Item>
                        </Menu.Dropdown>
                      </Menu>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <nav className="pager" aria-label="Страницы">
            <span>{total ? `${pageNo * PER + 1}–${Math.min((pageNo + 1) * PER, total)} из ${total}` : ''}</span>
            <span style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <Button size="xs" variant="subtle" disabled={pageNo === 0} onClick={() => setPageNo((p) => p - 1)}>‹ Раньше</Button>
              <span>Страница {pageNo + 1} из {pages}</span>
              <Button size="xs" variant="subtle" disabled={pageNo >= pages - 1} onClick={() => setPageNo((p) => p + 1)}>Позже ›</Button>
            </span>
          </nav>
        </>
      )}
    </>
  );
}
