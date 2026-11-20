import { useEffect, useState, type FormEvent } from 'react';
import { Icon } from './Icon';
import { Button, Chip, ConfirmDialog, Drawer, EmptyState, PageHeader, RoleBadge, Skeleton } from './UI';

type Branch = { id: string; name: string; location: string };
type ServiceCategory = { id: string; name: string };
type ManagedUser = { id: string; full_name: string; email: string; role: string;
  is_active: boolean; branch_ids: string[]; specialization: string | null };
type Props = { token: string; branches: Branch[]; refreshBranches: () => Promise<void>;
  onExpired: () => void };

export function Admin({ token, branches, refreshBranches, onExpired }: Props) {
  const [dialog, setDialog] = useState<'branch' | 'account' | null>(null);
  const [confirm, setConfirm] = useState<ManagedUser | null>(null);
  const [confirmKind, setConfirmKind] = useState<'status' | 'delete'>('status');
  const [editing, setEditing] = useState('');
  const [search, setSearch] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState('');
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [categories, setCategories] = useState<ServiceCategory[] | null>(null);
  const [categoryError, setCategoryError] = useState('');
  const [newRole, setNewRole] = useState('branch_manager');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  async function api(path: string, method = 'GET', body?: unknown) {
    const response = await fetch(`/api${path}`, { method,
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
    if (response.status === 401) { onExpired(); throw new Error('Your session expired. Sign in again.'); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Check the form values and try again.');
    }
    return response.status === 204 ? null : response.json();
  }

  async function loadUsers() { setUsers(await api('/admin/users')); }
  useEffect(() => {
    let active = true;
    api('/admin/users').then(data => { if (active) setUsers(data); })
      .catch(err => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    api('/requests/categories').then(data => { if (active) setCategories(data); })
      .catch(() => {
        if (active) setCategoryError('Unable to load specializations. Reload this page to try again.');
      });
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
      await api('/admin/branches', 'POST', { name: data.get('name'), location: data.get('location') });
      await refreshBranches(); form.reset(); setDialog(null);
    }, 'Branch created. You now have access to it.');
  }

  function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
    void mutate(async () => {
      await api('/admin/users', 'POST', { full_name: data.get('full_name'), email: data.get('email'),
        password: data.get('password'), role: data.get('role'), branch_ids: data.getAll('branch_ids'),
        specialization: data.get('specialization') || null });
      form.reset(); setNewRole('branch_manager'); await loadUsers(); setDialog(null);
    }, 'Account created. Share the credentials privately with the teammate.');
  }

  const normalizedSearch = search.trim().toLowerCase();
  const visible = users.filter(user => (!role || user.role === role)
    && (!status || user.is_active === (status === 'active'))
    && [user.full_name, user.email].some(value => value.toLowerCase().includes(normalizedSearch)));

  function closeDialog() { setDialog(null); setConfirm(null); setError(''); }

  return <section className="admin-area" aria-labelledby="admin-title">
    <PageHeader id="admin-title" title="People & branches" description="Manage teammates, roles, and branch access.">
      <Button variant="secondary" onClick={() => { setError(''); setDialog('branch'); }} disabled={busy}><Icon name="branch" size={17} />New branch</Button>
      <Button onClick={() => { setError(''); setNewRole('branch_manager'); setDialog('account'); }} disabled={busy}><Icon name="plus" size={17} />New account</Button>
    </PageHeader>
    {!dialog && !confirm && error && <p className="error" role="alert">{error}</p>}
    {categoryError && <p className="error" role="alert">{categoryError}</p>}
    {notice && <p className="success" role="status">{notice}</p>}
    {dialog && <Drawer title={dialog === 'branch' ? 'New branch' : 'New account'} busy={busy} onClose={closeDialog}>
      {error && <p className="error" role="alert">{error}</p>}
      {dialog === 'branch' ? <form onSubmit={createBranch}>
        <fieldset disabled={busy}><label htmlFor="branch-name">Branch name</label>
          <input id="branch-name" name="name" required maxLength={120} />
          <label htmlFor="branch-location">Location</label>
          <input id="branch-location" name="location" required maxLength={255} />
          <button>{busy ? 'Creating…' : 'Create branch'}</button></fieldset></form> : <>
        {categoryError && <p className="error" role="alert">{categoryError}</p>}
        <form onSubmit={createUser}>
        <fieldset disabled={busy || branches.length === 0}>
          <label htmlFor="full-name">Full name</label><input id="full-name" name="full_name" required maxLength={150} />
          <label htmlFor="new-email">Email</label><input id="new-email" name="email" type="email" autoComplete="off" required />
          <label htmlFor="new-password">Password</label>
          <input id="new-password" name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required aria-describedby="password-hint" />
          <p className="field-hint" id="password-hint">Use at least 12 characters.</p>
          <label htmlFor="new-role">Role</label><select id="new-role" name="role" value={newRole}
            onChange={event => setNewRole(event.target.value)}>
            <option value="branch_manager">Branch Manager</option><option value="technician">Technician</option></select>
          {newRole === 'technician' && categories &&
            <SpecializationSelect id="new-specialization" categories={categories} />}
          <BranchChecks branches={branches} />
          <p className="note">Select at least one branch.</p>
          <button>{busy ? 'Creating…' : 'Create account'}</button>
        </fieldset></form>
        {!branches.length && <p className="note">Create a branch first.</p>}
      </>}
    </Drawer>}
    {confirm && confirmKind === 'delete' && <ConfirmDialog title="Delete account?"
      description={`Permanently delete ${confirm.full_name} (${confirm.email})? This cannot be undone. Accounts with recorded activity must be disabled instead.`}
      confirmLabel={busy ? 'Deleting…' : 'Delete account'} busy={busy} error={error} onCancel={closeDialog}
      onConfirm={() => void mutate(async () => {
        await api(`/admin/users/${confirm.id}`, 'DELETE');
        setEditing(current => current === confirm.id ? '' : current);
        await loadUsers(); setConfirm(null);
      }, 'Account deleted.')} />}
    {confirm && confirmKind === 'status' && <Drawer title={confirm.is_active ? 'Disable account?' : 'Enable account?'} busy={busy} onClose={closeDialog}>
      {error && <p className="error" role="alert">{error}</p>}
      <p><strong>{confirm.full_name}</strong> {confirm.is_active ? 'will lose access to FixTrack.' : 'will regain access to their assigned branches.'}</p>
      <div className="actions confirm-actions">
        <Button variant="secondary" disabled={busy} onClick={closeDialog}>Cancel</Button>
        <Button variant={confirm.is_active ? 'danger' : undefined} disabled={busy} onClick={() => void mutate(async () => {
          await api(`/admin/users/${confirm.id}/active`, 'PATCH', { is_active: !confirm.is_active });
          await loadUsers(); setConfirm(null);
        }, confirm.is_active ? 'Account disabled.' : 'Account enabled.')}>
          {busy ? 'Saving…' : confirm.is_active ? 'Disable account' : 'Enable account'}
        </Button>
      </div>
    </Drawer>}
    <section className="card user-list" aria-labelledby="accounts-title">
      <header className="queue-heading"><h2 id="accounts-title">Managed accounts</h2>
        {!loading && <span className="count">{visible.length} {visible.length === 1 ? 'account' : 'accounts'} · {visible.filter(user => user.is_active).length} active</span>}
      </header>
      <div className="account-filters">
        <div><label htmlFor="account-search">Search accounts</label><div className="search-field"><Icon name="search" size={17} />
          <input id="account-search" type="search" placeholder="Name or email" value={search} onChange={event => setSearch(event.target.value)} />
        </div></div>
        <div><label htmlFor="account-role">Role</label><select id="account-role" value={role} onChange={event => setRole(event.target.value)}>
          <option value="">All roles</option><option value="branch_manager">Branch Manager</option><option value="technician">Technician</option>
          {users.some(user => user.role === 'administrator') && <option value="administrator">Administrator</option>}
        </select></div>
        <div><label htmlFor="account-status">Status</label><select id="account-status" value={status} onChange={event => setStatus(event.target.value)}>
          <option value="">All statuses</option><option value="active">Active</option><option value="disabled">Disabled</option>
        </select></div>
      </div>
      {loading ? <Skeleton label="Loading accounts…" /> : !visible.length ? <EmptyState icon="people" title={users.length ? 'No matching accounts' : 'No managed accounts yet'}>
        {users.length ? <Button variant="secondary" onClick={() => { setSearch(''); setRole(''); setStatus(''); }}>Clear filters</Button>
          : <Button variant="secondary" onClick={() => { setError(''); setNewRole('branch_manager'); setDialog('account'); }}>New account</Button>}
      </EmptyState> : <>
        <div className="account-columns account-labels" aria-hidden="true"><span>Account</span><span>Role</span><span>Status</span><span>Branch access</span><span>Actions</span></div>
        <ul className="account-list">{visible.map(user => {
          const granted = branches.filter(branch => user.branch_ids.includes(branch.id));
          const hidden = granted.slice(2);
          const expanded = editing === user.id;
          return <li key={user.id} className={`account-record${user.is_active ? '' : ' account-disabled'}`}>
            <div className="account-columns account-row">
              <div className="account-identity">
                <span className="avatar" aria-hidden="true">{user.full_name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('')}</span>
                <div><strong>{user.full_name}</strong><small>{user.email}</small></div>
              </div>
              <div><RoleBadge role={user.role} /></div>
              <div><Chip tone={user.is_active ? 'status-active' : ''}>{user.is_active ? 'Active' : 'Disabled'}</Chip></div>
              <div className="branch-chips">
                {granted.slice(0, 2).map(branch => <Chip key={branch.id} tone="branch-chip">{branch.name}</Chip>)}
                {hidden.length > 0 && <details className="row-disclosure branch-overflow" onKeyDown={event => {
                  if (event.key === 'Escape') {
                    event.currentTarget.open = false;
                    event.currentTarget.querySelector('summary')?.focus();
                  }
                }}>
                  <summary title={hidden.map(branch => branch.name).join(', ')} aria-label={`Show ${hidden.length} more branches for ${user.full_name}`}>+{hidden.length}</summary>
                  <ul className="row-popover">{hidden.map(branch => <li key={branch.id}>{branch.name}</li>)}</ul>
                </details>}
                {!granted.length && <span className="muted">None</span>}
              </div>
              <div className="account-actions">
                <Button type="button" variant="secondary" id={`access-${user.id}`} aria-expanded={expanded}
                  aria-controls={expanded ? `editor-${user.id}` : undefined} disabled={busy}
                  onClick={() => { setError(''); setEditing(expanded ? '' : user.id); }}>Edit account</Button>
                <details className="row-disclosure account-menu" onKeyDown={event => {
                  if (event.key === 'Escape') {
                    event.currentTarget.open = false;
                    event.currentTarget.querySelector('summary')?.focus();
                  }
                }}>
                  <summary aria-label={`Actions for ${user.full_name}`} title={`Actions for ${user.full_name}`}><Icon name="more" size={18} /></summary>
                  <div className="row-popover">
                    <Button variant={user.is_active ? 'danger' : 'secondary'} disabled={busy} onClick={event => {
                      const menu = event.currentTarget.closest('details')!;
                      menu.open = false; menu.querySelector('summary')?.focus();
                      setError(''); setConfirmKind('status'); setConfirm(user);
                    }}>{user.is_active ? 'Disable account' : 'Enable account'}</Button>
                    <Button variant="danger" disabled={busy} onClick={event => {
                      const menu = event.currentTarget.closest('details')!;
                      menu.open = false; menu.querySelector('summary')?.focus();
                      setError(''); setConfirmKind('delete'); setConfirm(user);
                    }}>Delete account</Button>
                  </div>
                </details>
              </div>
            </div>
            {expanded && <div className="account-editor" id={`editor-${user.id}`}>
              <form onSubmit={event => {
                event.preventDefault(); const data = new FormData(event.currentTarget);
                void mutate(async () => {
                  const updated: ManagedUser = await api(`/admin/users/${user.id}`, 'PATCH', {
                    full_name: data.get('full_name'), email: data.get('email'),
                  });
                  setUsers(previous => previous.map(item => item.id === updated.id ? updated : item));
                }, 'Account details saved.');
              }}><fieldset disabled={busy}>
                <label htmlFor={`name-${user.id}`}>Full name</label>
                <input id={`name-${user.id}`} name="full_name" defaultValue={user.full_name} required maxLength={150} />
                <label htmlFor={`email-${user.id}`}>Email</label>
                <input id={`email-${user.id}`} name="email" type="email" defaultValue={user.email} required maxLength={254} />
                <Button>Save details</Button>
              </fieldset></form>
              <form onSubmit={event => {
                event.preventDefault(); const data = new FormData(event.currentTarget);
                void mutate(async () => {
                  await api(`/admin/users/${user.id}/branches`, 'PUT', { branch_ids: data.getAll('branch_ids') });
                  await loadUsers();
                }, 'Branch access updated.');
              }}><fieldset disabled={busy}>
                <BranchChecks branches={branches} selected={user.branch_ids} />
                <div className="actions"><Button>Save access</Button>
                  <Button type="button" variant="secondary" onClick={() => {
                    setEditing(''); setError(''); document.getElementById(`access-${user.id}`)?.focus();
                  }}>Cancel</Button>
                </div>
              </fieldset></form>
              {user.role === 'technician' && categories && <form onSubmit={event => {
                event.preventDefault();
                const specialization = new FormData(event.currentTarget).get('specialization') || null;
                void mutate(async () => {
                  const updated: ManagedUser = await api(`/admin/users/${user.id}/specialization`, 'PATCH', { specialization });
                  setUsers(previous => previous.map(item => item.id === updated.id ? updated : item));
                }, 'Specialization saved.');
              }}><fieldset disabled={busy}>
                <SpecializationSelect key={user.specialization ?? ''} id={`specialization-${user.id}`}
                  categories={categories} current={user.specialization} />
                <Button variant="secondary">Save specialization</Button>
              </fieldset></form>}
            </div>}
          </li>;
        })}</ul>
      </>}
    </section>
  </section>;
}

function SpecializationSelect({ id, categories, current = null }: {
  id: string; categories: ServiceCategory[]; current?: string | null;
}) {
  return <>
    <label htmlFor={id}>Specialization</label>
    <select id={id} name="specialization" defaultValue={current ?? ''}>
      <option value="">No specialization</option>
      {current && !categories.some(category => category.id === current) &&
        <option value={current}>{current}</option>}
      {categories.map(category => <option key={category.id} value={category.id}>{category.name}</option>)}
    </select>
  </>;
}

function BranchChecks({ branches, selected = [] }: { branches: Branch[]; selected?: string[] }) {
  return <fieldset className="branch-checks"><legend>Branch access</legend>
    {branches.map(branch => <label key={branch.id}><input type="checkbox" name="branch_ids"
      value={branch.id} defaultChecked={selected.includes(branch.id)} />{branch.name}</label>)}
  </fieldset>;
}
