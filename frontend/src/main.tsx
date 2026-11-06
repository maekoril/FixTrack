import { StrictMode, useState, type FormEvent } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';
import { Admin } from './Admin';
import { Requests } from './Requests';

type User = { id: string; full_name: string; email: string; role: string };
type Branch = { id: string; name: string; location: string };

function App() {
  const [user, setUser] = useState<User | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const [tab, setTab] = useState<'requests' | 'admin'>('requests');

  function signOut() { setToken(null); setUser(null); setBranches([]); setTab('requests'); }
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
      setBranches(nextBranches); setUser(nextUser); setToken(access_token);
    } catch (err) {
      setError(err instanceof TypeError ? 'Cannot connect to FixTrack. Check that the API is running.'
        : err instanceof Error ? err.message : 'Unable to sign in.');
    } finally { setBusy(false); }
  }

  return <div className="shell">
    <header><a className="brand" href="/" aria-label="FixTrack home"><span>F</span>FixTrack</a>
      <span className="tag">Maintenance, connected.</span></header>
    {user && token ? <main className="workspace">
      <div className="workspace-heading"><div><p className="eyebrow">{user.role} WORKSPACE</p><h1>Welcome, {user.full_name}</h1></div><button className="secondary" onClick={signOut}>Sign out</button></div>
      <nav className="workspace-tabs" aria-label="Workspace"><button aria-current={tab === 'requests' ? 'page' : undefined} onClick={() => setTab('requests')}>Service requests</button>
        {user.role === 'administrator' && <button aria-current={tab === 'admin' ? 'page' : undefined} onClick={() => setTab('admin')}>People & branches</button>}</nav>
      {tab === 'requests' ? <Requests token={token} role={user.role} branches={branches} onExpired={signOut} />
        : <Admin token={token} branches={branches} refreshBranches={refreshBranches} onExpired={signOut} />}
    </main> : <main>
      <section className="intro"><p className="eyebrow">MULTI-BRANCH MAINTENANCE</p>
        <h1>Keep every branch<br />moving forward.</h1>
        <p className="lede">One place to report issues, coordinate repairs, and keep a clear service history.</p>
        <div className="steps"><span>01 &nbsp; Report</span><span>02 &nbsp; Repair</span><span>03 &nbsp; Resolve</span></div>
      </section>
      <section className="card" aria-labelledby="signin">
        <p className="eyebrow">WELCOME BACK</p><h2 id="signin">Sign in to FixTrack</h2>
        <p className="muted">Use the account provided by your administrator.</p>
        <form onSubmit={login}>
          <label htmlFor="email">Email address</label>
          <input id="email" name="email" type="email" autoComplete="username" required disabled={busy} />
          <label htmlFor="password">Password</label>
          <input id="password" name="password" type="password" autoComplete="current-password" required disabled={busy} />
          {error && <p className="error" role="alert">{error}</p>}
          <button disabled={busy}>{busy ? 'Signing in…' : 'Sign in →'}</button>
        </form><p className="note">Need access? Ask your project administrator to set up your account.</p>
      </section>
    </main>}
    <footer>FixTrack <span>Service you can trace. Progress you can see.</span></footer>
  </div>;
}

createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
