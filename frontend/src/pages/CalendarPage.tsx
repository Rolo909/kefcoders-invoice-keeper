import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Button } from '@mantine/core';
import { useCalendar, useSummary } from '../api/hooks';
import type { CalendarDay, Currency } from '../api/types';
import { useAuth } from '../auth/context';
import { MarkButton } from '../components/Marks';
import { useDialogs } from '../components/dialogs/context';
import { addDays, lastDayOfMonth, mondayIndex, monthOf, monthRange, shiftMonth } from '../lib/dates';
import { CURRENCIES, CURRENCY_SIGN, longDate, money, monthName, monthTitle, num, STATE_LABEL, statusLine, weekday } from '../lib/format';

const WEEK = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'];

function daySums(d: CalendarDay | undefined) {
  if (!d) return [];
  return CURRENCIES.map((c: Currency) => ({
    c,
    v: d.occurrences.filter((o) => o.currency === c).reduce((s, o) => s + Number(o.amount), 0) +
      d.planned.filter((p) => p.currency === c).reduce((s, p) => s + Number(p.amount), 0),
  })).filter((x) => x.v > 0);
}

export function CalendarPage() {
  const { today } = useAuth();
  const { openPeriod } = useDialogs();
  const [ym, setYm] = useState(monthOf(today));
  const [sel, setSel] = useState(today);
  const [focusDay, setFocusDay] = useState(today);
  const grid = useRef<HTMLDivElement>(null);
  const cal = useCalendar(ym);
  const [from, to] = monthRange(ym);
  const asOf = useSummary({ date_from: from, date_to: to, as_of: sel });

  useEffect(() => {
    document.title = `${monthTitle(ym)} — Календарь — Invoice Keeper`;
  }, [ym]);

  const byDate = useMemo(() => new Map((cal.data?.days ?? []).map((d) => [d.date, d])), [cal.data]);
  const cells = useMemo(() => {
    const first = `${ym}-01`;
    const start = addDays(first, -mondayIndex(first));
    const total = Math.ceil((mondayIndex(first) + lastDayOfMonth(Number(ym.slice(0, 4)), Number(ym.slice(5, 7)))) / 7) * 7;
    return Array.from({ length: total }, (_, i) => addDays(start, i));
  }, [ym]);

  const go = (n: number) => {
    const next = shiftMonth(ym, n);
    setYm(next);
    setSel(`${next}-01`);
    setFocusDay(`${next}-01`);
  };

  const label = (d: string) => {
    const day = byDate.get(d);
    const count = (day?.occurrences.length ?? 0) + (day?.planned.length ?? 0);
    if (!count) return `${longDate(d)}, платежей нет`;
    const parts = [
      ...(day?.occurrences ?? []).map((o) => `${o.recurring_payment.name}, ${money(o.amount, o.currency)}, ${STATE_LABEL[o.state].toLowerCase()}`),
      ...(day?.planned ?? []).map((p) => `${p.name}, ${money(p.amount, p.currency)}, по плану`),
    ];
    return `${longDate(d)}: ${parts.join('; ')}`;
  };

  const onKey = (e: KeyboardEvent) => {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key];
    if (!step) return;
    e.preventDefault();
    const next = addDays(focusDay, step);
    if (monthOf(next) !== ym) setYm(monthOf(next));
    setFocusDay(next);
    setSel(next);
    requestAnimationFrame(() => grid.current?.querySelector<HTMLButtonElement>(`[data-iso="${next}"]`)?.focus());
  };

  const day = byDate.get(sel);

  return (
    <>
      <div className="page-head">
        <h1>{monthTitle(ym)}</h1>
        <div className="actions month-nav">
          <Button size="xs" variant="subtle" onClick={() => go(-1)}>‹ {monthName(shiftMonth(ym, -1))}</Button>
          {ym !== monthOf(today) && <Button size="xs" variant="subtle" onClick={() => { setYm(monthOf(today)); setSel(today); setFocusDay(today); }}>Сегодня</Button>}
          <Button size="xs" variant="subtle" onClick={() => go(1)}>{monthName(shiftMonth(ym, 1))} ›</Button>
        </div>
      </div>

      <div className="cal-wrap">
        <section aria-label="Календарь оплат">
          <p className="sr-only" id="cal-help">Стрелки переходят между днями.</p>
          <div className="cal" ref={grid} role="group" aria-label={monthTitle(ym)} aria-describedby="cal-help" onKeyDown={onKey}>
            {WEEK.map((w) => <div className="wd" key={w} aria-hidden="true">{w}</div>)}
            {cells.map((d) => {
              const item = byDate.get(d);
              const sums = daySums(item);
              return (
                <button
                  key={d}
                  type="button"
                  data-iso={d}
                  className={`day${monthOf(d) !== ym ? ' out' : ''}${mondayIndex(d) >= 5 ? ' we' : ''}${d === today ? ' today' : ''}`}
                  tabIndex={d === focusDay ? 0 : -1}
                  aria-pressed={d === sel}
                  aria-label={label(d)}
                  onClick={() => { setSel(d); setFocusDay(d); }}
                >
                  <span className="n">{Number(d.slice(8))}</span>
                  <span className="marks" aria-hidden="true">
                    {item?.occurrences.map((o) => <i key={o.id} className={`mk ${o.state}`} />)}
                    {item?.planned.map((p) => <i key={p.recurring_payment_id + p.due_date} className="mk planned" />)}
                  </span>
                  {sums.map((s) => <span className="s" key={s.c} aria-hidden="true">{num(s.v).replace(',00', '')} {CURRENCY_SIGN[s.c]}</span>)}
                </button>
              );
            })}
          </div>
          <p className="legend" aria-hidden="true">
            <span><i className="mk paid" />оплачено</span>
            <span><i className="mk paid_late" />с опозданием</span>
            <span><i className="mk overdue" />просрочено</span>
            <span><i className="mk due_soon" />скоро</span>
            <span><i className="mk upcoming" />ожидает</span>
            <span><i className="mk planned" />по плану</span>
          </p>
          <p className="sr-only" aria-live="polite">{label(sel)}</p>
        </section>

        <aside className="day-panel" aria-labelledby="day-t">
          <h2 id="day-t">{longDate(sel)}, {weekday(sel)}</h2>
          {sel === today && <p className="muted small">сегодня</p>}
          <div style={{ marginTop: 8 }}>
            {day?.occurrences.map((o) => (
              <div className="day-item" key={o.id}>
                <div className="top">
                  <button type="button" className="link name" onClick={() => openPeriod(o.id)}>{o.recurring_payment.name}</button>
                  <span className="mono nowrap">{money(o.amount, o.currency)}</span>
                </div>
                <div className="top" style={{ alignItems: 'center' }}>
                  <span className={`st small ${o.state}`}>{statusLine(o, today)}</span>
                  {!o.paid_date && <MarkButton occ={o} />}
                </div>
              </div>
            ))}
            {day?.planned.map((p) => (
              <div className="day-item" key={p.recurring_payment_id}>
                <div className="top"><span className="name">{p.name}</span><span className="mono nowrap">{money(p.amount, p.currency)}</span></div>
                <span className="small muted">По плану — период появится ближе к сроку</span>
              </div>
            ))}
            {!day && <p className="muted" style={{ padding: '12px 0' }}>В этот день платежей нет.</p>}
          </div>

          <div className="asof">
            <h3>Итоги на {longDate(sel)}</h3>
            <p className="small muted" style={{ marginBottom: 8 }}>
              За {monthName(ym).toLowerCase()}, по фактическим датам оплаты.{sel > today ? ' Для будущей даты — если больше ничего не оплатить.' : ''}
            </p>
            <table>
              <thead><tr><th scope="col">Валюта</th><th scope="col">Оплачено</th><th scope="col">К оплате</th><th scope="col">Просрочено</th></tr></thead>
              <tbody>
                {(asOf.data?.totals ?? []).map((t) => (
                  <tr key={t.currency}>
                    <td>{t.currency}</td>
                    <td className="mono">{num(t.paid)}</td>
                    <td className="mono">{num(t.unpaid)}</td>
                    <td className={`mono${Number(t.overdue) ? ' red' : ''}`}>{num(t.overdue)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </aside>
      </div>
    </>
  );
}
