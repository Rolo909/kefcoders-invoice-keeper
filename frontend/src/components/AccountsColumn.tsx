import type { CurrencyTotal } from '../api/types';
import { CURRENCY_NAME, CURRENCY_SIGN, num } from '../lib/format';
import { CountUp } from './CountUp';

const pct = (v: number, of: number) => (of > 0 ? Math.round((v / of) * 100) : 0);

export function AccountsColumn({ totals, title, loading }: { totals: CurrencyTotal[] | undefined; title: string; loading: boolean }) {
  return (
    <section className="accounts" aria-labelledby="acc-t">
      <h2 id="acc-t">{title}</h2>
      <div className="accounts-list">
        {loading &&
          [0, 1, 2].map((i) => (
            <div className="acct" key={i} aria-hidden="true">
              <span className="sk" style={{ width: '40%', height: 18 }} />
              <span className="sk" style={{ marginTop: 14 }} />
              <span className="sk" style={{ marginTop: 8 }} />
            </div>
          ))}
        {!loading &&
          totals?.map((t) => {
            const planned = Number(t.planned);
            const paid = Number(t.paid);
            const budget = t.budget ? Number(t.budget) : 0;
            return (
              <div className="acct" key={t.currency}>
                <div className="acct-head"><b>{CURRENCY_NAME[t.currency]}</b><span aria-hidden="true">{CURRENCY_SIGN[t.currency]}</span></div>
                <dl>
                  <dt>План</dt><dd>{num(planned)}</dd>
                  <dt>Оплачено</dt><dd><CountUp value={paid} /></dd>
                  <dt>К оплате</dt><dd className="strong"><CountUp value={Number(t.unpaid)} /></dd>
                  {Number(t.overdue) > 0 && (<><dt className="red">из них просрочено</dt><dd className="red"><CountUp value={Number(t.overdue)} /></dd></>)}
                </dl>
                {budget > 0 && (
                  <div style={{ marginTop: 12 }}>
                    <div className="bar" role="img" aria-label={`Бюджет ${num(budget)}: оплачено ${pct(paid, budget)} %, план ${pct(planned, budget)} %`}>
                      <div className={`fill${paid > budget ? ' over' : ''}`} style={{ width: `${Math.min(100, (paid / budget) * 100)}%` }} />
                      <div className="cap" style={{ left: `${Math.min(99.5, (planned / budget) * 100)}%` }} />
                    </div>
                    <p className="bar-cap" aria-hidden="true">
                      <span><i className="lg-fill" />оплачено {pct(paid, budget)} %</span>
                      <span className={planned > budget ? 'red' : undefined}><i className="lg-cap" />план {pct(planned, budget)} %</span>
                      <span>бюджет {num(budget).replace(',00', '')}</span>
                    </p>
                  </div>
                )}
              </div>
            );
          })}
      </div>
    </section>
  );
}
