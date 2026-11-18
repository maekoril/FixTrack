import { useState, type FormEvent } from 'react';

type Technician = { id: string; full_name: string };
export type TechnicianOption = Technician & { specialization: string | null; matches_category: boolean };
export type WorkSchedule = { scheduled_start: string | null; scheduled_end: string | null };
type PriceEstimate = {
  hourly_rate: string; materials_estimate: string; duration_minutes: number; team_size: number;
  amount: string; suggested: string; override: string | null; reason: string;
};
export type WorkOrder = WorkSchedule & {
  id: string; technician_id: string; status: string; labor_cost: string; materials_cost: string;
  lead: Technician; assistants: Technician[]; price_estimate: PriceEstimate | null;
};
export type PlanningOperation = 'team' | 'schedule' | 'price';

const maxMoney = '9999999999.99';
const money = (value: string) => Number(value).toLocaleString('en-PH', { style: 'currency', currency: 'PHP' });

export function technicianLabel(technician: TechnicianOption) {
  const specialization = technician.specialization ? ` · ${technician.specialization}` : '';
  return `${technician.full_name}${specialization}${technician.matches_category ? ' (category match)' : ''}`;
}

function localDateTime(value: string | null) {
  if (!value) return '';
  const date = new Date(value);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function appointmentLabel(schedule: WorkSchedule) {
  if (!schedule.scheduled_start || !schedule.scheduled_end) return 'Unscheduled';
  return `${new Date(schedule.scheduled_start).toLocaleString()} – ${new Date(schedule.scheduled_end).toLocaleString()}`;
}

function AssistantChecks({ options, selected = [] }: { options: TechnicianOption[]; selected?: string[] }) {
  if (!options.length) return null;
  return <fieldset className="branch-checks">
    <legend>Supporting technicians (optional)</legend>
    {options.map(option => <label key={option.id}>
      <input type="checkbox" name="assistant_ids" value={option.id} defaultChecked={selected.includes(option.id)} />
      {technicianLabel(option)}
    </label>)}
  </fieldset>;
}

export function AssignmentFields({ id, options, defaultLead = '' }: {
  id: string; options: TechnicianOption[]; defaultLead?: string;
}) {
  const [lead, setLead] = useState(defaultLead);
  return <>
    <label htmlFor={id}>Lead technician</label>
    <select id={id} name="technician_id" value={lead} required onChange={event => setLead(event.target.value)}>
      <option value="" disabled>Select a lead technician</option>
      {options.map(option => <option key={option.id} value={option.id}>{technicianLabel(option)}</option>)}
    </select>
    {lead && <AssistantChecks options={options.filter(option => option.id !== lead)} />}
  </>;
}

export function WorkOrderSummary({ order }: { order: WorkOrder }) {
  const quote = order.price_estimate;
  return <dl>
    <dt>Lead technician</dt><dd>{order.lead.full_name}</dd>
    {order.assistants.length > 0 && <>
      <dt>Supporting technicians</dt><dd>{order.assistants.map(member => member.full_name).join(', ')}</dd>
    </>}
    <dt>Schedule</dt><dd>{appointmentLabel(order)}</dd>
    {quote && <>
      <dt>Estimated price</dt><dd>{money(quote.amount)}{quote.override !== null && ` (suggested ${money(quote.suggested)})`}</dd>
      <dt>Estimate basis</dt><dd>{quote.team_size} technician(s) · {quote.duration_minutes} min · {money(quote.hourly_rate)}/hr each · {money(quote.materials_estimate)} materials</dd>
      {quote.reason && <><dt>Price override reason</dt><dd>{quote.reason}</dd></>}
    </>}
  </dl>;
}

export function WorkOrderPlanning({ order, options, estimatedDuration, busy, onSave }: {
  order: WorkOrder; options: TechnicianOption[]; estimatedDuration: number | null; busy: boolean;
  onSave: (operation: PlanningOperation, data: unknown) => void;
}) {
  const quote = order.price_estimate;
  const assistants = order.assistants.map(member => member.id);
  const scheduledDuration = order.scheduled_start && order.scheduled_end
    ? (Date.parse(order.scheduled_end) - Date.parse(order.scheduled_start)) / 60000 : null;
  const plannedDuration = scheduledDuration ?? estimatedDuration;
  const teamSize = 1 + assistants.length;
  const id = order.id;

  function saveSchedule(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const start = String(data.get('scheduled_start') ?? '');
    const minutes = data.get('duration_minutes');
    if (!start) return;
    onSave('schedule', { scheduled_start: new Date(start).toISOString(), duration_minutes: minutes ? Number(minutes) : null });
  }

  return <>
    <details className="work-planning">
      <summary>Edit supporting technicians</summary>
      <form key={assistants.join(',')} onSubmit={event => {
        event.preventDefault();
        onSave('team', { assistant_ids: new FormData(event.currentTarget).getAll('assistant_ids') });
      }}>
        <fieldset disabled={busy}>
          <AssistantChecks options={options.filter(option => option.id !== order.technician_id)} selected={assistants} />
          <button className="secondary">Save team</button>
        </fieldset>
      </form>
    </details>
    <details className="work-planning">
      <summary>{order.scheduled_start ? 'Edit schedule' : 'Schedule work'}</summary>
      <form key={`${order.scheduled_start}-${order.scheduled_end}`} onSubmit={saveSchedule}>
        <fieldset disabled={busy}>
          <label htmlFor={`start-${id}`}>Planned start (local time)</label>
          <input id={`start-${id}`} type="datetime-local" name="scheduled_start"
            defaultValue={localDateTime(order.scheduled_start)} required />
          <label htmlFor={`duration-${id}`}>Scheduled duration (minutes)</label>
          <input id={`duration-${id}`} type="number" name="duration_minutes" min={1} max={10080} step={1}
            defaultValue={scheduledDuration ?? ''} required={estimatedDuration === null}
            aria-describedby={`duration-hint-${id}`} />
          <p className="field-hint" id={`duration-hint-${id}`}>{estimatedDuration === null
            ? 'Enter how long to reserve for the work.' : `Leave blank to use the service estimate of ${estimatedDuration} min.`}</p>
          <div className="actions">
            <button>Save schedule</button>
            {order.scheduled_start && <button className="secondary" type="button"
              onClick={() => onSave('schedule', { scheduled_start: null })}>Clear schedule</button>}
          </div>
        </fieldset>
      </form>
    </details>
    <details className="work-planning">
      <summary>{quote ? 'Edit price estimate' : 'Estimate price'}</summary>
      {quote && (quote.duration_minutes !== plannedDuration || quote.team_size !== teamSize) &&
        <p className="muted">The team size or duration changed. Calculate again to update the saved estimate.</p>}
      <form key={JSON.stringify(quote)} onSubmit={event => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        onSave('price', {
          hourly_rate: data.get('hourly_rate'),
          materials_estimate: data.get('materials_estimate'),
          override: data.get('override') || null,
          reason: data.get('reason'),
        });
      }}>
        <fieldset disabled={busy || plannedDuration === null}>
          <p className="muted">{plannedDuration === null
            ? 'Set a schedule or service duration before estimating the price.'
            : `Uses ${plannedDuration} min for each of ${teamSize} technician(s), plus estimated materials.`}</p>
          <label htmlFor={`rate-${id}`}>Hourly labor rate per technician (₱)</label>
          <input id={`rate-${id}`} type="number" name="hourly_rate" min={0} max={maxMoney}
            step="0.01" defaultValue={quote?.hourly_rate} required />
          <label htmlFor={`materials-estimate-${id}`}>Estimated materials (₱)</label>
          <input id={`materials-estimate-${id}`} type="number" name="materials_estimate"
            min={0} max={maxMoney} step="0.01" defaultValue={quote?.materials_estimate ?? '0'} required />
          <label htmlFor={`override-${id}`}>Manual total (₱, optional)</label>
          <input id={`override-${id}`} type="number" name="override" min={0} max={maxMoney}
            step="0.01" defaultValue={quote?.override ?? ''} />
          <label htmlFor={`price-reason-${id}`}>Reason for manual total</label>
          <textarea id={`price-reason-${id}`} name="reason" maxLength={10000} rows={2} defaultValue={quote?.reason ?? ''} />
          <button>Calculate and save</button>
        </fieldset>
      </form>
    </details>
  </>;
}
