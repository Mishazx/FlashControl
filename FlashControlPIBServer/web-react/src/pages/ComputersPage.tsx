import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, apiRequest } from '../api';
import { useAuth } from '../AuthContext';
import { Shell } from '../layout/Shell';
import { Drawer } from '../components/Drawer';
import { PanelTable, Pagination } from '../components/Table';
import { Loading, ErrorPanel } from '../components/Status';
import { formatDate, IdentityBadge, DetailItem } from '../components/Cells';
import { translate, agentStatusLabels, routeLabels, eventTypeLabels } from '../labels';
import type { Computer, PaginatedResponse } from '../types';

export function ComputersPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<PaginatedResponse<Computer> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hostname, setHostname] = useState('');
  const [agentStatus, setAgentStatus] = useState('');
  const [drawerId, setDrawerId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<PaginatedResponse<Computer>>('/computers', {
        limit: 25, offset, hostname: hostname || undefined, agent_status: agentStatus || undefined,
      });
      setData(d);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [offset, hostname, agentStatus]);

  useEffect(() => { load(); }, [load]);

  const applyFilter = () => { setOffset(0); load(); };

  const rows = data?.items.map((item) => {
    const agent = item.agent;
    return (
      <tr key={item.id} className="clickable" onClick={() => setDrawerId(item.id)}>
        <td>
          <span className="primary">{item.hostname}</span>
          <span className="secondary mono">{item.id}</span>
        </td>
        <td>{item.domain}</td>
        <td>
          {agent ? (
            <span className={`badge ${agent.status === 'online' ? 'same' : 'alert'}`}>
              {translate(agent.status, agentStatusLabels)}
            </span>
          ) : (
            <span className="badge warning">НЕ УСТАНОВЛЕН</span>
          )}
        </td>
        <td>{agent?.queue_size ? <span className="badge warning">{agent.queue_size}</span> : agent ? '0' : '—'}</td>
        <td>{translate(agent?.selected_route, routeLabels)}</td>
        <td>{formatDate(agent?.last_seen_at_utc || item.last_seen_at)}</td>
      </tr>
    );
  });

  const handleDelete = async () => {
    if (!drawerId) return;
    if (!window.confirm('Удалить компьютер и все связанные с ним события?')) return;
    try {
      await apiRequest(`/computers/${drawerId}`, { method: 'DELETE' });
      setDrawerId(null);
      load();
    } catch { /* noop */ }
  };

  return (
    <Shell eyebrow="ИНФРАСТРУКТУРА" title="Компьютеры" onRefresh={load}>
      <div className="toolbar">
        <input className="field search" placeholder="Имя компьютера" value={hostname} onChange={(e) => setHostname(e.target.value)} />
        <select className="field" value={agentStatus} onChange={(e) => setAgentStatus(e.target.value)}>
          <option value="">Все состояния</option>
          <option value="online">{translate('online', agentStatusLabels)}</option>
          <option value="offline">{translate('offline', agentStatusLabels)}</option>
          <option value="missing">{translate('missing', agentStatusLabels)}</option>
        </select>
        <button className="button" onClick={applyFilter}>Применить</button>
      </div>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <>
          <PanelTable
            headers={['Компьютер', 'Домен', 'Статус', 'Очередь', 'Маршрут', 'Последняя связь']}
            rows={rows}
          />
          <Pagination total={data.total} offset={data.offset} limit={data.limit} onChange={setOffset} />
        </>
      )}
      <ComputerDrawer id={drawerId} onClose={() => setDrawerId(null)} onDelete={user?.role === 'admin' ? handleDelete : undefined} onEventClick={(eid) => navigate(`/events/${encodeURIComponent(eid)}`)} />
    </Shell>
  );
}

function ComputerDrawer({ id, onClose, onDelete, onEventClick }: { id: string | null; onClose: () => void; onDelete?: () => void; onEventClick: (id: string) => void }) {
  const [computer, setComputer] = useState<Computer | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!id) { setComputer(null); return; }
    setLoading(true);
    api<Computer>(`/computers/${id}`).then(setComputer).catch(() => setComputer(null)).finally(() => setLoading(false));
  }, [id]);

  return (
    <Drawer open={!!id} eyebrow="КОМПЬЮТЕР" title={computer?.hostname || 'Загрузка…'} onClose={onClose} onDelete={onDelete} deleteLabel="Удалить">
      {loading && <div className="loading"><div className="spinner" /></div>}
      {computer && (
        <>
          <div className="detail-grid">
            <DetailItem label="Computer ID" value={computer.id} wide mono />
            <DetailItem label="Домен" value={computer.domain} />
            <DetailItem label="Последнее наблюдение" value={formatDate(computer.last_seen_at)} />
            {computer.agent ? (
              <>
                <DetailItem label="Статус агента" value={translate(computer.agent.status, agentStatusLabels)} />
                <DetailItem label="Версия агента" value={computer.agent.agent_version} />
                <DetailItem label="Agent ID" value={computer.agent.id} wide mono />
                <DetailItem label="Размер очереди" value={computer.agent.queue_size} />
                <DetailItem label="Маршрут" value={translate(computer.agent.selected_route, routeLabels)} />
                <DetailItem label="Текущие IP" value={(computer.agent.current_ips || []).join(', ')} wide mono />
                <DetailItem label="Последний heartbeat" value={formatDate(computer.agent.last_seen_at_utc)} />
              </>
            ) : (
              <DetailItem label="Агент" value="Не зарегистрирован" wide />
            )}
          </div>
          <h3 className="section-title">ПОСЛЕДНИЕ СОБЫТИЯ</h3>
          <PanelTable
            headers={['Время', 'Тип', 'Решение']}
            rows={computer.recent_observations?.map((x) => (
              <tr key={x.event_id} className="clickable" onClick={() => onEventClick(x.event_id)}>
                <td>{formatDate(x.observed_at_utc)}</td>
                <td>{translate(x.event_type, eventTypeLabels)}</td>
                <td><IdentityBadge value={x.identity_decision?.result} /></td>
              </tr>
            ))}
          />
          <h3 className="section-title">HOST DATA</h3>
          <pre className="json">{JSON.stringify(computer.last_host, null, 2)}</pre>
        </>
      )}
    </Drawer>
  );
}
