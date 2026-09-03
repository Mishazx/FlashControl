import type { ReactNode } from 'react';

interface PanelTableProps {
  headers: (string | { label: string; title?: string })[];
  rows: ReactNode;
  emptyText?: string;
}

export function PanelTable({ headers, rows, emptyText = 'Данных пока нет' }: PanelTableProps) {
  return (
    <div className="panel">
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              {headers.map((h, i) => {
                if (typeof h === 'object') {
                  return (
                    <th key={i} className={h.title ? 'hint' : ''} title={h.title}>
                      {h.label}
                    </th>
                  );
                }
                return <th key={i}>{h}</th>;
              })}
            </tr>
          </thead>
          <tbody>
            {rows || (
              <tr>
                <td colSpan={headers.length} className="empty">
                  {emptyText}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface PaginationProps {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
}

export function Pagination({ total, offset, limit, onChange }: PaginationProps) {
  const start = total ? offset + 1 : 0;
  const end = Math.min(offset + limit, total);
  return (
    <div className="pagination">
      <span>
        {start}–{end} из {total}
      </span>
      <div>
        <button
          type="button"
          className="button ghost"
          disabled={offset === 0}
          onClick={() => onChange(Math.max(0, offset - limit))}
        >
          Назад
        </button>{' '}
        <button
          type="button"
          className="button ghost"
          disabled={end >= total}
          onClick={() => onChange(offset + limit)}
        >
          Далее
        </button>
      </div>
    </div>
  );
}
