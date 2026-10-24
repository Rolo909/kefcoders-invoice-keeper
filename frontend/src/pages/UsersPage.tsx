import { useEffect } from 'react';
import { Button, Group } from '@mantine/core';
import { useUsers } from '../api/hooks';
import { useAuth } from '../auth/context';
import { RequireAdmin } from '../auth/guards';
import { useDialogs } from '../components/dialogs/context';
import { date } from '../lib/format';

function Users() {
  const { open } = useDialogs();
  const users = useUsers();
  return (
    <>
      <div className="page-head">
        <h1>Пользователи</h1>
        <div className="actions"><Button variant="filled" onClick={() => open({ type: 'userForm' })}>Новый пользователь</Button></div>
      </div>
      <table className="ledger stack" style={{ marginTop: 20 }}>
        <caption className="sr-only">Пользователи</caption>
        <thead><tr><th scope="col">Пользователь</th><th scope="col">Команда</th><th scope="col">Почта</th><th scope="col">Telegram</th><th scope="col">Роль</th><th scope="col">Создан</th><th scope="col"><span className="sr-only">Действия</span></th></tr></thead>
        <tbody>
          {users.isPending && <tr><td colSpan={7}><span className="sk" style={{ width: '50%' }} /></td></tr>}
          {(users.data?.items ?? []).map((u) => (
            <tr key={u.id}>
              <td data-k="name"><b>{u.full_name || u.login}</b><span className="name-sub mono">{u.login}</span></td>
              <td data-k="sum" className={u.team ? undefined : 'muted'}>{u.team?.name ?? 'все команды'}</td>
              <td data-k="hide-sm">{u.email || '—'}{u.email && <span className="name-sub">{u.notify_email ? 'напоминания приходят на почту' : 'напоминания на почту выключены'}</span>}</td>
              <td data-k="hide-sm" className={u.telegram_linked ? undefined : 'muted'}>{u.telegram_linked ? 'привязан' : 'не привязан'}</td>
              <td data-k="mark">{u.role === 'admin' ? 'Администратор' : 'Пользователь'}{u.is_system && <span className="env-tag">из .env</span>}</td>
              <td className="date" data-k="hide-sm">{date(u.created_at.slice(0, 10))}</td>
              <td className="acts" data-k="more">
                {u.is_system ? <span className="small muted">Меняется только в .env</span> : (
                  <Group gap={4} justify="flex-end">
                    <Button size="xs" variant="subtle" onClick={() => open({ type: 'userForm', user: u })} aria-label={`Изменить пользователя ${u.login}`}>Изменить</Button>
                    <Button size="xs" variant="subtle" color="red" onClick={() => open({ type: 'deleteUser', user: u })} aria-label={`Удалить пользователя ${u.login}`}>Удалить</Button>
                  </Group>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted" style={{ marginTop: 12 }}>Удаление или смена пароля сразу завершают все сессии пользователя. Отметки об оплате остаются в истории.</p>
    </>
  );
}

export function UsersPage() {
  const { isAdmin } = useAuth();
  useEffect(() => {
    document.title = isAdmin ? 'Пользователи — Invoice Keeper' : 'Нет доступа — Invoice Keeper';
  }, [isAdmin]);
  return <RequireAdmin><Users /></RequireAdmin>;
}
