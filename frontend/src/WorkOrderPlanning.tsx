import { formatDateTime, formatMoney as money } from './format';
import { useState, type FormEvent } from 'react';
import { AIEstimateHelper, type EstimateSuggestion } from './AIEstimateHelper';
import { priceInputsChanged } from './planning';

type Technician = { id: string; full_name: string };
export type TechnicianOption = Technician & { specialization: string | null; matches_category: boolean };
export type WorkSchedule = { scheduled_start: string | null; scheduled_end: string | null };
type MaterialItem = { name: string; quantity: string; unit_price: string; source: string; total?: string };
type PriceEstimate = {
  hourly_rate: string; materials_estimate: string; duration_minutes: number; team_size: number;
  amount: string; suggested: string; override: string | null; reason: string;
  version?: number; materials_items?: MaterialItem[] | null; labor_estimate?: string;
};
export type WorkOrder = WorkSchedule & {
  id: string; technician_id: string; status: string; labor_cost: string; materials_cost: string;
  lead: Technician; assistants: Technician[]; price_estimate: PriceEstimate | null;
  approved_price: { quote: PriceEstimate; approved_by_name: string; approved_at: string } | null;
  overrun_reason: string | null;
};
export type ServiceCategory = { id: string; name: string };
const difficulties = ['easy', 'moderate', 'hard'] as const;
export type Difficulty = typeof difficulties[number];
export const difficultyLabel = (value: Difficulty) => value[0].toUpperCase() + value.slice(1);
type SetupRequest = {
  priority: string | null;
  category: ServiceCategory | null;
  difficulty: Difficulty | null;
  duration_override_minutes: number | null;
  setup_missing?: string[] | null;
  setup_duration_suggestions?: Record<string, Partial<Record<Difficulty, number>>> | null;
};

const maxMoney = '9999999999.99';

function technicianLabel(technician: TechnicianOption) {
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
  return `${formatDateTime(schedule.scheduled_start)} – ${formatDateTime(schedule.scheduled_end)}`;
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
  const approved = order.approved_price;
  const actual = Number(order.labor_cost) + Number(order.materials_cost);
  const variance = approved ? Math.round((actual - Number(approved.quote.amount)) * 100) / 100 : 0;
  return <><dl>
    <dt>Lead technician</dt><dd>{order.lead.full_name}</dd>
    {order.assistants.length > 0 && <>
      <dt>Supporting technicians</dt><dd>{order.assistants.map(member => member.full_name).join(', ')}</dd>
    </>}
    <dt>Schedule</dt><dd>{appointmentLabel(order)}</dd>
    {quote && <>
      <dt>Estimated price · v{quote.version ?? 0}</dt><dd>{money(quote.amount)}{quote.override !== null && ` (suggested ${money(quote.suggested)})`}</dd>
      <dt>Estimate basis</dt><dd>{quote.team_size} technician(s) · {quote.duration_minutes} min · {money(quote.hourly_rate)}/hr each · {money(quote.materials_estimate)} materials</dd>
      {quote.reason && <><dt>Price override reason</dt><dd>{quote.reason}</dd></>}
    </>}
  </dl>
    {quote && <MaterialBreakdown quote={quote} />}
    {approved ? <section className="budget-review" aria-label="Approved budget">
      <h4>Approved budget · v{approved.quote.version ?? 0}</h4>
      <p>{money(approved.quote.amount)} · Approved by {approved.approved_by_name} on {formatDateTime(approved.approved_at)}</p>
      {quote && (quote.version ?? 0) !== (approved.quote.version ?? 0) && <>
        <p className="muted">The current estimate has changes awaiting approval. Cost comparison uses the approved version below.</p>
        <p>{approved.quote.team_size} technician(s) · {approved.quote.duration_minutes} min · {money(approved.quote.hourly_rate)}/hr each · {money(approved.quote.materials_estimate)} materials</p>
        <MaterialBreakdown quote={approved.quote} />
        {approved.quote.reason && <p>Manual total reason: {approved.quote.reason}</p>}
      </>}
      {order.status === 'completed' && <dl>
        <dt>Actual total</dt><dd>{money(actual.toFixed(2))}</dd>
        <dt>Budget variance</dt><dd>{variance > 0 ? `${money(variance.toFixed(2))} over budget`
          : variance < 0 ? `${money(Math.abs(variance).toFixed(2))} under budget` : 'Within budget (exact)'}</dd>
      </dl>}
    </section> : <p className="muted">No approved budget. {order.status === 'completed' ? 'An approved-budget comparison is unavailable.' : 'Save the estimate, then approve it to establish a budget.'}</p>}
    {order.overrun_reason && <p><strong>Cost explanation:</strong> {order.overrun_reason}</p>}
  </>;
}

function MaterialBreakdown({ quote }: { quote: PriceEstimate }) {
  if (!quote.materials_items) return <p className="muted">Materials saved as a total without line items.</p>;
  if (!quote.materials_items.length) return <p className="muted">No materials estimated.</p>;
  return <ul className="material-breakdown">{quote.materials_items.map((item, index) => <li key={index}>
    <strong>{item.name}</strong> · {item.quantity} × {money(item.unit_price)} = {money(item.total ?? '0')}
    <small>Price source: {item.source}</small>
  </li>)}</ul>;
}

export function RequestSetup({ request, order, canAssign, categories, options, busy, onSave, onSuggest }: {
  request: SetupRequest; order: WorkOrder | undefined; canAssign: boolean;
  categories: ServiceCategory[] | null; options: TechnicianOption[]; busy: boolean;
  onSave: (data: unknown) => Promise<void>;
  onSuggest: () => Promise<EstimateSuggestion>;
}) {
  const [initial] = useState(() => ({ request, order }));
  const saved = initial.request;
  const savedOrder = initial.order;
  const quote = savedOrder?.price_estimate;
  const [materialsItems, setMaterialsItems] = useState<MaterialItem[]>(quote?.materials_items ?? []);
  const [legacyMaterials, setLegacyMaterials] = useState(!!quote && !quote.materials_items);
  const [category, setCategory] = useState(saved.category?.id ?? '');
  const [difficulty, setDifficulty] = useState<Difficulty | ''>(saved.difficulty ?? '');
  const [durationOverride, setDurationOverride] = useState(String(saved.duration_override_minutes ?? ''));
  const [lead, setLead] = useState(savedOrder?.technician_id ?? '');
  const [assistants, setAssistants] = useState(savedOrder?.assistants.map(member => member.id) ?? []);
  const [clearSchedule, setClearSchedule] = useState(false);
  const [error, setError] = useState('');
  const [scheduleError, setScheduleError] = useState('');
  const scheduledStart = localDateTime(savedOrder?.scheduled_start ?? null);
  const scheduledDuration = savedOrder?.scheduled_start && savedOrder.scheduled_end
    ? Math.floor((Date.parse(savedOrder.scheduled_end) - Date.parse(savedOrder.scheduled_start)) / 60000) : null;
  const suggested = difficulty ? request.setup_duration_suggestions?.[category]?.[difficulty] : undefined;
  const categoryName = categories?.find(option => option.id === category)?.name;
  const available = options.map(option => ({
    ...option, matches_category: !!categoryName && option.specialization === categoryName,
  })).sort((left, right) => Number(right.matches_category) - Number(left.matches_category));
  const unavailable = [savedOrder?.lead, ...(savedOrder?.assistants ?? [])]
    .filter((member): member is Technician => !!member && !available.some(option => option.id === member.id));
  const teamOptions = [
    ...available.map(member => ({ id: member.id, label: technicianLabel(member), available: true })),
    ...unavailable.map(member => ({ id: member.id, label: `${member.full_name} (unavailable)`, available: false })),
  ];
  const changingLead = !!savedOrder && lead !== savedOrder.technician_id;
  const canPlan = !!savedOrder || canAssign;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setScheduleError('');
    const form = event.currentTarget;
    if (!form.checkValidity()) {
      const invalid = form.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>('input:invalid, select:invalid, textarea:invalid');
      const label = invalid?.labels?.[0]?.textContent ?? 'Setup field';
      setError(`${label}: ${invalid?.validationMessage ?? 'Check the entered value.'}`);
      form.reportValidity();
      return;
    }
    const fields = new FormData(form);
    const value = (name: string) => String(fields.get(name) ?? '');
    const number = (name: string) => value(name) === '' ? null : Number(value(name));
    const payload: Record<string, unknown> = {};
    if (!lead && materialsItems.length) {
      setError('Select a lead technician before saving material estimates.');
      return;
    }
    const priority = value('priority');
    if (priority && priority !== saved.priority) payload.priority = priority;
    if (categories && (category || null) !== (saved.category?.id ?? null)) {
      payload.category = { category_id: category || null };
    }
    const manualDuration = number('duration_override_minutes');
    if ((difficulty || null) !== saved.difficulty || manualDuration !== saved.duration_override_minutes) {
      payload.estimate = { difficulty: difficulty || null, duration_override_minutes: manualDuration };
    }
    if (canPlan && lead) {
      const teamChanged = !savedOrder || changingLead || assistants.length !== savedOrder.assistants.length
        || savedOrder.assistants.some(member => !assistants.includes(member.id));
      if (teamChanged) payload.team = {
        technician_id: lead, assistant_ids: assistants,
        previous_technician_id: savedOrder?.technician_id, reason: value('reassignment_reason'),
      };

      const start = value('scheduled_start');
      const minutes = number('scheduled_minutes');
      const scheduleChanged = clearSchedule || start !== scheduledStart || minutes !== scheduledDuration;
      const serviceDuration = manualDuration ?? suggested;
      if (scheduleChanged) {
        const input = form.elements.namedItem('scheduled_start') as HTMLInputElement;
        const startTime = Date.parse(start);
        if (!clearSchedule && ((!start && minutes !== null) || (start && !Number.isFinite(startTime)))) {
          setScheduleError('Enter a valid planned start time.');
          input.focus();
          return;
        }
        if (start && startTime < Date.now()) {
          setScheduleError('Choose a planned start time in the future.');
          input.focus();
          return;
        }
        payload.schedule = {
          scheduled_start: start ? new Date(startTime).toISOString() : null,
          duration_minutes: minutes,
        };
      }

      const rate = value('hourly_rate');
      const materials = legacyMaterials ? value('materials_estimate') : '0';
      const override = value('price_override');
      const reason = value('price_reason');
      const changedPrice = priceInputsChanged(quote ?? undefined, {
        rate, materials, items:materialsItems, legacy:legacyMaterials, override, reason,
      });
      const plannedDuration = start ? (minutes ?? serviceDuration) : serviceDuration;
      if (!rate && (Number(materials) || materialsItems.length || override || reason)) {
        setError('Enter an hourly labor rate to save a price estimate.');
        return;
      }
      if (rate && (changedPrice || (plannedDuration != null && (
        quote?.duration_minutes !== plannedDuration || quote?.team_size !== 1 + assistants.length
      )))) {
        payload.price = { hourly_rate: rate, materials_estimate: materials,
          ...(!legacyMaterials ? { materials_items: materialsItems } : {}), override: override || null, reason };
      }
      if (savedOrder) payload.work_order_id = savedOrder.id;
    }

    try {
      await onSave(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to save request setup.');
    }
  }

  return <form className="request-setup" noValidate onSubmit={submit} aria-labelledby="request-setup-title">
    <h3 id="request-setup-title">Request setup</h3>
    {error && <p className="error" role="alert">{error}</p>}
    {!!request.setup_missing?.length && <p className="setup-missing">
      <strong>Needs setup</strong> <span>{request.setup_missing.join(' · ')}</span>
    </p>}
    {canPlan && request.setup_missing?.length === 0 && <p className="success">Setup complete. Saved planning details are ready for the work order.</p>}
    <fieldset disabled={busy}>
      {canPlan && <AIEstimateHelper onGenerate={onSuggest}
        canAddMaterials={!!lead}
        legacyMaterialsTotal={legacyMaterials ? quote?.materials_estimate : undefined}
        onDuration={minutes => setDurationOverride(String(minutes))}
        onMaterials={items => {
          if (materialsItems.length + items.length > 100) {
            setError('The estimate supports up to 100 material lines. Remove some lines before adding suggestions.');
            return false;
          }
          setLegacyMaterials(false);
          setMaterialsItems(current => [...current, ...items.map(item => ({
            name: `${item.name} (${item.unit})`.slice(0, 180), quantity: item.quantity, unit_price: '', source: '',
          }))]);
          return true;
        }} />}
      <fieldset className="setup-group">
        <legend>Service details</legend>
        <div className="form-columns">
          <div><label htmlFor="setup-priority">Priority</label>
            <select id="setup-priority" name="priority" defaultValue={saved.priority ?? ''}>
              <option value="" disabled={saved.priority !== null}>Not prioritized</option>
              {['low', 'medium', 'high', 'urgent'].map(value => <option key={value} value={value}>{value}</option>)}
            </select></div>
          {categories && <div><label htmlFor="setup-category">Service category</label>
            <select id="setup-category" value={category} onChange={event => setCategory(event.target.value)}>
              <option value="">Uncategorized</option>
              {categories.map(option => <option key={option.id} value={option.id}>{option.name}</option>)}
            </select></div>}
          <div><label htmlFor="setup-difficulty">Difficulty</label>
            <select id="setup-difficulty" value={difficulty} onChange={event => setDifficulty(event.target.value as Difficulty | '')}>
              <option value="">Not set</option>
              {difficulties.map(value => <option key={value} value={value}>{difficultyLabel(value)}</option>)}
            </select></div>
          <div><label htmlFor="setup-duration">Service duration (minutes)</label>
            <input id="setup-duration" name="duration_override_minutes" type="number" min={1} max={10080}
              value={durationOverride} onChange={event => setDurationOverride(event.target.value)} aria-describedby="setup-duration-hint" />
            <p id="setup-duration-hint" className="field-hint" aria-live="polite">{suggested != null
              ? `Leave blank to use the ${suggested}-minute suggestion.`
              : 'Choose a category and difficulty for a suggestion, or enter minutes.'}</p></div>
        </div>
      </fieldset>
      {canPlan && <fieldset className="setup-group">
        <legend>Technicians</legend>
        {!available.length && !savedOrder ? <p className="muted">No active technicians have access to this branch.</p> : <>
          <label htmlFor="setup-lead">Lead technician</label>
          <select id="setup-lead" value={lead} onChange={event => {
            const value = event.target.value;
            setLead(value);
            setAssistants(current => current.filter(member => member !== value));
          }}>
            <option value="" disabled={!!savedOrder}>Unassigned</option>
            {teamOptions.map(member => <option key={member.id} value={member.id} disabled={!member.available}>
              {member.label}
            </option>)}
          </select>
          {changingLead && <><label htmlFor="setup-reason">Reason for changing lead</label>
            <textarea id="setup-reason" name="reassignment_reason" required maxLength={10000} rows={2} /></>}
          {lead && teamOptions.some(member => member.id !== lead) &&
            <fieldset className="branch-checks"><legend>Supporting technicians (optional)</legend>
              {teamOptions.filter(member => member.id !== lead).map(member =>
                <label key={member.id}><input type="checkbox" checked={assistants.includes(member.id)}
                  disabled={!member.available && !assistants.includes(member.id)}
                  onChange={event => {
                    const checked = event.target.checked;
                    setAssistants(current => checked ? [...current, member.id] : current.filter(id => id !== member.id));
                  }} />{member.label}</label>)}
            </fieldset>}
        </>}
      </fieldset>}
      {canPlan && lead && <>
        <fieldset className="setup-group">
          <legend>Schedule</legend>
          {scheduledStart && <label className="setup-clear"><input type="checkbox" checked={clearSchedule}
            onChange={event => { setClearSchedule(event.target.checked); setScheduleError(''); }} />Clear schedule on save</label>}
          <div className="form-columns">
            <div><label htmlFor="setup-start">Planned start (local time)</label>
              <input id="setup-start" type="datetime-local" name="scheduled_start" defaultValue={scheduledStart}
                disabled={clearSchedule} aria-invalid={!!scheduleError} aria-describedby={scheduleError ? 'setup-start-error' : undefined}
                onChange={() => setScheduleError('')} />
              {scheduleError && <p id="setup-start-error" className="error" role="alert">{scheduleError}</p>}</div>
            <div><label htmlFor="setup-slot-minutes">Scheduled duration (minutes)</label>
              <input id="setup-slot-minutes" type="number" name="scheduled_minutes" min={1} max={10080}
                defaultValue={scheduledDuration ?? ''} disabled={clearSchedule} aria-describedby="setup-slot-hint" />
              <p id="setup-slot-hint" className="field-hint">Leave blank to use the service duration.</p></div>
          </div>
        </fieldset>
        <fieldset className="setup-group">
          <legend>Price estimate</legend>
          <p className="muted setup-price-hint">Uses the scheduled or service duration for each technician, plus materials.</p>
          <div className="form-columns">
            <div><label htmlFor="setup-rate">Hourly labor rate per technician (₱)</label>
              <input id="setup-rate" type="number" name="hourly_rate" min={0} max={maxMoney} step="0.01"
                defaultValue={quote?.hourly_rate} required={!!quote} /></div>
            {legacyMaterials && <div><label htmlFor="setup-materials">Existing materials total (₱)</label>
              <input id="setup-materials" type="number" name="materials_estimate" min={0} max={maxMoney} step="0.01"
                defaultValue={quote?.materials_estimate ?? '0'} required />
              <button type="button" className="secondary" onClick={() => setLegacyMaterials(false)}>Replace with material line items</button>
            </div>}
            <div><label htmlFor="setup-override">Manual total (₱, optional)</label>
              <input id="setup-override" type="number" name="price_override" min={0} max={maxMoney} step="0.01"
                defaultValue={quote?.override ?? ''} /></div>
            <div><label htmlFor="setup-price-reason">Reason for manual total</label>
              <textarea id="setup-price-reason" name="price_reason" maxLength={10000} rows={2} defaultValue={quote?.reason} /></div>
          </div>
          {!legacyMaterials && <fieldset className="materials-editor">
            <legend>Estimated materials</legend>
            <p className="field-hint">Record the supplier quotation, receipt, or price list behind each unit price. Quantities allow up to three decimal places.</p>
            {materialsItems.map((item, index) => <fieldset className="material-item" key={index}>
              <legend>Material {index + 1}</legend>
              <div className="form-columns">
                {(['name', 'quantity', 'unit_price', 'source'] as const).map(field => <div key={field}>
                  <label htmlFor={`material-${index}-${field}`}>{({ name: 'Item name', quantity: 'Quantity', unit_price: 'Unit price (₱)', source: 'Price source' })[field]}</label>
                  <input id={`material-${index}-${field}`} value={item[field]} required
                    type={field === 'quantity' || field === 'unit_price' ? 'number' : 'text'}
                    min={field === 'quantity' ? '0.001' : field === 'unit_price' ? '0' : undefined}
                    max={field === 'quantity' ? '1000000' : field === 'unit_price' ? maxMoney : undefined}
                    step={field === 'quantity' ? '0.001' : field === 'unit_price' ? '0.01' : undefined}
                    maxLength={field === 'name' ? 180 : field === 'source' ? 500 : undefined}
                    onChange={event => setMaterialsItems(current => current.map((entry, position) => position === index
                      ? { ...entry, [field]: event.target.value } : entry))} />
                </div>)}
              </div>
              <button type="button" className="secondary" aria-label={`Remove material ${index + 1}`}
                onClick={() => setMaterialsItems(current => current.filter((_, position) => position !== index))}>Remove material</button>
            </fieldset>)}
            <button type="button" className="secondary" disabled={materialsItems.length >= 100}
              onClick={() => setMaterialsItems(current => [...current, { name: '', quantity: '1', unit_price: '', source: '' }])}>Add material</button>
            {!materialsItems.length && <p className="field-hint">No materials added. The materials estimate will be ₱0.00.</p>}
          </fieldset>}
        </fieldset>
      </>}
      <button>{busy ? 'Saving…' : 'Save setup'}</button>
    </fieldset>
  </form>;
}
