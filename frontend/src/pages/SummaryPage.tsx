import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Button, NativeSelect, TextInput } from '@mantine/core';
import { useBudgets, useSaveBudgets, useSummaries, useSummary } from '../api/hooks';
import type { Budget, Currency } from '../api/types';
import { useAuth } from '../auth/context';
import { toast } from '../components/dialogs/actions';
import { monthOf, monthRange, shiftMonth } from '../lib/dates';
import { CURRENCIES, CURRENCY_NAME, longDate, monthName, monthTitle, num } from '../lib/format';

type Mode = 'month' | 'year' | 'custom';

export function SummaryPage() {
  const { today, isAdmin } = useAuth();
  const cur = monthOf(today);
  const year = Number(today.slice(0, 4));
  const month = Number(today.slice(5, 7));
  const [mode, setMode] = useState<Mode>('month');
  const [ym, setYm] = useState(cur);
  const [custom, setCustom] = useState<[string, string]>(monthRange(cur));
  const [asOf, setAsOf] = useState(today);
  const range: [string, string] = mode === 'year' ? [`${year}-01-01`, `${year}-12-31`] : mode === 'custom' ? custom : monthRange(ym);
  const summary = useSummary({ date_from: range[0], date_to: range[1], as_of: asOf || today });
  const budgets = useBudgets(year, month);
  const save = useSaveBudgets();
  const planMonths = useMemo(() => Array.from({ length: 6 }, (_, i) => shiftMonth(cur, i + 1)), [cur]);
  const plan = useSummaries(planMonths.map((m) => ({ date_from: monthRange(m)[0], date_to: monthRange(m)[1] })));
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [bErr, setBErr] = useState('');

  useEffect(() => {
    document.title = 'Итоги — Invoice Keeper';
  }, []);

  useEffect(() => {
    if (!budgets.data) return;
    const next: Record<string, string> = {};
    budgets.data.forEach((b) => { next[`${b.period_type}:${b.currency}`] = num(b.amount); });
    setDraft(next);
  }, [budgets.data]);

  const monthBudget = (c: Currency) => budgets.data?.find((b) => b.currency === c && b.period_type === 'month')?.amount;
  const title = mode === 'year' ? `Итоги за ${year} год на ${longDate(asOf || today)}` : mode === 'custom'
    ? `Итоги за ${custom[0].split('-').reverse().join('.')}–${custom[1].split('-').reverse().join('.')} на ${longDate(asOf || today)}`
    : `Итоги за ${monthName(ym).toLowerCase()} на ${longDate(asOf || today)}`;

  const saveBudgets = async (e: FormEvent) => {
    e.preventDefault();
    const items: Budget[] = [];
    const bad: string[] = [];
    for (const type of ['month', 'year'] as const) {
      for (const c of CURRENCIES) {
        const raw = (draft[`${type}:${c}`] ?? '').replace(/\s/g, '').replace(',', '.');
        if (!/^\d+(\.\d{1,2})?$/.test(raw) || Number(raw) <= 0) bad.push(`${type === 'month' ? 'на месяц' : 'на год'} ${c}`);
        else items.push({ currency: c, period_type: type, year, month: type === 'month' ? month : null, amount: Number(raw).toFixed(2) });
      }
    }
    if (bad.length) return setBErr(`Введите сумму больше нуля в полях: ${bad.join(', ')}.`);
    setBErr('');
    try {
      await save.mutateAsync(items);
      toast('Бюджеты сохранены.');
    } catch {
      setBErr('Не удалось сохранить бюджеты. Попробуйте ещё раз.');
    }
  };

  return (
    <>
      <div className="page-head"><h1>Итоги</h1></div>
      <form className="filters" onSubmit={(e) => e.preventDefault()} aria-label="Период итогов">
        <div className="grp"><span id="s-mode">Период</span>
          <div className="seg" role="group" aria-labelledby="s-mode">
            {([['month', 'Месяц'], ['year', 'Год'], ['custom', 'Свои даты']] as const).map(([v, l]) => (
              <button key={v} type="button" aria-pressed={mode === v} onClick={() => setMode(v)}>{l}</button>
            ))}
          </div>
        </div>
        {mode === 'month' && (
          <NativeSelect label="Месяц" value={ym} onChange={(e) => setYm(e.currentTarget.value)} w={180}
            data={Array.from({ length: 13 }, (_, i) => shiftMonth(cur, i - 6)).map((m) => ({ value: m, label: monthTitle(m) }))} />
        )}
        {mode === 'year' && <NativeSelect label="Год" value={String(year)} data={[String(year)]} w={120} />}
        {mode === 'custom' && (
          <>
            <TextInput type="date" label="С" value={custom[0]} onChange={(e) => setCustom([e.currentTarget.value, custom[1]])} classNames={{ input: 'mono' }} w={150} />
            <TextInput type="date" label="по" value={custom[1]} onChange={(e) => setCustom([custom[0], e.currentTarget.value])} classNames={{ input: 'mono' }} w={150} />
          </>
        )}
        <TextInput type="date" label="Итоги на дату" value={asOf} onChange={(e) => setAsOf(e.currentTarget.value)} description="Оплачено — по фактическим датам не позже этой." classNames={{ input: 'mono' }} w={250} />
      </form>

      <h2 className="section-title" style={{ marginTop: 22 }}>{title}</h2>
      <p className="small muted" style={{ margin: '-6px 0 8px' }}>Каждая валюта считается отдельно, без курсов и конвертации.</p>
      <div className="summary-cards">
        {(summary.data?.totals ?? []).map((t) => (
          <div className="acct" key={t.currency}>
            <div className="acct-head"><b>{CURRENCY_NAME[t.currency]}</b><span>{t.currency}</span></div>
            <dl>
              <dt>План</dt><dd>{num(t.planned)}</dd>
              <dt>Оплачено</dt><dd>{num(t.paid)}</dd>
              <dt>К оплате</dt><dd className="strong">{num(t.unpaid)}</dd>
              <dt className={Number(t.overdue) ? 'red' : undefined}>Просрочено</dt><dd className={Number(t.overdue) ? 'red' : undefined}>{num(t.overdue)}</dd>
              <dt>С опозданием</dt><dd>{num(t.paid_late)}</dd>
              <dt>Периодов оплачено</dt><dd>{t.count_paid} из {t.count_total}</dd>
              {t.budget && <><dt>Бюджет</dt><dd>{num(t.budget)}{Number(t.budget_left) < 0 ? ` — план выше на ${num(-Number(t.budget_left))}` : ''}</dd></>}
            </dl>
          </div>
        ))}
      </div>
      <table className="ledger totals-table">
        <caption className="sr-only">Итоги по валютам</caption>
        <thead>
          <tr>
            <th scope="col">Валюта</th><th scope="col" className="r">План</th><th scope="col" className="r">Оплачено</th><th scope="col" className="r">К оплате</th>
            <th scope="col" className="r">Просрочено</th><th scope="col" className="r">С опозданием</th><th scope="col" className="r">Периодов</th><th scope="col" className="r">Бюджет</th><th scope="col">Исполнение</th>
          </tr>
        </thead>
        <tbody>
          {(summary.data?.totals ?? []).map((t) => {
            const budget = t.budget ? Number(t.budget) : 0;
            const paid = Number(t.paid);
            const planned = Number(t.planned);
            return (
              <tr key={t.currency}>
                <td><span className="serif" style={{ fontWeight: 700, fontSize: 19 }}>{t.currency}</span><span className="name-sub">{CURRENCY_NAME[t.currency]}</span></td>
                <td className="sum">{num(planned)}</td>
                <td className="sum">{num(paid)}</td>
                <td className="sum strong">{num(t.unpaid)}</td>
                <td className={`sum${Number(t.overdue) ? ' red' : ''}`}>{num(t.overdue)}</td>
                <td className={`sum${Number(t.paid_late) ? ' amber' : ''}`}>{num(t.paid_late)}</td>
                <td className="sum">{t.count_paid} из {t.count_total}</td>
                <td className="sum">{budget ? num(budget) : '—'}</td>
                <td style={{ width: 200 }}>
                  {budget ? (
                    <>
                      <div className="bar" role="img" aria-label={`Оплачено ${Math.round((paid / budget) * 100)} % бюджета, план ${Math.round((planned / budget) * 100)} %`}>
                        <div className={`fill${paid > budget ? ' over' : ''}`} style={{ width: `${Math.min(100, (paid / budget) * 100)}%` }} />
                        <div className="cap" style={{ left: `${Math.min(99.5, (planned / budget) * 100)}%` }} />
                      </div>
                      <p className="bar-cap"><span>оплачено {Math.round((paid / budget) * 100)} %</span>
                        <span className={planned > budget ? 'red' : undefined}>{planned > budget ? `план выше на ${num(planned - budget)}` : `свободно ${num(budget - planned)}`}</span></p>
                    </>
                  ) : <span className="small muted">Бюджет задан на месяц и год</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="small muted" style={{ marginTop: 10 }}>«Просрочено» — не оплачено, срок прошёл. «С опозданием» — оплачено позже срока.</p>

      <div className="two">
        <section aria-labelledby="b-t">
          <h2 id="b-t" className="section-title">Бюджеты на {year} год</h2>
          <form onSubmit={saveBudgets} noValidate>
            <table className="ledger budget-table">
              <thead><tr><th scope="col">Валюта</th><th scope="col" className="r">На {monthName(cur).toLowerCase()}</th><th scope="col" className="r">На год</th></tr></thead>
              <tbody>
                {CURRENCIES.map((c) => (
                  <tr key={c}>
                    <th scope="row" style={{ fontWeight: 700, borderBottom: '1px solid var(--rule)', textAlign: 'left' }}>{c}</th>
                    {(['month', 'year'] as const).map((type) => (
                      <td className="r" key={type}>
                        {isAdmin ? (
                          <TextInput aria-label={`Бюджет ${type === 'month' ? 'на месяц' : 'на год'}, ${c}`} inputMode="decimal" value={draft[`${type}:${c}`] ?? ''}
                            onChange={(e) => { const v = e.currentTarget.value; setDraft((d) => ({ ...d, [`${type}:${c}`]: v })); }} classNames={{ input: 'mono budget-input' }} />
                        ) : (
                          <span className="mono">{draft[`${type}:${c}`] ?? '—'}</span>
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {bErr && <p className="ik-error" role="alert" style={{ marginTop: 8 }}>{bErr}</p>}
            {isAdmin ? <Button type="submit" variant="filled" mt="md" loading={save.isPending}>Сохранить бюджеты</Button> : <p className="small muted" style={{ marginTop: 10 }}>Бюджеты меняет администратор.</p>}
          </form>
        </section>

        <section aria-labelledby="pl-t">
          <h2 id="pl-t" className="section-title">Плановые расходы</h2>
          <p className="small muted" style={{ marginBottom: 8 }}>По действующим платежам, на полгода вперёд. Прекращённые не учитываются.</p>
          <div style={{ overflowX: 'auto' }}>
            <table className="ledger">
              <thead><tr><th scope="col">Месяц</th>{CURRENCIES.map((c) => <th key={c} scope="col" className="r">{c}</th>)}</tr></thead>
              <tbody>
                {planMonths.map((m, i) => (
                  <tr key={m}>
                    <th scope="row" style={{ fontWeight: 400, textAlign: 'left', borderBottom: '1px solid var(--rule)' }}>{monthTitle(m)}</th>
                    {CURRENCIES.map((c) => {
                      const v = Number(plan[i]?.data?.totals.find((t) => t.currency === c)?.planned ?? 0);
                      const over = !!monthBudget(c) && v > Number(monthBudget(c));
                      return (
                        <td key={c} className={`sum${over ? ' red' : ''}`}>
                          {over && <span aria-hidden="true" style={{ marginRight: 4 }}>▲</span>}{plan[i]?.data ? num(v) : '…'}{over && <span className="sr-only">, выше бюджета</span>}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="small muted" style={{ marginTop: 8 }}><span className="red" aria-hidden="true">▲</span> — месяц, где план выше месячного бюджета.</p>
        </section>
      </div>
    </>
  );
}
