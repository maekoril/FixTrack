import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Icon } from './Icon';
import { Chip, DataRow, EmptyState, PageHeader, Skeleton } from './UI';
import { formatDate, formatDateTime as date, formatMoney } from './format';
import { queues, type QueueFocus } from './Dashboard';
import { pollWhileVisible } from './liveUpdates';
import { PhotoGallery, photoTypes, uploadPhoto, type Photo } from './Photos';
import { RequestIntakeForm, IntakeDetails, type IntakeDraft, type SavedIntake } from './RequestIntake';
import { setupSavedMessage } from './planning';
import {
  AssignmentFields, RequestSetup, WorkOrderSummary, appointmentLabel, difficultyLabel,
  type Difficulty, type ServiceCategory, type TechnicianOption, type WorkOrder, type WorkSchedule,
} from './WorkOrderPlanning';

type Branch = { id: string; name: string };
type Asset = { id: string; name: string; asset_tag: string };
type ServiceEstimate = { difficulty: Difficulty | null; duration_override_minutes: number | null };
type ServiceRequest = { id: string; title: string; description: string; location: string;
  branch_name: string; submitted_by_name: string; status: string; priority: string | null;
  created_at: string; asset_name: string | null; category: ServiceCategory | null;
  intake: SavedIntake | null; safety_flags: string[]; incomplete_info: boolean;
  estimated_duration_minutes: number | null; setup_missing?: string[] | null } & ServiceEstimate;
type Detail = ServiceRequest & {
  setup_duration_suggestions?: Record<string, Partial<Record<Difficulty, number>>> | null;
  photos: Photo[];
  eligible_technicians: TechnicianOption[] | null;
  appointment: WorkSchedule | null;
  work_orders: WorkOrder[];
  maintenance_logs: { id: string; work_order_id: string; action: string; notes: string;
    recorded_by_name: string; created_at: string }[];
  events: { id: string; action: string; actor_name: string;
    created_at: string; details: { from?: string | null; to?: string | null; technician_name?: string;
      reason?: string; notes?: string; work_order_id?: string; previous_technician_name?: string;
      previous?: ServiceEstimate; updated?: ServiceEstimate; assistants?: string[];
      price?: { version?: number; amount: string };
      approval?: { quote: { version?: number; amount: string } };
      scheduled_start?: string | null; scheduled_end?: string | null } }[];
};
type Props = { token: string; role: string; userId: string; branches: Branch[]; onExpired: () => void;
  openedRequest: { id: string }; initialFocus: QueueFocus | ''; initialBranch: string };
const pageSize = 25;
const label = (value: string) => value.replaceAll('_', ' ');
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

export function Requests({ token, role, userId, branches, onExpired, openedRequest, initialFocus, initialBranch }: Props) {
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
  const [categoryFilter, setCategoryFilter] = useState('');
  const [categories, setCategories] = useState<ServiceCategory[] | null>(null);
  const [categoryListError, setCategoryListError] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);
  const [version, setVersion] = useState(0);
  const [loading, setLoading] = useState(true);
  const [queueError, setQueueError] = useState('');
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
    setStatus(''); setPriority(''); setCategoryFilter(''); setSearch(''); setOffset(0);
  }, [initialFocus, initialBranch]);

  useEffect(() => {
    if (role !== 'administrator') return;
    const controller = new AbortController();
    setCategoryListError('');
    api('/categories', 'GET', undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) setCategories(result); })
      .catch(() => {
        if (!controller.signal.aborted) setCategoryListError('Unable to load categories. Select Refresh to try again.');
      });
    return () => controller.abort();
  }, [role, token, version]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setQueueError('');
    const query = new URLSearchParams({ offset: String(offset), limit: String(pageSize), search });
    if (branch) query.set('branch_id', branch);
    if (status) query.set('status', status);
    if (priority) query.set('priority', priority);
    if (categoryFilter) query.set('category_id', categoryFilter);
    if (focus) query.set('focus', focus);
    let pending = false;
    async function refresh(background = false) {
      if (pending) return;
      pending = true;
      try {
        const result = await api(`?${query}`, 'GET', undefined, controller.signal);
        if (!controller.signal.aborted) { setItems(result); setQueueError(''); }
      } catch (err) {
        if (!background && !controller.signal.aborted && err instanceof Error) {
          setItems([]); setQueueError(err.message);
        }
      } finally {
        pending = false;
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void refresh();
    const stop = pollWhileVisible(() => refresh(true));
    return () => { controller.abort(); stop(); };
  }, [branch, status, priority, categoryFilter, search, focus, offset, version, token]);

  useEffect(() => {
    setDetail(current => current?.id === selected ? current : null);
    setDetailFailed(false);
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

  async function submit(data: IntakeDraft) {
    setBusy(true); setError(''); setNotice('');
    try {
      const { photo: issuePhoto, ...payload } = data;
      const request: ServiceRequest = await api('', 'POST', payload);
      setShowForm(false); setBranch(''); setStatus(''); setPriority(''); setSearch(''); setOffset(0);
      setSelected(request.id);
      detailPanel.current?.focus();
      setNotice('Request submitted. Your administrator can now review it.');
      const photo = issuePhoto;
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

  async function saveSetup(data: unknown) {
    if (!detail || detail.id !== selected || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const saved: ServiceRequest = await api(`/${detail.id}/setup`, 'PATCH', data);
      setVersion(v => v + 1);
      setNotice(setupSavedMessage(saved.setup_missing ?? []));
    } finally { setBusy(false); }
  }

  async function confirmIntake(category: string, priority: string) {
    if (!detail || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/${detail.id}/triage-confirmation`, 'PATCH', {category, priority});
      setVersion(value => value + 1); setNotice('Intake confirmation saved.');
    } finally { setBusy(false); }
  }

  async function updateWork(workOrderId: string, operation: 'start' | 'logs' | 'complete' | 'price/approve', data?: unknown) {
    if (!detail || detail.id !== selected || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await api(`/${detail.id}/work-orders/${workOrderId}/${operation}`, 'POST', data);
      setVersion(v => v + 1);
      setNotice({
        start: 'Work started. The request is now in progress.',
        logs: 'Maintenance entry added.',
        complete: 'Work completed. The request is awaiting administrator verification.',
        'price/approve': 'Budget approved. This version is preserved for cost comparison.',
      }[operation]);
      return true;
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to update work order.'); }
    finally { setBusy(false); }
  }

  async function submitWork(event: FormEvent<HTMLFormElement>, orderId: string, operation: 'logs' | 'complete') {
    event.preventDefault();
    const form = event.currentTarget;
    const saved = await updateWork(orderId, operation, Object.fromEntries(new FormData(form)));
    if (saved && operation === 'logs') form.reset();
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

  async function addIssuePhoto(photo: File) {
    if (!detail || detail.id !== selected || busy) return;
    setBusy(true); setError(''); setNotice('');
    try {
      await uploadPhoto(token, detail.id, photo);
      setVersion(value => value + 1); setNotice('Photo added.');
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to upload photo.'); }
    finally { setBusy(false); }
  }

  async function reviewWork(event: FormEvent<HTMLFormElement>, decision: 'verify' | 'return') {
    event.preventDefault();
    const order = detail?.work_orders.at(-1);
    if (!detail || detail.id !== selected || !order || busy) return;
    const data = new FormData(event.currentTarget);
    const fields = decision === 'verify' ? { notes: data.get('notes') } : {
      technician_id: data.get('technician_id'), assistant_ids: data.getAll('assistant_ids'), reason: data.get('reason'),
    };
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
    <PageHeader id="requests-title" title={role === 'branch_manager' ? 'My requests' : role === 'technician' ? 'Assigned requests' : 'Service requests'} description={role === 'branch_manager' ? 'Report equipment and facility issues and follow their progress.' : role === 'technician' ? 'Review service requests linked to your assigned work.' : 'Review branch issues, set priorities, and follow each request’s history.'}>
      <button className="secondary" disabled={loading || busy} onClick={() => setVersion(v => v + 1)}><Icon name="refresh" size={17} />Refresh</button>
      {role === 'branch_manager' && <button ref={reportButton} className={showForm ? 'secondary' : undefined} aria-expanded={showForm} disabled={!branches.length || busy} onClick={() => setShowForm(!showForm)}>{showForm ? 'Cancel' : <><Icon name="plus" size={18} />Report an issue</>}</button>}
    </PageHeader>
    {error && <p className="error" role="alert">{error}</p>}
    {queueError && <p className="error" role="alert">{queueError}</p>}
    {categoryListError && <p className="error" role="alert">{categoryListError}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {showForm && <section className="card report-form" aria-labelledby="report-title">
      <div className="panel-heading"><span className="icon-tile"><Icon name="plus" /></span><div><h2 ref={reportHeading} tabIndex={-1} id="report-title">Report an issue</h2><p className="muted">Add enough detail for your administrator to review the issue.</p></div></div>
      <RequestIntakeForm token={token} branches={branches} branch={formBranch} assets={assets}
        busy={busy} onBranch={setFormBranch} onSubmit={submit} onExpired={onExpired}
        onCancel={() => { setShowForm(false); reportButton.current?.focus(); }} />
    </section>}
    {focus && <div className="dashboard-queue-filter">
      <span className="badge">{queues[focus].label}</span>
      <button className="secondary" onClick={() => {
        setFocus(''); setOffset(0);
        const query = branch ? `?${new URLSearchParams({ branch_id: branch })}` : '';
        window.location.hash = `#requests${query}`;
      }}>Clear dashboard filter</button>
    </div>}
    <div className={`card request-filters${role === 'administrator' ? ' request-filters-with-category' : ''}`}>
      <div><label htmlFor="filter-search">Search title</label><div className="search-field"><Icon name="search" size={18} /><input id="filter-search" type="search" maxLength={180} value={search} placeholder="Search…" onChange={event => { setSearch(event.target.value); setOffset(0); }} /></div></div>
      <div><label htmlFor="filter-branch">Branch</label><select id="filter-branch" value={branch} onChange={event => { setBranch(event.target.value); setOffset(0); }}><option value="">All branches</option>{branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
      <div><label htmlFor="filter-status">Status</label><select id="filter-status" value={status} onChange={event => { setStatus(event.target.value); setOffset(0); }}><option value="">All statuses</option>
        {['submitted', 'in_progress', 'awaiting_verification', 'closed'].map(value => <option key={value} value={value}>{label(value)}</option>)}</select></div>
      <div><label htmlFor="filter-priority">Priority</label><select id="filter-priority" value={priority} onChange={event => { setPriority(event.target.value); setOffset(0); }}><option value="">All priorities</option>
        {['low', 'medium', 'high', 'urgent'].map(value => <option key={value} value={value}>{value}</option>)}</select></div>
      {role === 'administrator' && <div>
        <label htmlFor="filter-category">Category</label>
        <select id="filter-category" value={categoryFilter} disabled={!categories}
          onChange={event => { setCategoryFilter(event.target.value); setOffset(0); }}>
          <option value="">All categories</option>
          <option value="uncategorized">Uncategorized</option>
          {categories?.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}
        </select>
      </div>}
    </div>
    <div className="request-layout"><div className="card queue">
      <div className="queue-heading"><h2 ref={queueHeading} tabIndex={-1}>Request queue</h2><span className="count">{loading ? 'Loading' : `${items.length} on this page`}</span></div>
      {loading ? <Skeleton label="Loading requests…" /> : !items.length ? <EmptyState icon="requests" title="No requests found">
        {search || branch || status || priority || categoryFilter ? 'Try changing your search or filters.' : role === 'branch_manager' ? 'Your reports will appear here once submitted.' : 'Requests will appear here when they’re available to you.'}
      </EmptyState> : <div className="request-list">{items.map(item =>
        <DataRow key={item.id} ref={selected === item.id ? selectedButton : null}
          className={`queue-item ${selected === item.id ? 'selected' : ''} ${item.safety_flags?.length ? 'queue-hazard' : ''}`}
          onClick={() => { setSelected(item.id); setError(''); detailPanel.current?.focus(); }} aria-pressed={selected === item.id}>
          <strong className="request-title">{item.title}<Icon name="arrow" size={16} /></strong>
          <span className="request-location">{item.branch_name} · {item.location} · {item.category?.name ?? 'Uncategorized'}</span>
          <span className="request-meta">
            <span className="queue-chips"><Chip tone={`priority-${item.priority}`}>{item.priority ?? 'Not prioritized'}</Chip>
              <Chip tone={`status-${item.status}`}>{label(item.status)}</Chip>
              {!!item.safety_flags?.length && <Chip tone="priority-urgent">Safety flagged</Chip>}
              {item.incomplete_info && <Chip tone="status-awaiting_verification">Incomplete info</Chip>}
              {role === 'administrator' && !!item.setup_missing?.length && <Chip tone="status-awaiting_verification">
                Needs setup · {item.setup_missing.length}
                <span className="sr-only">Missing {item.setup_missing.join(', ')}</span>
              </Chip>}</span>
            <span className="queue-reference"><span className="reference">#{item.id.slice(0, 8).toUpperCase()}</span><span>{formatDate(item.created_at)}</span></span>
          </span>
          {role === 'administrator' && !!item.setup_missing?.length && <small className="queue-setup-remaining">Still needed: {item.setup_missing.join(', ')}</small>}
          {role === 'administrator' && item.setup_missing?.length === 0 && ['submitted', 'in_progress'].includes(item.status) && <Chip tone="status-closed">Setup complete</Chip>}
        </DataRow>)}</div>}
      <div className="pagination"><button className="secondary" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - pageSize))}>Previous</button><span>Page {offset / pageSize + 1}</span>
        <button className="secondary" disabled={items.length < pageSize || loading} onClick={() => setOffset(offset + pageSize)}>Next</button></div>
    </div><aside ref={detailPanel} tabIndex={-1} className="card request-detail" aria-label="Request details">
      {selected && <button className="secondary back-to-queue" onClick={() => { setSelected(''); (selectedButton.current ?? queueHeading.current)?.focus(); }}><Icon name="back" size={16} />Back to queue</button>}
      {!selected ? <EmptyState icon="requests" title="Select a request">See its details and activity history.</EmptyState>
        : detailFailed ? <p>Unable to load this request. Select Refresh to try again.</p>
        : detail?.id !== selected ? <Skeleton label="Loading details…" /> : <>
          <p className="reference">#{detail.id.slice(0, 8).toUpperCase()}</p><h2>{detail.title}</h2>
          <div className="actions"><span className={`badge status-${detail.status}`}>{label(detail.status)}</span><span className={`badge priority-${detail.priority}`}>{detail.priority ?? 'Not prioritized'}</span></div>
          <dl>
            <dt>Branch / location</dt><dd>{detail.branch_name} · {detail.location}</dd>
            <dt>Category</dt><dd>{detail.category?.name ?? 'Uncategorized'}</dd>
            <dt>Difficulty</dt><dd>{detail.difficulty ? difficultyLabel(detail.difficulty) : 'Not set'}</dd>
            <dt>Estimated duration</dt>
            <dd>{detail.estimated_duration_minutes === null ? 'Not set'
              : `${detail.estimated_duration_minutes} min (${detail.duration_override_minutes === null ? 'suggested' : 'manual'})`}</dd>
            {detail.appointment && <><dt>Scheduled service</dt><dd>{appointmentLabel(detail.appointment)}</dd></>}
            <dt>Related asset</dt><dd>{detail.asset_name ?? 'General facility issue / no registered asset'}</dd>
            <dt>Reported by</dt><dd>{detail.submitted_by_name}</dd><dt>Submitted</dt><dd>{date(detail.created_at)}</dd>
          </dl>
          {detail.intake ? <IntakeDetails key={detail.id}
            intake={detail.intake} canEdit={detail.status !== 'awaiting_verification' && (role === 'administrator' || role === 'branch_manager')} busy={busy} onConfirm={confirmIntake} />
            : <><h3>Description</h3><p className="description">{detail.description}</p></>}
          <PhotoGallery key={`photos-${detail.id}`} token={token} requestId={detail.id} photos={detail.photos}
            busy={busy} onAdd={role === 'branch_manager' && detail.status !== 'closed' ? addIssuePhoto : undefined} />
          {role === 'administrator' && detail.status === 'awaiting_verification' &&
            <p className="muted">Job details are locked while awaiting verification. Verify the repair or return it for follow-up to make changes.</p>}
          {role === 'administrator' && ['submitted', 'in_progress'].includes(detail.status) && detail.eligible_technicians && (
            <RequestSetup key={JSON.stringify([detail.id, detail.priority, detail.category, detail.difficulty,
              detail.duration_override_minutes, detail.work_orders])} request={detail}
              order={[...detail.work_orders].reverse().find(order => order.status !== 'completed')}
              canAssign={detail.status === 'submitted' && !detail.work_orders.length}
              categories={categories} options={detail.eligible_technicians} busy={busy} onSave={saveSetup}
              onSuggest={() => api(`/${detail.id}/ai/estimate`, 'POST')} />
          )}
          {detail.work_orders.length > 0 && <section>
            <h3>Work orders</h3>
            {detail.work_orders.map(order => <section key={order.id} className="work-order">
              <span className={`badge status-${order.status}`}>{label(order.status)}</span>
              <WorkOrderSummary order={order} />
              {role === 'administrator' && order.status !== 'completed' && order.price_estimate &&
                (!order.approved_price || (order.approved_price.quote.version ?? 0) !== (order.price_estimate.version ?? 0)) &&
                <button type="button" disabled={busy} onClick={() => updateWork(order.id, 'price/approve',
                  { version: order.price_estimate!.version ?? 0 })}>
                  Approve estimate of {formatMoney(order.price_estimate.amount)}
                </button>}
              {detail.events.filter(event => event.action === 'work_returned' &&
                event.details.work_order_id === order.id).map(event =>
                <div key={event.id}><h4>Follow-up instructions</h4><p className="description">{event.details.reason}</p></div>)}
              {role === 'technician' && order.technician_id === userId && ['submitted', 'in_progress'].includes(detail.status) && order.status === 'assigned' && (
                <button type="button" disabled={busy} onClick={() => updateWork(order.id, 'start')}>Start work</button>
              )}
              {order.status === 'completed' && <dl>
                <dt>Labor cost</dt><dd>{formatMoney(order.labor_cost)}</dd>
                <dt>Materials cost</dt><dd>{formatMoney(order.materials_cost)}</dd>
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
                {order.technician_id === userId && <form onSubmit={event => submitWork(event, order.id, 'complete')}>
                  <fieldset disabled={busy}>
                    <legend>Complete work order</legend>
                    <label htmlFor={`labor-${order.id}`}>Labor cost</label>
                    <input id={`labor-${order.id}`} name="labor_cost" type="number" min="0" max="9999999999.99" step="0.01" defaultValue={order.labor_cost} required />
                    <label htmlFor={`materials-${order.id}`}>Materials cost</label>
                    <input id={`materials-${order.id}`} name="materials_cost" type="number" min="0" max="9999999999.99" step="0.01" defaultValue={order.materials_cost} required />
                    <label htmlFor={`overrun-${order.id}`}>Cost explanation (required when over approved budget)</label>
                    <textarea id={`overrun-${order.id}`} name="overrun_reason" maxLength={10000} rows={3}
                      aria-describedby={`overrun-hint-${order.id}`} />
                    <p id={`overrun-hint-${order.id}`} className="field-hint">{order.approved_price
                      ? `Approved budget: ${formatMoney(order.approved_price.quote.amount)}. Explain any additional labor or materials if the actual total exceeds it.`
                      : 'No approved budget is recorded. You can still explain the actual costs.'}</p>
                    <button>Submit for verification</button>
                  </fieldset>
                </form>}
              </>}
            </section>)}
          </section>}
          {role === 'administrator' && detail.status === 'awaiting_verification' && <section key={detail.work_orders.at(-1)?.id}>
            <h3>Review completed work</h3>
            <p className="muted">Review the work logs, repair photos, and actual costs before verifying or returning the repair.</p>
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
                  <AssignmentFields id="follow-up-technician" options={detail.eligible_technicians}
                    defaultLead={detail.eligible_technicians.some(technician =>
                      technician.id === detail.work_orders.at(-1)?.technician_id)
                      ? detail.work_orders.at(-1)?.technician_id : ''} />
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
            } else if (event.action === 'category_changed') {
              summary = `Category changed from ${event.details.from ?? 'Uncategorized'} to ${event.details.to ?? 'Uncategorized'}`;
            } else if (event.action === 'estimate_changed' && event.details.updated) {
              const { difficulty, duration_override_minutes } = event.details.updated;
              const estimate = duration_override_minutes === null ? 'Automatic duration' : `${duration_override_minutes} min (manual)`;
              summary = `Service estimate updated · ${difficulty ? difficultyLabel(difficulty) : 'Difficulty unset'} · ${estimate}`;
            } else if (event.action === 'work_order_assigned') {
              summary = `Assigned to ${event.details.technician_name}`;
            } else if (event.action === 'work_completed') {
              summary = 'Work completed and submitted for verification';
            } else if (event.action === 'work_returned') {
              summary = `Returned for follow-up and assigned to ${event.details.technician_name}`;
            } else if (event.action === 'work_reassigned') {
              summary = `Reassigned from ${event.details.previous_technician_name} to ${event.details.technician_name}`;
            } else if (event.action === 'work_team_changed') {
              summary = event.details.assistants?.length
                ? `Supporting technicians updated to ${event.details.assistants.join(', ')}`
                : 'Supporting technicians removed';
            } else if (event.action === 'work_schedule_changed') {
              summary = event.details.scheduled_start && event.details.scheduled_end
                ? `Work scheduled for ${appointmentLabel({ scheduled_start: event.details.scheduled_start, scheduled_end: event.details.scheduled_end })}`
                : 'Work schedule cleared';
            } else if (event.action === 'work_price_changed') {
              summary = event.details.price ? `Estimate v${event.details.price.version ?? 0} saved · ${formatMoney(event.details.price.amount)}`
                : 'Work order price estimate updated';
            } else if (event.action === 'work_price_approved') {
              summary = event.details.approval ? `Budget v${event.details.approval.quote.version ?? 0} approved · ${formatMoney(event.details.approval.quote.amount)}`
                : 'Work order budget approved';
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
