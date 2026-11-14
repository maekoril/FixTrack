import { useEffect, useState } from 'react';
import { pollWhileVisible } from './liveUpdates';

type Item = { id: string; request_id: string; title: string; action: string;
  created_at: string; read: boolean };
type Inbox = { unread: number; items: Item[] };

const messages: Record<string, string> = {
  submitted: 'New service request',
  priority_changed: 'Priority updated',
  work_order_assigned: 'Work assigned to you',
  work_reassigned: 'Work transferred to you',
  work_started: 'Repair started',
  maintenance_logged: 'Maintenance update added',
  work_completed: 'Repair awaiting verification',
  work_returned: 'Repair returned for follow-up',
  verified_and_closed: 'Repair verified and closed',
};

export function Notifications({ token, onExpired, onOpen }: {
  token: string; onExpired: () => void; onOpen: (requestId: string) => void;
}) {
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  const headers = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const response = await fetch('/api/notifications', { headers, signal: controller.signal });
        if (controller.signal.aborted) return;
        if (response.status === 401) { onExpired(); return; }
        if (!response.ok) throw new Error();
        const data = await response.json();
        if (!controller.signal.aborted) { setInbox(data); setError(''); }
      } catch {
        if (!controller.signal.aborted) setError('Unable to refresh notifications.');
      } finally { pending = false; }
    }
    void refresh();
    const stop = pollWhileVisible(refresh);
    return () => { controller.abort(); stop(); };
  }, [token, version, open]);

  async function openItem(item: Item) {
    try {
      const response = await fetch(`/api/notifications/${item.id}/read`, { method: 'PUT', headers });
      if (response.status === 401) { onExpired(); return; }
      if (response.status === 404) {
        setError('This notification is no longer available.');
        return;
      }
      if (!response.ok) throw new Error();
    } catch {
      setError('Unable to open the notification. Try again.');
      return;
    }
    setVersion(value => value + 1);
    setOpen(false);
    onOpen(item.request_id);
  }

  return <div className="notification-menu">
    <button type="button" className="secondary" aria-expanded={open} aria-controls="notification-inbox"
      onClick={() => setOpen(!open)}>Notifications{inbox?.unread ? ` (${inbox.unread})` : ''}</button>
    {open && <section id="notification-inbox" className="card notification-inbox" aria-label="Notifications">
      {error && <p role="alert">{error}</p>}
      {!inbox && !error && <p role="status">Loading notifications…</p>}
      {inbox && !inbox.items.length && <p>No notifications yet.</p>}
      {!!inbox?.items.length && <ul>{inbox.items.map(item => <li key={item.id}>
        <button type="button" className="secondary" onClick={() => void openItem(item)}>
          <strong>{messages[item.action]}</strong>
          <span>{item.title}</span>
          <small>{item.read ? '' : 'Unread · '}{new Date(item.created_at).toLocaleString()}</small>
        </button>
      </li>)}</ul>}
    </section>}
  </div>;
}
