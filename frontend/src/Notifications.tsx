import { useEffect, useRef, useState } from 'react';
import { formatDateTime } from './format';
import { EmptyState, Skeleton } from './UI';
import { pollWhileVisible } from './liveUpdates';
import { Icon } from './Icon';

const categories = {
  approval: { label: 'Approvals', icon: 'shield' },
  update: { label: 'Updates', icon: 'requests' },
  completed: { label: 'Completed', icon: 'check' },
} as const;
type Category = keyof typeof categories;
type Filter = Category | '';

type Item = { id: string; request_id: string; title: string; action: string;
  created_at: string; read: boolean; category: Category };
type Inbox = { unread: number; items: Item[] };

const messages: Record<string, string> = {
  safety_flagged: 'Safety hazard reported — review immediately',
  intake_confirmed: 'Intake category or priority updated',
  submitted: 'New service request',
  priority_changed: 'Priority updated',
  work_order_assigned: 'Work assigned to you',
  work_reassigned: 'Work transferred to you',
  work_team_changed: 'Work order team updated',
  work_schedule_changed: 'Work schedule updated',
  work_started: 'Repair started',
  maintenance_logged: 'Maintenance update added',
  work_completed: 'Technician completed work',
  work_returned: 'Repair returned for follow-up',
  verified_and_closed: 'Repair verified and closed',
};

export function Notifications({ token, open, onToggle, onExpired, onOpen }: {
  open: boolean; onToggle: (open: boolean) => void;
  token: string; onExpired: () => void; onOpen: (requestId: string) => void;
}) {
  const [filter, setFilter] = useState<Filter>('');
  const [result, setResult] = useState<{ filter: Filter; inbox: Inbox } | null>(null);
  const [loadError, setLoadError] = useState('');
  const [actionError, setActionError] = useState('');
  const [busy, setBusy] = useState<'opening' | 'marking' | null>(null);
  const [version, setVersion] = useState(0);
  const trigger = useRef<HTMLButtonElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const activeFilter = open ? filter : '';

  useEffect(() => {
    if (open) closeButton.current?.focus({ preventScroll: true });
  }, [open]);

  useEffect(() => {
    const controller = new AbortController();
    const headers = { Authorization: `Bearer ${token}` };
    const query = activeFilter ? `?${new URLSearchParams({ category: activeFilter })}` : '';
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch(`/api/notifications${query}`, { headers, signal: controller.signal });
        if (controller.signal.aborted) return;
        if (response.status === 401) { onExpired(); return; }
        if (!response.ok) throw new Error();
        const inbox: Inbox = await response.json();
        if (!controller.signal.aborted) { setResult({ filter: activeFilter, inbox }); setLoadError(''); }
      } catch {
        if (!controller.signal.aborted) setLoadError('Unable to refresh notifications.');
      } finally { pending = false; }
    }
    void refresh();
    const stop = pollWhileVisible(refresh);
    return () => { controller.abort(); stop(); };
  }, [token, version, open, activeFilter]);

  function closePanel() {
    setActionError('');
    onToggle(false);
    trigger.current?.focus();
  }

  async function openItem(item: Item) {
    if (busy) return;
    setBusy('opening');
    setActionError('');
    try {
      const response = await fetch(`/api/notifications/${item.id}/read`, {
        method: 'PUT', headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 401) { onExpired(); return; }
      if (response.status === 404) {
        setActionError('This notification is no longer available.');
        setVersion(value => value + 1);
        return;
      }
      if (!response.ok) throw new Error();
      setVersion(value => value + 1);
      closePanel();
      onOpen(item.request_id);
    } catch {
      setActionError('Unable to open the notification. Try again.');
    } finally { setBusy(null); }
  }

  async function markAllRead() {
    if (busy || !result?.inbox.unread) return;
    setBusy('marking');
    setActionError('');
    try {
      const response = await fetch('/api/notifications/read', {
        method: 'PUT', headers: { Authorization: `Bearer ${token}` },
      });
      if (response.status === 401) { onExpired(); return; }
      if (!response.ok) throw new Error();
      setResult(current => current === result ? { ...result, inbox: {
        unread: 0, items: result.inbox.items.map(item => ({ ...item, read: true })),
      } } : current);
      setVersion(value => value + 1);
    } catch {
      setActionError('Unable to mark all notifications as read. Try again.');
    } finally { setBusy(null); }
  }

  const unread = result?.inbox.unread ?? 0;
  const items = result?.filter === activeFilter ? result.inbox.items : null;
  const buttonLabel = unread ? `Notifications (${unread} unread)` : 'Notifications';

  return <div onKeyDown={event => {
    if (event.key === 'Escape' && open) closePanel();
  }}>
    <button ref={trigger} type="button" className="header-control header-icon" aria-label={buttonLabel} title={buttonLabel}
      aria-expanded={open} aria-controls={open ? 'notification-inbox' : undefined} onClick={() => {
        if (open) closePanel();
        else { setLoadError(''); setActionError(''); onToggle(true); }
      }}>
      <Icon name="bell" size={18} />
      {unread > 0 && <span className="header-unread" aria-hidden="true">{unread > 99 ? '99+' : unread}</span>}
    </button>
    {open && <section id="notification-inbox" className="card notification-inbox" aria-labelledby="notification-title">
      <header className="notification-heading">
        <span className="icon-tile"><Icon name="bell" size={18} /></span>
        <div><h2 id="notification-title">Notifications</h2>
          <p role="status" aria-atomic="true">{result ? (unread ? `${unread} unread ${unread === 1 ? 'notification' : 'notifications'}` : 'No unread notifications') : 'Inbox'}</p></div>
        <div className="notification-controls">
          <button type="button" className="header-control icon-button notification-bulk" aria-label="Mark all as read"
            title="Mark all as read" aria-disabled={busy !== null || unread === 0} aria-busy={busy === 'marking'}
            onClick={() => void markAllRead()}>
            {busy === 'marking' ? <span className="spinner" aria-hidden="true" /> : <Icon name="checkAll" size={19} />}
          </button>
          <button ref={closeButton} type="button" className="header-control icon-button" aria-label="Close notifications" onClick={closePanel}>
            <Icon name="close" size={18} />
          </button>
        </div>
      </header>
      <div className="notification-filters" role="group" aria-label="Filter notifications">
        {(['', ...Object.keys(categories)] as Filter[]).map(value => <button type="button" key={value}
          aria-pressed={filter === value} onClick={() => {
            if (filter === value) return;
            setLoadError(''); setActionError(''); setFilter(value);
          }}>{value ? categories[value].label : 'All'}</button>)}
      </div>
      <div className="notification-body" key={filter}>
        {(actionError || loadError) && <p className="error" role="alert">{actionError || loadError}</p>}
        {!items && !loadError && <Skeleton label="Loading notifications…" />}
        {items?.length === 0 && <EmptyState icon="bell" title={filter ? 'No notifications in this category' : 'No notifications yet'} />}
        {!!items?.length && <ul className="notification-list">{items.map(item => {
          const category = categories[item.category] ?? categories.update;
          return <li key={item.id} className="notification-item" data-unread={!item.read}>
            <span className={`icon-tile notification-${item.category ?? 'update'}`}><Icon name={category.icon} size={17} /></span>
            <div className="notification-content">
              <button type="button" className="notification-open" aria-disabled={busy !== null}
                onClick={() => void openItem(item)}>
                <strong>{item.category === 'approval' ? 'Repair awaiting verification' : messages[item.action] ?? 'Request activity'}</strong>
                <span>{item.title}</span>
              </button>
              <small className="notification-time">{item.read ? 'Read · ' : 'Unread · '}
                <time dateTime={item.created_at}>{formatDateTime(item.created_at)}</time></small>
            </div>
          </li>;
        })}</ul>}
      </div>
    </section>}
  </div>;
}
