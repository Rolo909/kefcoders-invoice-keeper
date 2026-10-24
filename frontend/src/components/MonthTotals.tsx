import type { CurrencyTotal } from '../api/types';
import { CURRENCY_NAME, CURRENCY_SIGN, numShort } from '../lib/format';
import { CountUp } from './CountUp';

const share = (v: number, of: number) => (of > 0 ? Math.min(100, (v / of) * 100) : 0);

export function MonthTotals({ totals, loading }: { totals: CurrencyTotal[] | undefined; loading: boolean }) {
  return (
    <section className="totals" aria-labelledby="tot-t">
      <h2 id="tot-t">Осталось оплатить</h2>
      <div className="totals-list">
        {loading &&
          [0, 1, 2].map((i) => (
            <div className="tot" key={i} aria-hidden="true">
              <span className="sk" style={{ width: '30%' }} />
              <span className="sk" style={{ width: '60%', height: 30, marginTop: 10 }} />
              <span className="sk" style={{ marginTop: 14 }} />
            </div>
          ))}
        {!loading &&
          totals
            ?.filter((t) => Number(t.planned) > 0)
            .map((t) => {
              const planned = Number(t.planned);
              const paid = Number(t.paid);
              const unpaid = Number(t.unpaid);
              const overdue = Number(t.overdue);
              const sign = CURRENCY_SIGN[t.currency];
              return (
                <div className="tot" key={t.currency}>
                  <span className="tot-cur">{CURRENCY_NAME[t.currency]}</span>
                  <p className={`tot-big${unpaid ? '' : ' muted'}`}><CountUp value={unpaid} /> <small>{sign}</small></p>
                  <div className="meter" role="img" aria-label={`Оплачено ${numShort(paid)} из ${numShort(planned)}${overdue ? `, просрочено ${numShort(overdue)}` : ''}`}>
                    <i style={{ width: `${share(paid, planned)}%` }} />
                    {overdue > 0 && <i className="overdue" style={{ width: `${share(overdue, planned)}%` }} />}
                  </div>
                  <p className="tot-cap">оплачено {numShort(paid)} из {numShort(planned)}</p>
                  {overdue > 0 && <p className="tot-cap red">просрочено {numShort(overdue)} {sign}</p>}
                  {t.budget_left !== null && Number(t.budget_left) < 0 && (
                    <p className="tot-cap red">план выше бюджета на {numShort(-Number(t.budget_left))} {sign}</p>
                  )}
                </div>
              );
            })}
      </div>
    </section>
  );
}
