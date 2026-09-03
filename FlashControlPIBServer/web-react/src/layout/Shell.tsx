import { useState, useEffect, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { useTheme } from '../ThemeContext';

interface ShellProps {
  eyebrow: string;
  title: string;
  children: ReactNode;
  onRefresh?: () => void;
}

export function Shell({ eyebrow, title, children, onRefresh }: ShellProps) {
  const { user } = useAuth();
  const { pref, setPref } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [utc, setUtc] = useState('');
  const [serverOk, setServerOk] = useState<boolean | null>(null);
  const location = useLocation();

  useEffect(() => {
    const id = setInterval(() => setUtc(`UTC ${new Date().toISOString().slice(11, 19)}`), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    const check = async () => {
      try {
        const r = await fetch('/health/ready');
        setServerOk(r.ok);
      } catch {
        setServerOk(false);
      }
    };
    check();
    const id = setInterval(check, 30000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const handleLogout = async () => {
    const csrf = document.cookie
      .split('; ')
      .find((v) => v.startsWith('flashcontrol_csrf='));
    const token = csrf ? decodeURIComponent(csrf.split('=').slice(1).join('=')) : '';
    const r = await fetch('/api/v1/auth/logout', {
      method: 'POST',
      headers: { 'X-CSRF-Token': token, Accept: 'application/json' },
    });
    if (r.ok || r.status === 401) window.location.assign('/login');
  };

  const isActive = (path: string) => location.pathname === path;

  const navItems = [
    { to: '/', icon: '⌁', label: 'Обзор' },
    { to: '/devices', icon: '▣', label: 'USB-устройства' },
    { to: '/computers', icon: '▤', label: 'Компьютеры' },
    { to: '/events', icon: '≋', label: 'События' },
    { to: '/alerts', icon: '△', label: 'Предупреждения' },
    ...(user?.role === 'admin' || user?.role === 'security'
      ? [{ to: '/audit', icon: '◎', label: 'Журнал действий' }]
      : []),
    ...(user?.role === 'admin' ? [{ to: '/users', icon: '♙', label: 'Пользователи' }] : []),
  ];

  return (
    <div className="shell">
      <aside className={`sidebar${sidebarOpen ? ' open' : ''}`}>
        <Link className="brand" to="/" aria-label="FlashControl">
          <span className="brand-mark" aria-hidden="true">FC</span>
          <span><strong>FlashControl</strong><small>USB AUDIT</small></span>
        </Link>
        <nav className="nav" aria-label="Основная навигация">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={isActive(item.to) ? 'active' : ''}
              onClick={() => setSidebarOpen(false)}
            >
              <span>{item.icon}</span>{item.label}
            </Link>
          ))}
        </nav>
        <div className="sidebar-foot">
          <span className={`status-dot${serverOk === true ? ' ok' : serverOk === false ? ' error' : ''}`} />
          <span>
            <small>MAIN SERVER</small>
            <strong>{serverOk === null ? 'Проверка…' : serverOk ? 'Доступен' : 'Недоступен'}</strong>
          </span>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <button className="menu-button" onClick={() => setSidebarOpen(!sidebarOpen)} aria-label="Открыть меню">☰</button>
          <div>
            <p className="eyebrow">{eyebrow}</p>
            <h1>{title}</h1>
          </div>
          <div className="topbar-actions">
            <div className="theme-toggle">
              <button className={pref === 'auto' ? 'active' : ''} onClick={() => setPref('auto')} title="Авто (системная)">⚙</button>
              <button className={pref === 'dark' ? 'active' : ''} onClick={() => setPref('dark')} title="Тёмная тема">☾</button>
              <button className={pref === 'light' ? 'active' : ''} onClick={() => setPref('light')} title="Светлая тема">☀</button>
            </div>
            <span className="user-chip">{user ? `${user.username} · ${user.role}` : '…'}</span>
            <span className="utc-clock">{utc || 'UTC --:--:--'}</span>
            {onRefresh && <button className="button ghost" onClick={onRefresh}>Обновить</button>}
            <button className="button ghost" onClick={handleLogout}>Выйти</button>
          </div>
        </header>
        <section className="content" aria-live="polite">
          {children}
        </section>
      </main>
    </div>
  );
}
