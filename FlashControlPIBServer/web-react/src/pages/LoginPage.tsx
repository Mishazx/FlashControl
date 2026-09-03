import { useState } from 'react';

export function LoginPage() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const response = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        const messages: Record<number, string> = {
          403: 'Нет доступа: учётка не в нужной группе Active Directory.',
          429: 'Слишком много попыток. Повторите позднее.',
          503: 'Каталог Active Directory недоступен.',
        };
        throw new Error(messages[response.status] || payload.detail || 'Неверное имя пользователя или пароль');
      }
      window.location.replace('/');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      <main className="login-card">
        <div className="login-brand">
          <span className="brand-mark">FC</span>
          <div>
            <strong>FlashControl</strong>
            <small>SECURITY CONSOLE</small>
          </div>
        </div>
        <div className="login-copy">
          <p className="eyebrow">DIRECTORY AUTHENTICATION</p>
          <h1>Вход в систему аудита</h1>
          <p>Войдите доменной учёткой Active Directory. В разработке также принимается локальная учётка.</p>
        </div>
        <form onSubmit={handleSubmit}>
          <label>
            Имя пользователя
            <input className="field" autoComplete="username" required autoFocus maxLength={128} value={username} onChange={(e) => setUsername(e.target.value)} />
          </label>
          <label>
            Пароль
            <input className="field" type="password" autoComplete="current-password" required maxLength={1024} value={password} onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <p className="login-error" role="alert">{error}</p>}
          <button className="button login-submit" type="submit" disabled={loading}>Войти</button>
        </form>
        <p className="login-note">В production вход идёт через Active Directory: доменный логин, проверка группы доступа и роль из групп AD.</p>
      </main>
    </div>
  );
}
