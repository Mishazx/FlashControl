import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, apiRequest } from '../api';
import { useAuth } from '../AuthContext';
import { Shell } from '../layout/Shell';
import { PanelTable, Pagination } from '../components/Table';
import { Loading, ErrorPanel } from '../components/Status';
import { formatDate, IdentityBadge, DecisionConfidence } from '../components/Cells';
import type { IdentityAlert, PaginatedResponse } from '../types';

export function AlertsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<PaginatedResponse<IdentityAlert> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<PaginatedResponse<IdentityAlert>>('/identity-alerts', { limit: 25, offset });
      setData(d);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [offset]);

  useEffect(() => { load(); }, [load]);

  const rows = data?.items.map((item) => (
    <tr key={item.event_id} className="clickable" onClick={() => navigate(`/events/${encodeURIComponent(item.event_id)}`)}>
      <td><IdentityBadge value={item.result} /></td>
      <td>{formatDate(item.observed_at_utc)}</td>
      <td>{item.hostname}</td>
      <td>{(item.reasons || []).join(', ')}</td>
      <td><DecisionConfidence result={item.result} confidence={item.confidence} /></td>
      <td className="mono">{item.candidate_physical_device_id}</td>
    </tr>
  ));

  return (
    <Shell eyebrow="IDENTITY ENGINE" title="Предупреждения" onRefresh={load}>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <>
          <PanelTable
            headers={['Тип', 'Время', 'Компьютер', 'Основания', { label: 'Confidence', title: 'Насколько система уверена в решении' }, 'Кандидат']}
            rows={rows}
            emptyText="Коллизий и подозрений на клон нет"
          />
          <Pagination total={data.total} offset={data.offset} limit={data.limit} onChange={setOffset} />
        </>
      )}
    </Shell>
  );
}
