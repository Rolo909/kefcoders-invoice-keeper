import { useState } from 'react';
import { Popover } from '@mantine/core';
import { Link } from 'react-router-dom';
import { useInbox, useReadInbox } from '../api/hooks';
import type { InboxItem } from '../api/types';
import { useAuth } from '../auth/context';
import { amountShort, date, dateTime, relative } from '../lib/format';
import { BellIcon } from './icons';

function line(i: InboxItem, today: string) {
  if (i.paid_date) return { text: `Уже оплачено ${date(i.paid_date)}`, red: false };
  if (i.payment_deleted) return { text: 'Платёж прекращён', red: false };
  if (i.occurrence_state === 'overdue') return { text: `Просрочено: ${amountShort(i.amount, i.currency)}, срок был ${date(i.due_date)}`, red: true };
  const rel = relative({ state: i.occurrence_state, due_date: i.due_date, paid_date: null, days_overdue: 0 }, today);
  return { text: `${amountShort(i.amount, i.currency)} · срок ${date(i.due_date)}, ${rel}`, red: false };
}

export function Bell() {
  const { user, today } = useAuth();
  const inbox = useInbox(!!user);
  const read = useReadInbox();
  const [opened, setOpened] = useState(false);
  const unread = inbox.data?.unread_count ?? 0;

  return (
    <Popover opened={opened} onChange={setOpened} position="bottom-end" width={380} shadow="md" zIndex={450} classNames={{ dropdown: 'ik-menu bell-panel' }}>
      <Popover.Target>
        <button type="button" className="icon-btn" onClick={() => setOpened((o) => !o)} aria-expanded={opened} aria-label={unread ? `Уведомления, непрочитанных: ${unread}` : 'Уведомления'}>
          <BellIcon />
          {unread > 0 && <span className="count" aria-hidden="true">{unread}</span>}
        </button>
      </Popover.Target>
      <Popover.Dropdown>
        <div className="menu-head">
          <b>Уведомления</b>
          {unread > 0 && <button type="button" className="link small" onClick={() => read.mutate('all')}>Прочитать все</button>}
        </div>
        <ul className="bell-list">
          {(inbox.data?.items ?? []).map((i) => {
            const l = line(i, today);
            return (
              <li key={i.id}>
                <Link
                  className={`menu-item${i.read ? ' read' : ''}`}
                  to={`/occurrences/${i.occurrence_id}`}
                  onClick={() => {
                    if (!i.read) read.mutate(i.id);
                    setOpened(false);
                  }}
                >
                  <span className="dot" aria-hidden="true" />
                  <span>
                    <span className="t">{i.payment_name}</span>
                    <span className={`s${l.red ? ' red' : ''}`}>{l.text}</span>
                    <span className="s">В панели · {dateTime(i.created_at)}{i.read ? '' : ' · не прочитано'}</span>
                  </span>
                </Link>
              </li>
            );
          })}
          {inbox.data && !inbox.data.items.length && <li className="muted" style={{ padding: 16 }}>Уведомлений пока нет. Они появятся за 3 дня до срока оплаты.</li>}
        </ul>
      </Popover.Dropdown>
    </Popover>
  );
}
