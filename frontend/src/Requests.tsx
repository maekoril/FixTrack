import { useEffect, useRef, useState, type FormEvent } from 'react';

type Branch = { id: string; name: string };
type Asset = { id: string; name: string; asset_tag: string };
type ServiceRequest = { id: string; title: string; description: string; location: string;
  branch_name: string; submitted_by_name: string; status: string; priority: string | null;
  created_at: string; asset_name: string | null };
type Detail = ServiceRequest & { events: { id: string; action: string; actor_name: string;
  created_at: string; details: { from?: string; to?: string } }[] };
type Props = { token: string; role: string; branches: Branch[]; onExpired: () => void };
const pageSize = 25;
const label = (value: string) => value.replaceAll('_', ' ');
const date = (value: string) => new Date(value).toLocaleString();

export function Requests({ token, role, branches, onExpired }: Props) {
  const [items, setItems] = useState<ServiceRequest[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const detailPanel = useRef<HTMLElement>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  const [selected, setSelected] = useState('');
  const [branch, setBranch] = useState('');
  const [status, setStatus] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [formBranch, setFormBranch] = useState(branches[0]?.id ?? '');
  const [assets, setAssets] = useState<Asset[]>([]);

  async function api(path: string, method = 'GET', body?: unknown, signal?: AbortSignal) {
    const response = await fetch(`/api/requests${path}`, { method, signal,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (response.status === 401) { onExpired(); throw new Error('Your session expired. Sign in again.'); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the form values and try again.');
    }
    return response.json();
  }

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const query = new URLSearchParams({ offset: String(offset), limit: String(pageSize), search });
    if (branch) query.set('branch_id', branch);
    if (status) query.set('status', status);
    api(`?${query}`, 'GET', undefined, controller.signal).then(setItems)
      .catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [branch, status, search, offset, version, token]);

  useEffect(() => {
    setDetail(null); setDetailFailed(false);
    if (!selected) return;
    const controller = new AbortController();
    api(`/${selected}`, 'GET', undefined, controller.signal).then(setDetail)
      .catch(err => { if (!controller.signal.aborted) { setError(err.message); setDetailFailed(true); } });
    return () => controller.abort();
  }, [selected, version, token]);

  useEffect(() => {
    setAssets([]);
    if (!showForm || !formBranch) return;
    const controller = new AbortController();
    api(`/assets?branch_id=${formBranch}`, 'GET', undefined, controller.signal).then(setAssets)
      .catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [showForm, formBranch, token]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    setBusy(true); setError(''); setNotice('');
    try {
      const request: ServiceRequest = await api('', 'POST', { branch_id: formBranch,
        title: data.get('title'), description: data.get('description'), location: data.get('location'),
        asset_id: data.get('asset_id') || null });
      setShowForm(false); setBranch(''); setStatus(''); setSearch(''); setOffset(0);
      setSelected(request.id); setVersion(v => v + 1);
      setNotice('Request submitted. Your administrator can now review it.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to submit request.'); }
    finally { setBusy(false); }
  }

  async function prioritize(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!detail) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/${detail.id}/priority`, 'PATCH', { priority: data.get('priority') });
      setVersion(v => v + 1); setNotice('Priority updated.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to update priority.'); }
    finally { setBusy(false); }
  }

  return <section className="requests-area" aria-labelledby="requests-title">
    <div className="section-heading"><div><p className="eyebrow">SERVICE DESK</p>
      <h2 id="requests-title">{role === 'employee' ? 'My requests' : role === 'technician' ? 'Assigned requests' : 'Service requests'}</h2>
      <p className="muted">{role === 'employee' ? 'Report an issue and follow its progress.' : 'Review issues across your accessible branches.'}</p>
    </div><div className="actions"><button className="secondary" disabled={loading || busy} onClick={() => setVersion(v => v + 1)}>Refresh</button>
      {role === 'employee' && <button disabled={!branches.length || busy} onClick={() => setShowForm(!showForm)}>{showForm ? 'Cancel' : '+ Report an issue'}</button>}</div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {showForm && <section className="card report-form"><h3>Report an issue</h3>
      <form onSubmit={submit}><fieldset disabled={busy}>
        <div className="form-columns"><div><label htmlFor="request-branch">Branch</label>
          <select id="request-branch" value={formBranch} required onChange={event => setFormBranch(event.target.value)}>
            {branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
          <div><label htmlFor="request-location">Location</label><input id="request-location" name="location" placeholder="e.g. Second floor, meeting room" required maxLength={255} /></div></div>
        <label htmlFor="request-title">Issue title</label><input id="request-title" name="title" placeholder="e.g. Air conditioner is leaking" minLength={3} maxLength={180} required />
        <label htmlFor="request-description">What happened?</label><textarea id="request-description" name="description" rows={4} minLength={10} maxLength={10000} required placeholder="Describe the problem and how it affects your work." />
        <label htmlFor="request-asset">Related asset (optional)</label><select key={formBranch} id="request-asset" name="asset_id" defaultValue="">
          <option value="">General facility issue / no registered asset</option>
          {assets.map(asset => <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.name}</option>)}</select>
        <button> {busy ? 'Submitting…' : 'Submit request'}</button>
      </fieldset></form></section>}
    <div className="request-filters"><label>Search title<input value={search} placeholder="Find a request…" onChange={event => { setSearch(event.target.value); setOffset(0); }} /></label>
      <label>Branch<select value={branch} onChange={event => { setBranch(event.target.value); setOffset(0); }}><option value="">All my branches</option>{branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <label>Status<select value={status} onChange={event => { setStatus(event.target.value); setOffset(0); }}><option value="">All statuses</option>
        {['submitted', 'in_progress', 'awaiting_verification', 'closed'].map(value => <option key={value} value={value}>{label(value)}</option>)}</select></label></div>
    <div className="request-layout"><div>
      {loading ? <p role="status">Loading requests…</p> : !items.length ? <div className="card empty-state"><h3>No requests here yet</h3><p className="muted">{role === 'employee' ? 'Report your first issue, or try changing your filters.' : 'Requests will appear here when employees report an issue.'}</p></div>
        : <div className="request-list">{items.map(item => <button key={item.id} className={`request-item ${selected === item.id ? 'selected' : ''}`} onClick={() => { setSelected(item.id); setError(''); if (window.matchMedia('(max-width: 900px)').matches) detailPanel.current?.scrollIntoView({ behavior: 'smooth' }); }} aria-pressed={selected === item.id}>
          <div className="request-meta"><span>#{item.id.slice(0, 8).toUpperCase()}</span><span className={`badge priority-${item.priority}`}>{item.priority ?? 'Not prioritized'}</span></div>
          <h3>{item.title}</h3><p>{item.branch_name} · {item.location}</p><div className="request-meta"><span className="badge">{label(item.status)}</span><span>{date(item.created_at)}</span></div>
        </button>)}</div>}
      <div className="pagination"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><span>Page {offset / pageSize + 1}</span>
        <button className="secondary" disabled={items.length < pageSize || loading} onClick={() => setOffset(offset + pageSize)}>Next</button></div>
    </div><aside ref={detailPanel} className="card request-detail" aria-label="Request details">
      {!selected ? <div className="empty-state"><p className="eyebrow">THE FULL PICTURE</p><h3>Select a request</h3><p className="muted">See the report, priority, and activity history.</p></div>
        : detailFailed ? <p>Unable to load this request. Select Refresh to try again.</p>
        : !detail ? <p role="status">Loading details…</p> : <>
          <p className="eyebrow">#{detail.id.slice(0, 8).toUpperCase()}</p><h2>{detail.title}</h2>
          <div className="actions"><span className="badge">{label(detail.status)}</span><span className={`badge priority-${detail.priority}`}>{detail.priority ?? 'Not prioritized'}</span></div>
          <dl><dt>Branch / location</dt><dd>{detail.branch_name} · {detail.location}</dd><dt>Related asset</dt><dd>{detail.asset_name ?? 'General facility issue / no registered asset'}</dd><dt>Reported by</dt><dd>{detail.submitted_by_name}</dd><dt>Submitted</dt><dd>{date(detail.created_at)}</dd></dl>
          <h3>Description</h3><p className="description">{detail.description}</p>
          {role === 'administrator' && detail.status !== 'closed' && <form key={`${detail.id}-${detail.priority}`} onSubmit={prioritize}><label htmlFor="priority">Set priority</label><select id="priority" name="priority" defaultValue={detail.priority ?? ''} required disabled={busy}><option value="" disabled>Select priority</option>{['low', 'medium', 'high', 'urgent'].map(value => <option key={value} value={value}>{value}</option>)}</select><button disabled={busy}>Save priority</button></form>}
          <h3 className="history-heading">Activity history</h3><ol className="timeline">{detail.events.map(event => <li key={event.id}><strong>{event.action === 'priority_changed' ? `Priority changed from ${event.details.from ?? 'unset'} to ${event.details.to}` : label(event.action)}</strong><small>{event.actor_name} · {date(event.created_at)}</small></li>)}</ol>
        </>}
    </aside></div>
  </section>;
}
