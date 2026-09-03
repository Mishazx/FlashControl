import { useCallback, useEffect, useState } from 'react';
import { api, apiRequest } from '../api';
import { Shell } from '../layout/Shell';
import { Drawer } from '../components/Drawer';
import { PanelTable } from '../components/Table';
import { Loading, ErrorPanel } from '../components/Status';
import { formatDate } from '../components/Cells';
import { roleLabel } from '../labels';
import type { User, PaginatedResponse } from '../types';

export function UsersPage() {
  const [data, setData] = useState<PaginatedResponse<User> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit' | null>(null);
  const [selectedUser, setSelectedUser] = useState<User | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<PaginatedResponse<User>>('/users', { q: query || undefined });
      setData(d);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [query]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.items.map((user) => (
    <tr key={user.id} className="clickable" onClick={() => { setSelectedUser(user); setDrawerMode('edit'); }}>
      <td>
        <span className="primary">{user.username}</span>
        <span className="secondary">{user.is_local ? 'Локальная учётная запись' : 'Учётная запись LDAP'}</span>
      </td>
      <td><span className="badge info">{roleLabel(user.role)}</span></td>
      <td><span className={`badge ${user.enabled ? 'same' : 'alert'}`}>{user.enabled ? 'Активен' : 'Отключён'}</span></td>
      <td>{user.active_sessions || '—'}</td>
      <td>{formatDate(user.last_login_at_utc)}</td>
      <td>{formatDate(user.created_at_utc)}</td>
    </tr>
  ));

  return (
    <Shell eyebrow="АДМИНИСТРИРОВАНИЕ" title="Пользователи" onRefresh={load}>
      <div className="toolbar">
        <input className="field search" placeholder="Поиск по логину" value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && load()} />
        <button className="button" onClick={() => load()}>Найти</button>
        <button className="button push-right" onClick={() => { setSelectedUser(null); setDrawerMode('create'); }}>Добавить пользователя</button>
      </div>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <PanelTable
          headers={['Пользователь', 'Роль', 'Статус', 'Сессии', 'Последний вход', 'Создан']}
          rows={rows}
          emptyText="Пользователи не найдены"
        />
      )}
      {drawerMode === 'create' && <UserCreateDrawer onClose={() => setDrawerMode(null)} onSaved={() => { setDrawerMode(null); load(); }} />}
      {drawerMode === 'edit' && selectedUser && <UserEditDrawer user={selectedUser} onClose={() => setDrawerMode(null)} onSaved={() => { setDrawerMode(null); load(); }} />}
    </Shell>
  );
}

function UserCreateDrawer({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [username, setUsername] = useState('');
  const [role, setRole] = useState('auditor');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await apiRequest('/users', { method: 'POST', body: { username, role, password } });
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Drawer open eyebrow="ПОЛЬЗОВАТЕЛИ" title="Новый пользователь" onClose={onClose}>
      <form className="user-form" onSubmit={handleSubmit}>
        <label>
          Логин
          <input className="field" name="username" required maxLength={128} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label>
          Роль
          <select className="field" name="role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="admin">{roleLabel('admin')}</option>
            <option value="security">{roleLabel('security')}</option>
            <option value="auditor">{roleLabel('auditor')}</option>
          </select>
        </label>
        <label className="wide">
          Пароль
          <input className="field" name="password" type="password" required minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
          <small>Не менее 12 символов</small>
        </label>
        {error && <p className="form-error">{error}</p>}
        <div className="drawer-actions wide">
          <button className="button" type="submit">Создать пользователя</button>
        </div>
      </form>
    </Drawer>
  );
}

function UserEditDrawer({ user, onClose, onSaved }: { user: User; onClose: () => void; onSaved: () => void }) {
  const [role, setRole] = useState(user.role);
  const [enabled, setEnabled] = useState(user.enabled);
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    const body: Record<string, unknown> = { role, enabled };
    if (password) body.password = password;
    try {
      await apiRequest(`/users/${user.id}`, { method: 'PATCH', body });
      onSaved();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <Drawer open eyebrow="ПОЛЬЗОВАТЕЛИ" title={user.username} onClose={onClose}>
      <form className="user-form" onSubmit={handleSubmit}>
        <label>
          Роль
          <select className="field" value={role} onChange={(e) => setRole(e.target.value as User['role'])}>
            <option value="admin">{roleLabel('admin')}</option>
            <option value="security">{roleLabel('security')}</option>
            <option value="auditor">{roleLabel('auditor')}</option>
          </select>
        </label>
        <label>
          Статус
          <select className="field" value={String(enabled)} onChange={(e) => setEnabled(e.target.value === 'true')}>
            <option value="true">Активен</option>
            <option value="false">Отключён</option>
          </select>
        </label>
        {user.is_local ? (
          <label className="wide">
            Новый пароль <span className="optional">(необязательно)</span>
            <input className="field" name="password" type="password" minLength={12} autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <small>После смены пароля все сессии пользователя будут завершены.</small>
          </label>
        ) : (
          <div className="form-note wide">Роль учётной записи LDAP обновляется при следующем входе согласно настройкам Active Directory.</div>
        )}
        {error && <p className="form-error">{error}</p>}
        <div className="drawer-actions wide">
          <button className="button" type="submit">Сохранить изменения</button>
        </div>
      </form>
    </Drawer>
  );
}
