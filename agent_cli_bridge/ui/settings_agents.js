// Settings › Agents. Classic script. Needs settings_models.js (the shared Settings chrome on
// globalThis.__acbUi) and, when a page mounts it, models.js (window.AgentModels).
"use strict";
{

globalThis.__acbUi = globalThis.__acbUi || {};
const acb = globalThis.__acbUi;

const AGENTS_LEDE = "The command-line agents on this computer: version, sign-in and update.";
const AGENTS_HELP = "The newest published version is shown beside each one. Update upgrades that computer's own copy the way it was installed (Homebrew, npm, or the CLI's own updater); Uninstall removes it the same way — neither while that CLI is answering a chat. Install adds a missing one with its vendor's official installer (an install script, WinGet or npm); sign in to it afterwards.";

const agentsSettingsState = function agentsSettingsState(options) {
  const state = {
    machines: [null], api: null,
    keyOf: (target) => target?.key ?? target?.id ?? "",
    labelOf: (target) => target?.label || target?.name || "This computer",
    whereOf: () => "",
    focusKey: "", notice: "",
    title: "Agents", lede: AGENTS_LEDE, help: AGENTS_HELP,
    emptyText: "No computer online — start the app there to see its CLIs.",
    toast: () => {}, onUpdated: () => {}, onStatus: () => {}, onChange: () => {},
    ...options,
  };
  if (!state.api || typeof state.api.status !== "function") {
    throw new Error("mountAgentsSettings needs api.status(target, { force })");
  }
  return state;
};

const noteAgentUpdate = function noteAgentUpdate(view, target, result) {
  const { state, statuses } = view;
  if (result?.status) {
    acb.syncMachineStatus(target, result.status);
    statuses.set(state.keyOf(target), result.status);
    state.onStatus(target, result.status);
  }
  state.onUpdated(target, result);
};

const agentCliExtras = function agentCliExtras(state) {
  const extras = {};
  if (state.openWindow) extras.openWindow = state.openWindow;
  if (state.sleep) extras.sleep = state.sleep;
  if (state.pollMs) extras.pollMs = state.pollMs;
  return extras;
};

const createAgentsCli = function createAgentsCli(view) {
  const { state } = view;
  return globalThis.AgentModels.cliSettings({
    api: state.api,
    keyOf: (target) => state.keyOf(target),
    whereOf: (target) => state.whereOf(target),
    onChange: () => {
      renderAgentsSettings(view);
      state.onChange();
    },
    onUpdated: (target, result) => noteAgentUpdate(view, target, result),
    toast: (message) => state.toast(message),
    classes: {
      primary: "acb-btn acb-btn-primary acb-btn-sm",
      secondary: "acb-btn acb-btn-secondary acb-btn-sm",
    },
    ...agentCliExtras(state),
  });
};

const buildAgentsChrome = function buildAgentsChrome(doc, state) {
  const { head, ledeNode } = acb.categoryHead(doc, state.title, state.lede);
  const group = acb.make(doc, "div", "settings-group");
  const groupHead = acb.make(doc, "div", "settings-group-head");
  const recheck = acb.button(doc, "acb-btn acb-btn-ghost acb-btn-sm cli-recheck", {
    title: "Check versions and sign-ins again",
    text: "Check again",
  });
  groupHead.append(acb.make(doc, "h4", "settings-group-title", "Installed"), recheck);
  const card = acb.make(doc, "div", "settings-card cli-settings");
  const computers = acb.make(doc, "div", "settings-computers");
  card.append(computers);
  group.append(groupHead, card);
  const help = state.help ? acb.helpBlock(doc, "How updates work", state.help) : null;
  if (help) group.append(help);
  // A warning in place of the list (the app's "that computer is offline"); "" shows the list.
  const notice = acb.make(doc, "p", "settings-banner warning");
  notice.hidden = true;
  return { head, ledeNode, group, recheck, computers, help, notice };
};

const loadAgentStatus = function loadAgentStatus(view, target, { force = false } = {}) {
  const { state, statuses, requests } = view;
  const key = state.keyOf(target);
  const request = (requests.get(key) || 0) + 1;
  requests.set(key, request);
  if (!statuses.get(key) || force) statuses.set(key, { isLoading: true });
  return Promise.resolve()
    .then(() => state.api.status(target, { force }))
    .catch((error) => ({ error: error?.message || String(error), agents: [] }))
    .then((status) => {
      if (requests.get(key) !== request) return;
      acb.syncMachineStatus(target, status);
      statuses.set(key, status || { agents: [] });
      state.onStatus(target, status);
      renderAgentsSettings(view);
    });
};

const appendMissingAgents = function appendMissingAgents(view, section, target, status) {
  const missing = view.cli.renderMissingList(view.doc, target, status);
  if (!missing) return;
  section.append(acb.make(view.doc, "span", "settings-sublabel cli-missing-head", "Not in use"), missing);
};

const renderAgentMachine = function renderAgentMachine(view, target) {
  const { state, statuses, doc } = view;
  const key = state.keyOf(target);
  const focused = state.focusKey && key === state.focusKey ? " focused" : "";
  const section = acb.make(doc, "div", `cli-machine${focused}`);
  const machineHead = acb.make(doc, "div", "cli-machine-head");
  machineHead.append(acb.make(doc, "span", "settings-sublabel", state.labelOf(target)));
  section.append(machineHead);
  const status = statuses.get(key);
  if (!status || status.isLoading) {
    section.append(acb.make(doc, "p", "settings-hint", "Checking versions…"));
    if (!status) loadAgentStatus(view, target);
    return section;
  }
  if (status.error && !(status.agents || []).length) {
    section.append(acb.make(doc, "p", "settings-hint error-text", `Could not check: ${status.error}`));
    return section;
  }
  section.append(view.cli.renderList(doc, target, status));
  appendMissingAgents(view, section, target, status);
  return section;
};

const renderAgentMachines = function renderAgentMachines(view) {
  const { state, computers, doc } = view;
  const machines = state.machines || [];
  if (!machines.length) {
    computers.classList.remove("single");
    computers.replaceChildren(acb.make(doc, "p", "settings-empty", state.emptyText));
    return;
  }
  computers.classList.toggle("single", machines.length === 1);
  computers.replaceChildren(...machines.map((target) => renderAgentMachine(view, target)));
};

const renderAgentsSettings = function renderAgentsSettings(view) {
  const { state, ledeNode, notice, group } = view;
  ledeNode.textContent = state.lede || "";
  notice.textContent = state.notice || "";
  notice.hidden = !state.notice;
  group.hidden = Boolean(state.notice);
  if (!state.notice) renderAgentMachines(view);
};

// "Check again": forget the shown machines' versions and sign-ins, ask again.
const refreshAgentsSettings = function refreshAgentsSettings(view, { force = true } = {}) {
  const { state, statuses, cli } = view;
  const machines = state.machines || [];
  for (const target of machines) {
    statuses.set(state.keyOf(target), { isLoading: true });
    cli.forget(target);
  }
  renderAgentsSettings(view);
  return Promise.all(machines.map((target) => loadAgentStatus(view, target, { force })));
};

const agentsSettingsController = function agentsSettingsController(view) {
  const { state, recheck, computers, help, notice, cli, statuses, container } = view;
  return {
    elements: { recheck, computers, help, notice },
    cli,
    update(patch = {}) {
      Object.assign(state, patch);
      renderAgentsSettings(view);
    },
    render: () => renderAgentsSettings(view),
    refresh: (options) => refreshAgentsSettings(view, options),
    statusOf(target) {
      const status = statuses.get(state.keyOf(target));
      return status && !status.isLoading ? status : null;
    },
    setStatus(target, status) {
      statuses.set(state.keyOf(target), status);
      renderAgentsSettings(view);
    },
    destroy: () => acb.unmountSettings(container),
  };
};

// Fills `container` (a Settings category) with the Agents page: one section per machine (its
// name hidden when there is only one), each CLI's row from models.js cliSettings, and "Check
// again". `machines` are the app's targets (a one-machine host passes [null] or one object);
// `api` is cliSettings' plus status(target, { force }). Returns the controller; its `cli` is the
// cliSettings controller, for a failed reply's "Sign in" link elsewhere on the page.
const mountAgentsSettings = function mountAgentsSettings(container, options = {}) {
  const doc = container.ownerDocument;
  const state = agentsSettingsState(options);
  const chrome = buildAgentsChrome(doc, state);
  container.classList.add(...acb.SETTINGS_ROOT_CLASSES);
  container.replaceChildren(chrome.head, chrome.notice, chrome.group);
  const view = {
    container,
    doc,
    state,
    statuses: new Map(), // target key → a status answer, or { isLoading }
    requests: new Map(), // target key → request number (a newer one wins)
    ...chrome,
  };
  view.cli = createAgentsCli(view);
  chrome.recheck.addEventListener("click", () => refreshAgentsSettings(view));
  renderAgentsSettings(view);
  return agentsSettingsController(view);
};

acb.AGENTS_LEDE = AGENTS_LEDE;
acb.mountAgentsSettings = mountAgentsSettings;
}
