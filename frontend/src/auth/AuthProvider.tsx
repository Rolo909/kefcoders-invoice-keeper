import { useEffect, useMemo, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { setUnauthorizedHandler } from '../api/client';
import { qk, useMe } from '../api/hooks';
import { todayIn } from '../lib/dates';
import { AuthContext, type AuthState } from './context';
import { onAuthChangedElsewhere } from './sync';

export function AuthProvider({ children }: { children: ReactNode }) {
  const me = useMe();
  const qc = useQueryClient();
  const navigate = useNavigate();

  useEffect(() => {
    setUnauthorizedHandler(() => {
      qc.removeQueries({ queryKey: qk.me });
      const next = window.location.pathname + window.location.search;
      navigate(`/login?next=${encodeURIComponent(next)}`, { replace: true });
    });
    return () => setUnauthorizedHandler(null);
  }, [qc, navigate]);

  // В другой вкладке вошли под другим пользователем или вышли — показываем актуальное состояние.
  useEffect(() => onAuthChangedElsewhere(() => window.location.reload()), []);

  const value = useMemo<AuthState>(() => {
    const data = me.isError ? undefined : me.data;
    return {
      me: data,
      user: data?.user,
      isAdmin: data?.user.role === 'admin',
      today: data?.server_today ?? todayIn(data?.timezone ?? 'Europe/Moscow'),
      loading: me.isPending,
    };
  }, [me.data, me.isError, me.isPending]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
