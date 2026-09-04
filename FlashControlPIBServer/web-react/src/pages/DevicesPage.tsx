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
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [comparedDevices, setComparedDevices] = useState<Device[] | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

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

  useEffect(() => {
    const visibleIds = new Set(data?.items.map((item) => item.id) || []);
    setSelectedIds((ids) => ids.filter((id) => !visibleIds.size || visibleIds.has(id)));
  }, [data]);

  const applyFilter = () => { setOffset(0); load(); };

  const toggleSelection = (id: string) => {
    setSelectedIds((ids) => ids.includes(id) ? ids.filter((value) => value !== id) : [...ids, id]);
  };

  const compareSelected = async () => {
    if (selectedIds.length < 2) return;
    setCompareLoading(true);
    try {
      const devices = await Promise.all(selectedIds.map((id) => api<Device>(`/devices/${id}`)));
      setComparedDevices(devices);
    } finally {
      setCompareLoading(false);
    }
  };

  const rows = data?.items.map((item) => (
    <tr key={item.id} className="clickable" onClick={() => setDrawerId(item.id)}>
      <td className="selection-cell" onClick={(event) => event.stopPropagation()}>
        <input
          aria-label={`Выбрать ${[item.vendor, item.product].filter(Boolean).join(' ') || item.id} для сравнения`}
          type="checkbox"
          checked={selectedIds.includes(item.id)}
          onChange={() => toggleSelection(item.id)}
        />
      </td>
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
        <button className="button compare-button" disabled={selectedIds.length < 2 || compareLoading} onClick={compareSelected}>
          {compareLoading ? 'Загрузка…' : `Сравнить (${selectedIds.length})`}
        </button>
        {selectedIds.length > 0 && <button className="button ghost" onClick={() => setSelectedIds([])}>Снять выбор</button>}
      </div>
      {loading && <Loading />}
      {error && <ErrorPanel message={error} />}
      {data && !loading && (
        <>
          <PanelTable
            headers={['', 'Устройство', 'VID:PID', 'Storage serial', 'Hardware hash', { label: 'Confidence', title: identityConfidenceHints.high }, 'Последнее наблюдение']}
            rows={rows}
          />
          <Pagination total={data.total} offset={data.offset} limit={data.limit} onChange={setOffset} />
        </>
      )}
      {comparedDevices && <DeviceComparison devices={comparedDevices} onClose={() => setComparedDevices(null)} />}
      <DeviceDrawer id={drawerId} onClose={() => setDrawerId(null)} onDelete={user?.role === 'admin' ? handleDelete : undefined} />
    </Shell>
  );
}

function DeviceComparison({ devices, onClose }: { devices: Device[]; onClose: () => void }) {
  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [onClose]);

  const deviceName = (device: Device) => [device.vendor, device.product].filter(Boolean).join(' ') || 'Неизвестное устройство';
  const list = (items: string[] | undefined) => items?.join(', ') || '—';
  const rows: { label: string; values: string[]; mono?: boolean }[] = [
    { label: 'Производитель и модель', values: devices.map(deviceName) },
    { label: 'VID:PID', values: devices.map((d) => d.vid || d.pid ? `${d.vid || '—'}:${d.pid || '—'}` : '—'), mono: true },
    { label: 'Серийный номер накопителя', values: devices.map((d) => d.storage_serial || '—'), mono: true },
    { label: 'Аппаратный хеш', values: devices.map((d) => d.hardware_stable_sha256 || '—'), mono: true },
    { label: 'Статус', values: devices.map((d) => translate(d.status, deviceStatusLabels)) },
    { label: 'Уверенность идентификации', values: devices.map((d) => translate(d.identity_confidence, confidenceLabels)) },
    { label: 'Впервые замечена', values: devices.map((d) => formatDate(d.first_seen_at)) },
    { label: 'Последнее наблюдение', values: devices.map((d) => formatDate(d.last_seen_at)) },
    { label: 'Использовалась на ПК', values: devices.map((d) => list(d.used_on_computers?.map((computer) => computer.hostname))) },
    { label: 'Пользователи', values: devices.map((d) => list(d.seen_user_sids)) },
    { label: 'Состояний носителя', values: devices.map((d) => String(d.media_states?.length || 0)) },
    { label: 'Наблюдений', values: devices.map((d) => String(d.recent_observations?.length || 0)) },
  ];

  return (
    <div className="comparison-backdrop" onMouseDown={onClose}>
      <section className="comparison panel" role="dialog" aria-modal="true" aria-label="Сравнение USB-устройств" onMouseDown={(event) => event.stopPropagation()}>
        <div className="panel-head">
          <div>
            <h2>Сравнение устройств</h2>
            <p>Подсвечены только параметры, в которых выбранные флешки отличаются.</p>
          </div>
          <button className="button ghost push" onClick={onClose}>Закрыть</button>
        </div>
        <div className="table-wrap comparison-body">
          <table className="comparison-table">
            <thead><tr><th>Параметр</th>{devices.map((device) => <th key={device.id}>{deviceName(device)}<span className="secondary mono">{device.id}</span></th>)}</tr></thead>
            <tbody>{rows.map((row) => {
              const different = new Set(row.values).size > 1;
              return <tr key={row.label} className={different ? 'different' : 'matching'}>
                <td className="comparison-label">{row.label}</td>
                {row.values.map((value, index) => <td key={devices[index].id} className={row.mono ? 'mono' : ''}>{value}</td>)}
              </tr>;
            })}</tbody>
          </table>
        </div>
      </section>
    </div>
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
