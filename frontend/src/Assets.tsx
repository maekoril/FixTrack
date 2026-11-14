import { useEffect, useState, type FormEvent } from 'react';
import { Icon } from './Icon';

type Asset = { id: string; asset_tag: string; name: string; branch_id: string; branch_name: string; location: string; condition: string };
type Detail = Asset & { total_cost: string; history: { id: string; title: string; status: string; created_at: string;
  orders: { technician: string; status: string; cost: string }[] }[] };

export function Assets({ token, branches, onExpired, onRequest }: {
  token: string; branches: { id: string; name: string }[]; onExpired: () => void; onRequest: (id: string) => void;
}) {
  const [items, setItems] = useState<Asset[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [selected, setSelected] = useState('');
  const [search, setSearch] = useState('');
  const [branch, setBranch] = useState('');
  const [offset, setOffset] = useState(0);
  const [historyOffset, setHistoryOffset] = useState(0);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [version, setVersion] = useState(0);
  async function api(path: string, method = 'GET', data?: unknown, signal?: AbortSignal) {
    const response = await fetch('/api/assets' + path, { method, signal,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(data ? { body: JSON.stringify(data) } : {}) });
    if (response.status === 401) { onExpired(); throw new Error('Sign in again.'); }
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Check the asset details.');
    return result;
  }
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const query = new URLSearchParams({ search, offset: String(offset) });
    if (branch) query.set('branch_id', branch);
    api(`?${query}`, 'GET', undefined, controller.signal).then(setItems)
      .catch(err => { if (!controller.signal.aborted) setError(err.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [token, branch, search, offset, version]);
  useEffect(() => {
    setDetail(null);
    if (!selected) return;
    const controller = new AbortController();
    api(`/${selected}?offset=${historyOffset}`, 'GET', undefined, controller.signal).then(setDetail)
      .catch(err => { if (!controller.signal.aborted) setError(err.message); });
    return () => controller.abort();
  }, [token, selected, historyOffset, version]);
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const asset = await api(creating ? '' : `/${selected}`, creating ? 'POST' : 'PATCH',
        Object.fromEntries(new FormData(event.currentTarget)));
      setSelected(asset.id); setCreating(false); setEditing(false); setVersion(v => v + 1);
    } catch (err) { setError(err instanceof Error ? err.message : 'Unable to save asset.'); }
    finally { setBusy(false); }
  }
  return <section className="assets-area">
    <div className="section-heading"><div><p className="eyebrow">Equipment & facilities</p><h1>Asset registry</h1>
      <p className="muted">A service record for every piece of equipment.</p></div>
      <button disabled={busy || !branches.length} onClick={() => { setCreating(true); setEditing(false); }}>
        <Icon name="plus" size={18} />Register asset</button></div>
    {error && <p role="alert" className="error">{error}</p>}
    <div className="card asset-filters">
      <div><label htmlFor="asset-search">Find equipment</label><input id="asset-search" type="search" value={search}
        placeholder="Search name or asset tag" onChange={e => { setSearch(e.target.value); setOffset(0); }} /></div>
      <div><label htmlFor="asset-branch">Branch</label><select id="asset-branch" value={branch} onChange={e => { setBranch(e.target.value); setOffset(0); }}>
        <option value="">All branches</option>{branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></div>
    </div>
    {(creating || (editing && detail)) && <section className="card report-form">
      <h2>{creating ? 'Register equipment' : 'Edit asset'}</h2>
      <form key={creating ? 'new' : selected} onSubmit={save}><fieldset disabled={busy}>
        {creating && <><label htmlFor="new-asset-branch">Branch</label><select id="new-asset-branch" name="branch_id" required>
          {branches.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}</select></>}
        <div className="form-columns">{([
          ['asset_tag', 'Asset tag', 80], ['name', 'Equipment name', 150], ['location', 'Location', 255], ['condition', 'Condition', 80],
        ] as const).map(([field, label, max]) => <div key={field}><label htmlFor={`asset-${field}`}>{label}</label>
          <input id={`asset-${field}`} name={field} maxLength={max} required={field !== 'location'} defaultValue={creating ? '' : detail?.[field]} /></div>)}</div>
        <div className="actions"><button>{busy ? 'Saving…' : 'Save asset'}</button><button className="secondary" type="button" onClick={() => { setCreating(false); setEditing(false); }}>Cancel</button></div>
      </fieldset></form></section>}
    <div className="request-layout">
      <section className="card queue"><div className="queue-heading"><h2>Equipment</h2><span className="count">{items.length} on this page</span></div>
        {loading ? <p className="empty-state" role="status">Loading equipment…</p> : !items.length ? <div className="empty-state"><Icon name="asset" /><h3>No assets found</h3><p>Register equipment or adjust your filters.</p></div>
          : <div className="request-list">{items.map(asset => <button key={asset.id} className={`request-item ${selected === asset.id ? 'selected' : ''}`}
            onClick={() => { setSelected(asset.id); setHistoryOffset(0); setEditing(false); }} aria-pressed={selected === asset.id}>
            <span className="request-meta"><span className="reference">{asset.asset_tag}</span><span className="badge">{asset.condition}</span></span>
            <strong className="request-title">{asset.name}<Icon name="arrow" size={16} /></strong><span className="muted">{asset.branch_name} · {asset.location || 'Location unspecified'}</span>
          </button>)}</div>}
        <div className="pagination"><button className="secondary" disabled={!offset || loading} onClick={() => setOffset(offset - 25)}>Previous</button><span>Page {offset / 25 + 1}</span><button className="secondary" disabled={items.length < 25 || loading} onClick={() => setOffset(offset + 25)}>Next</button></div>
      </section>
      <aside className="card request-detail" aria-label="Asset details">
        {!detail ? <div className="empty-state"><span className="icon-tile"><Icon name="asset" /></span><h2>{selected ? 'Loading asset…' : 'Select equipment'}</h2><p>Inspect its service history and recorded costs.</p></div> : <>
          <p className="eyebrow">{detail.asset_tag}</p><h2>{detail.name}</h2>
          <span className="badge">{detail.condition}</span>
          <dl><dt>Branch</dt><dd>{detail.branch_name}</dd><dt>Location</dt><dd>{detail.location || 'Unspecified'}</dd><dt>Total recorded repair costs</dt><dd>{detail.total_cost}</dd></dl>
          <button className="secondary" onClick={() => { setCreating(false); setEditing(true); }}>Edit asset</button>
          <h3 className="history-heading">Repair history</h3>
          {!detail.history.length && <p className="muted">No linked requests on this page.</p>}
          <ol className="timeline">{detail.history.map(request => <li key={request.id}>
            <button className="history-link" onClick={() => onRequest(request.id)}>{request.title}<Icon name="arrow" size={16} /></button>
            <small>{new Date(request.created_at).toLocaleDateString()} · {request.status.replaceAll('_', ' ')}</small>
            {request.orders.map((order, index) => <p key={index} className="description">{order.technician} · {order.status.replaceAll('_', ' ')} · {order.cost}</p>)}
          </li>)}</ol>
          <div className="pagination"><button className="secondary" disabled={!historyOffset} onClick={() => setHistoryOffset(historyOffset - 25)}>Previous</button>
            <button className="secondary" disabled={detail.history.length < 25} onClick={() => setHistoryOffset(historyOffset + 25)}>Next</button></div>
        </>}
      </aside>
    </div>
  </section>;
}
