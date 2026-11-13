import { useEffect, useState, type FormEvent } from 'react';
import { Icon } from './Icon';

type Branch = { id: string; name: string; location: string };
type ManagedUser = { id: string; full_name: string; email: string; role: string;
  is_active: boolean; branch_ids: string[] };
type Props = { token: string; branches: Branch[]; refreshBranches: () => Promise<void>;
  onExpired: () => void };

export function Admin({ token, branches, refreshBranches, onExpired }: Props) {
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  async function api(path: string, method = 'GET', body?: unknown) {
    const response = await fetch(`/api/admin${path}`, { method,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (response.status === 401) { onExpired(); throw new Error('Your session expired. Sign in again.'); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the form values and try again.');
    }
    return response.json();
  }

  async function loadUsers() { setUsers(await api('/users')); }
  useEffect(() => {
    let active = true;
    api('/users').then(data => { if (active) setUsers(data); })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [token]);

  async function mutate(action: () => Promise<void>, message: string) {
    setBusy(true); setError(''); setNotice('');
    try { await action(); setNotice(message); }
    catch (err) { setError(err instanceof TypeError ? 'Cannot reach the server. Try again.'
      : err instanceof Error ? err.message : 'Something went wrong.'); }
    finally { setBusy(false); }
  }

  function createBranch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void mutate(async () => {
      await api('/branches', 'POST', { name: data.get('name'), location: data.get('location') });
      await refreshBranches(); form.reset();
    }, 'Branch created. You now have access to it.');
  }

  function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void mutate(async () => {
      await api('/users', 'POST', { full_name: data.get('full_name'), email: data.get('email'),
        password: data.get('password'), role: data.get('role'), branch_ids: data.getAll('branch_ids') });
      form.reset(); await loadUsers();
    }, 'Account created. Share the credentials privately with the teammate.');
  }

  return <section className="admin-area" aria-labelledby="admin-title">
    <div className="section-heading"><div><p className="eyebrow">ADMINISTRATION</p>
      <h1 id="admin-title">People &amp; branches</h1>
      <p className="muted">Create branch records and manage who can access them.</p></div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    <div className="admin-grid">
      <section className="card"><div className="panel-heading"><span className="icon-tile"><Icon name="branch" /></span><div><h2>Create a branch</h2><p className="muted">Add a location to your workspace.</p></div></div><form onSubmit={createBranch}>
        <fieldset disabled={busy}><label htmlFor="branch-name">Branch name</label>
          <input id="branch-name" name="name" required maxLength={120} />
          <label htmlFor="branch-location">Location</label>
          <input id="branch-location" name="location" required maxLength={255} />
          <button>Create branch</button></fieldset></form>
      </section>
      <section className="card"><div className="panel-heading"><span className="icon-tile"><Icon name="people" /></span><div><h2>Create an account</h2><p className="muted">Set a role and assign branch access.</p></div></div><form onSubmit={createUser}>
        <fieldset disabled={busy || branches.length === 0}>
          <label htmlFor="full-name">Full name</label><input id="full-name" name="full_name" required maxLength={150} />
          <label htmlFor="new-email">Email</label><input id="new-email" name="email" type="email" autoComplete="off" required />
          <label htmlFor="new-password">Password</label>
          <input id="new-password" name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required aria-describedby="password-hint" />
          <p className="field-hint" id="password-hint">Use at least 12 characters.</p>
          <label htmlFor="new-role">Role</label><select id="new-role" name="role">
            <option value="employee">Employee</option><option value="technician">Technician</option></select>
          <BranchChecks branches={branches} />
          <p className="note">Select one branch for an employee. Technicians may work across several.</p>
          <button>Create account</button>
        </fieldset></form>
        {!branches.length && <p>Create a branch first.</p>}
      </section>
    </div>
    <section className="card user-list"><h2>Managed accounts</h2>
      <p className="muted">Employees and technicians whose branches are all within your access.</p>
      {loading ? <p role="status">Loading accounts…</p> : !users.length ? <p>No managed accounts yet.</p>
        : users.map(user => <article key={user.id} className="user-row">
          <div className="user-summary"><div><strong>{user.full_name}</strong><small>{user.email} · <span className="role">{user.role}</span></small></div><span className={`badge ${user.is_active ? 'priority-low' : 'priority-null'}`}>{user.is_active ? 'Active' : 'Disabled'}</span></div>
          <form onSubmit={event => {
            event.preventDefault(); const data = new FormData(event.currentTarget);
            void mutate(async () => {
              await api(`/users/${user.id}/branches`, 'PUT', { branch_ids: data.getAll('branch_ids') });
              await loadUsers();
            }, 'Branch access updated.');
          }}><fieldset disabled={busy}><BranchChecks branches={branches} selected={user.branch_ids} />
            <div className="actions"><button className="secondary">Save access</button>
              <button type="button" className="secondary" onClick={() => void mutate(async () => {
                await api(`/users/${user.id}/active`, 'PATCH', { is_active: !user.is_active });
                await loadUsers();
              }, user.is_active ? 'Account disabled.' : 'Account enabled.')}>{user.is_active ? 'Disable account' : 'Enable account'}</button>
            </div></fieldset></form>
        </article>)}
    </section>
  </section>;
}

function BranchChecks({ branches, selected = [] }: { branches: Branch[]; selected?: string[] }) {
  return <fieldset className="branch-checks"><legend>Branch access</legend>
    {branches.map(branch => <label key={branch.id}><input type="checkbox" name="branch_ids"
      value={branch.id} defaultChecked={selected.includes(branch.id)} />{branch.name}</label>)}
  </fieldset>;
}
