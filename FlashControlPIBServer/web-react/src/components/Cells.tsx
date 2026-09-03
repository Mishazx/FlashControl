import { translate, identityResultLabels, confidenceLabels, identityConfidenceHints, decisionConfidenceHints } from '../labels';

export function formatDate(value?: string | null): string {
  if (!value) return '—';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value) : d.toLocaleString('ru-RU', { hour12: false });
}

export function ShortHash({ value }: { value?: string | null }) {
  if (!value) return <>—</>;
  return (
    <span className="mono hash" title={value}>
      {value.slice(0, 12)}…
    </span>
  );
}

export function IdentityBadge({ value }: { value?: string | null }) {
  const kind =
    value === 'SAME'
      ? 'same'
      : ['SERIAL_COLLISION', 'CLONE_SUSPECTED'].includes(value || '')
        ? 'alert'
        : value === 'LIKELY_SAME'
          ? 'info'
          : 'warning';
  return <span className={`badge ${kind}`}>{translate(value, identityResultLabels)}</span>;
}

export function ConfidenceBadge({ level }: { level?: string | null }) {
  const kind = level === 'high' ? 'same' : level === 'likely' ? 'info' : 'warning';
  const hint = identityConfidenceHints[level || ''] || identityConfidenceHints.unknown;
  return (
    <span className={`badge ${kind} hint`} title={hint}>
      {translate(level, confidenceLabels)}
    </span>
  );
}

export function DecisionConfidence({ result, confidence }: { result?: string; confidence?: number | null }) {
  const percent = confidence != null ? `${Math.round(confidence * 100)}%` : '—';
  const hint = decisionConfidenceHints[result || ''] || 'Насколько система уверена в решении.';
  return (
    <span className="hint" title={hint}>
      {percent}
    </span>
  );
}

export function DetailItem({
  label,
  value,
  wide,
  mono,
  title,
}: {
  label: string;
  value: React.ReactNode;
  wide?: boolean;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className={`detail-item${wide ? ' wide' : ''}`}>
      <label className={title ? 'hint' : ''} title={title}>
        {label}
      </label>
      <div className={mono ? 'mono' : ''}>{value || '—'}</div>
    </div>
  );
}
