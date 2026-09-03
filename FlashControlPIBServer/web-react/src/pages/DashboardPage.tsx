import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api } from '../api';
import { Shell } from '../layout/Shell';
import { Loading, ErrorPanel } from '../components/Status';
import { IdentityBadge } from '../components/Cells';
import { formatDate } from '../components/Cells';
import type { DashboardStats, IdentityAlert, Observation } from '../types';

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [alerts, setAlerts] = useState<IdentityAlert[]>([]);
  const [events, setEvents] = useState<Observation[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, a, e] = await Promise.all([
        api<DashboardStats>('/dashboard'),
        api<{ items: IdentityAlert[] }>('/identity-alerts', { limit: 5 }),
        api<{ items: Observation[] }>('/observations', { limit: 6 }),
      ]);
      setStats(s);
      setAlerts(a.items);
      setEvents(e.items);
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
            <Metric label="Компьютеры" value={stats.computers} />
            <Metric label="Физические устройства" value={stats.physical_devices} />
            <Metric label="Наблюдения" value={stats.observations} />
            <Metric label="Media states" value={stats.media_states} />
            <Metric label="Компьютеры онлайн" value={`${stats.agents_online}/${stats.computers}`} />
            <Metric label="Очередь не пуста" value={stats.agents_with_backlog} alert={!!stats.agents_with_backlog} />
            <Metric label="Требуют внимания" value={stats.identity_alerts} alert />
          </div>

          <div className="split-grid">
            <div className="panel">
              <div className="panel-head">
                <div>
                  <h2>Последние события</h2>
                  <p>Свежие наблюдения агентов</p>
                </div>
              </div>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Время</th>
                      <th>Источник</th>
                      <th>Решение</th>
                    </tr>
                  </thead>
                  <tbody>
                    {events.length === 0 ? (
                      <tr><td colSpan={3} className="empty">Событий пока нет</td></tr>
                    ) : (
                      events.map((item) => (
                        <tr key={item.event_id} className="clickable" onClick={() => navigate(`/events/${encodeURIComponent(item.event_id)}`)}>
                          <td>{formatDate(item.observed_at_utc)}</td>
                          <td>
                            <span className="primary">{item.hostname}</span>
                            <span className="secondary mono">{item.event_id}</span>
                          </td>
                          <td><IdentityBadge value={item.identity_decision?.result} /></td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="panel">
              <div className="panel-head">
                <div>
                  <h2>Identity Engine</h2>
                  <p>Распределение решений</p>
                </div>
              </div>
              <div className="bar-list">
                {Object.entries(stats.identity_results || {}).length === 0 ? (
                  <div className="empty">Решений пока нет</div>
                ) : (() => {
                  const results = Object.entries(stats.identity_results || {});
                  const max = Math.max(1, ...results.map(([, c]) => c));
                  return results.map(([name, count]) => (
                    <div key={name} className="bar-row">
                      <span><IdentityBadge value={name} /></span>
                      <div className="bar-track">
                        <div
                          className={`bar-fill${['SERIAL_COLLISION', 'CLONE_SUSPECTED'].includes(name) ? ' warning' : ''}`}
                          style={{ width: `${Math.max(3, (count / max) * 100)}%` }}
                        />
                      </div>
                      <strong>{count}</strong>
                    </div>
                  ));
                })()}
              </div>
            </div>
          </div>

          <div className="panel" style={{ marginTop: 18 }}>
            <div className="panel-head">
              <div>
                <h2>Активные предупреждения</h2>
                <p>Коллизии serial и подозрения на клон</p>
              </div>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Тип</th>
                    <th>Компьютер</th>
                    <th>Время</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.length === 0 ? (
                    <tr><td colSpan={3} className="empty">Предупреждений нет</td></tr>
                  ) : (
                    alerts.map((item) => (
                      <tr key={item.event_id} className="clickable" onClick={() => navigate(`/events/${encodeURIComponent(item.event_id)}`)}>
                        <td><IdentityBadge value={item.result} /></td>
                        <td>{item.hostname}</td>
                        <td>{formatDate(item.observed_at_utc)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
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
