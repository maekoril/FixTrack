import { useEffect, useState, type FormEvent } from 'react';

type Totals = {
  closed_requests: number;
  completed_orders: number;
  labor_cost: string;
  materials_cost: string;
  total_cost: string;
};
type Report = {
  totals: Totals;
  branches: (Totals & { branch_id: string; branch_name: string })[];
};

const metrics = [
  ['closed_requests', 'Verified closures'],
  ['completed_orders', 'Completed work orders'],
  ['labor_cost', 'Labor cost'],
  ['materials_cost', 'Materials cost'],
  ['total_cost', 'Total cost'],
] as const;

export function Reports({ token, branches, onExpired }: {
  token: string; branches: { id: string; name: string }[]; onExpired: () => void;
}) {
  const [filters, setFilters] = useState(() => {
    const today = new Date().toISOString().slice(0, 10);
    return new URLSearchParams({
      start_date: today.slice(0, 7) + '-01', end_date: today, branch_id: '',
    });
  });
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const controller = new AbortController();
    const query = new URLSearchParams(filters);
    if (!query.get('branch_id')) query.delete('branch_id');
    async function load() {
      try {
        const response = await fetch(`/api/reports/repairs?${query}`, {
          headers: { Authorization: `Bearer ${token}` }, signal: controller.signal,
        });
        if (controller.signal.aborted) return;
        if (response.status === 401) { onExpired(); return; }
        if (response.status === 404) throw new Error('This branch is no longer available. Choose another branch.');
        if (response.status === 422) throw new Error('Enter a valid date range.');
        if (!response.ok) throw new Error('Unable to load the repair report. Try again.');
        const data: Report = await response.json();
        if (!controller.signal.aborted) setReport(data);
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof TypeError
          ? 'Unable to connect to FixTrack. Try again.'
          : err instanceof Error ? err.message : 'Unable to load the repair report.');
      }
    }
    void load();
    return () => controller.abort();
  }, [token, filters]);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const fields = new FormData(event.currentTarget);
    const start = String(fields.get('start_date'));
    const end = String(fields.get('end_date'));
    if (start > end) {
      setError('The end date must be on or after the start date.');
      return;
    }
    setReport(null);
    setError('');
    setFilters(new URLSearchParams({
      start_date: start, end_date: end, branch_id: String(fields.get('branch_id')),
    }));
  }

  return <section aria-labelledby="reports-title">
    <header className="section-heading">
      <div><h1 id="reports-title">Repair reports</h1>
        <p className="muted">Review verified closures and costs for completed work, including follow-ups.</p></div>
    </header>
    <form className="card report-filters" onSubmit={submit}>
      <label>Branch<select name="branch_id" defaultValue={filters.get('branch_id') ?? ''}>
        <option value="">All accessible branches</option>
        {branches.map(branch => <option key={branch.id} value={branch.id}>{branch.name}</option>)}
      </select></label>
      <label>Start date<input name="start_date" type="date" required defaultValue={filters.get('start_date') ?? ''} /></label>
      <label>End date<input name="end_date" type="date" required defaultValue={filters.get('end_date') ?? ''} /></label>
      <button type="submit">Run report</button>
    </form>
    {error && <p className="error" role="alert">{error}</p>}
    {!report && !error && <p role="status">Loading repair report…</p>}
    {report && <section className="card report-results" aria-labelledby="report-period">
      <h2 id="report-period">Branch summary</h2>
      <p className="muted">{filters.get('start_date')} to {filters.get('end_date')} (UTC, both dates included)</p>
      {report.branches.length ? <div className="report-table-scroll" role="region" aria-label="Repair report by branch" tabIndex={0}>
        <table className="report-table" aria-labelledby="report-period">
          <thead><tr><th scope="col">Branch</th>
            {metrics.map(([key, label]) => <th scope="col" key={key}>{label}</th>)}
          </tr></thead>
          <tbody>{report.branches.map(branch => <tr key={branch.branch_id}>
            <th scope="row">{branch.branch_name}</th>
            {metrics.map(([key]) => <td key={key}>{branch[key]}</td>)}
          </tr>)}</tbody>
          <tfoot><tr><th scope="row">Total</th>
            {metrics.map(([key]) => <td key={key}>{report.totals[key]}</td>)}
          </tr></tfoot>
        </table>
      </div> : <p>No accessible branches.</p>}
    </section>}
  </section>;
}
