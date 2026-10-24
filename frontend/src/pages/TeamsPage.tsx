import { useEffect } from 'react';
import { Button, Group } from '@mantine/core';
import { useTeams } from '../api/hooks';
import { useAuth } from '../auth/context';
import { RequireAdmin } from '../auth/guards';
import { useTeamScope } from '../auth/team';
import { useDialogs } from '../components/dialogs/context';
import { date, plural } from '../lib/format';

function Teams() {
  const { open } = useDialogs();
  const { teamId, setTeamId } = useTeamScope();
  const teams = useTeams();
  const items = teams.data?.items ?? [];
  return (
    <>
      <div className="page-head">
        <h1>Команды</h1>
        <div className="actions"><Button variant="filled" onClick={() => open({ type: 'teamForm' })}>Новая команда</Button></div>
      </div>
      <p className="lead">
        Каждая команда видит только свои платежи и общие. Общий платёж каждая команда оплачивает сама: у неё свои периоды и своя отметка «Оплачено».
      </p>
      {teams.isSuccess && !items.length ? (
        <div className="empty">
          <h2>Команд пока нет</h2>
          <p>Создайте команду, затем добавьте в неё пользователей. Напоминания команды бот пишет в её Telegram-чат.</p>
          <Button variant="outline" onClick={() => open({ type: 'teamForm' })}>Создать первую команду</Button>
        </div>
      ) : (
        <table className="ledger stack">
          <caption className="sr-only">Команды</caption>
          <thead><tr><th scope="col">Команда</th><th scope="col">Чат Telegram</th><th scope="col" className="r">Участники</th><th scope="col">Создана</th><th scope="col"><span className="sr-only">Действия</span></th></tr></thead>
          <tbody>
            {teams.isPending && <tr><td colSpan={5}><span className="sk" style={{ width: '50%' }} /></td></tr>}
            {items.map((t) => (
              <tr key={t.id}>
                <td data-k="name"><b>{t.name}</b>{t.id === teamId && <span className="name-sub">выбрана в шапке</span>}</td>
                <td data-k="mark" className={t.telegram_chat_id ? 'mono' : 'muted'}>{t.telegram_chat_id ?? 'общий чат из .env'}</td>
                <td className="sum" data-k="sum">{t.members_count} {plural(t.members_count, 'человек', 'человека', 'человек')}</td>
                <td className="date" data-k="hide-sm">{date(t.created_at.slice(0, 10))}</td>
                <td className="acts" data-k="more">
                  <Group gap={4} justify="flex-end" wrap="nowrap">
                    {t.id !== teamId && <Button size="xs" variant="subtle" onClick={() => setTeamId(t.id)} aria-label={`Смотреть данные команды ${t.name}`}>Смотреть</Button>}
                    <Button size="xs" variant="subtle" onClick={() => open({ type: 'teamForm', team: t })} aria-label={`Изменить команду ${t.name}`}>Изменить</Button>
                    <Button size="xs" variant="subtle" color="red" onClick={() => open({ type: 'deleteTeam', team: t })} aria-label={`Удалить команду ${t.name}`}>Удалить</Button>
                  </Group>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="small muted" style={{ marginTop: 12 }}>
        Новая команда получает общие платежи с ближайшего срока, без долгов за прошлое. Удалить можно только команду без участников и оплат.
      </p>
    </>
  );
}

export function TeamsPage() {
  const { isAdmin } = useAuth();
  useEffect(() => {
    document.title = isAdmin ? 'Команды — Invoice Keeper' : 'Нет доступа — Invoice Keeper';
  }, [isAdmin]);
  return <RequireAdmin><Teams /></RequireAdmin>;
}
