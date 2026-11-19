import assert from 'node:assert/strict';
import test from 'node:test';
import { priceInputsChanged, setupSavedMessage } from './planning.ts';

const items = [{ name:'Tape', quantity:'2', unit_price:'25.00', source:'Supplier quote' }];
const quote = { hourly_rate:'250.00', materials_estimate:'50.00', materials_items:items,
  override:null, reason:'' };
const edited = { rate:'250', materials:'0', items, legacy:false, override:'', reason:'' };

test('unchanged itemized materials do not trigger a price update on partial setup saves', () => {
  assert.equal(priceInputsChanged(quote, edited), false);
  assert.equal(priceInputsChanged(quote, {...edited, items:[{...items[0], quantity:'2.000', unit_price:'25'}]}), false);
});
test('price changes still capture amounts, sources, quantities, and manual totals', () => {
  for (const field of [{rate:'300'}, {items:[{...items[0], source:'New quotation'}]},
    {items:[{...items[0], quantity:'3'}]}, {override:'600', reason:'Additional work'}]) {
    assert.equal(priceInputsChanged(quote, {...edited, ...field}), true);
  }
});
test('legacy materials totals remain editable and switching to itemization is a change', () => {
  const legacy = {...quote, materials_items:null};
  assert.equal(priceInputsChanged(legacy, {...edited, legacy:true, materials:'50'}), false);
  assert.equal(priceInputsChanged(legacy, edited), true);
});
test('saved status distinguishes partial setup from complete planning', () => {
  assert.equal(setupSavedMessage(['Schedule','Price estimate']), 'Setup saved. Still needed: Schedule, Price estimate.');
  assert.equal(setupSavedMessage([]), 'Setup saved. All planning details are complete.');
});
