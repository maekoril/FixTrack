import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

export const intakeCategories = [
  ['plumbing', 'plumbing', 'Plumbing'], ['electrical', 'electrical', 'Electrical'],
  ['hvac', 'air-conditioning-ventilation', 'Air Conditioning & Ventilation'],
  ['carpentry', 'carpentry', 'Carpentry'], ['civil_structural', 'civil-structural', 'Civil & Structural'],
  ['appliance_equipment', 'equipment-repair', 'Equipment Repair'], ['it_network', 'it-network', 'IT & Network'],
  ['pest_control', 'pest-control', 'Pest Control'], ['cleaning_sanitation', 'cleaning-sanitation', 'Cleaning & Sanitation'],
  ['other', 'other', 'Other'],
] as const;
const categoryId = (value: string) => intakeCategories.find(item => item[0] === value)?.[1] ?? value;
const humanize = (value: string) => value.replaceAll('_', ' ');
type PhotoAnalysis = { provided: boolean; visible_issue: string | null; severity_estimate: string;
  suggested_tools_or_parts: string[]; matches_description: boolean | null };
type TriageResult = { original_description: string; normalized_description: string; language_detected: string;
  category: string; subcategory: string; priority: string; priority_reason: string; safety_flags: string[];
  confidence: number; needs_more_info: boolean; follow_up_questions: string[]; photo_analysis: PhotoAnalysis };
type FollowUpRound = { answers: { question: string; answer: string }[] };
type TriageResponse = { result: TriageResult | null; triage_id: string | null; incomplete_info: boolean;
  manual_fallback: boolean; message: string | null; safety_flags: string[] };
export type IntakeDraft = { branch_id: string; title: string; description: string; location: string;
  asset_id: string | null; category_id: string; priority: string; triage_id: string | null; photo: File | null };
export type SavedIntake = {
  original_description: string; normalized_description: string; language_detected: string;
  ai_category: string | null; ai_priority: string | null; ai_subcategory: string | null;
  ai_priority_reason: string | null; ai_safety_flags: string[]; ai_confidence: number | null;
  final_category: string | null; final_priority: string | null; ai_overridden: boolean;
  incomplete_info: boolean; photo_analysis: PhotoAnalysis | null;
  conversation: FollowUpRound[];
};

export function SafetyNotice({ flags }: { flags: string[] }) {
  const hazards = flags.filter(flag => flag !== 'none');
  if (!hazards.length) return null;
  return <div className="intake-safety" role="alert"><strong>Safety concern — immediate review</strong>
    <p>{hazards.map(humanize).join(' · ')}</p><p>Follow your branch’s safety procedures. The safety flags remain visible even if priority is changed.</p></div>;
}

export function RequestIntakeForm({ token, branches, branch, assets, busy, onBranch, onSubmit, onCancel, onExpired }: {
  token: string; branches: { id: string; name: string }[]; branch: string;
  assets: { id: string; name: string; asset_tag: string }[]; busy: boolean;
  onBranch: (value: string) => void; onSubmit: (data: IntakeDraft) => Promise<void>;
  onCancel: () => void; onExpired: () => void;
}) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [location, setLocation] = useState('');
  const [asset, setAsset] = useState('');
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [result, setResult] = useState<TriageResponse | null>(null);
  const [conversation, setConversation] = useState<FollowUpRound[]>([]);
  const [answers, setAnswers] = useState<string[]>([]);
  const [stage, setStage] = useState<'draft' | 'questions' | 'review' | 'manual'>('draft');
  const [category, setCategory] = useState('');
  const [priority, setPriority] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!photo) { setPreview(''); return; }
    const url = URL.createObjectURL(photo); setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  function invalidate() {
    setResult(null); setConversation([]); setAnswers([]); setStage('draft'); setError('');
  }

  async function analyze() {
    const rounds = stage === 'questions' && result?.result ? [...conversation, {
      answers: result.result.follow_up_questions.map((question, index) => ({question, answer: answers[index] ?? ''})),
    }] : conversation;
    setLoading(true); setError('');
    const form = new FormData();
    form.set('description', description); form.set('branch_id', branch); form.set('location_detail', location);
    form.set('conversation', JSON.stringify(rounds));
    if (photo) form.set('image', photo);
    try {
      const response = await fetch('/api/requests/triage', {method:'POST', headers:{Authorization:`Bearer ${token}`}, body:form});
      if (response.status === 401) { onExpired(); throw new Error('Your session expired. Sign in again.'); }
      const body = await response.json();
      if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : 'AI review is unavailable. Submit manually.');
      const next: TriageResponse = body;
      setResult(next); setConversation(rounds); setAnswers([]);
      if (next.manual_fallback || !next.result) { setStage('manual'); setError(next.message ?? 'Continue with manual intake.'); }
      else {
        setCategory(next.result.category); setPriority(next.result.priority);
        setStage(next.result.needs_more_info ? 'questions' : 'review');
      }
    } catch (err) { setError(err instanceof Error ? err.message : 'AI review failed. Submit manually.'); setStage('manual'); setResult(null); }
    finally { setLoading(false); }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (stage === 'draft' || stage === 'questions') { await analyze(); return; }
    if (!category || !priority) { setError('Choose a category and priority before submitting.'); return; }
    await onSubmit({branch_id:branch, title, description, location, asset_id:asset || null,
      category_id:categoryId(category), priority, triage_id:stage === 'review' ? result?.triage_id ?? null : null, photo});
  }

  const suggestion = result?.result;
  const overridden = suggestion && (category !== suggestion.category || priority !== suggestion.priority);
  return <form onSubmit={event => void submit(event)}>
    <fieldset disabled={busy || loading}>
      <div className="form-columns"><div><label htmlFor="request-branch">Branch</label>
        <select id="request-branch" value={branch} required onChange={event => {onBranch(event.target.value); setAsset(''); invalidate();}}>
          {branches.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></div>
        <div><label htmlFor="request-location">Location</label><input id="request-location" value={location} required maxLength={255}
          onChange={event => {setLocation(event.target.value); invalidate();}} placeholder="e.g. 2nd floor, near cashier" /></div></div>
      <label htmlFor="request-title">Issue title</label><input id="request-title" value={title} onChange={event => setTitle(event.target.value)} minLength={3} maxLength={180} required />
      <label htmlFor="request-description">What happened? (English, Tagalog, or Taglish)</label>
      <textarea id="request-description" value={description} onChange={event => {setDescription(event.target.value); invalidate();}}
        rows={4} maxLength={10000} required placeholder="e.g. tumutulo yung aircon sa may cashier" />
      <label htmlFor="request-asset">Related asset (optional)</label><select id="request-asset" value={asset} onChange={event => setAsset(event.target.value)}>
        <option value="">General facility issue / no registered asset</option>
        {assets.map(item => <option key={item.id} value={item.id}>{item.asset_tag} · {item.name}</option>)}</select>
      <label htmlFor="report-photo">Issue photo (optional)</label><input id="report-photo" type="file" accept="image/jpeg,image/png,image/webp"
        aria-describedby="report-photo-hint" onChange={event => {
          const file = event.target.files?.[0] ?? null; invalidate();
          if (file && (file.size > 5 * 1024 * 1024 || !['image/jpeg','image/png','image/webp'].includes(file.type))) {
            setError('Choose a JPEG, PNG, or WebP photo up to 5 MB.'); event.target.value = ''; setPhoto(null);
          } else setPhoto(file);
        }} />
      <p id="report-photo-hint" className="field-hint">JPEG, PNG, or WebP up to 5 MB. AI review sends the issue, location, answers, and optional resized photo to Groq.
        Recognized contact details are removed from text; avoid including people or private information in photos.</p>
      {preview && <img className="intake-photo-preview" src={preview} alt="Selected issue photo preview" />}
      <SafetyNotice flags={result?.safety_flags ?? []} />
      {stage === 'questions' && suggestion && <section className="intake-followup" aria-labelledby="followup-title">
        <h3 id="followup-title">A few details before creating the request</h3>
        <p>Follow-up round {conversation.length + 1} of 2. No ticket has been created.</p>
        {suggestion.follow_up_questions.map((question, index) => <div key={question}>
          <label htmlFor={`followup-${index}`}>{question}</label><input id={`followup-${index}`} value={answers[index] ?? ''} required maxLength={2000}
            onChange={event => setAnswers(current => suggestion.follow_up_questions.map((_, position) => position === index ? event.target.value : current[position] ?? ''))} />
        </div>)}
      </section>}
      {stage === 'review' && suggestion && <section className="intake-review">
        <h3>Review AI suggestions</h3><p className="description">{suggestion.normalized_description}</p>
        <p className="field-hint">Detected language: {suggestion.language_detected} · Confidence: {Math.round(suggestion.confidence * 100)}% · {suggestion.subcategory}</p>
        <p>{suggestion.priority_reason}</p>
        {result?.incomplete_info && <p className="intake-incomplete"><strong>Incomplete info:</strong> Two follow-up rounds are complete. This request will be flagged for staff review.</p>}
        {suggestion.photo_analysis.provided && <div><h4>Photo observations</h4><p>{suggestion.photo_analysis.visible_issue ?? 'No clear issue visible.'}</p>
          <p>Estimated visible severity: {suggestion.photo_analysis.severity_estimate}. {suggestion.photo_analysis.matches_description === false ? 'Photo may not match the description.' : ''}</p>
          {!!suggestion.photo_analysis.suggested_tools_or_parts.length && <p className="field-hint">Tentative tools / parts: {suggestion.photo_analysis.suggested_tools_or_parts.join(', ')}</p>}</div>}
      </section>}
      {(stage === 'review' || stage === 'manual') && <div className="form-columns">
        <div><label htmlFor="report-category">Service category {suggestion && <span className="badge">AI suggested</span>}</label>
          <select id="report-category" required value={category} onChange={event => setCategory(event.target.value)}><option value="">Select category</option>
            {intakeCategories.map(item => <option key={item[0]} value={item[0]}>{item[2]}</option>)}</select></div>
        <div><label htmlFor="report-priority">Priority {suggestion && <span className="badge">AI suggested</span>}</label>
          <select id="report-priority" required value={priority} onChange={event => setPriority(event.target.value)}><option value="">Select priority</option>
            {['low','medium','high','urgent'].map(item => <option key={item} value={item}>{item}</option>)}</select></div>
      </div>}
      {overridden && <p className="field-hint">Your changes will be saved alongside the AI suggestions as a human override.</p>}
      {error && <p className="error" role="alert">{error}</p>}
      <p role="status">{loading ? 'Reviewing the issue… You can submit manually if AI is unavailable.' : ''}</p>
      <div className="actions"><button>{busy ? 'Submitting…' : loading ? 'Reviewing…' : stage === 'draft' ? 'Review with AI' : stage === 'questions' ? 'Send answers' : 'Submit request'}</button>
        {(stage === 'draft' || stage === 'questions' || stage === 'review') && <button type="button" className="secondary" onClick={() => {
          setStage('manual'); setResult(null); setError('');
        }}>Continue manually</button>}
        <button type="button" className="secondary" onClick={onCancel}>Cancel</button></div>
    </fieldset>
  </form>;
}

export function IntakeDetails({ intake, canEdit, busy, onConfirm }: {
  intake: SavedIntake; canEdit: boolean; busy: boolean;
  onConfirm: (category: string, priority: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const editorId = useId();
  const editButton = useRef<HTMLButtonElement>(null);
  const [category, setCategory] = useState(intake.final_category ?? '');
  const [priority, setPriority] = useState(intake.final_priority ?? '');
  const [error, setError] = useState('');
  return <section className="intake-details">
    <SafetyNotice flags={intake.ai_safety_flags} />
    {intake.incomplete_info && <p className="intake-incomplete"><strong>Incomplete info:</strong> Review the report and follow-up answers before planning work.</p>}
    <div className="intake-heading"><h3>Description</h3>
      {canEdit && <button ref={editButton} type="button" className="secondary" disabled={busy}
        aria-label="Edit category and priority" aria-expanded={editing} aria-controls={editorId}
        onClick={() => { setCategory(intake.final_category ?? ''); setPriority(intake.final_priority ?? ''); setError(''); setEditing(!editing); }}>Edit</button>}
    </div>
    <p className="description">{intake.normalized_description || intake.original_description}</p>
    {intake.normalized_description && intake.normalized_description !== intake.original_description &&
      <details><summary>Original report</summary><p className="description">{intake.original_description}</p></details>}
    {!!intake.conversation.length && <details><summary>Follow-up answers</summary>{intake.conversation.flatMap((round, index) => round.answers.map(qa =>
      <p key={`${index}-${qa.question}`}><strong>{qa.question}</strong><br />{qa.answer}</p>))}</details>}
    <div id={editorId} hidden={!editing || !canEdit}>
      {editing && canEdit && <form className="intake-editor" onSubmit={event => {
        event.preventDefault(); setError('');
        void onConfirm(category, priority).then(() => { setEditing(false); editButton.current?.focus(); })
          .catch(err => setError(err instanceof Error ? err.message : 'Unable to save changes.'));
      }}><fieldset disabled={busy}><legend>Category &amp; priority</legend>
        <div className="form-columns"><div>
          <label htmlFor={`${editorId}-category`}>Category</label><select id={`${editorId}-category`} autoFocus value={category} onChange={event => setCategory(event.target.value)} required>
            <option value="">Select category</option>{intakeCategories.map(item => <option key={item[0]} value={item[0]}>{item[2]}</option>)}</select>
        </div><div>
          <label htmlFor={`${editorId}-priority`}>Priority</label><select id={`${editorId}-priority`} value={priority} onChange={event => setPriority(event.target.value)} required>
            <option value="">Select priority</option>{['low','medium','high','urgent'].map(item => <option key={item} value={item}>{item[0].toUpperCase() + item.slice(1)}</option>)}</select>
        </div></div>
        {intake.ai_category && <p className="field-hint">AI suggestion: {intakeCategories.find(item => item[0] === intake.ai_category)?.[2] ?? humanize(intake.ai_category)} · {intake.ai_priority}
          {intake.ai_confidence !== null && ` · ${Math.round(Number(intake.ai_confidence) * 100)}% confidence`}
          {intake.ai_overridden && '. Human override recorded.'}</p>}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="actions"><button>{busy ? 'Saving…' : 'Save changes'}</button>
          <button type="button" className="secondary" onClick={() => { setEditing(false); setError(''); editButton.current?.focus(); }}>Cancel</button></div>
      </fieldset></form>}
    </div>
  </section>;
}
