import { useId, useState } from 'react';
import { Icon } from './Icon';

export type SuggestedMaterial = { name: string; quantity: string; unit: string; notes: string };
export type EstimateSuggestion = {
  summary: string; tasks: string[]; duration_minutes: number | null;
  materials: SuggestedMaterial[]; assumptions: string[]; missing_information: string[];
};

export function AIEstimateHelper({ onGenerate, onMaterials, onDuration, legacyMaterialsTotal, canAddMaterials }: {
  onGenerate: () => Promise<EstimateSuggestion>;
  onMaterials: (items: SuggestedMaterial[]) => boolean;
  onDuration: (minutes: number) => void;
  legacyMaterialsTotal?: string;
  canAddMaterials: boolean;
}) {
  const [suggestion, setSuggestion] = useState<EstimateSuggestion | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [addedMaterials, setAddedMaterials] = useState(false);
  const [usedDuration, setUsedDuration] = useState(false);
  const titleId = useId();

  async function generate() {
    if (loading) return;
    setLoading(true); setError('');
    try {
      setSuggestion(await onGenerate());
      setAddedMaterials(false); setUsedDuration(false);
    }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to generate suggestions.'); }
    finally { setLoading(false); }
  }

  return <section className="ai-estimate-helper" aria-labelledby={titleId}>
    <header className="ai-estimate-header">
      <div className="ai-estimate-heading"><span className="icon-tile"><Icon name="tool" size={18} /></span>
        <div><h4 id={titleId}>AI estimate assistant</h4><p className="field-hint">A starting point for your estimate.</p></div>
      </div>
      <button type="button" className="secondary" disabled={loading} onClick={() => void generate()}>
        {loading ? <span className="spinner" aria-hidden="true" /> : <Icon name="refresh" size={16} />}
        {loading ? 'Generating…' : suggestion ? 'Regenerate' : 'Generate plan'}
      </button>
    </header>
    <p className="field-hint ai-estimate-disclosure">Uses saved details via Groq. Review before saving.</p>
    <details className="ai-estimate-details ai-data-details">
      <summary>What gets shared?</summary>
      <p className="field-hint">Groq receives the saved issue, equipment name and condition, category, difficulty, and recent maintenance notes.
        Free text is sent as entered; photos and account details are excluded. Save request changes before generating.</p>
    </details>
    <span role="status" className={loading ? 'field-hint ai-estimate-status' : 'sr-only'}>
      {loading ? 'Preparing a plan. You can continue estimating manually.'
        : suggestion ? 'Plan ready for review. Changes apply only when you save setup.' : ''}
    </span>
    {error && <p role="alert" className="error">{error}</p>}
    {suggestion && <div className="ai-suggestion">
      <p className="ai-plan-summary">{suggestion.summary}</p>
      <div className="ai-estimate-duration">
        <div><span className="field-hint">Service duration</span>
          <strong>{suggestion.duration_minutes !== null ? suggestion.duration_minutes + ' min' : 'Needs more info'}</strong>
        </div>
        {suggestion.duration_minutes !== null && <button type="button" className="secondary" disabled={usedDuration || loading} onClick={() => {
          onDuration(suggestion.duration_minutes!); setUsedDuration(true);
        }}>{usedDuration ? <><Icon name="check" size={16} />Added to form</> : 'Use duration'}</button>}
      </div>
      <p className="field-hint">Existing scheduled slots stay fixed.</p>
      {!!suggestion.materials.length && <>
        <details className="ai-estimate-details">
          <summary>Proposed materials <span className="ai-detail-count">{suggestion.materials.length}</span></summary>
          <ul className="ai-material-list">{suggestion.materials.map((item, index) => <li key={index}>
            <div><strong>{item.name}</strong><span>{item.quantity} {item.unit}</span></div>
            {item.notes && <p className="field-hint">{item.notes}</p>}
          </li>)}</ul>
        </details>
        <div className="ai-material-actions">
          <button type="button" className="secondary" disabled={addedMaterials || !canAddMaterials || loading} onClick={() => {
            if (onMaterials(suggestion.materials)) setAddedMaterials(true);
          }}>{addedMaterials ? 'Materials added to form' : legacyMaterialsTotal !== undefined
            ? 'Replace materials total with items' : 'Add materials to form'}</button>
          <p className="field-hint">{legacyMaterialsTotal !== undefined
            ? 'Replaces ₱' + legacyMaterialsTotal + '. Add verified unit prices and sources before saving.'
            : 'Check for duplicates; add verified unit prices and sources.'}</p>
          {!canAddMaterials && <p className="field-hint">Select a lead technician to add materials.</p>}
        </div>
      </>}
      {!!suggestion.missing_information.length && <details className="ai-estimate-details ai-review-needed">
        <summary>Information needed <span className="ai-detail-count">{suggestion.missing_information.length}</span></summary>
        <ul>{suggestion.missing_information.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </details>}
      {!!suggestion.tasks.length && <details className="ai-estimate-details">
        <summary>Repair tasks <span className="ai-detail-count">{suggestion.tasks.length}</span></summary>
        <ol>{suggestion.tasks.map((task, index) => <li key={index}>{task}</li>)}</ol>
      </details>}
      {!!suggestion.assumptions.length && <details className="ai-estimate-details">
        <summary>Assumptions to confirm <span className="ai-detail-count">{suggestion.assumptions.length}</span></summary>
        <ul>{suggestion.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </details>}
      <p className="field-hint ai-estimate-footer">Draft only · Save setup to apply · Budget approval is separate</p>
    </div>}
  </section>;
}
