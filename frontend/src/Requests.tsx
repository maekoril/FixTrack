import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Icon } from './Icon';
import { queues, type QueueFocus } from './Dashboard';
import { pollWhileVisible } from './liveUpdates';
import { PhotoGallery, photoTypes, uploadPhoto, type Photo } from './Photos';

type Branch = { id: string; name: string };
type Asset = { id: string; name: string; asset_tag: string };
type ServiceRequest = { id: string; title: string; description: string; location: string;
  branch_name: string; submitted_by_name: string; status: string; priority: string | null;
  created_at: string; asset_name: string | null };
type Detail = ServiceRequest & {
  photos: Photo[];
  eligible_technicians: { id: string; full_name: string }[] | null;
  work_orders: { id: string; technician_id: string; status: string; labor_cost: string; materials_cost: string }[];
  maintenance_logs: { id: string; work_order_id: string; action: string; notes: string;
    recorded_by_name: string; created_at: string }[];
  events: { id: string; action: string; actor_name: string;
    created_at: string; details: { from?: string; to?: string; technician_name?: string;
      reason?: string; notes?: string; work_order_id?: string; previous_technician_name?: string } }[];
};
type Props = { token: string; role: string; branches: Branch[]; onExpired: () => void;
  openedRequest: { id: string }; initialFocus: QueueFocus | ''; initialBranch: string };
const pageSize = 25;
const label = (value: string) => value.replaceAll('_', ' ');
const date = (value: string) => new Date(value).toLocaleString();

function MaintenanceHistory({ logs }: { logs: Detail['maintenance_logs'] }) {
  if (!logs.length) return null;
  return <>
    <h4>Maintenance history</h4>
    <ol className="timeline">{logs.map(log =>
      <li key={log.id}><strong>{log.action}</strong>
        <small>{log.recorded_by_name} · {date(log.created_at)}</small>
        <p className="description">{log.notes}</p>
      </li>)}</ol>
  </>;
}

export function Requests({ token, role, branches, onExpired, openedRequest, initialFocus, initialBranch }: Props) {
  const [items, setItems] = useState<ServiceRequest[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const detailPanel = useRef<HTMLElement>(null);
  const selectedButton = useRef<HTMLButtonElement>(null);
  const queueHeading = useRef<HTMLHeadingElement>(null);
  const reportHeading = useRef<HTMLHeadingElement>(null);
  const reportButton = useRef<HTMLButtonElement>(null);
  const [detailFailed, setDetailFailed] = useState(false);
  const [selected, setSelected] = useState(openedRequest.id);
  const [branch, setBranch] = useState(initialBranch);
  const [focus, setFocus] = useState(initialFocus);
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
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
      throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : 'Check the form values and try again.'),
        { status: response.status });
    }
    return response.json();
  }

  useEffect(() => {
    if (openedRequest.id) setSelected(openedRequest.id);
  }, [openedRequest]);

  useEffect(() => {
    setFocus(initialFocus); setBranch(initialBranch);
    setStatus(''); setPriority(''); setSearch(''); setOffset(0);
  }, [initialFocus, initialBranch]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError('');
    const query = new URLSearchParams({ offset: String(offset), limit: String(pageSize), search });
    if (branch) query.set('branch_id', branch);
    if (status) query.set('status', status);
    if (priority) query.set('priority', priority);
    if (focus) query.set('focus', focus);
    let pending = false;
    async function refresh(background = false) {
      if (pending) return;
      pending = true;
      try {
        const result = await api(`?${query}`, 'GET', undefined, controller.signal);
        if (!controller.signal.aborted) setItems(result);
      } catch (err) {
        if (!background && !controller.signal.aborted && err instanceof Error) setError(err.message);
      } finally {
        pending = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void refresh();
    const stop = pollWhileVisible(() => refresh(true));
    return () => { controller.abort(); stop(); };
  }, [branch, status, priority, search, focus, offset, version, token]);

  useEffect(() => {
    setDetail(null); setDetailFailed(false);
    if (!selected) return;
    const controller = new AbortController();
    let pending = false;
    async function refresh(background = false) {
      if (pending) return;
      pending = true;
      try {
        const result = await api(`/${selected}`, 'GET', undefined, controller.signal);
        if (!controller.signal.aborted) { setDetail(result); setDetailFailed(false); }
      } catch (err) {
        if (!controller.signal.aborted && err instanceof Error &&
          (!background || ('status' in err && err.status === 404))) {
          setDetail(null); setError(err.message); setDetailFailed(true);
        }
      } finally { pending = false; }
    }
    void refresh();
    const stop = pollWhileVisible(() => refresh(true));
    return () => { controller.abort(); stop(); };
  }, [selected, version, token]);

  useEffect(() => {
    setAssets([]);
    if (!showForm || !formBranch) return;
    const controller = new AbortController();
    api(`/assets?branch_id=${formBranch}`, 'GET', undefined, controller.signal).then(setAssets)
      .catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [showForm, formBranch, token]);

  useEffect(() => {
    if (showForm) reportHeading.current?.focus();
  }, [showForm]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const data = new FormData(event.currentTarget);
    setBusy(true); setError(''); setNotice('');
    try {
      const request: ServiceRequest = await api('', 'POST', { branch_id: formBranch,
        title: data.get('title'), description: data.get('description'), location: data.get('location'),
        asset_id: data.get('asset_id') || null });
      setShowForm(false); setBranch(''); setStatus(''); setPriority(''); setSearch(''); setOffset(0);
      setSelected(request.id);
      detailPanel.current?.focus();
      setNotice('Request submitted. Your administrator can now review it.');
      const photo = data.get('photo');
      if (photo instanceof File && photo.size) {
        try { await uploadPhoto(token, request.id, photo); }
        catch (err) {
          setError(`The request was saved. ${err instanceof Error ? err.message : 'Photo upload failed.'} Use Add issue photo to try again.`);
        }
      }
      setVersion(v => v + 1);
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

  async function assignTechnician(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || detail.id !== selected || busy) return;
    const data = new FormData(event.currentTarget);
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/${detail.id}/work-orders`, 'POST', { technician_id: data.get('technician_id') });
      setVersion(v => v + 1); setNotice('Technician assigned.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to assign technician.'); }
    finally { setBusy(false); }
  }

  async function updateWork(workOrderId: string, operation: 'start' | 'logs' | 'complete' | 'reassign', data?: unknown) {
    if (!detail || detail.id !== selected || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/${detail.id}/work-orders/${workOrderId}/${operation}`, 'POST', data);
      setVersion(v => v + 1);
      setNotice({
        start: 'Work started. The request is now in progress.',
        logs: 'Maintenance entry added.',
        complete: 'Work completed. The request is awaiting administrator verification.',
        reassign: 'Work order reassigned.',
      }[operation]);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to update work order.'); }
    finally { setBusy(false); }
  }

  function submitWork(event: FormEvent<HTMLFormElement>, orderId: string, operation: 'logs' | 'complete') {
    event.preventDefault();
    void updateWork(orderId, operation, Object.fromEntries(new FormData(event.currentTarget)));
  }

  async function attachPhoto(event: FormEvent<HTMLFormElement>, orderId?: string) {
    event.preventDefault();
    if (!detail || detail.id !== selected || busy) return;
    const form = event.currentTarget;
    const photo = new FormData(form).get('photo');
    if (!(photo instanceof File) || !photo.size) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await uploadPhoto(token, detail.id, photo, orderId);
      form.reset();
      setVersion(v => v + 1);
      setNotice('Photo added.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to upload photo.'); }
    finally { setBusy(false); }
  }

  async function reviewWork(event: FormEvent<HTMLFormElement>, decision: 'verify' | 'return') {
    event.preventDefault();
    const order = detail?.work_orders.at(-1);
    if (!detail || detail.id !== selected || !order || busy) return;
    const fields = Object.fromEntries(new FormData(event.currentTarget));
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/${detail.id}/${decision}`, 'POST', { ...fields, work_order_id: order.id });
      setVersion(v => v + 1);
      setNotice(decision === 'verify' ? 'Repair verified and request closed.'
        : 'Repair returned and follow-up work assigned.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to review the repair.'); }
    finally { setBusy(false); }
  }

  return <section className="requests-area" aria-labelledby="requests-title">
    <div className="section-heading"><div><p className="eyebrow">SERVICE DESK</p>
      <h1 id="requests-title">{role === 'branch_manager' ? 'My requests' : role === 'technician' ? 'Assigned requests' : 'Service requests'}</h1>
      <p className="muted">{role === 'branch_manager' ? 'Report equipment and facility issues and follow their progress.' : role === 'technician' ? 'Review service requests linked to your assigned work.' : 'Review branch issues, set priorities, and follow each request’s history.'}</p>
    </div><div className="actions"><button className="secondary" disabled={loading || busy} onClick={() => setVersion(v => v + 1)}><Icon name="refresh" size={17} />Refresh</button>
      {role === 'branch_manager' && <button ref={reportButton} className={showForm ? 'secondary' : undefined} aria-expanded={showForm} disabled={!branches.length || busy} onClick={() => setShowForm(!showForm)}>{showForm ? 'Cancel' : <><Icon name="plus" size={18} />Report an issue</>}</button>}</div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {showForm && <section className="card report-form" aria-labelledby="report-title">
      <div className="panel-heading"><span className="icon-tile"><Icon name="plus" /></span><div><h2 ref={reportHeading} tabIndex={-1} id="report-title">Report an issue</h2><p className="muted">Add enough detail for your administrator to review the issue.</p></div></div>
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
        <label htmlFor="report-photo">Issue photo (optional)</label>
        <input id="report-photo" name="photo" type="file" accept={photoTypes} aria-describedby="report-photo-hint" />
        <p className="field-hint" id="report-photo-hint">JPEG, PNG, or WebP up to 8 MB.</p>
        <div className="actions"><button>{busy ? 'Submitting…' : 'Submit request'}<Icon name="arrow" size={16} /></button>
          <button type="button" className="secondary" onClick={() => { setShowForm(false); reportButton.current?.focus(); }}>Cancel</button></div>
      </fieldset></form></section>}
    {focus && <div className="dashboard-queue-filter">
      <span className="badge">{queues[focus].label}</span>
      <button className="secondary" onClick={() => {
        setFocus(''); setOffset(0);
        const query = branch ? `?${new URLSearchParams({ branch_id: branch })}` : '';
        window.location.hash = `#requests${query}`;
      }}>Clear dashboard filter</button>
    </div>}
    <div className="card request-filters">
      <div><label htmlFor="filter-search">Search title</label><div className="search-field"><Icon name="search" size={18} /><input id="filter-search" type="search" maxLength={180} value={search} placeholder="Search…" onChange={event => { setSearch(event.target.value); setOffset(0); }} /></div></div>
      <div><label htmlFor="filter-branch">Branch</label><select id="filter-branch" value={branch} onChange={event => { setBranch(event.target.value); setOffset(0); }}><option value="">All branches</option>{branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
      <div><label htmlFor="filter-status">Status</label><select id="filter-status" value={status} onChange={event => { setStatus(event.target.value); setOffset(0); }}><option value="">All statuses</option>
        {['submitted', 'in_progress', 'awaiting_verification', 'closed'].map(value => <option key={value} value={value}>{label(value)}</option>)}</select></div>
      <div><label htmlFor="filter-priority">Priority</label><select id="filter-priority" value={priority} onChange={event => { setPriority(event.target.value); setOffset(0); }}><option value="">All priorities</option>
        {['low', 'medium', 'high', 'urgent'].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
    </div>
    <div className="request-layout"><div className="card queue">
      <div className="queue-heading"><h2 ref={queueHeading} tabIndex={-1}>Request queue</h2><span className="count">{loading ? 'Loading' : `${items.length} on this page`}</span></div>
      {loading ? <p className="empty-state" role="status">Loading requests…</p> : !items.length ? <div className="empty-state"><span className="icon-tile"><Icon name="requests" /></span><h3>No requests found</h3><p className="muted">{search || branch || status || priority ? 'Try changing your search or filters.' : role === 'branch_manager' ? 'Your reports will appear here once submitted.' : 'Requests will appear here when they’re available to you.'}</p></div>
        : <div className="request-list">{items.map(item => <button key={item.id} ref={selected === item.id ? selectedButton : null} className={`request-item ${selected === item.id ? 'selected' : ''}`} onClick={() => { setSelected(item.id); setError(''); detailPanel.current?.focus(); }} aria-pressed={selected === item.id}>
          <span className="request-meta"><span className="reference">#{item.id.slice(0, 8).toUpperCase()}</span><span className={`badge priority-${item.priority}`}>{item.priority ?? 'Not prioritized'}</span></span>
          <strong className="request-title">{item.title}<Icon name="arrow" size={16} /></strong>
          <span className="request-location"><Icon name="pin" size={15} />{item.branch_name} · {item.location}</span>
          <span className="request-meta"><span className={`badge status-${item.status}`}>{label(item.status)}</span><span>{date(item.created_at)}</span></span>
        </button>)}</div>}
      <div className="pagination"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><span>Page {offset / pageSize + 1}</span>
        <button className="secondary" disabled={items.length < pageSize || loading} onClick={() => setOffset(offset + pageSize)}>Next</button></div>
    </div><aside ref={detailPanel} tabIndex={-1} className="card request-detail" aria-label="Request details">
      {selected && <button className="secondary back-to-queue" onClick={() => { setSelected(''); (selectedButton.current ?? queueHeading.current)?.focus(); }}><Icon name="back" size={16} />Back to queue</button>}
      {!selected ? <div className="empty-state"><span className="icon-tile"><Icon name="requests" size={23} /></span><h2>Select a request</h2><p className="muted">See the report, priority, and activity history.</p></div>
        : detailFailed ? <p>Unable to load this request. Select Refresh to try again.</p>
        : !detail ? <p role="status">Loading details…</p> : <>
          <p className="eyebrow reference">#{detail.id.slice(0, 8).toUpperCase()}</p><h2>{detail.title}</h2>
          <div className="actions"><span className={`badge status-${detail.status}`}>{label(detail.status)}</span><span className={`badge priority-${detail.priority}`}>{detail.priority ?? 'Not prioritized'}</span></div>
          <dl><dt>Branch / location</dt><dd>{detail.branch_name} · {detail.location}</dd><dt>Related asset</dt><dd>{detail.asset_name ?? 'General facility issue / no registered asset'}</dd><dt>Reported by</dt><dd>{detail.submitted_by_name}</dd><dt>Submitted</dt><dd>{date(detail.created_at)}</dd></dl>
          <h3>Description</h3><p className="description">{detail.description}</p>
          <PhotoGallery key={`photos-${detail.id}`} token={token} requestId={detail.id} photos={detail.photos} />
          {role === 'branch_manager' && detail.status !== 'closed' && (
            <form onSubmit={event => void attachPhoto(event)}>
              <fieldset disabled={busy}>
                <label htmlFor="issue-photo">Issue photo</label>
                <input id="issue-photo" name="photo" type="file" required accept={photoTypes} />
                <button className="secondary">Add issue photo</button>
              </fieldset>
            </form>
          )}
          {role === 'administrator' && detail.status !== 'closed' && <form key={`priority-${detail.id}`} onSubmit={prioritize}><label htmlFor="priority">Set priority</label><select id="priority" name="priority" defaultValue={detail.priority ?? ''} required disabled={busy}><option value="" disabled>Select priority</option>{['low', 'medium', 'high', 'urgent'].map(value => <option key={value} value={value}>{value}</option>)}</select><button disabled={busy}>Save priority</button></form>}
          {detail.status === 'submitted' && !detail.work_orders.length && detail.eligible_technicians && (detail.eligible_technicians.length ? (
            <form key={`assignment-${detail.id}`} onSubmit={assignTechnician}>
              <label htmlFor="technician">Technician</label>
              <select id="technician" name="technician_id" defaultValue="" required disabled={busy}>
                <option value="" disabled>Select technician</option>
                {detail.eligible_technicians.map(technician => <option key={technician.id} value={technician.id}>{technician.full_name}</option>)}
              </select>
              <button disabled={busy}>Assign technician</button>
            </form>
          ) : <p className="muted">No active technicians have access to this branch.</p>)}
          {detail.work_orders.length > 0 && <section>
            <h3>Work orders</h3>
            {detail.work_orders.map(order => <section key={order.id} className="work-order">
              <span className={`badge status-${order.status}`}>{label(order.status)}</span>
              {role === 'administrator' && ['submitted', 'in_progress'].includes(detail.status)
                && ['assigned', 'in_progress'].includes(order.status) && (
                detail.eligible_technicians?.some(technician => technician.id !== order.technician_id)
                  ? <form onSubmit={event => {
                    event.preventDefault();
                    const data = Object.fromEntries(new FormData(event.currentTarget));
                    void updateWork(order.id, 'reassign', { ...data, previous_technician_id: order.technician_id });
                  }}>
                    <fieldset disabled={busy}>
                      <legend>Reassign work order</legend>
                      <label htmlFor={`replacement-${order.id}`}>Replacement technician</label>
                      <select id={`replacement-${order.id}`} name="technician_id" defaultValue="" required>
                        <option value="" disabled>Select technician</option>
                        {detail.eligible_technicians.filter(technician => technician.id !== order.technician_id)
                          .map(technician => <option key={technician.id} value={technician.id}>{technician.full_name}</option>)}
                      </select>
                      <label htmlFor={`reassignment-reason-${order.id}`}>Reason for reassignment</label>
                      <textarea id={`reassignment-reason-${order.id}`} name="reason" required maxLength={10000} rows={3} />
                      <button className="secondary">Reassign technician</button>
                    </fieldset>
                  </form>
                  : <p className="muted">No other active technician has access to this branch.</p>
              )}
              {detail.events.filter(event => event.action === 'work_returned' &&
                event.details.work_order_id === order.id).map(event =>
                <div key={event.id}><h4>Follow-up instructions</h4><p className="description">{event.details.reason}</p></div>)}
              {role === 'technician' && ['submitted', 'in_progress'].includes(detail.status) && order.status === 'assigned' && (
                <button type="button" disabled={busy} onClick={() => updateWork(order.id, 'start')}>Start work</button>
              )}
              {order.status === 'completed' && <dl>
                <dt>Labor cost</dt><dd>{order.labor_cost}</dd>
                <dt>Materials cost</dt><dd>{order.materials_cost}</dd>
              </dl>}
              <MaintenanceHistory logs={detail.maintenance_logs.filter(log => log.work_order_id === order.id)} />
              {role === 'technician' && detail.status === 'in_progress' && order.status === 'in_progress' && <>
                <form onSubmit={event => void attachPhoto(event, order.id)}>
                  <fieldset disabled={busy}>
                    <label htmlFor={`repair-photo-${order.id}`}>Repair photo</label>
                    <input id={`repair-photo-${order.id}`} name="photo" type="file" accept={photoTypes} required />
                    <button className="secondary">Add repair photo</button>
                  </fieldset>
                </form>
                <form onSubmit={event => submitWork(event, order.id, 'logs')}>
                  <fieldset disabled={busy}>
                    <label htmlFor={`action-${order.id}`}>Maintenance action</label>
                    <input id={`action-${order.id}`} name="action" required maxLength={180} placeholder="e.g. Diagnosed leak" />
                    <label htmlFor={`notes-${order.id}`}>Diagnosis or repair notes</label>
                    <textarea id={`notes-${order.id}`} name="notes" required maxLength={10000} rows={3} />
                    <button className="secondary">Add maintenance entry</button>
                  </fieldset>
                </form>
                <form onSubmit={event => submitWork(event, order.id, 'complete')}>
                  <fieldset disabled={busy}>
                    <legend>Complete work order</legend>
                    <label htmlFor={`labor-${order.id}`}>Labor cost</label>
                    <input id={`labor-${order.id}`} name="labor_cost" type="number" min="0" max="9999999999.99" step="0.01" defaultValue={order.labor_cost} required />
                    <label htmlFor={`materials-${order.id}`}>Materials cost</label>
                    <input id={`materials-${order.id}`} name="materials_cost" type="number" min="0" max="9999999999.99" step="0.01" defaultValue={order.materials_cost} required />
                    <button>Complete work</button>
                  </fieldset>
                </form>
              </>}
            </section>)}
          </section>}
          {role === 'administrator' && detail.status === 'awaiting_verification' && <section>
            <h3>Review completed work</h3>
            <form onSubmit={event => reviewWork(event, 'verify')}>
              <fieldset disabled={busy}>
                <label htmlFor="verification-notes">Verification notes (optional)</label>
                <textarea id="verification-notes" name="notes" maxLength={10000} rows={3} />
                <button>Verify and close</button>
              </fieldset>
            </form>
            {detail.eligible_technicians?.length ? (
              <form onSubmit={event => reviewWork(event, 'return')}>
                <fieldset disabled={busy}>
                  <label htmlFor="follow-up-technician">Follow-up technician</label>
                  <select id="follow-up-technician" name="technician_id"
                    defaultValue={detail.eligible_technicians.some(technician =>
                      technician.id === detail.work_orders.at(-1)?.technician_id)
                      ? detail.work_orders.at(-1)?.technician_id : ''} required>
                    <option value="" disabled>Select technician</option>
                    {detail.eligible_technicians.map(technician =>
                      <option key={technician.id} value={technician.id}>{technician.full_name}</option>)}
                  </select>
                  <label htmlFor="follow-up-reason">What still needs repair?</label>
                  <textarea id="follow-up-reason" name="reason" required maxLength={10000} rows={3} />
                  <button className="secondary">Return for follow-up</button>
                </fieldset>
              </form>
            ) : <p className="muted">Assign branch access to an active technician to return this repair.</p>}
          </section>}
          {role === 'branch_manager' && <MaintenanceHistory logs={detail.maintenance_logs} />}
          <h3 className="history-heading">Activity history</h3>
          <ol className="timeline">{detail.events.map(event => {
            let summary = label(event.action);
            if (event.action === 'priority_changed') {
              summary = `Priority changed from ${event.details.from ?? 'unset'} to ${event.details.to}`;
            } else if (event.action === 'work_order_assigned') {
              summary = `Assigned to ${event.details.technician_name}`;
            } else if (event.action === 'work_completed') {
              summary = 'Work completed and submitted for verification';
            } else if (event.action === 'work_returned') {
              summary = `Returned for follow-up and assigned to ${event.details.technician_name}`;
            } else if (event.action === 'work_reassigned') {
              summary = `Reassigned from ${event.details.previous_technician_name} to ${event.details.technician_name}`;
            } else if (event.action === 'verified_and_closed') {
              summary = 'Repair verified and request closed';
            }
            const note = event.details.reason || event.details.notes;
            return <li key={event.id}><strong>{summary}</strong><small>{event.actor_name} · {date(event.created_at)}</small>
              {note && <p className="description">{note}</p>}
            </li>;
          })}</ol>
        </>}
    </aside></div>
  </section>;
}
