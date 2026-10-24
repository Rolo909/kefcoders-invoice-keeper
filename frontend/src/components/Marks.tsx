import { Button } from '@mantine/core';
import type { Occurrence } from '../api/types';
import { useToday } from '../auth/context';
import { date, days, relative, shortDate } from '../lib/format';
import { isFresh, stampStyle } from '../lib/hits';
import { useDialogs } from './dialogs/context';

export function Stamp({ occ }: { occ: Occurrence }) {
  const today = useToday();
  const late = occ.state === 'paid_late';
  return (
    <span className={`stamp${late ? ' late' : ''}${isFresh(occ.id) ? ' hit' : ''}`} style={stampStyle(occ.id, occ.paid_date, late, today)}>
      Оплачено <em>{shortDate(occ.paid_date)}</em>
    </span>
  );
}

export function PaidMark({ occ }: { occ: Occurrence }) {
  return (
    <>
      <Stamp occ={occ} />
      {occ.state === 'paid_late' && <span className="late-inline">позже на {days(occ.days_overdue)}</span>}
    </>
  );
}

export function MarkButton({ occ, quiet = false }: { occ: Occurrence; quiet?: boolean }) {
  const { open } = useDialogs();
  return (
    <Button
      size="xs"
      variant={quiet ? "transparent" : "outline"}
      onClick={() => open({ type: "markPaid", occ })}
      aria-label={`Отметить оплату: ${occ.recurring_payment.name}, срок ${date(occ.due_date)}`}
    >
      Отметить оплату
    </Button>
  );
}

export function MarkCell({ occ, canMark = true }: { occ: Occurrence; canMark?: boolean }) {
  const today = useToday();
  if (occ.paid_date) return <PaidMark occ={occ} />;
  if (occ.state === 'overdue') {
    return (
      <div className="mark-row">
        <span className="note-red">{relative(occ, today)}</span>
        {canMark && <MarkButton occ={occ} />}
      </div>
    );
  }
  if (occ.state === 'due_soon') {
    return (
      <div className="mark-row">
        <span className="soon">
          <b>{relative(occ, today)}</b>
          {occ.last_reminder_at && <small>напомнили в Telegram {shortDate(occ.last_reminder_at.slice(0, 10))}</small>}
        </span>
        {canMark && <MarkButton occ={occ} />}
      </div>
    );
  }
  return (
    <div className="mark-row">
      <span className="muted">{relative(occ, today)}</span>
      {canMark && <MarkButton occ={occ} quiet />}
    </div>
  );
}

export function StatusText({ occ }: { occ: Occurrence }) {
  const today = useToday();
  const text = occ.paid_date
    ? `оплачено ${shortDate(occ.paid_date)}${occ.state === 'paid_late' ? `, позже на ${days(occ.days_overdue)}` : ''}`
    : relative(occ, today);
  return <span className={`st ${occ.state}`}>{text}</span>;
}
