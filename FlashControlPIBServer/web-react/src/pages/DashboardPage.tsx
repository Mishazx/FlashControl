import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { Shell } from '../layout/Shell';
import { Loading, ErrorPanel } from '../components/Status';
import type { DashboardStats } from '../types';

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setStats(await api<DashboardStats>('/dashboard'));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Shell eyebrow="ЦЕНТР МОНИТОРИНГА" title="Обзор" onRefresh={load}>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {stats && !loading && (
        <>
          <div className="metric-grid">
            <Metric label="Всего компьютеров" value={stats.computers} />
            <Metric label="Сейчас онлайн" value={stats.agents_online} />
            <Metric label="Всего событий" value={stats.observations} />
            <Metric label="Требуют внимания" value={stats.identity_alerts} alert={stats.identity_alerts > 0} />
          </div>
        </>
      )}
    </Shell>
  );
}

function Metric({ label, value, alert }: { label: string; value: string | number; alert?: boolean }) {
  return (
    <article className={`metric${alert ? ' alert' : ''}`}>
      <p>{label}</p>
      <strong>{value}</strong>
    </article>
  );
}
