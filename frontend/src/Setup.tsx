import { useState, type FormEvent } from 'react';

const fields = [
  { name: 'setup_token', label: 'Setup token', type: 'password', minLength: 32 },
  { name: 'full_name', label: 'Full name', maxLength: 150, autoComplete: 'name' },
  { name: 'email', label: 'Email address', type: 'email', maxLength: 254, autoComplete: 'username' },
  { name: 'branch', label: 'Branch name', maxLength: 120 },
  { name: 'location', label: 'Branch location', maxLength: 255 },
  { name: 'password', label: 'Password (at least 12 characters)', type: 'password',
    minLength: 12, maxLength: 1024, autoComplete: 'new-password' },
];

export function Setup({ onCreated }: { onCreated: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function createAdmin(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    const { setup_token, ...data } = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const response = await fetch('/api/setup/admin', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-Setup-Token': String(setup_token).trim() },
        body: JSON.stringify(data),
        signal: AbortSignal.timeout(15000),
      });
      if (!response.ok) {
        const result = await response.json().catch(() => null);
        throw new Error(typeof result?.detail === 'string' ? result.detail
          : response.status === 422 ? 'Check the email address and fill in all fields.'
            : 'Setup is unavailable. Check that the API and PostgreSQL are running.');
      }
      onCreated();
    } catch (err) {
      setError(err instanceof TypeError || (err instanceof DOMException && err.name === 'TimeoutError')
        ? 'Setup could not reach FixTrack in time. Check that the API and PostgreSQL are running.'
        : err instanceof Error ? err.message : 'Unable to create the administrator.');
    } finally {
      setBusy(false);
    }
  }

  return <>
    <h2 id="signin">Create the first administrator</h2>
    <p className="muted">Use the setup token configured in the API environment.</p>
    <form onSubmit={createAdmin}>
      {fields.map(({ name, label, ...input }) => <div key={name}>
        <label htmlFor={name}>{label}</label>
        <input id={name} name={name} required disabled={busy} {...input} />
      </div>)}
      {error && <p className="error" role="alert">{error}</p>}
      <button disabled={busy}>{busy ? 'Creating administrator…' : 'Create administrator'}</button>
    </form>
    <p className="note"><a href="#signin">Back to sign in</a></p>
  </>;
}
