import { StrictMode, useEffect, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import './workspace.css';
import { Admin } from './Admin';
import { Requests } from './Requests';
import { Icon } from './Icon';
import { Setup } from './Setup';
import { Notifications } from './Notifications';
import { Dashboard, queues, type QueueFocus } from './Dashboard';
import { Assets } from './Assets';

type User = { id: string; full_name: string; email: string; role: string };
type Branch = { id: string; name: string; location: string };

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [section, setSection] = useState(window.location.hash);
  const [adminCreated, setAdminCreated] = useState(false);
  const [notificationRequest, setNotificationRequest] = useState({ id: '' });
  const [route, query] = section.split('?');
  const tab = user?.role === 'administrator' && route === '#people' ? 'admin'
    : user?.role === 'administrator' && route === '#assets' ? 'assets'
    : user?.role === 'administrator' && (!route || route === '#dashboard') ? 'dashboard' : 'requests';
  const queueParams = new URLSearchParams(query);
  const queueFocus = queueParams.get('focus') ?? '';
  const initialFocus = Object.hasOwn(queues, queueFocus) ? queueFocus as QueueFocus : '';

  function signOut() {
    setToken(null); setUser(null); setBranches([]); setSection('');
    setNotificationRequest({ id: '' });
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }
  async function refreshBranches() {
    const response = await fetch('/api/branches', { headers: { Authorization: `Bearer ${token}` } });
    if (response.status === 401) { signOut(); throw new Error('Your session expired. Sign in again.'); }
    if (!response.ok) throw new Error('Unable to refresh branches.');
    setBranches(await response.json());
  }

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(''); setBusy(true);
    const data = new FormData(event.currentTarget);
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: data.get('email'), password: data.get('password') }),
      });
      if (!response.ok) throw new Error(response.status === 401
        ? 'Invalid email or password.' : 'Sign-in is unavailable. Please try again.');
      const { access_token } = await response.json();
      const headers = { Authorization: `Bearer ${access_token}` };
      const [profile, branchResponse] = await Promise.all([
        fetch('/api/auth/me', { headers }), fetch('/api/branches', { headers }),
      ]);
      if (!profile.ok || !branchResponse.ok) throw new Error('Unable to load your workspace.');
      const nextUser: User = await profile.json();
      const nextBranches: Branch[] = await branchResponse.json();
      if (['#setup', '#signin'].includes(window.location.hash)) {
        window.history.replaceState(null, '', window.location.pathname + window.location.search);
        setSection('');
      }
      setBranches(nextBranches); setUser(nextUser); setToken(access_token);
    } catch (err) {
      setError(err instanceof TypeError ? 'Cannot connect to FixTrack. Check that the API is running.'
        : err instanceof Error ? err.message : 'Unable to sign in.');
    } finally { setBusy(false); }
  }

  useEffect(() => {
    const syncSection = () => setSection(window.location.hash);
    window.addEventListener('hashchange', syncSection);
    return () => window.removeEventListener('hashchange', syncSection);
  }, []);

  const requestLabel = user?.role === 'branch_manager' ? 'My requests'
    : user?.role === 'technician' ? 'Assigned requests' : 'Service requests';
  const initials = user?.full_name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('');

  if (user && token) return <div className="app-shell">
    <a className="skip-link" href="#workspace" onClick={event => {
      event.preventDefault();
      document.getElementById('workspace')?.focus();
    }}>Skip to content</a>
    <aside className="sidebar">
      <a className="brand" href="#requests"><span className="brand-mark"><Icon name="mark" size={24} /></span>FixTrack</a>
      <nav className="workspace-nav" aria-label="Workspace">
        <p className="eyebrow nav-label">Workspace</p>
        {user.role === 'administrator' && <a href="#dashboard" aria-current={tab === 'dashboard' ? 'page' : undefined}><Icon name="dashboard" />Overview</a>}
        {user.role === 'administrator' && <a href="#assets" aria-current={tab === 'assets' ? 'page' : undefined}><Icon name="asset" />Assets</a>}
        <a href="#requests" aria-current={tab === 'requests' ? 'page' : undefined}><Icon name="requests" />{requestLabel}</a>
        {user.role === 'administrator' && <a href="#people" aria-current={tab === 'admin' ? 'page' : undefined}><Icon name="people" />People &amp; branches</a>}
      </nav>
      <div className="sidebar-scope"><Icon name="branch" /><div><strong>Branch access</strong><span>{branches.length} {branches.length === 1 ? 'branch' : 'branches'} available</span></div></div>
    </aside>
    <div className="app-body">
      <header className="app-header">
        <div className="breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{tab === 'admin' ? 'People & branches' : tab === 'dashboard' ? 'Overview' : tab === 'assets' ? 'Assets' : requestLabel}</strong></div>
        <div className="session"><Notifications token={token} onExpired={signOut} onOpen={id => {
          setNotificationRequest({ id });
          window.location.hash = '#requests';
        }} /><span className="avatar" aria-hidden="true">{initials}</span><div className="session-user"><strong>{user.full_name}</strong><small>{user.role.replaceAll('_', ' ')}</small></div>
          <button type="button" className="secondary sign-out header-icon" aria-label="Sign out" title="Sign out"
            onClick={signOut}><Icon name="logout" size={18} /></button></div>
      </header>
      <main className="workspace" id="workspace" tabIndex={-1}>
        {tab === 'requests' ? <Requests token={token} role={user.role} branches={branches} onExpired={signOut} openedRequest={notificationRequest}
          initialFocus={initialFocus} initialBranch={queueParams.get('branch_id') ?? ''} />
          : tab === 'dashboard' ? <Dashboard token={token} branches={branches} onExpired={signOut} onRequest={id => {
              setNotificationRequest({ id }); window.location.hash = '#requests';
            }} />
            : tab === 'assets' ? <Assets token={token} branches={branches} onExpired={signOut} onRequest={id => {
              setNotificationRequest({ id }); window.location.hash = '#requests';
            }} />
            : <Admin token={token} branches={branches} refreshBranches={refreshBranches} onExpired={signOut} />}
      </main>
    </div>
  </div>;

  return <main className="login-shell">
    <section className="intro" aria-labelledby="intro-title">
      <a className="brand" href="/"><span className="brand-mark"><Icon name="mark" size={24} /></span>FixTrack</a>
      <div className="intro-content">
        <p className="eyebrow intro-kicker"><span />Multi-branch maintenance</p>
        <h1 id="intro-title">Keep every branch <em>moving forward.</em></h1>
        <p className="lede">Report issues, coordinate repairs, and keep a clear service history across your branches.</p>
      </div>
      <ol className="steps" aria-label="Maintenance workflow">
        <li><span><Icon name="requests" /></span><div><small>01</small><strong>Report</strong></div></li>
        <li><span><Icon name="tool" /></span><div><small>02</small><strong>Repair</strong></div></li>
        <li><span><Icon name="check" /></span><div><small>03</small><strong>Resolve</strong></div></li>
      </ol>
    </section>
    <section className="login-side" aria-labelledby="signin">
      <div className="card login-card">
        <span className="icon-tile"><Icon name="mark" size={26} /></span>
        {section === '#setup' ? <Setup onCreated={() => {
          setError('');
          setAdminCreated(true);
          window.location.hash = '#signin';
        }} /> : <>
          <p className="eyebrow">FixTrack workspace</p><h2 id="signin">Sign in to FixTrack</h2>
          <p className="muted">Use the account provided by your administrator.</p>
          {adminCreated && <p role="status">Administrator created. Sign in with your new account.</p>}
          <form onSubmit={login}>
            <label htmlFor="email">Email address</label>
            <input id="email" name="email" type="email" autoComplete="username" required disabled={busy} />
            <label htmlFor="password">Password</label>
            <input id="password" name="password" type="password" autoComplete="current-password" required disabled={busy} />
            {error && <p className="error" role="alert">{error}</p>}
            <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}<Icon name="arrow" size={18} /></button>
          </form>
          <p className="note"><strong>Need access?</strong> Ask your administrator to set up an account.</p>
        </>}
      </div>
    </section>
  </main>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
