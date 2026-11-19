import { StrictMode, useEffect, useRef, useState, type FormEvent } from 'react';
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
import { Reports } from './Reports';
import { Button, ConfirmDialog, RoleBadge } from './UI';

type User = { id: string; full_name: string; email: string; role: string };
type Branch = { id: string; name: string; location: string };

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [compactNav, setCompactNav] = useState(() => window.matchMedia('(max-width: 800px)').matches);
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [section, setSection] = useState(window.location.hash);
  const [adminCreated, setAdminCreated] = useState(false);
  const [notificationRequest, setNotificationRequest] = useState({ id: '' });
  const [headerPanel, setHeaderPanel] = useState<'notifications' | 'account' | null>(null);
  const [confirmSignOut, setConfirmSignOut] = useState(false);
  const [signedOut, setSignedOut] = useState(false);
  const headerControls = useRef<HTMLDivElement>(null);
  const accountButton = useRef<HTMLButtonElement>(null);
  const signInHeading = useRef<HTMLHeadingElement>(null);
  const [route, query] = section.split('?');
  const tab = user?.role === 'administrator' && route === '#people' ? 'admin'
    : user?.role === 'administrator' && route === '#assets' ? 'assets'
    : user?.role === 'administrator' && route === '#reports' ? 'reports'
    : user?.role === 'administrator' && (!route || route === '#dashboard') ? 'dashboard' : 'requests';
  const queueParams = new URLSearchParams(query);
  const queueFocus = queueParams.get('focus') ?? '';
  const initialFocus = Object.hasOwn(queues, queueFocus) ? queueFocus as QueueFocus : '';

  function signOut() {
    setToken(null); setUser(null); setBranches([]); setSection('');
    setNotificationRequest({ id: '' });
    setShowPassword(false);
    setHeaderPanel(null);
    setConfirmSignOut(false);
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
    setSignedOut(false);
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
    const narrow = window.matchMedia('(max-width: 800px)');
    function adapt() { setCompactNav(narrow.matches); }
    narrow.addEventListener('change', adapt);
    return () => narrow.removeEventListener('change', adapt);
  }, []);

  useEffect(() => {
    const syncSection = () => setSection(window.location.hash);
    window.addEventListener('hashchange', syncSection);
    return () => window.removeEventListener('hashchange', syncSection);
  }, []);

  useEffect(() => {
    if (!headerPanel) return;
    function closeOutside(event: Event) {
      if (event.target instanceof Node && !headerControls.current?.contains(event.target)) {
        setHeaderPanel(null);
      }
    }
    document.addEventListener('pointerdown', closeOutside);
    document.addEventListener('focusin', closeOutside);
    return () => {
      document.removeEventListener('pointerdown', closeOutside);
      document.removeEventListener('focusin', closeOutside);
    };
  }, [headerPanel]);

  useEffect(() => {
    if (!signedOut) return;
    signInHeading.current?.focus();
    const timeout = window.setTimeout(() => setSignedOut(false), 4500);
    return () => window.clearTimeout(timeout);
  }, [signedOut]);

  const requestLabel = user?.role === 'branch_manager' ? 'My requests'
    : user?.role === 'technician' ? 'Assigned requests' : 'Service requests';
  const initials = user?.full_name.trim().split(/\s+/).slice(0, 2).map(part => part[0]).join('');
  const toast = <div className="toast-region" role="status" aria-atomic="true">
    {signedOut && <div className="card session-toast"><Icon name="check" size={18} />Signed out successfully.</div>}
  </div>;

  if (user && token) return <>{toast}<div className={`app-shell${compactNav ? ' compact-nav' : ''}`}>
    <a className="skip-link" href="#workspace" onClick={event => {
      event.preventDefault();
      document.getElementById('workspace')?.focus();
    }}>Skip to content</a>
    <aside className="sidebar">
      <div className="sidebar-top">
        <a className="brand" href="#requests" aria-label="FixTrack" title="FixTrack">
          <span className="brand-mark"><Icon name="mark" size={22} /></span><span className="brand-name">FixTrack</span>
        </a>
        <Button variant="secondary" type="button" className="nav-toggle icon-button" aria-label={compactNav ? 'Expand navigation' : 'Collapse navigation'}
          title={compactNav ? 'Expand navigation' : 'Collapse navigation'} aria-expanded={!compactNav} aria-controls="workspace-nav"
          onClick={() => setCompactNav(value => !value)}><Icon name="menu" size={18} /></Button>
      </div>
      <nav className="workspace-nav" id="workspace-nav" aria-label="Workspace">
        {([
          ['dashboard', '#dashboard', 'dashboard', 'Overview'],
          ['requests', '#requests', 'requests', requestLabel],
          ['assets', '#assets', 'asset', 'Assets'],
          ['reports', '#reports', 'report', 'Reports'],
          ['admin', '#people', 'people', 'People & branches'],
        ] as const).filter(([section]) => user.role === 'administrator' || section === 'requests')
          .map(([section, href, icon, label]) => <a key={section} href={href} title={label}
            aria-label={label} onClick={() => {
              if (window.matchMedia('(max-width: 640px)').matches) {
                setCompactNav(true);
                document.getElementById('workspace')?.focus({ preventScroll: true });
              }
            }} aria-current={tab === section ? 'page' : undefined}>
            <Icon name={icon} size={19} /><span>{label}</span>
          </a>)}
      </nav>
      <details className="sidebar-scope" onKeyDown={event => {
        if (event.key === 'Escape' && event.currentTarget.open) {
          event.currentTarget.open = false;
          event.currentTarget.querySelector('summary')?.focus();
        }
      }}>
        <summary aria-label={`Branch access, ${branches.length} available`} title="Branch access">
          <Icon name="branch" size={18} /><span>{branches.length} {branches.length === 1 ? 'branch' : 'branches'}</span><Icon name="chevron" size={14} />
        </summary>
        <div className="scope-options"><strong>Requests by branch</strong>
          <a href="#requests" onClick={event => { event.currentTarget.closest('details')!.open = false; }}>All accessible branches</a>
          {branches.map(branch => <a key={branch.id} href={`#requests?${new URLSearchParams({ branch_id: branch.id })}`}
            onClick={event => { event.currentTarget.closest('details')!.open = false; }}>{branch.name}</a>)}
        </div>
      </details>
    </aside>
    <div className="app-body">
      <header className="app-header">
        <nav className="breadcrumb" aria-label="Breadcrumb"><span>Workspace</span><span aria-hidden="true">/</span><strong>{tab === 'admin' ? 'People & branches' : tab === 'dashboard' ? 'Overview' : tab === 'assets' ? 'Assets' : tab === 'reports' ? 'Reports' : requestLabel}</strong></nav>
        <div className="session" ref={headerControls}>
          <Notifications token={token} open={headerPanel === 'notifications'}
            onToggle={open => setHeaderPanel(current => open ? 'notifications' : current === 'notifications' ? null : current)}
            onExpired={signOut} onOpen={id => {
              setNotificationRequest({ id });
              window.location.hash = '#requests';
            }} />
          <div onKeyDown={event => {
            if (event.key === 'Escape' && headerPanel === 'account') {
              setHeaderPanel(null);
              accountButton.current?.focus();
            }
          }}>
            <button ref={accountButton} type="button" className="header-control account-trigger" aria-label="Account options"
              title="Account options" aria-expanded={headerPanel === 'account'}
              aria-controls={headerPanel === 'account' ? 'account-options' : undefined}
              onClick={() => setHeaderPanel(headerPanel === 'account' ? null : 'account')}>
              <span className="avatar" aria-hidden="true">{initials}</span><Icon name="chevron" size={14} />
            </button>
            {headerPanel === 'account' && <section id="account-options" className="card account-panel" aria-label="Account">
              <div className="account-panel-identity"><strong>{user.full_name}</strong><RoleBadge role={user.role} /></div>
              <button type="button" className="account-sign-out" onClick={() => {
                accountButton.current?.focus();
                setHeaderPanel(null);
                setConfirmSignOut(true);
              }}><Icon name="logout" size={18} />Sign out</button>
            </section>}
          </div>
        </div>
      </header>
      <main className="workspace" id="workspace" tabIndex={-1}>
        <div className="page-transition" key={tab}>
        {tab === 'requests' ? <Requests token={token} role={user.role} userId={user.id} branches={branches} onExpired={signOut} openedRequest={notificationRequest}
          initialFocus={initialFocus} initialBranch={queueParams.get('branch_id') ?? ''} />
          : tab === 'dashboard' ? <Dashboard token={token} branches={branches} onExpired={signOut} onRequest={id => {
              setNotificationRequest({ id }); window.location.hash = '#requests';
            }} />
            : tab === 'assets' ? <Assets token={token} branches={branches} onExpired={signOut} onRequest={id => {
              setNotificationRequest({ id }); window.location.hash = '#requests';
            }} />
            : tab === 'reports' ? <Reports token={token} branches={branches} onExpired={signOut} />
            : <Admin token={token} branches={branches} refreshBranches={refreshBranches} onExpired={signOut} />}
        </div>
      </main>
    </div>
    {confirmSignOut && <ConfirmDialog title="Sign out?" description="Any unsaved changes will be lost."
      confirmLabel="Sign out" onCancel={() => setConfirmSignOut(false)} onConfirm={() => {
        signOut();
        setSignedOut(true);
      }} />}
  </div></>;

  return <>{toast}<main className="login-shell">
    <section className="intro" aria-labelledby="intro-title">
      <a className="brand" href="/"><span className="brand-mark"><Icon name="mark" size={24} /></span>FixTrack</a>
      <div className="intro-content">
        <p className="intro-kicker"><span />Multi-branch maintenance</p>
        <h1 id="intro-title">Keep every branch <em>moving forward.</em></h1>
        <p className="lede">Report issues, coordinate repairs, and keep a clear service history across your branches.</p>
      </div>
      <ol className="steps" aria-label="Maintenance workflow">
        <li><span><Icon name="requests" /></span><div><strong>Report</strong></div></li>
        <li><span><Icon name="tool" /></span><div><strong>Repair</strong></div></li>
        <li><span><Icon name="check" /></span><div><strong>Resolve</strong></div></li>
      </ol>
    </section>
    <section className="login-side" aria-labelledby="signin">
      <div className="card login-card">
        {section === '#setup' ? <Setup onCreated={() => {
          setError('');
          setAdminCreated(true);
          window.location.hash = '#signin';
        }} /> : <>
          <h2 id="signin" ref={signInHeading} tabIndex={-1}>Sign in to FixTrack</h2>
          <p className="muted">Use the account provided by your administrator.</p>
          {adminCreated && <p role="status">Administrator created. Sign in with your new account.</p>}
          <form onSubmit={login}>
            <label htmlFor="email">Email address</label>
            <input id="email" name="email" type="email" autoComplete="username" required disabled={busy} />
            <label htmlFor="password">Password</label>
            <div className="password-field">
              <input id="password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required disabled={busy} />
              <button type="button" className="secondary icon-button" aria-label={showPassword ? 'Hide password' : 'Show password'}
                aria-controls="password" onClick={() => setShowPassword(value => !value)}>
                <Icon name={showPassword ? 'eyeOff' : 'eye'} size={18} />
              </button>
            </div>
            {error && <p className="error" role="alert">{error}</p>}
            <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}{busy ? <span className="spinner" aria-hidden="true" /> : <Icon name="arrow" size={18} />}</button>
          </form>
          <p className="note"><strong>Need access?</strong> Ask your administrator to set up an account.</p>
        </>}
      </div>
    </section>
  </main></>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
