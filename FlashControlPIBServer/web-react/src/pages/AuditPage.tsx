import { useCallback, useEffect, useState } from 'react';
import { api } from '../api';
import { Shell } from '../layout/Shell';
import { PanelTable, Pagination } from '../components/Table';
import { Loading, ErrorPanel } from '../components/Status';
import { formatDate } from '../components/Cells';
import { translate, auditResultLabels } from '../labels';
import type { AuditLogEntry, PaginatedResponse } from '../types';

export function AuditPage() {
  const [data, setData] = useState<PaginatedResponse<AuditLogEntry> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [success, setSuccess] = useState('');
  const [action, setAction] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<PaginatedResponse<AuditLogEntry>>('/audit-log', {
        limit: 25, offset, action: action || undefined, success: success || undefined,
      });
      setData(d);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [offset, success, action]);

  useEffect(() => { load(); }, [load]);

  const applyFilter = () => { setOffset(0); load(); };

  const rows = data?.items.map((item, i) => (
    <tr key={item.id || i}>
      <td>{formatDate(item.created_at_utc)}</td>
      <td>
        <span className="primary">{item.username}</span>
        <span className="secondary mono">{item.source_ip}</span>
      </td>
      <td>{item.action}</td>
      <td>
        <span className={`badge ${item.success ? 'same' : 'alert'}`}>
          {translate(String(item.success), auditResultLabels)}
        </span>
      </td>
      <td className="mono">{JSON.stringify(item.details)}</td>
    </tr>
  ));

  return (
    <Shell eyebrow="БЕЗОПАСНОСТЬ" title="Журнал действий" onRefresh={load}>
      <div className="toolbar">
        <select className="field" value={success} onChange={(e) => setSuccess(e.target.value)}>
          <option value="">Все результаты</option>
          <option value="true">Успешные</option>
          <option value="false">Неуспешные</option>
        </select>
        <input className="field search" placeholder="Действие, например auth.login" value={action} onChange={(e) => setAction(e.target.value)} />
        <button className="button" onClick={applyFilter}>Применить</button>
      </div>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <>
          <PanelTable
            headers={['Время', 'Пользователь / IP', 'Действие', 'Результат', 'Детали']}
            rows={rows}
            emptyText="Записей аудита нет"
          />
          <Pagination total={data.total} offset={data.offset} limit={data.limit} onChange={setOffset} />
        </>
      )}
    </Shell>
  );
}
