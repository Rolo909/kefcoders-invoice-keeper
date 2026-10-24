import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Button, Group, TextInput } from '@mantine/core';
import { downloadUrl, ApiError } from '../../api/client';
import { useAttachments, useOccurrence, useOccurrences } from '../../api/hooks';
import type { OccurrenceDetail } from '../../api/types';
import { useAuth } from '../../auth/context';
import { ACTION_LABEL, describeAudit } from '../../lib/audit';
import { addDays, diffDays } from '../../lib/dates';
import { bytes, CURRENCY_SIGN, date, dateTime, days, num, PERIOD_LABEL, statusLine } from '../../lib/format';
import { isFresh, stampStyle } from '../../lib/hits';
import { ClipIcon } from '../icons';
import { usePaymentActions } from './actions';
import { useDialogs } from './context';

const CHANNEL: Record<string, string> = { telegram: 'Telegram', email: 'Почта', webhook: 'Webhook', inapp: 'В панели' };

function PayForm({ occ }: { occ: OccurrenceDetail }) {
  const { today } = useAuth();
  const actions = usePaymentActions();
  const [value, setValue] = useState(today);
  const [error, setError] = useState('');
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!value) return setError('Укажите дату оплаты.');
    if (value > today) return setError(`Укажите дату не позже сегодняшней — ${date(today)}.`);
    setError('');
    try {
      await actions.markPaid(occ, value, true);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось отметить оплату. Попробуйте ещё раз.');
    }
  };
  return (
    <form className="pay-box" onSubmit={submit} noValidate>
      <div className="row">
        <TextInput type="date" label="Фактическая дата оплаты" value={value} max={today} onChange={(e) => setValue(e.currentTarget.value)} error={error || undefined} classNames={{ input: 'mono' }} />
        <Button type="submit" variant="filled" loading={actions.pending}>Отметить оплату</Button>
      </div>
      <p className="small muted">Срок периода не изменится. Дату можно будет исправить.</p>
    </form>
  );
}

export function PeriodCard({ id, asPage = false }: { id: string; asPage?: boolean }) {
  const { today, user, isAdmin } = useAuth();
  const { open } = useDialogs();
  const q = useOccurrence(id);
  const files = useAttachments(id);
  const siblings = useOccurrences({ recurring_payment_id: q.data?.recurring_payment_id, team_id: q.data?.team.id, sort: '-due_date', limit: 6 }, !!q.data);

  if (q.isPending) return <div aria-busy="true"><span className="sk" style={{ width: '60%', height: 28 }} /><span className="sk" style={{ marginTop: 18, height: 48, width: '40%' }} /></div>;
  if (q.isError || !q.data) return <div className="empty"><h2>Период не найден</h2><p>Возможно, платёж прекратили и будущий период удалился.</p><Link to="/occurrences">Открыть все периоды</Link></div>;

  const o = q.data;
  const p = o.recurring_payment;
  const Title = asPage ? 'h1' : 'h2';
  const late = o.state === 'paid_late';

  return (
    <div className="period">
      <p className="crumbs">
        <Link to={`/recurring-payments/${p.id}`}>Регулярный платёж</Link> · {PERIOD_LABEL[p.period].toLowerCase()}{p.is_deleted ? ' · прекращён' : ''}
      </p>
      <Title className="display" style={{ fontSize: asPage ? 40 : 28, lineHeight: 1.15 }}>{p.name}</Title>
      <p className={`st ${o.state}`} style={{ marginTop: 8 }}>{statusLine(o, today)}</p>
      <p className="big-sum">{num(o.amount)}<small>{CURRENCY_SIGN[o.currency]}</small></p>
      <dl className="facts">
        <div><dt className="sr-only">Срок</dt><dd>Срок <b>{date(o.due_date)}</b></dd></div>
        <div><dt className="sr-only">Номер периода</dt><dd>Период <b>№ {o.seq + 1}</b></dd></div>
        {isAdmin && <div><dt className="sr-only">Команда</dt><dd>Команда <b>{o.team.name}</b></dd></div>}
        {o.paid_by && <div><dt className="sr-only">Отметка</dt><dd>Отметка <b>{o.paid_by.full_name ?? o.paid_by.login}</b></dd></div>}
      </dl>

      {!o.paid_date ? (
        <PayForm occ={o} />
      ) : (
        <div className="pay-box">
          <div>
            <span className={`stamp${late ? ' late' : ''}${isFresh(o.id) ? ' hit' : ''}`} style={stampStyle(o.id, o.paid_date, late, today)}>
              Оплачено <em>{date(o.paid_date).slice(0, 5)}</em>
            </span>
            {late && <span className="stamp-late-note">Позже срока на {days(o.days_overdue)}. Если оплатили раньше, исправьте дату.</span>}
          </div>
          <Group gap="xs">
            <Button size="xs" variant="outline" onClick={() => open({ type: 'changeDate', occ: o })}>Изменить дату оплаты</Button>
            <Button size="xs" variant="outline" color="red" onClick={() => open({ type: 'unmark', occ: o })}>Снять отметку</Button>
          </Group>
        </div>
      )}

      <h3 className="section-title" style={{ fontSize: 19, marginTop: 28 }}>Чеки и ссылки</h3>
      <ul className="list-ruled">
        {(files.data ?? []).map((f) => (
          <li key={f.id}>
            <span>
              <ClipIcon />{' '}
              <a href={f.kind === 'link' ? f.url ?? '#' : downloadUrl(f.id)} target="_blank" rel="noreferrer">{f.original_name}</a>{' '}
              <span className="small muted">{f.size ? `${bytes(f.size)} · ` : ''}{f.uploaded_by.full_name ?? f.uploaded_by.login}, {dateTime(f.created_at)}</span>
            </span>
            {(isAdmin || f.uploaded_by.id === user?.id) && (
              <Button size="xs" variant="subtle" color="red" onClick={() => open({ type: 'deleteAttachment', occ: o, att: f })} aria-label={`Удалить вложение ${f.original_name}`}>Удалить</Button>
            )}
          </li>
        ))}
        {files.data && !files.data.length && <li className="muted">Чеков и ссылок пока нет.</li>}
      </ul>
      <Button size="xs" variant="outline" mt="sm" onClick={() => open({ type: 'attach', occ: o })}>Прикрепить чек или ссылку</Button>

      <div className={asPage ? 'cols-2' : ''}>
        <section>
          <h3 className="section-title" style={{ fontSize: 19, marginTop: 28 }}>Напоминания</h3>
          <ul className="list-ruled">
            {o.reminders.map((r) => (
              <li key={r.id}>
                <span><b>{CHANNEL[r.channel]}</b><span className="name-sub">{r.kind === 'overdue' ? 'о просрочке' : 'за 3 дня до срока'}</span></span>
                <span className={`small ${r.status === 'failed' ? 'red' : 'muted'}`} style={{ textAlign: 'right' }}>
                  {dateTime(r.created_at)} · {r.status === 'sent' ? 'доставлено' : r.status === 'pending' ? 'отправляется' : `не доставлено: ${r.last_error}`}
                </span>
              </li>
            ))}
            {!o.reminders.length && (
              <li className="muted">{diffDays(today, o.due_date) > 3 && !o.paid_date ? `Напомним за 3 дня до срока, ${date(addDays(o.due_date, -3))}.` : 'Напоминаний не было.'}</li>
            )}
          </ul>
        </section>
        <section>
          <h3 className="section-title" style={{ fontSize: 19, marginTop: 28 }}>История</h3>
          <ul className="list-ruled">
            {o.history.map((a) => (
              <li key={a.id} style={{ display: 'block' }}>
                <b>{ACTION_LABEL[a.action] ?? a.action}</b> <span className="small muted">{dateTime(a.at)} · {a.actor?.full_name ?? a.actor_login}</span>
                <span className="name-sub">{describeAudit(a)}</span>
              </li>
            ))}
            {!o.history.length && <li className="muted">Изменений не было.</li>}
          </ul>
        </section>
      </div>

      <h3 className="section-title" style={{ fontSize: 19 }}>Все периоды платежа</h3>
      <ul className="list-ruled">
        {(siblings.data?.items ?? []).map((s) => (
          <li key={s.id} style={s.id === o.id ? { fontWeight: 700 } : undefined}>
            <Link className="mono" to={`/occurrences/${s.id}`} aria-current={s.id === o.id ? 'true' : undefined}>{date(s.due_date)}</Link>
            <span className={`st small ${s.state}`}>{statusLine(s, today)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
