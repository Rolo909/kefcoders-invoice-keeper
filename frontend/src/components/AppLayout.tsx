import { Button, Menu } from '@mantine/core';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/context';
import { Bell } from './Bell';
import { useDialogs } from './dialogs/context';
import { Logo } from './Logo';

const MAIN = [
  { to: '/', label: 'Сводка', end: true },
  { to: '/occurrences', label: 'Периоды' },
  { to: '/recurring-payments', label: 'Платежи' },
  { to: '/calendar', label: 'Календарь' },
  { to: '/summary', label: 'Итоги' },
];
const ADMIN = [
  { to: '/users', label: 'Пользователи' },
  { to: '/audit', label: 'Журнал' },
];

export function AppLayout() {
  const { user, isAdmin } = useAuth();
  const { open } = useDialogs();
  const location = useLocation();
  const moreItems = [MAIN[4], ...(isAdmin ? ADMIN : []), { to: '/settings', label: 'Профиль' }];
  const moreActive = moreItems.some((i) => location.pathname.startsWith(i.to));
  const navClass = ({ isActive }: { isActive: boolean }) => (isActive ? 'active' : undefined);

  return (
    <>
      <a className="skip" href="#main">Перейти к содержимому</a>
      <header className="mast">
        <div className="mast-row">
          <Link className="brand" to="/"><Logo /></Link>
          <Bell />
          <NavLink className={({ isActive }) => `who${isActive ? ' active' : ''}`} to="/settings" aria-label={`${user?.full_name ?? user?.login}, профиль`}>
            <b>{user?.full_name ?? user?.login}</b>
          </NavLink>
          {isAdmin && <Button variant="filled" onClick={() => open({ type: 'newPayment' })}>Новый платёж</Button>}
        </div>
        <nav className="tabs" aria-label="Разделы">
          {MAIN.map((i) => <NavLink key={i.to} to={i.to} end={i.end} className={navClass}>{i.label}</NavLink>)}
          {isAdmin && <span className="gap" aria-hidden="true" />}
          {isAdmin && ADMIN.map((i) => <NavLink key={i.to} to={i.to} className={navClass}>{i.label}</NavLink>)}
        </nav>
      </header>

      <main id="main" className="page" tabIndex={-1}>
        <Outlet />
      </main>

      <nav className="bottom-nav" aria-label="Разделы">
        {MAIN.slice(0, 4).map((i) => <NavLink key={i.to} to={i.to} end={i.end} className={navClass}>{i.label}</NavLink>)}
        <Menu position="top-end" zIndex={450} width={200}>
          <Menu.Target>
            <button type="button" className={moreActive ? 'active' : undefined}>Ещё</button>
          </Menu.Target>
          <Menu.Dropdown>
            {moreItems.map((i) => (
              <Menu.Item key={i.to} component={NavLink} to={i.to}>{i.label}</Menu.Item>
            ))}
          </Menu.Dropdown>
        </Menu>
      </nav>
    </>
  );
}
