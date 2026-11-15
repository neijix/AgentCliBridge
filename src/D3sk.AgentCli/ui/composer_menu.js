// Menus on the chat box: slash commands, effort, mode, web search, context. Classic script.
"use strict";
{

globalThis.__acbComposer = globalThis.__acbComposer || {};
const acb = globalThis.__acbComposer;

const SLASH_CACHE_MS = 60_000;
const SLASH_SOURCE_LABELS = { project: "Project", user: "User", skill: "Skill", builtin: "Built-in" };

const WEB_MODES = ["off", "scout", "combined"];
const WEB_MODE_TITLES = {
  off: "Web off — the agent does not search or read the web",
  scout: "Scout — the agent searches and reads the web only through D3SKWEBSCOUT (your own Chrome)",
  combined: "Scout + built-in search — the agent's own web search too; pages are still read through the scout",
};
const WEB_ENGINES = [
  ["auto", "Auto — Google, then DuckDuckGo, Brave, Bing", "Auto"],
  ["google", "Google", "Google"],
  ["duckduckgo", "DuckDuckGo", "DuckDuckGo"],
  ["brave", "Brave Search", "Brave"],
  ["bing", "Bing", "Bing"],
  ["both", "Google + DuckDuckGo (merged)", "Google + DuckDuckGo"],
];
const WEB_SEARCHES_MIN = 1;
const WEB_SEARCHES_MAX = 20;
const WEB_SEARCHES_DEFAULT = 5;
const CONTEXT_RING = 2 * Math.PI * 12;

// The filter being typed, when the message so far is one "/word" and nothing else; null otherwise.
function slashQuery(text) {
  const match = /^\/([A-Za-z0-9._:-]*)$/.exec(String(text ?? ""));
  return match ? match[1].toLowerCase() : null;
}

// Names that start with the filter, then names that contain it, then descriptions that mention
// it. An empty filter keeps the given order.
function filterSlashCommands(commands, query) {
  const list = Array.isArray(commands) ? commands : [];
  const needle = String(query || "").toLowerCase();
  if (!needle) return list.slice();
  const rankOf = (command) => {
    const name = String(command.name || "").toLowerCase();
    if (name.startsWith(needle)) return 0;
    if (name.includes(needle)) return 1;
    return String(command.description || "").toLowerCase().includes(needle) ? 2 : -1;
  };
  return list
    .map((command, index) => ({ command, index, rank: rankOf(command) }))
    .filter((row) => row.rank >= 0)
    .sort((a, b) => a.rank - b.rank || a.index - b.index)
    .map((row) => row.command);
}

// "/name " replaces a half-typed "/word"; anything else already written becomes its arguments.
function applySlashCommand(text, name) {
  const current = String(text ?? "");
  const rest = slashQuery(current) !== null ? "" : current.replace(/^\s+/, "");
  return `/${name} ${rest}`;
}

function slashSourceLabel(source) {
  return SLASH_SOURCE_LABELS[source] || "";
}

function clampSearches(value) {
  if (value === "" || value === null || value === undefined) return WEB_SEARCHES_DEFAULT;
  const number = Math.round(Number(value));
  if (!Number.isFinite(number)) return WEB_SEARCHES_DEFAULT;
  return Math.max(WEB_SEARCHES_MIN, Math.min(WEB_SEARCHES_MAX, number));
}

// { mode, engine, maxSearches, onMode } with every field valid; onMode = what ticking Web brings back.
function normalizeWeb(web = {}) {
  const mode = WEB_MODES.includes(web.mode) ? web.mode : "scout";
  const onMode = mode !== "off" ? mode : web.onMode === "combined" ? "combined" : "scout";
  const engine = WEB_ENGINES.some(([value]) => value === web.engine) ? web.engine : "auto";
  return { mode, engine, maxSearches: clampSearches(web.maxSearches ?? WEB_SEARCHES_DEFAULT), onMode, isLocked: Boolean(web.isLocked) };
}

function webSummary(web) {
  if (web.mode === "off") return WEB_MODE_TITLES.off;
  const engine = WEB_ENGINES.find(([value]) => value === web.engine)?.[2] || "Auto";
  return `${WEB_MODE_TITLES[web.mode]} · engine: ${engine} · up to ${web.maxSearches} searches`;
}

function buildEffortControls(ctx) {
  const { doc, id, n, make, button, setAttributes } = ctx;
  n.effortWrap = make(doc, "div", "composer-pop-wrap");
  n.effort = button(doc, "composer-chip composer-effort", { label: "Effort" });
  setAttributes(n.effort, { "aria-haspopup": "dialog", "aria-expanded": "false", "aria-controls": `${id}-effort` });
  n.effortPop = setAttributes(make(doc, "div", "composer-pop effort-pop"), { role: "dialog", "aria-label": "Effort" });
  n.effortPop.id = `${id}-effort`;
  n.effortPop.hidden = true;
  n.effortHead = make(doc, "div", "effort-pop-head");
  n.effortValue = make(doc, "span", "effort-pop-value");
  n.effortHelp = make(doc, "span", "effort-pop-help", "?");
  n.effortHelp.title = "Higher effort means more thorough responses, but takes longer and uses your limits faster.";
  n.effortHead.append(make(doc, "span", "effort-pop-title", "Effort"), n.effortValue, n.effortHelp);
  n.effortEnds = make(doc, "div", "effort-pop-ends");
  n.effortEnds.append(make(doc, "span", "", "Faster"), make(doc, "span", "", "Smarter"));
  n.effortTrack = setAttributes(make(doc, "div", "effort-track"), {
    role: "slider", tabindex: 0, "aria-label": "Effort", "aria-valuemin": 0,
  });
  n.effortMarks = make(doc, "div", "effort-marks");
  n.ultracodeLabel = make(doc, "label", "web-check composer-ultracode");
  n.ultracode = make(doc, "input");
  n.ultracode.type = "checkbox";
  n.ultracodeLabel.append(n.ultracode, "Ultracode");
  n.ultracodeLabel.hidden = true;
  n.effortPop.append(n.effortHead, n.effortEnds, n.effortTrack, n.effortMarks, n.ultracodeLabel);
  n.effortWrap.append(n.effort, n.effortPop);
  n.effort.hidden = true;
}

function effortSteps(ctx, profile) {
  const labels = ctx.Models.EFFORT_LABELS;
  const steps = profile.levels.map((value) => ({ value, label: labels[value] }));
  return profile.recommended ? steps : [{ value: "auto", label: labels.auto }, ...steps];
}

function effortStepIndex(ctx, profile, steps) {
  const level = ctx.Models.clampEffort(profile, ctx.s.effort);
  const shown = level === "auto" && profile.recommended ? profile.recommended : level;
  return Math.max(0, steps.findIndex((step) => step.value === shown));
}

function currentEffortProfile(ctx) {
  const { agent, model } = acb.selection(ctx);
  return acb.effortProfileFor(ctx, agent?.flavor, model);
}

function effortStop(ctx, step, stepIndex, index) {
  const { doc, make, button, setAttributes } = ctx;
  const isCurrent = stepIndex === index;
  const title = step.value === "max"
    ? `${step.label} — may use excessive tokens: long replies, limits reached sooner. For the hardest tasks`
    : step.label;
  const stop = setAttributes(button(doc, isCurrent ? "effort-stop current" : "effort-stop", { label: step.label, title }), { tabindex: -1 });
  stop.dataset.value = step.value;
  stop.append(make(doc, "span", isCurrent ? "effort-thumb" : "effort-dot"));
  // The redraw detaches the stop; the pop must not read that click as outside.
  stop.addEventListener("click", (event) => {
    event.stopPropagation();
    pickEffort(ctx, step.value);
  });
  return stop;
}

function renderEffort(ctx) {
  const { doc, s, n, make, setAttributes } = ctx;
  const { agent, model } = acb.selection(ctx);
  const flavor = agent?.flavor || "";
  const profile = acb.effortProfileFor(ctx, flavor, model);
  n.effort.hidden = !profile;
  n.effortWrap.hidden = !profile;
  n.ultracodeLabel.hidden = !acb.isUltracodeOffered(ctx, flavor, model);
  n.ultracode.checked = Boolean(s.ultracode);
  n.ultracodeLabel.title = s.ultracode
    ? "Ultracode is on — Claude runs multi-agent workflows for every substantive task (uses far more of your quota). Untick to turn it off"
    : "Ultracode — Claude runs multi-agent workflows for every substantive task: more thorough, far more of your quota";
  if (!profile) {
    closeEffort(ctx);
    return;
  }
  const steps = effortSteps(ctx, profile);
  const index = effortStepIndex(ctx, profile, steps);
  const { value, label } = steps[index];
  const isRecommended = value === profile.recommended;
  n.effort.textContent = !n.ultracodeLabel.hidden && s.ultracode ? `${label} · Ultracode` : label;
  n.effort.title = value === "auto"
    ? "Effort — Auto lets the CLI pick. Higher thinks longer and uses more of your quota"
    : `Effort: ${label}${isRecommended ? " (recommended for this model)" : ""} — higher thinks longer and uses more of your quota`;
  n.effort.setAttribute("aria-label", `Effort: ${n.effort.textContent}`);
  n.effortValue.textContent = label;
  setAttributes(n.effortTrack, { "aria-valuemax": steps.length - 1, "aria-valuenow": index, "aria-valuetext": label });
  const columns = `repeat(${steps.length}, minmax(0, 1fr))`;
  n.effortTrack.style.gridTemplateColumns = columns;
  n.effortMarks.style.gridTemplateColumns = columns;
  const fill = make(doc, "span", "effort-fill");
  fill.style.width = `${((index + 0.5) / steps.length) * 100}%`;
  n.effortTrack.replaceChildren(fill, ...steps.map((step, stepIndex) => effortStop(ctx, step, stepIndex, index)));
  const recommendedIndex = steps.findIndex((step) => step.value === profile.recommended);
  n.effortMarks.hidden = recommendedIndex < 0;
  n.effortMarks.replaceChildren(...steps.map((step, stepIndex) => (
    make(doc, "span", "effort-mark", stepIndex === recommendedIndex ? "Recommended" : "")
  )));
}

// Picking the model's recommended level is "auto": the CLI's own pick, which follows the model.
function pickEffort(ctx, value) {
  const profile = currentEffortProfile(ctx);
  ctx.s.effort = profile?.recommended && value === profile.recommended ? "auto" : value;
  renderEffort(ctx);
  ctx.n.effortTrack.focus?.();
  ctx.s.onEffortChange(ctx.s.effort);
}

function stepEffort(ctx, delta) {
  const profile = currentEffortProfile(ctx);
  if (!profile) return;
  const steps = effortSteps(ctx, profile);
  const next = Math.max(0, Math.min(steps.length - 1, effortStepIndex(ctx, profile, steps) + delta));
  pickEffort(ctx, steps[next].value);
}

function closeEffort(ctx) {
  if (ctx.n.effortPop.hidden) return;
  ctx.n.effortPop.hidden = true;
  ctx.n.effort.setAttribute("aria-expanded", "false");
}

function wireEffort(ctx) {
  const { n } = ctx;
  n.effort.addEventListener("click", (event) => {
    event.stopPropagation();
    if (!n.effortPop.hidden) {
      closeEffort(ctx);
      return;
    }
    closeMode(ctx);
    closeContext(ctx);
    closeSlash(ctx);
    n.effortPop.hidden = false;
    n.effort.setAttribute("aria-expanded", "true");
    n.effortTrack.focus?.();
  });
  n.effortTrack.addEventListener("keydown", (event) => {
    const deltas = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1, Home: -99, End: 99 };
    if (!(event.key in deltas)) return;
    event.preventDefault();
    stepEffort(ctx, deltas[event.key]);
  });
  n.effortPop.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    closeEffort(ctx);
    n.effort.focus?.();
  });
  n.ultracode.addEventListener("change", () => {
    ctx.s.ultracode = n.ultracode.checked;
    renderEffort(ctx);
    ctx.s.onUltracodeChange(n.ultracode.checked);
  });
}

function buildModeControls(ctx) {
  const { doc, id, n, make, button, setAttributes } = ctx;
  n.modeWrap = make(doc, "div", "composer-pop-wrap");
  n.permission = button(doc, "composer-chip composer-mode", { label: "Permission mode" });
  setAttributes(n.permission, { "aria-haspopup": "menu", "aria-expanded": "false", "aria-controls": `${id}-mode` });
  n.modePop = setAttributes(make(doc, "div", "composer-pop mode-pop"), { role: "menu", "aria-label": "Mode" });
  n.modePop.id = `${id}-mode`;
  n.modePop.hidden = true;
  n.modeWrap.append(n.permission, n.modePop);
}

function modeRows(ctx) {
  return [...ctx.n.modePop.querySelectorAll(".mode-row")];
}

function modeRow(ctx, value, label, index, current, flavor) {
  const { doc, make, button, setAttributes, icon, P } = ctx;
  const isCurrent = value === current;
  const row = setAttributes(button(doc, isCurrent ? "mode-row current" : "mode-row"), {
    role: "menuitemradio", "aria-checked": isCurrent,
  });
  row.dataset.value = value;
  const check = make(doc, "span", "mode-row-check");
  if (isCurrent) check.append(icon(doc, "check"));
  row.append(
    make(doc, "span", "mode-row-name", P.name(label)), check,
    make(doc, "span", "mode-row-key", index < 9 ? String(index + 1) : ""),
    make(doc, "span", "mode-row-desc", P.describe(value, flavor)),
  );
  row.addEventListener("click", (event) => {
    event.stopPropagation();
    pickPermission(ctx, value);
  });
  return row;
}

function renderPermission(ctx) {
  const { doc, s, n, make, setAttributes, P } = ctx;
  const flavor = acb.selection(ctx).agent?.flavor || "";
  const offered = acb.offeredPermissions(ctx, flavor);
  n.modeWrap.hidden = !offered.length;
  if (!offered.length) {
    closeMode(ctx);
    return;
  }
  const current = P.effective(offered, s.permission);
  const name = P.name(offered.find(([value]) => value === current)?.[1] || current);
  // A redraw while a reply streams must not drop the keyboard out of the menu.
  const focused = n.modePop.contains(doc.activeElement) ? doc.activeElement.dataset?.value : null;
  n.permission.textContent = name;
  n.permission.setAttribute("aria-label", `Mode: ${name}`);
  n.permission.dataset.value = current;
  n.permission.title = s.permissionTitle || `Mode: ${name} — ${P.describe(current, flavor)}`;
  const title = setAttributes(make(doc, "div", "composer-pop-title", "Mode"), { role: "presentation" });
  n.modePop.replaceChildren(title, ...offered.map(([value, label], index) => modeRow(ctx, value, label, index, current, flavor)));
  if (focused) modeRows(ctx).find((row) => row.dataset.value === focused)?.focus?.();
}

function pickPermission(ctx, value) {
  ctx.s.permission = value;
  closeMode(ctx);
  renderPermission(ctx);
  ctx.n.permission.focus?.();
  ctx.s.onPermissionChange(value);
}

function closeMode(ctx) {
  if (ctx.n.modePop.hidden) return;
  ctx.n.modePop.hidden = true;
  ctx.n.permission.setAttribute("aria-expanded", "false");
}

function wireMode(ctx) {
  const { n } = ctx;
  n.permission.addEventListener("click", (event) => {
    event.stopPropagation();
    if (!n.modePop.hidden) {
      closeMode(ctx);
      return;
    }
    closeEffort(ctx);
    closeContext(ctx);
    closeSlash(ctx);
    n.modePop.hidden = false;
    n.permission.setAttribute("aria-expanded", "true");
    const rows = modeRows(ctx);
    (rows.find((row) => row.getAttribute("aria-checked") === "true") || rows[0])?.focus?.();
  });
  // A mode's number picks it; the arrows move; Escape goes back to the chip.
  n.modePop.addEventListener("keydown", (event) => onModeKey(ctx, event));
}

function onModeKey(ctx, event) {
  const rows = modeRows(ctx);
  const at = rows.indexOf(ctx.doc.activeElement);
  const isPlain = !event.ctrlKey && !event.metaKey && !event.altKey;
  const numbered = isPlain && /^[1-9]$/.test(event.key) ? rows[Number(event.key) - 1] : null;
  if (numbered) pickPermission(ctx, numbered.dataset.value);
  else if ((event.key === "ArrowDown" || event.key === "ArrowUp") && rows.length) {
    const step = event.key === "ArrowDown" ? 1 : rows.length - 1;
    rows[((at < 0 ? 0 : at) + step) % rows.length].focus?.();
  } else if (event.key === "Escape") {
    closeMode(ctx);
    ctx.n.permission.focus?.();
  } else return;
  event.preventDefault();
  event.stopPropagation();
}

function buildContextControls(ctx) {
  const { doc, id, n, make, button, setAttributes, icon } = ctx;
  n.contextWrap = make(doc, "div", "context-wrap");
  n.meter = button(doc, "context-meter", { title: "Context window" });
  setAttributes(n.meter, { "aria-haspopup": "dialog", "aria-expanded": "false", "aria-controls": `${id}-context` });
  n.meterLabel = make(doc, "span", "context-meter-label");
  n.meter.append(icon(doc, "context"), n.meterLabel);
  n.meter.hidden = true;
  n.contextPop = setAttributes(make(doc, "div", "context-pop"), { role: "dialog", "aria-label": "Context window" });
  n.contextPop.id = `${id}-context`;
  n.contextPop.hidden = true;
  n.contextLabel = make(doc, "div", "context-pop-label");
  n.contextDetail = make(doc, "div", "context-pop-detail");
  n.contextHint = make(doc, "p", "context-pop-hint");
  n.contextAction = button(doc, "acb-btn acb-btn-ghost");
  n.contextPop.append(n.contextLabel, n.contextDetail, n.contextHint, n.contextAction);
  n.contextWrap.append(n.meter, n.contextPop);
}

function renderContext(ctx) {
  const { s, n } = ctx;
  const model = s.context;
  if (!model) {
    n.meter.hidden = true;
    n.contextPop.hidden = true;
    n.meter.setAttribute("aria-expanded", "false");
    return;
  }
  n.meter.hidden = false;
  n.meter.className = `context-meter ${model.tone || "ok"}`;
  n.meter.title = `Context ${model.label} (${model.percent}%)`;
  n.meter.setAttribute("aria-label", `Context ${model.label}`);
  n.meterLabel.textContent = `${model.percent}%`;
  const ring = n.meter.querySelector(".context-ring");
  if (ring) {
    ring.style.strokeDasharray = String(CONTEXT_RING);
    ring.style.strokeDashoffset = String(CONTEXT_RING * (1 - model.percent / 100));
  }
  n.contextLabel.textContent = `Context · ${model.label} (${model.percent}%)`;
  const counted = acb.formatTokenCount;
  const detail = model.detail ?? (model.cached
    ? `${counted(model.cached)} cached · ${counted(model.fresh)} fresh · ${counted(model.output)} output`
    : model.source === "estimate" ? "Estimated from this transcript" : "");
  n.contextDetail.textContent = detail;
  n.contextDetail.hidden = !detail;
  n.contextHint.textContent = model.hint || "";
  n.contextAction.textContent = s.contextActionLabel;
  n.contextAction.hidden = !s.onContextAction || !s.contextActionLabel;
}

function closeContext(ctx) {
  if (ctx.n.contextPop.hidden) return;
  ctx.n.contextPop.hidden = true;
  ctx.n.meter.setAttribute("aria-expanded", "false");
}

function wireContext(ctx) {
  const { n, s } = ctx;
  n.meter.addEventListener("click", (event) => {
    event.stopPropagation();
    closeMode(ctx);
    closeEffort(ctx);
    const isOpening = n.contextPop.hidden;
    n.contextPop.hidden = !isOpening;
    n.meter.setAttribute("aria-expanded", String(isOpening));
  });
  n.contextAction.addEventListener("click", () => {
    closeContext(ctx);
    s.onContextAction?.();
  });
}

function webSourceChoices(ctx, sources, radios) {
  const { doc, id, make } = ctx;
  for (const [value, label, detail] of [
    ["scout", "Scout only", "Real search results from your Chrome — nothing else."],
    ["combined", "Scout + built-in search", "The agent's own web search too, for a second set of results."],
  ]) {
    const choice = make(doc, "label", "web-choice");
    const radio = make(doc, "input");
    radio.type = "radio";
    radio.name = `${id}-web-source`;
    radio.value = value;
    const text = make(doc, "span", "", label);
    text.append(make(doc, "small", "", detail));
    choice.append(radio, text);
    sources.append(choice);
    radios.push(radio);
  }
}

function wireWebDialog(controller, parts) {
  const { on, radios, engine, count, close, done, dialog } = parts;
  on.addEventListener("change", () => controller.onChange({ mode: on.checked ? controller.stateOn() : "off" }));
  for (const radio of radios) {
    radio.addEventListener("change", () => {
      if (radio.checked) controller.onChange({ mode: radio.value, onMode: radio.value });
    });
  }
  engine.addEventListener("change", () => controller.onChange({ engine: engine.value }));
  count.addEventListener("change", () => controller.onChange({ maxSearches: clampSearches(count.value) }));
  close.addEventListener("click", () => dialog.close());
  done.addEventListener("click", () => dialog.close());
}

// The Web search dialog: on / off, Scout or Scout + built-in search, the engine, how many searches.
function buildWebDialog(ctx) {
  const { doc, id, s, make, button, setAttributes, option } = ctx;
  const dialog = setAttributes(make(doc, "dialog", "web-dialog acb-ui"), { "aria-labelledby": `${id}-web-title` });
  dialog.id = `${id}-web`;
  const head = make(doc, "div", "dialog-head");
  const title = make(doc, "h3", "", "Web search");
  title.id = `${id}-web-title`;
  const close = button(doc, "acb-btn acb-btn-ghost", { label: "Close", text: "✕" });
  head.append(title, close);
  const main = make(doc, "label", "web-choice web-choice-main");
  const on = make(doc, "input");
  on.type = "checkbox";
  const mainText = make(doc, "span", "", "Search and read the web");
  const note = make(doc, "small");
  mainText.append(note);
  main.append(on, mainText);
  const fieldset = make(doc, "fieldset", "web-options");
  const sources = setAttributes(make(doc, "div", "web-field"), { role: "radiogroup", "aria-labelledby": `${id}-web-source` });
  const sourceLabel = make(doc, "span", "web-field-label", "Search with");
  sourceLabel.id = `${id}-web-source`;
  sources.append(sourceLabel);
  const radios = [];
  webSourceChoices(ctx, sources, radios);
  const engineField = make(doc, "label", "web-field");
  const engine = make(doc, "select");
  engine.append(...WEB_ENGINES.map(([value, label]) => option(doc, value, label)));
  engineField.append(make(doc, "span", "web-field-label", "Search engine"), engine);
  const countField = make(doc, "label", "web-field");
  const count = make(doc, "input", "web-count");
  count.type = "number";
  setAttributes(count, { min: WEB_SEARCHES_MIN, max: WEB_SEARCHES_MAX, step: 1, inputmode: "numeric" });
  count.title = `How many web searches a request may run (${WEB_SEARCHES_MIN}–${WEB_SEARCHES_MAX})`;
  countField.append(make(doc, "span", "web-field-label", "Searches per request"), count);
  fieldset.append(sources, engineField, countField);
  const actions = make(doc, "div", "approval-actions");
  const done = button(doc, "acb-btn acb-btn-primary", { text: "Done" });
  actions.append(make(doc, "span", "spacer"), done);
  dialog.append(head, main, fieldset, actions);
  const controller = {
    dialog,
    onChange: () => {},
    stateOn: () => s.web.onMode,
    render(state, noteText) {
      note.textContent = noteText || "";
      on.checked = state.mode !== "off";
      on.disabled = state.isLocked;
      fieldset.disabled = state.mode === "off" || state.isLocked;
      for (const radio of radios) radio.checked = radio.value === state.onMode;
      engine.value = state.engine;
      count.value = String(state.maxSearches);
    },
  };
  wireWebDialog(controller, { on, radios, engine, count, close, done, dialog });
  return controller;
}

function renderWeb(ctx) {
  const { s, n } = ctx;
  n.web.hidden = !s.web;
  if (!s.web) return;
  const state = s.web;
  const summary = webSummary(state);
  n.webOn.checked = state.mode !== "off";
  n.webOn.disabled = state.isLocked;
  n.webLabel.title = state.isLocked ? `${summary}${s.webScope}` : `${summary}${s.webScope}. Untick to turn the web off`;
  n.webButton.setAttribute("aria-pressed", String(state.mode !== "off"));
  n.webButton.title = `Web options — ${summary}`;
  ctx.webDialog.render(state, state.isLocked ? s.webLockedNote : s.webNote);
}

function changeWeb(ctx, patch) {
  ctx.s.web = normalizeWeb({ ...ctx.s.web, ...patch });
  renderWeb(ctx);
  ctx.s.onWebChange({ ...ctx.s.web });
}

function wireWeb(ctx) {
  const { n } = ctx;
  n.webOn.addEventListener("change", () => changeWeb(ctx, { mode: n.webOn.checked ? ctx.s.web.onMode : "off" }));
  n.webButton.addEventListener("click", () => {
    renderWeb(ctx);
    ctx.webDialog.dialog.showModal?.();
  });
  ctx.webDialog.onChange = (patch) => changeWeb(ctx, patch);
}

function slashTarget(ctx) {
  if (!ctx.s.slashCommands) return null;
  const selected = acb.selection(ctx);
  return { selected, key: String(ctx.s.slashKey(selected) ?? "") };
}

function slashRow(ctx, command, index) {
  const { doc, id, slash, make, setAttributes } = ctx;
  const row = make(doc, "div", index === slash.index ? "slash-row selected" : "slash-row");
  row.id = `${id}-slash-${index}`;
  setAttributes(row, { role: "option", "aria-selected": index === slash.index });
  row.append(make(doc, "span", "slash-name", `/${command.name}`));
  if (command.argument_hint) row.append(make(doc, "span", "slash-hint", command.argument_hint));
  row.append(make(doc, "span", "slash-desc", command.description || ""));
  const source = slashSourceLabel(command.source);
  if (source) row.append(make(doc, "span", "slash-source", source));
  row.title = command.description || "";
  row.addEventListener("mousedown", (event) => event.preventDefault()); // the message keeps the focus
  row.addEventListener("click", () => pickSlash(ctx, command));
  return row;
}

function renderSlash(ctx) {
  const { id, slash, n, make } = ctx;
  const rows = filterSlashCommands(slash.commands, slash.filter);
  slash.rows = rows;
  slash.index = Math.max(0, Math.min(slash.index, rows.length - 1));
  if (!rows.length) {
    const note = slash.commands.length ? `No command matches "/${slash.filter}"` : slash.note;
    n.slashList.replaceChildren(make(ctx.doc, "p", "slash-empty", note));
    n.input.removeAttribute("aria-activedescendant");
    return;
  }
  n.slashList.replaceChildren(...rows.map((command, index) => slashRow(ctx, command, index)));
  n.input.setAttribute("aria-activedescendant", `${id}-slash-${slash.index}`);
  n.slashList.children[slash.index]?.scrollIntoView?.({ block: "nearest" });
}

function closeSlash(ctx) {
  const slash = ctx.slash;
  if (!slash.isOpen) return;
  slash.isOpen = false;
  slash.request += 1; // a listing still on its way is dropped
  ctx.n.slashPop.hidden = true;
  ctx.n.slashButton.setAttribute("aria-expanded", "false");
  ctx.n.input.removeAttribute("aria-activedescendant");
}

async function openSlash(ctx, filter) {
  const target = slashTarget(ctx);
  if (!target) return;
  const slash = ctx.slash;
  const cached = ctx.slashCache.get(target.key);
  const isFresh = cached && Date.now() - cached.at < SLASH_CACHE_MS;
  Object.assign(slash, {
    isOpen: true, key: target.key, filter, index: 0,
    commands: cached?.commands || [], note: "Loading…",
  });
  ctx.n.slashPop.hidden = false;
  ctx.n.slashButton.setAttribute("aria-expanded", "true");
  renderSlash(ctx);
  if (isFresh) return;
  const request = ++slash.request;
  const listed = await loadSlashCommands(ctx, target);
  if (request !== slash.request) return;
  Object.assign(slash, listed);
  renderSlash(ctx);
}

async function loadSlashCommands(ctx, target) {
  let commands = [];
  let note = "";
  try {
    const listed = await ctx.s.slashCommands(target.selected);
    if (listed === null || listed === undefined) {
      note = "Pick an online machine and a project first.";
    } else {
      commands = Array.isArray(listed) ? listed : [];
      ctx.slashCache.set(target.key, { at: Date.now(), commands });
      const name = target.selected.agent ? ctx.Models.agentDisplayName(target.selected.agent) : target.selected.command;
      if (!commands.length) note = `${name} has no slash commands here — they work with Claude Code.`;
    }
  } catch (error) {
    note = error?.message || String(error);
  }
  return { commands, note };
}

function pickSlash(ctx, command) {
  const input = ctx.n.input;
  closeSlash(ctx);
  input.value = applySlashCommand(input.value, command.name);
  input.focus();
  input.setSelectionRange?.(input.value.length, input.value.length);
  ctx.s.onInput(input.value);
}

// Enter or Tab picks a listed command; anything else (including Enter on an empty list) is not handled.
function handleSlashKey(ctx, event) {
  const slash = ctx.slash;
  const count = slash.rows.length;
  const isPick = (event.key === "Enter" && !event.shiftKey) || event.key === "Tab";
  if (event.key === "Escape") closeSlash(ctx);
  else if (count && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
    slash.index = (slash.index + (event.key === "ArrowDown" ? 1 : count - 1)) % count;
    renderSlash(ctx);
  } else if (count && isPick) pickSlash(ctx, slash.rows[slash.index]);
  else return false;
  return true;
}

function wireSlash(ctx) {
  const { n } = ctx;
  // The button is a shortcut for typing "/": in an empty message it writes it.
  n.slashButton.addEventListener("click", (event) => {
    event.stopPropagation();
    if (ctx.slash.isOpen) closeSlash(ctx);
    else {
      if (!n.input.value.trim()) n.input.value = "/";
      openSlash(ctx, slashQuery(n.input.value) || "");
    }
    n.input.focus();
  });
  n.input.addEventListener("input", () => onSlashInput(ctx));
  n.input.addEventListener("keydown", (event) => onComposerKey(ctx, event));
}

function onSlashInput(ctx) {
  const { n, s } = ctx;
  const query = s.slashCommands ? slashQuery(n.input.value) : null;
  if (query === null) closeSlash(ctx);
  else if (ctx.slash.isOpen) {
    Object.assign(ctx.slash, { filter: query, index: 0 });
    renderSlash(ctx);
  } else openSlash(ctx, query);
  s.onInput(n.input.value);
}

function onComposerKey(ctx, event) {
  if (event.isComposing) return;
  if (ctx.slash.isOpen && handleSlashKey(ctx, event)) {
    event.preventDefault();
    event.stopImmediatePropagation();
    return;
  }
  if (event.key === "Enter" && !event.shiftKey && ctx.s.sendOnEnter()) {
    event.preventDefault();
    acb.send(ctx);
  }
}

function wireDismiss(ctx) {
  const { doc, n } = ctx;
  const onDocumentClick = (event) => {
    if (!n.contextWrap.contains(event.target)) closeContext(ctx);
    if (!n.modeWrap.contains(event.target)) closeMode(ctx);
    if (!n.effortWrap.contains(event.target)) closeEffort(ctx);
    if (!n.slashPop.contains(event.target) && !n.slashButton.contains(event.target)) closeSlash(ctx);
  };
  const onDocumentKey = (event) => {
    if (event.key !== "Escape") return;
    closeContext(ctx);
    closeMode(ctx);
    closeEffort(ctx);
  };
  ctx.onDocumentClick = onDocumentClick;
  ctx.onDocumentKey = onDocumentKey;
  doc.addEventListener("click", onDocumentClick);
  doc.addEventListener("keydown", onDocumentKey);
}

Object.assign(acb, {
  slashQuery, filterSlashCommands, applySlashCommand, slashSourceLabel,
  WEB_MODES, WEB_MODE_TITLES, WEB_ENGINES, clampSearches, normalizeWeb, webSummary,
  buildEffortControls, renderEffort, closeEffort, wireEffort,
  buildModeControls, renderPermission, closeMode, wireMode,
  buildContextControls, renderContext, closeContext, wireContext,
  buildWebDialog, renderWeb, wireWeb,
  slashTarget, closeSlash, wireSlash, wireDismiss,
});
}
