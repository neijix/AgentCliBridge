// Settings catalog: every machine's CLIs, and the Models tables. Classic script.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

const MODEL_TABLE_FOLD = 12;
const openModelGroups = new WeakMap();

const machineName = function machineName(machine) {
  return machine.name;
};

const blankModelRow = function blankModelRow(agent, model) {
  return {
    model,
    command: agent.command,
    key: acb.modelKey(agent.command, model),
    isNew: false,
    isOptional: false,
    price: null,
    label: "",
    offeredBy: [],
  };
};

const absorbModel = function absorbModel(entry, agent, model, label, fresh, optional) {
  const row = entry.models.get(model) || blankModelRow(agent, model);
  row.isNew = row.isNew || fresh.has(model);
  row.isOptional = row.isOptional || optional.has(model);
  row.price = row.price || agent.prices?.[model] || null;
  row.label = row.label || acb.modelLabel(agent, model);
  row.offeredBy.push(label);
  entry.models.set(model, row);
};

const absorbAgent = function absorbAgent(byAgent, label, agent) {
  if (agent.metrics) acb.rememberModelMetrics(agent.metrics);
  const entry = byAgent.get(agent.command) || {
    command: agent.command,
    name: acb.agentDisplayName(agent),
    hubs: [],
    models: new Map(),
  };
  entry.hubs.push(label);
  const fresh = new Set(agent.new_models || []);
  const optional = new Set(agent.optional_models || []);
  entry.isPriced = entry.isPriced || acb.isPricedAgent(agent);
  entry.isLocal = entry.isLocal || acb.isLocalAgent(agent);
  for (const model of agent.models || []) absorbModel(entry, agent, model, label, fresh, optional);
  byAgent.set(agent.command, entry);
};

const catalogModels = function catalogModels(entry) {
  const models = [];
  for (const row of entry.models.values()) {
    const onlyOn = row.offeredBy.length < entry.hubs.length ? row.offeredBy : [];
    models.push({
      model: row.model,
      command: row.command,
      key: row.key,
      isNew: row.isNew,
      isOptional: row.isOptional,
      price: row.price,
      label: row.label,
      offeredBy: row.offeredBy,
      onlyOn,
    });
  }
  return models;
};

// One group per CLI, models in first-seen order. `onlyOn` is empty when every machine lists it.
const modelCatalog = function modelCatalog(machines, labelOf) {
  const labelFor = labelOf || machineName;
  const byAgent = new Map();
  for (const machine of machines || []) {
    const label = labelFor(machine) || machine.name || "";
    for (const agent of machine.agents || []) absorbAgent(byAgent, label, agent);
  }
  const groups = [];
  for (const entry of byAgent.values()) {
    groups.push({
      command: entry.command,
      name: entry.name,
      isPriced: entry.isPriced || false,
      isLocal: entry.isLocal || false,
      models: catalogModels(entry),
    });
  }
  return groups;
};

const modelWhereNote = function modelWhereNote(row, agentName) {
  if (!row.onlyOn?.length) return null;
  const where = row.onlyOn.join(", ");
  const shown = row.label || acb.modelDisplayName(row.model);
  if (row.command === "mlx") {
    return { text: `${where} only`, title: `Only ${where} has ${shown} downloaded.` };
  }
  return {
    text: `${where} only`,
    title: `Only ${where} lists ${shown} for ${agentName}. On the other machines it stays out of the picker until their ${agentName} lists it too (models.${row.command} in that machine's agent_cli_bridge.json, or a CLI update).`,
  };
};

const newModelsNote = function newModelsNote(agents, seen) {
  const known = seen || new Set();
  const fresh = [];
  for (const agent of agents || []) {
    for (const model of agent.new_models || []) {
      if (known.has(acb.modelKey(agent.command, model))) continue;
      fresh.push({
        command: agent.command,
        name: acb.agentDisplayName(agent),
        model,
        shown: acb.modelDisplayName(model, agent),
      });
    }
  }
  if (!fresh.length) return null;
  const keys = [];
  const detail = [];
  for (const item of fresh) {
    keys.push(acb.modelKey(item.command, item.model));
    detail.push(`New: ${item.name} · ${item.shown}`);
  }
  const text = fresh.length === 1 ? `New model: ${fresh[0].shown}` : `${fresh.length} new models available`;
  return { count: fresh.length, keys, text, detail };
};

const modelTableHead = function modelTableHead(doc) {
  const head = doc.createElement("tr");
  const columns = [["Model", ""], ["Intelligence", "num bar"], ["Speed", "num bar"], ["Price", "num price"]];
  for (const column of columns) {
    const cell = acb.make(doc, "th", column[1], column[0]);
    cell.scope = "col";
    head.append(cell);
  }
  const thead = doc.createElement("thead");
  thead.append(head);
  return thead;
};

const modelBarCell = function modelBarCell(doc, kind, value, max, text) {
  const cell = acb.make(doc, "td", "num bar");
  const wrap = acb.make(doc, "div", `model-bar ${kind}`);
  const track = acb.make(doc, "span", "model-bar-track");
  const label = acb.make(doc, "span", "model-bar-value", text);
  const percent = acb.modelBarPercent(value, max);
  if (percent !== null) {
    const fill = acb.make(doc, "span", "model-bar-fill");
    fill.style.width = `${percent}%`;
    fill.append(label);
    track.append(fill);
  } else {
    track.classList.add("empty");
    track.append(label);
  }
  wrap.append(track);
  cell.append(wrap);
  return cell;
};

const appendTag = function appendTag(doc, label, className, note) {
  if (!note) return;
  const tag = acb.make(doc, "span", className, note.text);
  if (note.title) tag.title = note.title;
  label.append(tag);
};

const modelTableRow = function modelTableRow(doc, item, name, spec) {
  const isIn = acb.isModelInPicker({
    isNew: item.isNew, isOptional: item.isOptional, key: item.key, hidden: spec.hidden, shown: spec.shown,
  });
  const price = acb.modelPriceNote(item.model, item.price, spec.isPriced, spec.isLocal);
  const metrics = acb.modelMetrics(item.model);
  const row = doc.createElement("tr");
  if (isIn) row.classList.add("in-picker");
  const nameCell = doc.createElement("td");
  const label = acb.make(doc, "label", "model-toggle");
  const box = doc.createElement("input");
  box.type = "checkbox";
  box.checked = isIn;
  box.addEventListener("change", function () { spec.onToggle(item.key, box.checked); });
  const shownName = item.label || acb.modelDisplayName(item.model);
  const modelName = acb.make(doc, "span", "model-name", shownName);
  modelName.title = shownName === item.model ? shownName : item.model;
  label.append(box, modelName);
  appendTag(doc, label, "model-index", acb.modelIndexNote(item.model));
  appendTag(doc, label, "model-limited", acb.modelLimitedNote(item.model));
  appendTag(doc, label, "model-preview", acb.modelPreviewNote(item.model));
  if (item.isNew) label.append(acb.make(doc, "span", "model-new", "new"));
  appendTag(doc, label, "model-where", modelWhereNote(item, name));
  nameCell.append(label);
  const priceCell = acb.make(doc, "td", `num price${price.isFree ? " free" : ""}`, price.text);
  priceCell.title = price.title;
  row.append(
    nameCell,
    modelBarCell(doc, "intelligence", metrics.intelligence, spec.maxIntelligence, acb.formatModelIntelligence(metrics)),
    modelBarCell(doc, "speed", metrics.speed, spec.maxSpeed, acb.formatModelSpeed(metrics)),
    priceCell,
  );
  return { row, isIn, price };
};

const metricCeilings = function metricCeilings(catalog) {
  let maxIntelligence = 0;
  let maxSpeed = 0;
  for (const group of catalog) {
    for (const item of group.models) {
      const metrics = acb.modelMetrics(item.model);
      if (Number.isFinite(metrics.intelligence)) maxIntelligence = Math.max(maxIntelligence, metrics.intelligence);
      if (Number.isFinite(metrics.speed)) maxSpeed = Math.max(maxSpeed, metrics.speed);
    }
  }
  return { maxIntelligence, maxSpeed };
};

const tableOptions = function tableOptions(options) {
  const given = options || {};
  return {
    hidden: given.hidden === undefined ? new Set() : given.hidden,
    shown: given.shown === undefined ? new Set() : given.shown,
    freeOnly: given.freeOnly === undefined ? false : given.freeOnly,
    query: given.query === undefined ? "" : given.query,
    onToggle: given.onToggle || function onToggle() {},
    emptyText: given.emptyText === undefined ? "No agent CLI found on this computer." : given.emptyText,
  };
};

const keepDrawnRow = function keepDrawnRow(freeOnly, isPriced, drawn, item) {
  if (!freeOnly || !isPriced) return true;
  if (drawn.price.isFree || drawn.isIn || item.isNew) return true;
  return false;
};

const collectDrawnRows = function collectDrawnRows(doc, group, settings, ceilings) {
  const rows = [];
  const ranked = acb.sortModelsByIntelligence(group.models);
  for (const item of ranked) {
    const drawn = modelTableRow(doc, item, group.name, {
      hidden: settings.hidden,
      shown: settings.shown,
      isPriced: group.isPriced,
      isLocal: group.isLocal,
      maxIntelligence: ceilings.maxIntelligence,
      maxSpeed: ceilings.maxSpeed,
      onToggle: settings.onToggle,
    });
    if (!keepDrawnRow(settings.freeOnly, group.isPriced, drawn, item)) continue;
    rows.push({ row: drawn.row, isIn: drawn.isIn, price: drawn.price, item });
  }
  return rows;
};

const rowIsVisible = function rowIsVisible(entry, search, isOpen, name) {
  if (!search) return isOpen || entry.isIn || entry.item.isNew;
  const label = entry.item.label || "";
  const shown = acb.modelDisplayName(entry.item.model);
  return label.toLowerCase().includes(search)
    || shown.toLowerCase().includes(search)
    || name.toLowerCase().includes(search);
};

const foldButton = function foldButton(doc, container, catalog, settings, open, name, rowCount, isOpen) {
  const toggle = acb.make(doc, "button", "acb-btn acb-btn-ghost acb-btn-sm", isOpen ? "Show fewer" : `Show all ${rowCount}`);
  toggle.type = "button";
  toggle.setAttribute("aria-expanded", String(isOpen));
  toggle.addEventListener("click", function () {
    if (isOpen) open.delete(name);
    else open.add(name);
    acb.renderModelTables(container, catalog, settings);
  });
  return toggle;
};

const modelGroupCard = function modelGroupCard(doc, visible) {
  const card = acb.make(doc, "div", "settings-card");
  if (!visible.length) {
    card.append(acb.make(doc, "p", "settings-empty", "None in the dropdown — Show all to pick some."));
    return card;
  }
  const table = acb.make(doc, "table", "model-table");
  const tbody = doc.createElement("tbody");
  for (const entry of visible) tbody.append(entry.row);
  table.append(modelTableHead(doc), tbody);
  card.append(table);
  return card;
};

const modelGroupElement = function modelGroupElement(doc, container, catalog, settings, open, group, rows, search) {
  const inPicker = rows.filter(function (entry) { return entry.isIn; }).length;
  const isFoldable = !search && rows.length > MODEL_TABLE_FOLD;
  const isOpen = !isFoldable || open.has(group.name);
  const visible = [];
  for (const entry of rows) {
    if (rowIsVisible(entry, search, isOpen, group.name)) visible.push(entry);
  }
  if (search && !visible.length) return null;
  const node = acb.make(doc, "div", "settings-group model-group");
  const head = acb.make(doc, "div", "settings-group-head");
  const title = acb.make(doc, "h4", "settings-group-title");
  title.append(
    acb.make(doc, "span", "settings-sublabel", group.name),
    acb.make(doc, "span", "model-group-count", `${inPicker} of ${rows.length} in the dropdown`),
  );
  head.append(title);
  if (isFoldable) head.append(foldButton(doc, container, catalog, settings, open, group.name, rows.length, isOpen));
  node.append(head, modelGroupCard(doc, visible));
  return node;
};

const renderModelTables = function renderModelTables(container, catalog, options) {
  const settings = tableOptions(options);
  const doc = container.ownerDocument;
  const groupsIn = catalog || [];
  if (!groupsIn.length) {
    container.replaceChildren(acb.make(doc, "p", "settings-empty", settings.emptyText));
    return;
  }
  if (!openModelGroups.has(container)) openModelGroups.set(container, new Set());
  const open = openModelGroups.get(container);
  const ceilings = metricCeilings(groupsIn);
  const search = String(settings.query || "").trim().toLowerCase();
  const groups = [];
  for (const group of groupsIn) {
    const rows = collectDrawnRows(doc, group, settings, ceilings);
    if (!rows.length) continue;
    const built = modelGroupElement(doc, container, groupsIn, settings, open, group, rows, search);
    if (built) groups.push(built);
  }
  if (!groups.length) {
    groups.push(acb.make(doc, "p", "settings-empty", `No model matches “${String(settings.query).trim()}”.`));
  }
  container.replaceChildren(...groups);
};

const toggleModelSets = function toggleModelSets(hidden, shown, key, isVisible) {
  const nextHidden = new Set(hidden);
  const nextShown = new Set(shown);
  if (isVisible) {
    nextHidden.delete(key);
    nextShown.add(key);
  } else {
    nextHidden.add(key);
    nextShown.delete(key);
  }
  return { hidden: nextHidden, shown: nextShown };
};

const newModelKeys = function newModelKeys(agents) {
  const keys = [];
  for (const agent of agents || []) {
    for (const model of agent.new_models || []) keys.push(acb.modelKey(agent.command, model));
  }
  return keys;
};

acb.modelCatalog = modelCatalog;
acb.modelWhereNote = modelWhereNote;
acb.newModelsNote = newModelsNote;
acb.renderModelTables = renderModelTables;
acb.MODEL_TABLE_FOLD = MODEL_TABLE_FOLD;
acb.toggleModelSets = toggleModelSets;
acb.newModelKeys = newModelKeys;
}
