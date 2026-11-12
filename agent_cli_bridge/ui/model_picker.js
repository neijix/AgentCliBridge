// Which models a picker offers, and the <select> it fills. Classic script.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

// A curated model is in unless the owner hid it; a new one stays out until the owner ticks it,
// and so does an optional one (a paid Open Router model).
const isModelInPicker = function isModelInPicker(spec) {
  const given = spec || {};
  const isNew = given.isNew === undefined ? false : given.isNew;
  const isOptional = given.isOptional === undefined ? false : given.isOptional;
  const key = given.key === undefined ? "" : given.key;
  const hidden = given.hidden === undefined ? new Set() : given.hidden;
  const shown = given.shown === undefined ? new Set() : given.shown;
  if (isNew || isOptional) return shown.has(key);
  return !hidden.has(key);
};

const optionCost = function optionCost(isPriced, model, prices) {
  if (!isPriced) return null;
  const price = acb.modelPriceNote(model, prices?.[model]);
  if (!price || price.isFree || price.text === "—") return null;
  return price.text;
};

const optionLabel = function optionLabel(name, model, agent, cost) {
  const parts = [name, acb.modelDisplayName(model, agent)];
  const notes = [acb.modelIndexNote(model), acb.modelLimitedNote(model), acb.modelPreviewNote(model)];
  for (const note of notes) {
    if (note) parts.push(note.text);
  }
  if (cost) parts.push(cost);
  return parts.join(" · ");
};

// [{ label, agent, options: [{ value, key, model, label }] }]. `keep` stays listed even when
// hidden — the open chat's own model. `valueFor` is what the host sends back.
const pickerGroups = function pickerGroups(agents, spec) {
  const given = spec || {};
  const hidden = given.hidden === undefined ? new Set() : given.hidden;
  const shown = given.shown === undefined ? new Set() : given.shown;
  const keep = given.keep === undefined ? null : given.keep;
  const valueFor = given.valueFor || function valueFor(agent, model) {
    return acb.modelKey(agent.command, model);
  };
  const groups = [];
  for (const agent of agents || []) {
    if (agent.metrics) acb.rememberModelMetrics(agent.metrics);
    const name = acb.agentDisplayName(agent);
    const fresh = new Set(agent.new_models || []);
    const optional = new Set(agent.optional_models || []);
    const isPriced = acb.isPricedAgent(agent);
    const ranked = acb.sortModelsByIntelligence((agent.models || []).map(function (model) {
      return { model };
    }));
    const options = [];
    for (const item of ranked) {
      const model = item.model;
      const key = acb.modelKey(agent.command, model);
      const value = valueFor(agent, model);
      const isIn = isModelInPicker({ isNew: fresh.has(model), isOptional: optional.has(model), key, hidden, shown });
      if (!isIn && value !== keep) continue;
      const cost = optionCost(isPriced, model, agent.prices);
      options.push({ value, key, model, label: optionLabel(name, model, agent, cost) });
    }
    if (options.length) groups.push({ label: name, agent, options });
  }
  return groups;
};

const pickerEmptyText = function pickerEmptyText(agents) {
  return (agents || []).length ? "Every model hidden — enable one in Settings" : "No subscriptions on this machine";
};

const fillPicker = function fillPicker(select, groups, emptyText) {
  const doc = select.ownerDocument;
  const blank = emptyText === undefined ? "No subscriptions on this machine" : emptyText;
  const nodes = [];
  for (const group of groups) {
    const node = doc.createElement("optgroup");
    node.label = group.label;
    for (const item of group.options) {
      const option = doc.createElement("option");
      option.value = item.value;
      option.textContent = item.label;
      node.append(option);
    }
    nodes.push(node);
  }
  if (!nodes.length) {
    const option = doc.createElement("option");
    option.value = "";
    option.textContent = blank;
    nodes.push(option);
  }
  select.replaceChildren(...nodes);
};

acb.isModelInPicker = isModelInPicker;
acb.pickerGroups = pickerGroups;
acb.pickerEmptyText = pickerEmptyText;
acb.fillPicker = fillPicker;
}
