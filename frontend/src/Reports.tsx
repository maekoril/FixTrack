import { useEffect, useState, type FormEvent } from 'react';
import { EmptyState, PageHeader, Skeleton } from './UI';
import { formatMoney, formatReportDate } from './format';

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

function valueFor(row: Totals, key: keyof Totals) {
  const value = row[key];
  return typeof value === 'string' ? formatMoney(value) : value.toLocaleString('en-PH');
}

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
    <PageHeader id="reports-title" title="Repair reports" description="Compare repair volume and recorded costs across branches." />
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
    {!report && !error && <Skeleton label="Loading repair report…" />}
    {report && <section className="card report-results" aria-labelledby="report-period">
      <div className="queue-heading"><h2 id="report-period">Branch summary</h2>
        <p className="muted">{formatReportDate(filters.get('start_date')!)}–{formatReportDate(filters.get('end_date')!)} · UTC, inclusive</p></div>
      {report.branches.length ? <div className="report-table-wrap">
        <table className="report-table" role="table" aria-labelledby="report-period">
          <thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col">Branch</th>
            {metrics.map(([key, label]) => <th role="columnheader" scope="col" key={key}>{label}</th>)}
          </tr></thead>
          <tbody role="rowgroup">{report.branches.map(branch => {
            const total = Number(report.totals.total_cost);
            const share = total > 0 ? Number(branch.total_cost) / total * 100 : 0;
            return <tr key={branch.branch_id} role="row">
              <th scope="row" role="rowheader">{branch.branch_name}</th>
              {metrics.map(([key, label]) => <td key={key} role="cell">
                <span className="report-mobile-label" aria-hidden="true">{label}</span>
                <span>{valueFor(branch, key)}</span>
                {key === 'total_cost' && <div className="cost-share" title={`${share.toFixed(1)}% of reported cost`}>
                  <span className="sr-only">{share.toFixed(1)}% of reported cost</span>
                  <span style={{ width: `${share}%` }} aria-hidden="true" />
                </div>}
              </td>)}
            </tr>;
          })}</tbody>
          <tfoot role="rowgroup"><tr role="row"><th scope="row" role="rowheader">Total</th>
            {metrics.map(([key, label]) => <td key={key} role="cell"><span className="report-mobile-label" aria-hidden="true">{label}</span><span>{valueFor(report.totals, key)}</span></td>)}
          </tr></tfoot>
        </table>
      </div> : <EmptyState icon="report" title="No accessible branches." />}
    </section>}
  </section>;
}
