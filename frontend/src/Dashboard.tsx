import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { pollWhileVisible } from './liveUpdates';

export const queues = {
  needs_assignment: { label: 'Needs assignment', icon: 'people', description: 'Submitted without a work order' },
  urgent_open: { label: 'Urgent open requests', icon: 'requests', description: 'Urgent requests across active stages' },
  work_in_progress: { label: 'Work in progress', icon: 'tool', description: 'Repairs technicians have started' },
  awaiting_verification: { label: 'Awaiting verification', icon: 'check', description: 'Completed repairs ready for review' },
} as const;
export type QueueFocus = keyof typeof queues;
const queueKeys = Object.keys(queues) as QueueFocus[];

export function Dashboard({ token, branches, onExpired, onRequest }: {
  token: string; branches: { id: string; name: string }[]; onExpired: () => void; onRequest: (id: string) => void;
}) {
  const [branch, setBranch] = useState('');
  const [counts, setCounts] = useState<Record<QueueFocus, number> | null>(null);
  const [error, setError] = useState('');
  const [urgent, setUrgent] = useState<{ id: string; title: string; branch_name: string; status: string }[]>([]);
  const [updated, setUpdated] = useState<Date | null>(null);
  const [paused, setPaused] = useState(false);

  function queueLink(focus: QueueFocus) {
    const query = new URLSearchParams({ focus });
    if (branch) query.set('branch_id', branch);
    return `#requests?${query}`;
  }

  useEffect(() => {
    const controller = new AbortController();
    let pending = false;
    async function refresh() {
      if (pending) return;
      pending = true;
      try {
        const query = branch ? `?${new URLSearchParams({ branch_id: branch })}` : '';
        const options = { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal };
        const requestsQuery = new URLSearchParams({ focus: 'urgent_open', limit: '4' });
        if (branch) requestsQuery.set('branch_id', branch);
        const [response, urgentResponse] = await Promise.all([
          fetch(`/api/requests/dashboard${query}`, options),
          fetch(`/api/requests?${requestsQuery}`, options),
        ]);
        if (controller.signal.aborted) return;
        if (response.status === 401 || urgentResponse.status === 401) { onExpired(); return; }
        if (!response.ok || !urgentResponse.ok) throw new Error();
        const [data, requests] = await Promise.all([response.json(), urgentResponse.json()]);
        if (!controller.signal.aborted) {
          setCounts(data); setUrgent(requests); setUpdated(new Date()); setError('');
        }
      } catch {
        if (!controller.signal.aborted) setError('Unable to refresh the overview.');
      } finally { pending = false; }
    }
    void refresh();
    const stop = paused ? () => {} : pollWhileVisible(refresh);
    return () => { controller.abort(); stop(); };
  }, [token, branch, paused]);

  return <section className="dashboard-area" aria-labelledby="dashboard-title">
    <div className="section-heading">
      <div><p className="eyebrow">Maintenance overview</p><h1 id="dashboard-title">Operations, in focus.</h1>
        <p className="muted">Track the work. Resolve what matters.</p></div>
      <div className="dashboard-branch">
        <label htmlFor="dashboard-branch">Branch</label>
        <select id="dashboard-branch" value={branch} onChange={event => {
          setCounts(null); setUrgent([]); setUpdated(null); setError(''); setBranch(event.target.value);
        }}>
          <option value="">All branches</option>
          {branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </div>
    </div>
    {error && <p className="error" role="alert">{error}</p>}
    {!counts && !error && <p role="status">Loading dashboard counts…</p>}
    <div className="overview-stage">
      <section className="review-spotlight">
        <div className="spotlight-heading"><span className="eyebrow">Ready for your review</span><Icon name="check" size={28} /></div>
        <div className="spotlight-value"><strong key={counts?.awaiting_verification}>{counts?.awaiting_verification ?? '–'}</strong>
          <h2>Repairs awaiting<br />verification.</h2></div>
        <p>Review the technician’s work, inspect the photos, and decide the next step.</p>
        <a className="spotlight-link" href={queueLink('awaiting_verification')}>Review completed work <Icon name="arrow" /></a>
      </section>
    <div className="dashboard-grid">
      {queueKeys.filter(key => key !== 'awaiting_verification').map(key => {
        const queue = queues[key];
        const query = new URLSearchParams({ focus: key });
        if (branch) query.set('branch_id', branch);
        return <a className={`card dashboard-card dashboard-${key}`} key={key} href={`#requests?${query}`}>
          <div className="dashboard-card-icons"><span className="icon-tile"><Icon name={queue.icon} /></span><Icon name="arrow" size={18} /></div>
          <h2>{queue.label}</h2>
          <strong className="dashboard-count" key={counts?.[key]}>{counts?.[key] ?? '–'}</strong>
          <p className="muted">{queue.description}</p>
        </a>;
      })}
    </div>
    </div>
    <div className="update-status">
      <span>{error ? 'Updates interrupted' : updated ? `Updated ${updated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Connecting…'}</span>
      <button className="text-button" aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? 'Resume updates' : 'Pause updates'}</button>
    </div>
    <div className="dashboard-bottom">
      <section className="urgent-panel card">
        <div className="queue-heading"><div><p className="eyebrow">Priority watch</p><h2>Urgent requests</h2></div>
          <a className="text-link" href={queueLink('urgent_open')}>View all <Icon name="arrow" size={16} /></a></div>
        {counts && !urgent.length && <div className="empty-state"><span className="icon-tile"><Icon name="check" /></span><h3>No urgent requests</h3><p>No open requests are marked urgent in this branch view.</p></div>}
        {urgent.map(request => <button className="urgent-row" key={request.id} onClick={() => onRequest(request.id)}>
          <span className="urgent-marker" aria-hidden="true" />
          <span><strong>{request.title}</strong><small>{request.branch_name}</small></span>
          <span className="badge">{request.status.replaceAll('_', ' ')}</span><Icon name="arrow" size={18} />
        </button>)}
      </section>
      <a className="asset-shortcut card" href="#assets"><span className="icon-tile"><Icon name="asset" size={28} /></span>
        <p className="eyebrow">Asset intelligence</p><h2>The story behind<br />every repair.</h2><p>Equipment records, service history, and repair costs in one place.</p>
        <span className="shortcut-action">Explore the registry <Icon name="arrow" size={18} /></span></a>
    </div>
  </section>;
}
