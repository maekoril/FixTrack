import { useState } from 'react';

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

  async function generate() {
    if (loading) return;
    setLoading(true); setError(''); setSuggestion(null);
    setAddedMaterials(false); setUsedDuration(false);
    try { setSuggestion(await onGenerate()); }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to generate suggestions.'); }
    finally { setLoading(false); }
  }

  return <section className="ai-estimate-helper" aria-labelledby="ai-estimate-title" aria-busy={loading}>
    <h4 id="ai-estimate-title">AI estimate assistant</h4>
    <p className="field-hint">Generate repair tasks, material quantities, and a service duration from the saved issue and maintenance notes.
      Save any changes to the request before generating.</p>
    <p className="field-hint">Generating sends the issue details, equipment name and condition, category, difficulty, and recent maintenance notes to Groq.
      Photos and account details are excluded. Suggestions need your review and verified prices.</p>
    <button type="button" className="secondary" disabled={loading} onClick={() => void generate()}>
      {loading ? 'Generating suggestions…' : 'Generate AI suggestions'}
    </button>
    <span role="status" className="field-hint">{loading ? 'Preparing a repair plan. You can continue estimating manually.' : ''}</span>
    {error && <p role="alert" className="error">{error}</p>}
    {suggestion && <div className="ai-suggestion">
      <p><strong>Suggested plan:</strong> {suggestion.summary}</p>
      {!!suggestion.tasks.length && <><h5>Repair tasks</h5><ul>{suggestion.tasks.map((task, index) => <li key={index}>{task}</li>)}</ul></>}
      {suggestion.duration_minutes !== null ? <>
        <p><strong>Suggested service duration:</strong> {suggestion.duration_minutes} minutes per technician.</p>
        <button type="button" className="secondary" disabled={usedDuration} onClick={() => {
          onDuration(suggestion.duration_minutes!); setUsedDuration(true);
        }}>{usedDuration ? 'Duration added to form' : 'Use suggested service duration'}</button>
        <p className="field-hint">Review and save the form to apply. An existing scheduled slot keeps its saved duration.</p>
      </> : <p>More information is needed to suggest a service duration.</p>}
      {!!suggestion.materials.length && <>
        <h5>Proposed materials</h5>
        <ul>{suggestion.materials.map((item, index) => <li key={index}>
          <strong>{item.name}</strong> · {item.quantity} {item.unit}<p className="field-hint">{item.notes}</p>
        </li>)}</ul>
        <button type="button" className="secondary" disabled={addedMaterials || !canAddMaterials} onClick={() => {
          if (onMaterials(suggestion.materials)) setAddedMaterials(true);
        }}>{addedMaterials ? 'Materials added to form' : legacyMaterialsTotal !== undefined
          ? 'Replace materials total with proposed items' : 'Add proposed materials to estimate'}</button>
        <p className="field-hint">{legacyMaterialsTotal !== undefined
          ? `Replaces the existing materials total of ₱${legacyMaterialsTotal} in this form. Enter verified prices and sources for the new items before saving.`
          : 'Adds new lines with empty prices and sources for you to complete. Check for duplicates before saving.'}</p>
        {!canAddMaterials && <p className="field-hint">Select a lead technician in the form to add materials to a work-order estimate.</p>}
      </>}
      {!!suggestion.assumptions.length && <><h5>Assumptions to confirm</h5><ul>{suggestion.assumptions.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
      {!!suggestion.missing_information.length && <><h5>Information needed</h5><ul>{suggestion.missing_information.map((item, index) => <li key={index}>{item}</li>)}</ul></>}
    </div>}
  </section>;
}
