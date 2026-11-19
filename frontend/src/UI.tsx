import { useLayoutEffect, useId, useRef, type ComponentProps, type ReactNode } from 'react';
import { Icon } from './Icon';

export function Button({ variant, className = '', ...props }: ComponentProps<'button'> & {
  variant?: 'secondary' | 'danger';
}) {
  return <button {...props} className={`${variant ?? ''} ${className}`.trim()} />;
}

export function DataRow({ className = '', ...props }: ComponentProps<'button'>) {
  return <button {...props} type="button" className={`request-item ${className}`.trim()} />;
}

export function Chip({ tone = '', children }: { tone?: string; children: ReactNode }) {
  return <span className={`badge ${tone}`.trim()}>{children}</span>;
}

const roles = {
  administrator: { label: 'Administrator', icon: 'shield' },
  branch_manager: { label: 'Branch Manager', icon: 'branch' },
  technician: { label: 'Technician', icon: 'tool' },
} as const;

export function RoleBadge({ role }: { role: string }) {
  const info = roles[role as keyof typeof roles];
  return <Chip tone={`role-badge role-${role}`}>
    {info && <Icon name={info.icon} size={14} />}{info?.label ?? role}
  </Chip>;
}

export function PageHeader({ id, title, description, children }: {
  id?: string; title: string; description: string; children?: ReactNode;
}) {
  return <header className="section-heading">
    <div><h1 id={id}>{title}</h1><p className="muted">{description}</p></div>
    {children && <div className="actions">{children}</div>}
  </header>;
}

export function EmptyState({ icon, title, children }: {
  icon: ComponentProps<typeof Icon>['name']; title: string; children?: ReactNode;
}) {
  return <div className="empty-state">
    <span className="icon-tile"><Icon name={icon} size={18} /></span>
    <div><strong>{title}</strong>{children && <div>{children}</div>}</div>
  </div>;
}

export function Skeleton({ label }: { label: string }) {
  return <div className="skeleton-state" role="status"><span>{label}</span>
    <div aria-hidden="true" /><div aria-hidden="true" />
  </div>;
}

function useModalDialog() {
  const ref = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const dialog = ref.current!;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    return () => {
      dialog.close();
      trigger?.focus();
    };
  }, []);
  return ref;
}

export function ConfirmDialog({ title, description, confirmLabel, onCancel, onConfirm }: {
  title: string; description: string; confirmLabel: string; onCancel: () => void; onConfirm: () => void;
}) {
  const ref = useModalDialog();
  const heading = useId();
  const message = useId();
  return <dialog ref={ref} className="card confirm-dialog" aria-labelledby={heading} aria-describedby={message}
    onCancel={event => { event.preventDefault(); onCancel(); }}>
    <h2 id={heading}>{title}</h2>
    <p id={message} className="muted">{description}</p>
    <div className="actions confirm-actions">
      <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
      <Button type="button" variant="danger" onClick={onConfirm}>{confirmLabel}</Button>
    </div>
  </dialog>;
}

export function Drawer({ title, onClose, busy, children }: {
  title: string; onClose: () => void; busy: boolean; children: ReactNode;
}) {
  const ref = useModalDialog();
  const heading = useId();
  return <dialog ref={ref} className="drawer" aria-labelledby={heading} onCancel={event => {
    event.preventDefault();
    if (!busy) onClose();
  }}>
    <header className="drawer-header"><h2 id={heading}>{title}</h2>
      <Button variant="secondary" type="button" className="icon-button" aria-label="Close dialog" disabled={busy} onClick={onClose}>
        <Icon name="close" size={18} />
      </Button>
    </header>
    <div className="drawer-body" aria-busy={busy}>{children}</div>
  </dialog>;
}
