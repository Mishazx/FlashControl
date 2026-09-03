import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, apiRequest } from '../api';
import { useAuth } from '../AuthContext';
import { Shell } from '../layout/Shell';
import { Drawer } from '../components/Drawer';
import { PanelTable, Pagination } from '../components/Table';
import { Loading, ErrorPanel } from '../components/Status';
import { formatDate, ShortHash, ConfidenceBadge, DetailItem } from '../components/Cells';
import { translate, deviceStatusLabels, confidenceLabels, identityConfidenceHints } from '../labels';
import type { Device, PaginatedResponse } from '../types';

export function DevicesPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [data, setData] = useState<PaginatedResponse<Device> | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [offset, setOffset] = useState(0);
  const [hash, setHash] = useState('');
  const [status, setStatus] = useState('');
  const [drawerId, setDrawerId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const d = await api<PaginatedResponse<Device>>('/devices', { limit: 25, offset, hardware_hash: hash || undefined, status: status || undefined });
      setData(d);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [offset, hash, status]);

  useEffect(() => { load(); }, [load]);

  const applyFilter = () => { setOffset(0); load(); };

  const rows = data?.items.map((item) => (
    <tr key={item.id} className="clickable" onClick={() => setDrawerId(item.id)}>
      <td>
        <span className="primary">{[item.vendor, item.product].filter(Boolean).join(' ') || 'Неизвестное устройство'}</span>
        <span className="secondary mono">{item.id}</span>
      </td>
      <td>{item.vid || item.pid ? `${item.vid}:${item.pid}` : '—'}</td>
      <td className="mono">{item.storage_serial}</td>
      <td><ShortHash value={item.hardware_stable_sha256} /></td>
      <td><ConfidenceBadge level={item.identity_confidence} /></td>
      <td>{formatDate(item.last_seen_at)}</td>
    </tr>
  ));

  const handleDelete = async () => {
    if (!drawerId) return;
    if (!window.confirm('Удалить USB-устройство и все связанные с ним события?')) return;
    try {
      await apiRequest(`/devices/${drawerId}`, { method: 'DELETE' });
      setDrawerId(null);
      load();
    } catch { /* noop */ }
  };

  return (
    <Shell eyebrow="ИНВЕНТАРИЗАЦИЯ" title="USB-устройства" onRefresh={load}>
      <div className="toolbar">
        <input className="field search" placeholder="Полный hardware hash" value={hash} onChange={(e) => setHash(e.target.value)} />
        <select className="field" value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">Все статусы</option>
          <option value="provisional">{translate('provisional', deviceStatusLabels)}</option>
        </select>
        <button className="button" onClick={applyFilter}>Применить</button>
      </div>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <>
          <PanelTable
            headers={['Устройство', 'VID:PID', 'Storage serial', 'Hardware hash', { label: 'Confidence', title: identityConfidenceHints.high }, 'Последнее наблюдение']}
            rows={rows}
          />
          <Pagination total={data.total} offset={data.offset} limit={data.limit} onChange={setOffset} />
        </>
      )}
      <DeviceDrawer id={drawerId} onClose={() => setDrawerId(null)} onDelete={user?.role === 'admin' ? handleDelete : undefined} />
    </Shell>
  );
}

function DeviceDrawer({ id, onClose, onDelete }: { id: string | null; onClose: () => void; onDelete?: () => void }) {
  const [device, setDevice] = useState<Device | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!id) { setDevice(null); return; }
    setLoading(true);
    api<Device>(`/devices/${id}`).then(setDevice).catch(() => setDevice(null)).finally(() => setLoading(false));
  }, [id]);

  const title = device ? [device.vendor, device.product].filter(Boolean).join(' ') || 'Неизвестное устройство' : 'Загрузка…';

  return (
    <Drawer open={!!id} eyebrow="USB-УСТРОЙСТВО" title={title} onClose={onClose} onDelete={onDelete} deleteLabel="Удалить">
      {loading && <div className="loading"><div className="spinner" /></div>}
      {device && (
        <>
          <div className="detail-grid">
            <DetailItem label="Physical Device ID" value={device.id} wide mono />
            <DetailItem label="Статус" value={translate(device.status, deviceStatusLabels)} />
            <DetailItem label="Confidence" value={translate(device.identity_confidence, confidenceLabels)} title={identityConfidenceHints[device.identity_confidence || '']} />
            <DetailItem label="VID:PID" value={device.vid || device.pid ? `${device.vid}:${device.pid}` : '—'} />
            <DetailItem label="Storage serial" value={device.storage_serial} mono />
            <DetailItem label="Hardware hash" value={device.hardware_stable_sha256} wide mono />
            <div className="detail-item wide">
              <label>Использовалась на ПК</label>
              <div>
                {device.used_on_computers?.map((c) => (
                  <span key={c.id} className="badge info">{c.hostname}</span>
                )) || '—'}
              </div>
            </div>
            <DetailItem label="SID пользователей" value={(device.seen_user_sids || []).join(', ')} wide mono />
          </div>
          <h3 className="section-title">MEDIA STATES ({device.media_states?.length || 0})</h3>
          <div className="detail-grid">
            {device.media_states?.map((x, i) => (
              <div key={i} className="detail-item wide">
                <label>MEDIA STATE · {formatDate(x.last_seen_at)}</label>
                <div className="mono">
                  identity {x.media_identity_sha256}<br />state {x.media_state_sha256}
                </div>
              </div>
            )) || <div className="empty">Нет данных</div>}
          </div>
          <h3 className="section-title">ИСХОДНЫЕ ПРИЗНАКИ</h3>
          <pre className="json">{JSON.stringify(device.representative_device, null, 2)}</pre>
        </>
      )}
    </Drawer>
  );
}
