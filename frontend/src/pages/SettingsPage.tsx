import { useEffect, useState, type FormEvent } from 'react';
import { Button, Checkbox, TextInput, useMantineColorScheme } from '@mantine/core';
import { useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useCalendarSubscription, useLinkCode, useLogout, useRevokeCalendar, useUpdateMe } from '../api/hooks';
import { useAuth } from '../auth/context';
import { toast } from '../components/dialogs/actions';
import { CalendarIcon, TelegramIcon } from '../components/icons';

export function SettingsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const logout = useLogout();
  const link = useLinkCode();
  const update = useUpdateMe();
  const calendar = useCalendarSubscription();
  const revokeCalendar = useRevokeCalendar();
  const { colorScheme, setColorScheme } = useMantineColorScheme();
  const [email, setEmail] = useState(user?.email ?? '');
  const [notify, setNotify] = useState(user?.notify_email ?? false);
  const [error, setError] = useState('');

  useEffect(() => {
    document.title = 'Профиль — Invoice Keeper';
  }, []);

  if (!user) return null;

  const saveEmail = async (e: FormEvent) => {
    e.preventDefault();
    if (email && !/^\S+@\S+\.\S+$/.test(email)) return setError('Введите адрес целиком, например name@kefcoders.ru.');
    if (notify && !email) return setError('Укажите почту, чтобы получать на неё напоминания.');
    setError('');
    try {
      await update.mutateAsync({ email: email.trim() || null, notify_email: notify });
      toast(notify ? `Сохранено. Напоминания будут приходить на ${email}.` : 'Сохранено. Напоминания на почту выключены.');
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : 'Не удалось сохранить. Попробуйте ещё раз.');
    }
  };

  const code = link.data?.code;
  const feed = calendar.data;

  const copyFeed = async () => {
    if (!feed) return;
    try {
      await navigator.clipboard.writeText(feed.url);
      toast('Ссылка скопирована. Вставьте её в календаре: «Добавить по URL».');
    } catch {
      toast('Не удалось скопировать — выделите ссылку и скопируйте вручную.');
    }
  };

  const disableFeed = async () => {
    await revokeCalendar.mutateAsync();
    calendar.reset();
    toast('Ссылка отключена: календари перестанут получать сроки. Новую можно получить в любой момент.');
  };

  return (
    <div className="prof">
      <div className="page-head"><h1>Профиль</h1></div>
      <p className="lead">{user.full_name ?? user.login} · {user.login} · {user.role === 'admin' ? 'администратор' : 'пользователь'}</p>
      {user.is_system && <p className="small muted" style={{ margin: '-8px 0 22px' }}>Учётная запись администратора задана в файле .env: логин и пароль меняются только там.</p>}

      <section className="block" aria-labelledby="tg-t">
        <h2 id="tg-t"><TelegramIcon />Telegram</h2>
        <p className="muted">Напоминания приходят в общий чат команды. Привяжите свой аккаунт, чтобы отмечать оплату кнопкой «Оплачено» прямо в сообщении бота.</p>
        {user.telegram_linked ? (
          <div><span className="stamp" style={{ transform: 'rotate(-2deg)' }}>Привязан</span></div>
        ) : (
          <>
            <ol className="steps">
              <li><span>Получите код привязки. Он действует 10 минут.</span></li>
              <li><span>Откройте бота Invoice Keeper в Telegram в личных сообщениях.</span></li>
              <li><span>Отправьте боту команду <kbd>/link {code ?? '123456'}</kbd>.</span></li>
            </ol>
            {code ? (
              <div style={{ display: 'grid', gap: 8 }} aria-live="polite">
                <span className="code">{code.slice(0, 3)} {code.slice(3)}</span>
                <span className="small muted">Код действует до {new Date(link.data!.expires_at).toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })}. Бот ответит, когда аккаунт будет привязан.</span>
                <div><Button size="xs" variant="subtle" onClick={() => link.mutate()}>Получить новый код</Button></div>
              </div>
            ) : (
              <div><Button variant="filled" loading={link.isPending} onClick={() => link.mutate()}>Получить код</Button></div>
            )}
          </>
        )}
      </section>

      <section className="block" aria-labelledby="cal-t">
        <h2 id="cal-t"><CalendarIcon />Календарь</h2>
        <p className="muted">Сроки платежей в Google, Outlook, Яндекс- или Apple-календаре: сумма, статус и напоминание за 3 дня. Календарь сам подтягивает изменения — оплату, новые платежи, просрочки.</p>
        {feed ? (
          <div style={{ display: 'grid', gap: 12, maxWidth: 560 }} aria-live="polite">
            <TextInput label="Ссылка для подписки" value={feed.url} readOnly classNames={{ input: 'mono' }}
              onFocus={(e) => e.currentTarget.select()} />
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <Button variant="filled" onClick={copyFeed}>Скопировать ссылку</Button>
              <Button component="a" href={feed.webcal_url} variant="outline">Открыть в приложении календаря</Button>
            </div>
            <ol className="steps">
              <li><span><b>Google Календарь:</b> «Другие календари» → «+» → «Добавить по URL».</span></li>
              <li><span><b>Яндекс Календарь:</b> «Новый календарь» → «Подписаться на календарь».</span></li>
              <li><span><b>Outlook:</b> «Добавить календарь» → «Подписаться из Интернета».</span></li>
            </ol>
            <p className="small muted">По ссылке без входа видны сроки и суммы — не публикуйте её. Google обновляет подписку раз в несколько часов, остальные — чаще.</p>
            <div><Button size="xs" variant="subtle" color="red" loading={revokeCalendar.isPending} onClick={disableFeed}>Отключить ссылку</Button></div>
          </div>
        ) : (
          <div><Button variant="filled" loading={calendar.isPending} onClick={() => calendar.mutate()}>Получить ссылку</Button></div>
        )}
      </section>

      <section className="block" aria-labelledby="em-t">
        <h2 id="em-t">Почта</h2>
        {user.is_system ? (
          <p className="muted">Почта для напоминаний настраивается у пользователей. Администратор из .env получает уведомления в общем чате Telegram и в колокольчике панели.</p>
        ) : (
        <form onSubmit={saveEmail} noValidate style={{ display: "grid", gap: 14, maxWidth: 460 }}>
          <TextInput type="email" inputMode="email" autoComplete="email" label="Адрес для напоминаний" placeholder="name@kefcoders.ru" value={email}
            onChange={(e) => setEmail(e.currentTarget.value)} error={error || undefined} />
          <Checkbox label="Присылать напоминания на почту" description="Письмо приходит одновременно с сообщением в Telegram, за 3 дня до срока." checked={notify}
            onChange={(e) => setNotify(e.currentTarget.checked)} />
          <div><Button type="submit" variant="outline" loading={update.isPending}>Сохранить настройки почты</Button></div>
        </form>
        )}
      </section>

      <section className="block" aria-labelledby="th-t">
        <h2 id="th-t">Оформление</h2>
        <div className="seg" role="group" aria-labelledby="th-t">
          <button type="button" aria-pressed={colorScheme !== 'dark'} onClick={() => setColorScheme('light')}>Светлая тема</button>
          <button type="button" aria-pressed={colorScheme === 'dark'} onClick={() => setColorScheme('dark')}>Тёмная тема</button>
        </div>
      </section>

      <section className="block" aria-labelledby="se-t">
        <h2 id="se-t">Сессия</h2>
        <p className="muted">Вход сохраняется на 7 дней на этом устройстве.</p>
        <div>
          <Button variant="outline" color="red" loading={logout.isPending} onClick={async () => {
            try {
              await logout.mutateAsync();
            } finally {
              navigate('/login?state=loggedout', { replace: true });
            }
          }}>Выйти</Button>
        </div>
      </section>
    </div>
  );
}
