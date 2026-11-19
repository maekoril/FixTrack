type MaterialFields = { name: string; quantity: string; unit_price: string; source: string };
type Quote = { hourly_rate: string; materials_estimate: string; materials_items?: MaterialFields[] | null;
  override: string | null; reason: string };

export function priceInputsChanged(quote: Quote | undefined, edited: {
  rate: string; materials: string; items: MaterialFields[]; legacy: boolean; override: string; reason: string;
}) {
  if (!quote) return true;
  const money = (value: string | null) => value === null || value === '' ? null : Number(value);
  const lines = (items: MaterialFields[]) => items.map(item => ({
    name: item.name.trim(), quantity: Number(item.quantity), unit_price: Number(item.unit_price), source: item.source.trim(),
  }));
  return Number(edited.rate) !== Number(quote.hourly_rate)
    || money(edited.override) !== money(quote.override)
    || (edited.override ? edited.reason.trim() : '') !== quote.reason
    || (edited.legacy ? Number(edited.materials) !== Number(quote.materials_estimate)
      : quote.materials_items == null || JSON.stringify(lines(edited.items)) !== JSON.stringify(lines(quote.materials_items)));
}

export function setupSavedMessage(missing: string[]) {
  return missing.length ? `Setup saved. Still needed: ${missing.join(', ')}.`
    : 'Setup saved. All planning details are complete.';
}
