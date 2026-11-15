// Settings › Models. Classic script. Needs icons.js (globalThis.__acbUi) and, when a page mounts
// it, models.js (window.AgentModels). components.js publishes mountModelsSettings on window.AgentUI.
"use strict";
{

globalThis.__acbUi = globalThis.__acbUi || {};
const acb = globalThis.__acbUi;

// The "Reading the tables" help: [text, isEmphasis] runs.
const MODELS_HELP = [
  ["Each subscription is a table, strongest first; a long one shows only what the dropdown offers and the new models until you click Show all. Intelligence and speed are the Artificial Analysis Intelligence Index and median output tokens per second, refreshed automatically when models change or with Refresh. Open Router rows marked "],
  ["graduated", true],
  [" have been on that list for a while (a number in Intelligence). "],
  ["limited", true],
  [" is free for a limited time — that endpoint may disappear (Zen ids such as big-pickle do not). "],
  ["preview", true],
  [" has not graduated yet (a lab preview, stealth, or alpha). A model marked "],
  ["new", true],
  [" appeared since, and joins the picker once you tick it. "],
  ["Price", true],
  [" is what Open Router bills per million tokens (input / output); paid ones join the picker only once you tick them, and the other subscriptions show "],
  ["Plan", true],
  [" (included in it)."],
];
const MODELS_LEDE = "Which models the composer's dropdown offers. Untick one to hide it; it still runs when a chat asks for it.";

// The Settings categories wear the shared palette (palette.css) like the chat box.
const SETTINGS_ROOT_CLASSES = ["acb-ui", "acb-settings"];
const CATALOG_KEYS = ["models", "new_models", "optional_models", "prices", "labels", "metrics", "account"];

const unmountSettings = function unmountSettings(container) {
  container.classList.remove(...SETTINGS_ROOT_CLASSES);
  container.replaceChildren();
};

const categoryHead = function categoryHead(doc, title, lede) {
  const head = acb.make(doc, "header", "settings-category-head");
  head.append(acb.make(doc, "h3", "settings-category-title", title));
  const ledeNode = acb.make(doc, "p", "settings-category-lede", lede || "");
  head.append(ledeNode);
  return { head, ledeNode };
};

const helpBlock = function helpBlock(doc, summary, runs) {
  const details = acb.make(doc, "details", "settings-help");
  details.append(acb.make(doc, "summary", "", summary));
  const text = doc.createElement("p");
  for (const [run, isEmphasis] of typeof runs === "string" ? [[runs]] : runs) {
    text.append(isEmphasis ? acb.make(doc, "em", "", run) : run);
  }
  details.append(text);
  return details;
};

const copyCatalogFields = function copyCatalogFields(target, row) {
  for (const key of CATALOG_KEYS) {
    if (row[key] !== undefined) target[key] = row[key];
  }
};

const rememberRowMetrics = function rememberRowMetrics(row) {
  const Models = globalThis.AgentModels;
  if (row?.metrics && typeof Models.rememberModelMetrics === "function") {
    Models.rememberModelMetrics(row.metrics);
  }
};

const upsertCatalogAgent = function upsertCatalogAgent(machine, row) {
  const existing = machine.agents.find((agent) => agent?.command === row.command);
  if (existing) {
    copyCatalogFields(existing, row);
    return;
  }
  const entry = {
    command: row.command,
    name: row.name || row.command,
    flavor: row.flavor || "",
    models: row.models,
  };
  copyCatalogFields(entry, row);
  machine.agents.push(entry);
};

const syncMachineStatus = function syncMachineStatus(machine, status) {
  if (!status || !Array.isArray(status.agents)) return;
  for (const row of status.agents) {
    rememberRowMetrics(row);
    if (!machine || !Array.isArray(machine.agents) || !Array.isArray(row?.models)) continue;
    upsertCatalogAgent(machine, row);
  }
};

const modelsSettingsState = function modelsSettingsState(options) {
  const state = {
    machines: [], catalog: null, labelOf: undefined,
    hidden: new Set(), shown: new Set(), freeOnly: false, query: "",
    title: "Models", lede: MODELS_LEDE, help: MODELS_HELP,
    emptyText: "No agent CLI found on this computer.",
    onToggle: () => {}, onFreeOnlyChange: () => {}, onQueryChange: () => {}, onRefresh: null,
    ...options,
  };
  state.hidden = new Set(state.hidden);
  state.shown = new Set(state.shown);
  return state;
};

const buildModelsChrome = function buildModelsChrome(doc, state) {
  const { head, ledeNode } = categoryHead(doc, state.title, state.lede);
  const group = acb.make(doc, "div", "settings-group");
  const groupHead = acb.make(doc, "div", "settings-group-head");
  const refreshButton = acb.button(doc, "acb-btn acb-btn-ghost acb-btn-sm model-refresh", {
    title: "Refresh each CLI's models and the Artificial Analysis ratings",
    text: "Refresh",
  });
  groupHead.append(acb.make(doc, "h4", "settings-group-title", "Catalog"), refreshButton);
  const card = acb.make(doc, "div", "settings-card models-settings");
  return { head, ledeNode, group, groupHead, refreshButton, card };
};

const buildModelSearch = function buildModelSearch(doc, state) {
  const item = acb.make(doc, "div", "settings-item");
  const field = acb.make(doc, "label", "settings-field");
  const searchText = acb.make(doc, "span", "", "Find a model ");
  searchText.append(acb.make(doc, "em", "", "searches every subscription, ticked or not"));
  const search = acb.make(doc, "input", "model-search");
  search.type = "search";
  search.autocomplete = "off";
  search.spellcheck = false;
  search.placeholder = "opus, grok-4.7, free…";
  search.value = state.query;
  field.append(searchText, search);
  item.append(field);
  return { item, search };
};

const buildFreeSwitch = function buildFreeSwitch(doc, id) {
  const item = acb.make(doc, "div", "settings-item settings-row");
  const freeHead = acb.make(doc, "div", "settings-card-head");
  const freeLabel = acb.make(doc, "label", "settings-label", "Free models only");
  freeLabel.htmlFor = `${id}-free`;
  freeHead.append(freeLabel, acb.make(doc, "p", "settings-lede", "Hides the paid Open Router models you have not ticked."));
  const free = acb.make(doc, "input", "settings-switch");
  free.type = "checkbox";
  free.id = `${id}-free`;
  free.setAttribute("role", "switch");
  item.append(freeHead, free);
  return { item, free };
};

const appendModelsHelp = function appendModelsHelp(group, doc, state) {
  if (!state.help) return null;
  const help = helpBlock(doc, "Reading the tables", state.help);
  group.append(help);
  return help;
};

const modelsCatalog = function modelsCatalog(view) {
  const { state } = view;
  return state.catalog || globalThis.AgentModels.modelCatalog(state.machines, state.labelOf);
};

const toggleModelVisibility = function toggleModelVisibility(view, key, isVisible) {
  const { state } = view;
  const next = globalThis.AgentModels.toggleModelSets(state.hidden, state.shown, key, isVisible);
  state.hidden = next.hidden;
  state.shown = next.shown;
  renderModelsSettings(view);
  state.onToggle(key, isVisible, { hidden: new Set(state.hidden), shown: new Set(state.shown) });
};

const renderModelsSettings = function renderModelsSettings(view) {
  const { state, ledeNode, free, search, tables } = view;
  ledeNode.textContent = state.lede || "";
  free.checked = Boolean(state.freeOnly);
  if (search.value !== state.query) search.value = state.query;
  globalThis.AgentModels.renderModelTables(tables, modelsCatalog(view), {
    hidden: state.hidden,
    shown: state.shown,
    freeOnly: state.freeOnly,
    query: state.query,
    emptyText: state.emptyText,
    onToggle: (key, isVisible) => toggleModelVisibility(view, key, isVisible),
  });
};

const readOkJson = function readOkJson(response) {
  if (response?.ok && typeof response.json === "function") return response.json();
  return null;
};

// One machine that fails to answer is skipped; the others still refresh.
const refreshOneMachine = function refreshOneMachine(win, machine) {
  return win
    .fetch(`/api/machines/${encodeURIComponent(machine.id)}/cli-status?force=true`, { credentials: "same-origin" })
    .then(readOkJson)
    .then((status) => status && syncMachineStatus(machine, status))
    .catch(() => {});
};

const refreshMachineStatuses = function refreshMachineStatuses(win, machines) {
  const online = machines.filter((machine) => machine && machine.id && machine.online !== false);
  return Promise.all(online.map((machine) => refreshOneMachine(win, machine)));
};

const refreshLocalStatus = function refreshLocalStatus(win, state) {
  return win
    .fetch("/api/agents/status?force=1", { credentials: "same-origin" })
    .then(readOkJson)
    .then((status) => status && syncMachineStatus(state.machines?.[0], status))
    .catch(() => {})
    .then(() => win.fetch("/api/agents?refresh=1", { credentials: "same-origin" }).catch(() => null))
    .then((response) => (response?.ok && typeof response.json === "function" ? response.json() : undefined));
};

const refreshFromNetwork = function refreshFromNetwork(win, state) {
  if (Array.isArray(state.machines) && state.machines.some((machine) => machine && machine.id)) {
    return refreshMachineStatuses(win, state.machines).then(() => {
      state.catalog = null;
      return undefined;
    });
  }
  return refreshLocalStatus(win, state);
};

const replaceMachines = function replaceMachines(state, agents, name) {
  state.machines = [{ name: name || state.machines?.[0]?.name || "This computer", agents }];
  state.catalog = null;
};

const applyMachineList = function applyMachineList(state, fresh) {
  if (fresh.length && Array.isArray(fresh[0]?.agents)) state.machines = fresh;
  else replaceMachines(state, fresh, state.machines?.[0]?.name);
  state.catalog = null;
};

const applyCatalogObject = function applyCatalogObject(state, fresh) {
  if (Array.isArray(fresh.machines)) {
    state.machines = fresh.machines;
    state.catalog = null;
    return;
  }
  if (Array.isArray(fresh.agents)) {
    replaceMachines(state, fresh.agents);
    return;
  }
  if (Array.isArray(fresh.catalog)) state.catalog = fresh.catalog;
};

const applyCatalogRefresh = function applyCatalogRefresh(state, fresh) {
  if (Array.isArray(fresh)) {
    applyMachineList(state, fresh);
    return;
  }
  if (fresh && typeof fresh === "object") applyCatalogObject(state, fresh);
};

const finishModelsRefresh = function finishModelsRefresh(view) {
  view.isRefreshing = false;
  view.refreshButton.disabled = false;
  view.refreshButton.textContent = "Refresh";
  renderModelsSettings(view);
};

const refreshModelsSettings = function refreshModelsSettings(view) {
  const { state, refreshButton, win } = view;
  if (view.isRefreshing) return Promise.resolve();
  view.isRefreshing = true;
  refreshButton.disabled = true;
  refreshButton.textContent = "Refreshing…";
  const asked = typeof state.onRefresh === "function" ? Promise.resolve(state.onRefresh()) : Promise.resolve(undefined);
  return asked
    .then((fresh) => (fresh === undefined && typeof win?.fetch === "function" ? refreshFromNetwork(win, state) : fresh))
    .then((fresh) => applyCatalogRefresh(state, fresh))
    .finally(() => finishModelsRefresh(view));
};

const wireModelsControls = function wireModelsControls(view) {
  const { search, free, refreshButton, state } = view;
  search.addEventListener("input", () => {
    state.query = search.value;
    renderModelsSettings(view);
    state.onQueryChange(state.query);
  });
  free.addEventListener("change", () => {
    state.freeOnly = free.checked;
    renderModelsSettings(view);
    state.onFreeOnlyChange(state.freeOnly);
  });
  refreshButton.addEventListener("click", () => refreshModelsSettings(view));
};

const modelsSettingsController = function modelsSettingsController(view) {
  const { state, refreshButton, search, free, help, tables, container } = view;
  return {
    elements: { refresh: refreshButton, search, freeOnly: free, help, tables },
    update(patch = {}) {
      Object.assign(state, patch);
      if ("hidden" in patch) state.hidden = new Set(patch.hidden);
      if ("shown" in patch) state.shown = new Set(patch.shown);
      renderModelsSettings(view);
    },
    render: () => renderModelsSettings(view),
    refresh: () => refreshModelsSettings(view),
    get hidden() { return new Set(state.hidden); },
    get shown() { return new Set(state.shown); },
    destroy: () => unmountSettings(container),
  };
};

// Fills `container` (a Settings category) with the Models page and returns its controller.
// `machines` ([{ name, agents }], labelled by `labelOf`) or a ready `catalog` (modelCatalog);
// `hidden` / `shown` are the owner's saved sets. A tick saves through onToggle(key, isVisible,
// { hidden, shown }) — the page has already moved the key between the two sets.
const mountModelsSettings = function mountModelsSettings(container, options = {}) {
  const doc = container.ownerDocument;
  const state = modelsSettingsState(options);
  const id = acb.takeMountId("acb-models");
  const built = buildModelsChrome(doc, state);
  const search = buildModelSearch(doc, state);
  const free = buildFreeSwitch(doc, id);
  built.card.append(search.item, free.item);
  built.group.append(built.groupHead, built.card);
  const help = appendModelsHelp(built.group, doc, state);
  const tables = acb.make(doc, "div", "model-visibility");
  container.classList.add(...SETTINGS_ROOT_CLASSES);
  container.replaceChildren(built.head, built.group, tables);
  const view = {
    container, doc, win: doc.defaultView, state, id,
    head: built.head, ledeNode: built.ledeNode, group: built.group,
    refreshButton: built.refreshButton, search: search.search, free: free.free,
    help, tables, isRefreshing: false,
  };
  wireModelsControls(view);
  renderModelsSettings(view);
  return modelsSettingsController(view);
};

acb.SETTINGS_ROOT_CLASSES = SETTINGS_ROOT_CLASSES;
acb.unmountSettings = unmountSettings;
acb.categoryHead = categoryHead;
acb.helpBlock = helpBlock;
acb.syncMachineStatus = syncMachineStatus;
acb.MODELS_LEDE = MODELS_LEDE;
acb.mountModelsSettings = mountModelsSettings;
}
