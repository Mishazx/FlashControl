import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { api, apiRequest } from '../api';
import { useAuth } from '../AuthContext';
import { Shell } from '../layout/Shell';
import { Drawer } from '../components/Drawer';
import { PanelTable, Pagination } from '../components/Table';
import { Loading, ErrorPanel } from '../components/Status';
import { formatDate, ShortHash, IdentityBadge, DecisionConfidence, DetailItem } from '../components/Cells';
import { translate, identityResultLabels, eventTypeLabels, decisionConfidenceHints } from '../labels';
import type { Observation, PaginatedResponse } from '../types';

const DECISIONS = ['SAME', 'LIKELY_SAME', 'UNKNOWN', 'SERIAL_COLLISION', 'CLONE_SUSPECTED', 'DIFFERENT'];

export function EventsPage() {
  const { eventId } = useParams();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<PaginatedResponse<Observation> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [decision, setDecision] = useState('');
  const [eventType, setEventType] = useState('');
  const [drawerId, setDrawerId] = useState<string | null>(eventId || null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<PaginatedResponse<Observation>>('/observations', {
        limit: 25, offset, decision: decision || undefined, event_type: eventType || undefined,
      });
      setData(d);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [offset, decision, eventType]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (eventId) setDrawerId(eventId); }, [eventId]);

  const applyFilter = () => { setOffset(0); load(); };

  const rows = data?.items.map((item) => (
    <tr key={item.event_id} className="clickable" onClick={() => { setDrawerId(item.event_id); navigate(`/events/${encodeURIComponent(item.event_id)}`, { replace: true }); }}>
      <td>{formatDate(item.observed_at_utc)}</td>
      <td>
        <span className="primary">{item.hostname}</span>
        <span className="secondary">{item.user_sid}</span>
      </td>
      <td>{translate(item.event_type, eventTypeLabels)}</td>
      <td><IdentityBadge value={item.identity_decision?.result} /></td>
      <td><ShortHash value={item.hardware_stable_sha256} /></td>
      <td className="mono">{item.event_id}</td>
    </tr>
  ));

  const handleDelete = async () => {
    if (!drawerId) return;
    if (!window.confirm('Удалить событие наблюдения?')) return;
    try {
      await apiRequest(`/observations/${drawerId}`, { method: 'DELETE' });
      setDrawerId(null);
      navigate('/events', { replace: true });
      load();
    } catch { /* noop */ }
  };

  return (
    <Shell eyebrow="ЖУРНАЛ АУДИТА" title="События" onRefresh={load}>
      <div className="toolbar">
        <select className="field" value={decision} onChange={(e) => setDecision(e.target.value)}>
          <option value="">Все решения</option>
          {DECISIONS.map((x) => <option key={x} value={x}>{translate(x, identityResultLabels)}</option>)}
        </select>
        <select className="field" value={eventType} onChange={(e) => setEventType(e.target.value)}>
          <option value="">Все события</option>
          {['snapshot', 'connected', 'disconnected'].map((x) => <option key={x} value={x}>{translate(x, eventTypeLabels)}</option>)}
        </select>
        <button className="button" onClick={applyFilter}>Применить</button>
      </div>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <>
          <PanelTable
            headers={['Время', 'Компьютер / SID', 'Событие', 'Решение', 'Hardware hash', 'Event ID']}
            rows={rows}
          />
          <Pagination total={data.total} offset={data.offset} limit={data.limit} onChange={setOffset} />
        </>
      )}
      <EventDrawer id={drawerId} onClose={() => { setDrawerId(null); navigate('/events', { replace: true }); }} onDelete={user?.role === 'admin' || user?.role === 'security' ? handleDelete : undefined} />
    </Shell>
  );
}

function EventDrawer({ id, onClose, onDelete }: { id: string | null; onClose: () => void; onDelete?: () => void }) {
  const [obs, setObs] = useState<Observation | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!id) { setObs(null); return; }
    setLoading(true);
    api<Observation>(`/observations/${id}`).then(setObs).catch(() => setObs(null)).finally(() => setLoading(false));
  }, [id]);

  const decision = obs?.identity_decision;

  return (
    <Drawer open={!!id} eyebrow="OBSERVATION" title={obs?.hostname || 'Загрузка…'} onClose={onClose} onDelete={onDelete} deleteLabel="Удалить">
      {loading && <div className="loading"><div className="spinner" /></div>}
      {obs && (
        <>
          <div className="detail-grid">
            <DetailItem label="Event ID" value={obs.event_id} wide mono />
            <DetailItem label="Время" value={formatDate(obs.observed_at_utc)} />
            <DetailItem label="Тип" value={translate(obs.event_type, eventTypeLabels)} />
            <DetailItem label="Решение" value={translate(decision?.result, identityResultLabels)} />
            <DetailItem
              label="Confidence"
              value={decision?.confidence != null ? `${Math.round(decision.confidence * 100)}%` : '—'}
              title={decisionConfidenceHints[decision?.result || '']}
            />
            <DetailItem label="Physical Device ID" value={obs.physical_device_id} wide mono />
            <DetailItem label="Основания" value={(decision?.reasons || []).join(', ')} wide />
          </div>
          <h3 className="section-title">RAW OBSERVATION</h3>
          <pre className="json">{JSON.stringify(obs.raw_observation, null, 2)}</pre>
        </>
      )}
    </Drawer>
  );
}
