import type { ReactNode } from 'react';
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from './context';

export function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) {
    return (
      <div className="login-page" aria-busy="true">
        <span className="sr-only">Загружаем панель</span>
      </div>
    );
  }
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  return <Outlet />;
}

export function RequireAdmin({ children, back = '/' }: { children: ReactNode; back?: string }) {
  const { isAdmin } = useAuth();
  if (isAdmin) return <>{children}</>;
  return (
    <div className="denied">
      <h1>Раздел доступен только администратору</h1>
      <p className="muted">Этим разделом управляет администратор. Если вам нужен доступ, напишите ему.</p>
      <p>
        <Link to={back}>Вернуться к сводке</Link>
      </p>
    </div>
  );
}
