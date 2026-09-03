import { useEffect, type ReactNode } from 'react';

interface DrawerProps {
  open: boolean;
  eyebrow: string;
  title: string;
  onClose: () => void;
  onDelete?: () => void;
  deleteLabel?: string;
  children: ReactNode;
}

export function Drawer({ open, eyebrow, title, onClose, onDelete, deleteLabel, children }: DrawerProps) {
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && open) onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [open, onClose]);

  return (
    <>
      <div className={`drawer-backdrop${open ? '' : ' hidden'}`} onClick={onClose} />
      <aside className={`drawer${open ? ' open' : ''}`} aria-label="Детальная информация" aria-hidden={!open}>
        <div className="drawer-head">
          <div className="drawer-heading">
            <p className="eyebrow">{eyebrow}</p>
            <h2>{title}</h2>
          </div>
          <div className="drawer-head-actions">
            {onDelete && (
              <button className="button danger ghost" type="button" onClick={onDelete}>
                {deleteLabel || 'Удалить'}
              </button>
            )}
            <button className="icon-button" aria-label="Закрыть" onClick={onClose}>×</button>
          </div>
        </div>
        <div className="drawer-body">{children}</div>
      </aside>
    </>
  );
}
