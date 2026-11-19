import { useEffect, useState } from 'react';
import { Icon } from './Icon';
import { Chip, EmptyState, PageHeader, Skeleton } from './UI';
import { pollWhileVisible } from './liveUpdates';

export const queues = {
  needs_assignment: { label: 'Needs assignment', icon: 'people', description: 'Submitted without a work order' },
  urgent_open: { label: 'Urgent open requests', icon: 'requests', description: 'Urgent requests across active stages' },
  work_in_progress: { label: 'Work in progress', icon: 'tool', description: 'Repairs technicians have started' },
  awaiting_verification: { label: 'Repairs awaiting verification', icon: 'check', description: 'Completed repairs ready for review' },
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
    <PageHeader id="dashboard-title" title="Overview" description="Monitor repair activity across your branches.">
      <div className="dashboard-branch">
        <label htmlFor="dashboard-branch">Branch</label>
        <select id="dashboard-branch" value={branch} onChange={event => {
          setCounts(null); setUrgent([]); setUpdated(null); setError(''); setBranch(event.target.value);
        }}>
          <option value="">All branches</option>
          {branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </div>
    </PageHeader>
    {error && <p className="error" role="alert">{error}</p>}
    <div className="card dashboard-grid" aria-label="Repair queues">
      {queueKeys.map(key => <StatCard key={key} queueKey={key} href={queueLink(key)} count={counts?.[key]} />)}
    </div>
    <div className="update-status">
      <span>{error ? 'Updates interrupted' : updated ? `Updated ${updated.toLocaleTimeString('en-PH', { hour: 'numeric', minute: '2-digit' })}` : 'Connecting…'}</span>
      <button className="text-button" aria-pressed={paused} onClick={() => setPaused(!paused)}>{paused ? 'Resume updates' : 'Pause updates'}</button>
    </div>
    <div className="dashboard-bottom">
      <section className="urgent-panel card">
        <div className="queue-heading"><h2>Urgent requests</h2>
          <a className="text-link" href={queueLink('urgent_open')}>View queue <Icon name="arrow" size={16} /></a></div>
        {!counts && !error && <Skeleton label="Loading urgent requests…" />}
        {counts && !urgent.length && <EmptyState icon="check" title="No urgent requests for this branch view." />}
        {urgent.map(request => <button className="urgent-row" key={request.id} onClick={() => onRequest(request.id)}>
          <span className="urgent-marker" aria-hidden="true" />
          <span><strong>{request.title}</strong><small>{request.branch_name}</small></span>
          <Chip tone={`status-${request.status}`}>{request.status.replaceAll('_', ' ')}</Chip><Icon name="arrow" size={16} />
        </button>)}
      </section>
      <a className="asset-shortcut card" href="#assets"><span className="icon-tile"><Icon name="asset" /></span>
        <div><h2>Asset registry</h2><p className="muted">Equipment, repair history, and costs</p></div>
        <Icon name="arrow" size={18} />
      </a>
    </div>
  </section>;
}

function StatCard({ queueKey, href, count }: { queueKey: QueueFocus; href: string; count?: number }) {
  const queue = queues[queueKey];
  const [display, setDisplay] = useState<number>();
  useEffect(() => {
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (!count || motion.matches) { setDisplay(count); return; }
    let frame: number;
    const start = performance.now();
    function update(now: number) {
      const fraction = Math.min((now - start) / 320, 1);
      setDisplay(Math.round(count! * (1 - (1 - fraction) ** 3)));
      if (fraction < 1) frame = requestAnimationFrame(update);
    }
    const finish = () => { cancelAnimationFrame(frame); setDisplay(count); };
    frame = requestAnimationFrame(update);
    motion.addEventListener('change', finish);
    return () => { cancelAnimationFrame(frame); motion.removeEventListener('change', finish); };
  }, [count]);

  return <a className={`dashboard-card dashboard-${queueKey}`} href={href} title={queue.description}>
    <span className="icon-tile"><Icon name={queue.icon} size={18} /></span>
    <div><h2>{queue.label}</h2><strong className="dashboard-count">
      <span aria-hidden="true">{count === undefined ? '–' : display ?? 0}</span>
      <span className="sr-only">{count ?? 'Loading'}</span>
    </strong></div>
    <Icon name="arrow" size={16} />
  </a>;
}
