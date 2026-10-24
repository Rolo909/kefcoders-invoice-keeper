import { useEffect, useState } from 'react';
import { Button, PasswordInput, TextInput } from '@mantine/core';
import { useForm } from 'react-hook-form';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { ApiError } from '../api/client';
import { useLogin } from '../api/hooks';
import { useAuth } from '../auth/context';
import { Logo } from '../components/Logo';

const SECTION: Record<string, string> = {
  '/occurrences': 'Периоды', '/recurring-payments': 'Регулярные платежи', '/calendar': 'Календарь', '/summary': 'Итоги',
  '/teams': 'Команды', '/users': 'Пользователи', '/audit': 'Журнал', '/settings': 'Профиль',
};

export function LoginPage() {
  const { user } = useAuth();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const login = useLogin();
  const [error, setError] = useState('');
  const next = params.get('next') || '/';
  const safeNext = next.startsWith('/') && !next.startsWith('//') ? next : '/';
  const section = SECTION[`/${safeNext.split('/')[1]}`];
  const { register, handleSubmit, setFocus, resetField, formState: { errors } } = useForm<{ login: string; password: string }>({
    defaultValues: { login: '', password: '' },
  });

  useEffect(() => {
    document.title = 'Вход — Invoice Keeper';
    setFocus('login');
  }, [setFocus]);

  if (user && !login.isPending) return <Navigate to={safeNext} replace />;

  const submit = handleSubmit(async (v) => {
    setError('');
    try {
      await login.mutateAsync({ login: v.login.trim(), password: v.password });
      navigate(safeNext, { replace: true });
    } catch (e) {
      resetField('password');
      if (e instanceof ApiError && e.status === 429) setError('Слишком много попыток входа. Попробуйте снова через минуту.');
      else if (e instanceof ApiError && e.status === 401) setError('Неверный логин или пароль. Проверьте раскладку клавиатуры и Caps Lock.');
      else setError(e instanceof ApiError ? e.detail : 'Сервер не отвечает. Попробуйте ещё раз через минуту.');
    }
  });

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={submit} noValidate aria-labelledby="lg-t">
        <Logo />
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <h1 id="lg-t">Вход</h1>
          <span className="stamp" aria-hidden="true" style={{ fontSize: 12, transform: 'rotate(-3deg)' }}>Книга платежей</span>
        </div>
        {section && !params.get('state') && <p className="note">Войдите, чтобы открыть раздел «{section}».</p>}
        {params.get('state') === 'loggedout' && <p className="note" role="status">Вы вышли из панели.</p>}
        {error && <p className="form-error" role="alert">{error}</p>}
        <TextInput
          label="Логин"
          autoComplete="username"
          autoCapitalize="off"
          spellCheck={false}
          classNames={{ input: 'mono' }}
          error={errors.login?.message}
          {...register('login', { validate: (v) => !!v.trim() || 'Введите логин.' })}
        />
        <PasswordInput label="Пароль" autoComplete="current-password" error={errors.password?.message} {...register('password', { required: 'Введите пароль.' })} />
        <Button type="submit" variant="filled" size="md" loading={login.isPending}>Войти</Button>
        <p className="small muted">Нет учётной записи? Её создаёт администратор вашей команды.</p>
      </form>
    </main>
  );
}
