// The chat box: message, attachments, send and resize. Classic script.
"use strict";
{

globalThis.__acbComposer = globalThis.__acbComposer || {};
const acb = globalThis.__acbComposer;

const COMPOSER_MIN_HEIGHT = 52;
const COMPOSER_MAX_VIEWPORT = 0.7;
const COMPOSER_CHROME = 240;
const CONTEXT_WARN_PERCENT = 70;
const CONTEXT_DANGER_PERCENT = 90;
const MAX_ATTACHMENTS = 10;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024;
const MAX_TOTAL_BYTES = 25 * 1024 * 1024;
const INLINE_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"]);
const DEFAULT_PLACEHOLDER = "Ask anything… Enter to send, Shift+Enter for a new line";
const TOUCH_PLACEHOLDER = "Ask anything…";

// The floor matches the textarea's CSS min-height; the cap leaves the page's header, the bar and
// the foot on screen. chatbox.css's max-height uses the same formula.
function composerHeightLimit(viewportHeight) {
  const room = Math.round(viewportHeight - COMPOSER_CHROME);
  const share = Math.round(viewportHeight * COMPOSER_MAX_VIEWPORT);
  return Math.max(COMPOSER_MIN_HEIGHT, Math.min(share, room));
}

// deltaY is clientY - startY: dragging the top edge up (negative) grows the box.
function nextComposerHeight(startHeight, deltaY, viewportHeight) {
  const next = Math.round(startHeight - deltaY);
  return Math.max(COMPOSER_MIN_HEIGHT, Math.min(composerHeightLimit(viewportHeight), next));
}

function formatTokenCount(tokens) {
  return tokens >= 1000 ? `${(tokens / 1000).toFixed(1)}k` : String(tokens);
}

function contextTone(percent) {
  if (percent >= CONTEXT_DANGER_PERCENT) return "danger";
  if (percent >= CONTEXT_WARN_PERCENT) return "warn";
  return "ok";
}

function contextHint(percent, cached, fresh, source, used) {
  if (percent >= CONTEXT_DANGER_PERCENT) {
    return "This chat is nearly full. A new chat in this project is cheaper than stretching this one.";
  }
  if (percent >= CONTEXT_WARN_PERCENT) {
    return "This chat is filling up. A new chat in this project stays cheaper than stretching this one.";
  }
  if (cached > fresh) return "Mostly cached — later turns in this chat stay cheaper than starting over.";
  if (source === "estimate" && used <= 0) {
    return "This chat's context window. Real fill appears once Claude or Grok reports usage.";
  }
  if (source === "estimate") return "Estimated from the transcript. Claude and Grok sessions show the real window fill.";
  if (source === "grok") return "How full this chat's context window is — Grok's last reported total.";
  return "How full this chat's context window is.";
}

function contextUsage(usage) {
  const breakdown = usage && typeof usage === "object" ? usage : {};
  const cached = (Number(breakdown.cache_creation_input_tokens) || 0) + (Number(breakdown.cache_read_input_tokens) || 0);
  return {
    cached,
    fresh: Number(breakdown.input_tokens) || 0,
    output: Number(breakdown.output_tokens) || 0,
  };
}

// What the meter shows: `used` tokens of `window`; `usage` is Claude's last usage block, `source`
// says where the figure comes from ("claude", "grok", or "estimate" — characters / 4).
function contextMeterModel({ used = 0, window = 200000, usage = null, source = "estimate" } = {}) {
  const percent = !window || used <= 0 ? 0 : Math.max(0, Math.min(100, Math.round((100 * used) / window)));
  const { cached, fresh, output } = contextUsage(usage);
  return {
    used, window, percent, tone: contextTone(percent), source, cached, fresh, output,
    label: `${formatTokenCount(used)} / ${formatTokenCount(window)}`,
    hint: contextHint(percent, cached, fresh, source, used),
  };
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${Number((bytes / 1024 / 1024).toFixed(1))} MB`;
}

function acceptOneFile(file, count, total, limits, notes) {
  if (count >= limits.maxCount) {
    notes.push(`At most ${limits.maxCount} files per message.`);
    return null;
  }
  if (file.size > limits.maxBytes) {
    notes.push(`${file.name} is larger than ${formatSize(limits.maxBytes)}.`);
    return false;
  }
  if (total + file.size > limits.maxTotal) {
    notes.push(`Attachments are limited to ${formatSize(limits.maxTotal)} per message.`);
    return null;
  }
  return true;
}

// Which of `files` fit beside the `current` ones: { accepted, notes } — a note per file left out.
function acceptFiles(current, files, { maxCount = MAX_ATTACHMENTS, maxBytes = MAX_ATTACHMENT_BYTES, maxTotal = MAX_TOTAL_BYTES } = {}) {
  const accepted = [];
  const notes = [];
  let count = current.length;
  let total = current.reduce((sum, file) => sum + (file.size || 0), 0);
  for (const file of files || []) {
    const verdict = acceptOneFile(file, count, total, { maxCount, maxBytes, maxTotal }, notes);
    if (verdict === null) break;
    if (!verdict) continue;
    count += 1;
    total += file.size;
    accepted.push(file);
  }
  return { accepted, notes };
}

function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
    reader.readAsDataURL(file);
  });
}

// Files as JSON: [{ name, media_type, data (base64) }] — what a host's API takes.
function encodeAttachments(files) {
  return Promise.all([...(files || [])].map(async (file) => ({
    name: file.name || "file",
    media_type: file.type || "application/octet-stream",
    data: await readAsBase64(file),
  })));
}

function isTouchKeyboard(win) {
  try {
    return Boolean(win?.matchMedia?.("(pointer: coarse) and (hover: none)")?.matches);
  } catch {
    return false;
  }
}

function composerDefaults(env, win) {
  const noop = () => {};
  return {
    agents: [], hidden: new Set(), shown: new Set(), keep: null, value: "",
    valueFor: undefined, pickerEmptyText: null, pickerTitle: "Subscription · model",
    permissions: env.permissions.modes, maxPermission: null, permission: env.permissions.defaultMode, permissionTitle: "",
    effort: "auto", ultracode: false,
    web: null, webNote: "Claude requests only. Pages are always read through D3SKWEBSCOUT, in your own Chrome.",
    webScope: " (Claude only)", webLockedNote: "Fixed for this chat — start a new one to change it.",
    autoCommit: null,
    context: null, contextActionLabel: "New chat in this project",
    isStreaming: false, canSend: true, sendTitle: "", placeholder: "",
    canAttach: true, maxAttachments: MAX_ATTACHMENTS, maxAttachmentBytes: MAX_ATTACHMENT_BYTES, maxTotalBytes: MAX_TOTAL_BYTES,
    slashCommands: null, slashKey: (selected) => selected.value,
    sendOnEnter: () => !isTouchKeyboard(win),
    onSend: noop, onStop: noop, onAgentChange: noop, onPermissionChange: noop, onEffortChange: noop,
    onUltracodeChange: noop, onWebChange: noop, onAutoCommitChange: noop, onFilesChange: noop,
    onContextAction: null, onInput: noop, onPreview: null, toast: noop,
    shouldAnnounce: false, replyReadyText: "Reply ready",
  };
}

function createComposerState(env, container, options) {
  const doc = container.ownerDocument;
  const win = doc.defaultView || env.root;
  const s = { ...composerDefaults(env, win), ...options };
  if (s.web) s.web = acb.normalizeWeb(s.web);
  return {
    env, doc, win, container, s,
    id: env.takeMountId("acb-composer"),
    pending: [], optionInfo: new Map(), slashCache: new Map(),
    slash: { isOpen: false, key: "", commands: [], rows: [], index: 0, filter: "", note: "", request: 0 },
    n: {},
    make: env.make, button: env.button, setAttributes: env.setAttributes, icon: env.icon, option: env.option,
    Models: env.Models, P: env.permissions,
  };
}

function offeredPermissions(ctx, flavor) {
  const { s, P } = ctx;
  return P.forFlavor(P.allowed(s.permissions, s.maxPermission), flavor || "");
}

function permissionNow(ctx, flavor) {
  const { s, P } = ctx;
  const offered = offeredPermissions(ctx, flavor);
  const list = offered.length ? offered : P.allowed(s.permissions, s.maxPermission);
  return P.effective(list, s.permission);
}

function effortProfileFor(ctx, flavor, model) {
  return ctx.Models.effortProfile(flavor || "", model || "");
}

function isUltracodeOffered(ctx, flavor, model) {
  return Boolean(effortProfileFor(ctx, flavor, model)) && ctx.Models.canUltracode(flavor || "", model || "");
}

function selection(ctx) {
  const { s, n, optionInfo, Models } = ctx;
  const value = n.picker.value || "";
  const known = optionInfo.get(value);
  const command = known?.agent?.command || value.split(Models.SEPARATOR)[0] || "";
  const model = known ? known.model : (value.split(Models.SEPARATOR)[1] || "");
  const flavor = known?.agent?.flavor;
  return {
    value,
    agent: known?.agent || null,
    command,
    model,
    permission: permissionNow(ctx, flavor),
    effort: Models.clampEffort(effortProfileFor(ctx, flavor, model), s.effort),
    ultracode: Boolean(s.ultracode) && isUltracodeOffered(ctx, flavor, model),
    web: s.web ? { mode: s.web.mode, engine: s.web.engine, maxSearches: s.web.maxSearches } : null,
    autoCommit: s.autoCommit,
  };
}

function buildMessageBox(ctx) {
  const { doc, id, n, make, button, setAttributes, icon } = ctx;
  n.box = make(doc, "div", "composer-box");
  n.resizer = setAttributes(make(doc, "div", "composer-resizer"), {
    role: "separator", tabindex: 0, "aria-orientation": "horizontal", "aria-label": "Resize message box",
    "aria-valuemin": COMPOSER_MIN_HEIGHT,
  });
  n.resizer.title = "Drag to resize · double-click to reset · send restores the default size";
  n.slashPop = make(doc, "div", "slash-pop");
  n.slashPop.id = `${id}-slash`;
  n.slashPop.hidden = true;
  n.slashList = setAttributes(make(doc, "div", "slash-list"), { role: "listbox", "aria-label": "Slash commands" });
  n.slashPop.append(n.slashList);
  n.input = make(doc, "textarea");
  n.input.rows = 2;
  n.input.setAttribute("aria-label", "Message");
  n.stop = button(doc, "composer-go composer-stop", { label: "Stop the reply", title: "Stop the reply" });
  n.stop.append(icon(doc, "stop"));
  n.stop.hidden = true;
  n.sendButton = make(doc, "button", "composer-go composer-send");
  n.sendButton.type = "submit";
  n.sendButton.setAttribute("aria-label", "Send message");
  n.sendButton.append(icon(doc, "send"));
  n.go = make(doc, "div", "composer-go-group");
  n.go.append(n.stop, n.sendButton);
  n.inputRow = make(doc, "div", "composer-input-row");
  n.inputRow.append(n.input, n.go);
  n.box.append(n.resizer, n.slashPop, n.inputRow);
}

function buildToolRow(ctx) {
  const { doc, id, n, make, button, setAttributes, icon } = ctx;
  n.attach = button(doc, "composer-icon", { label: "Attach files" });
  n.attach.append(icon(doc, "attach"));
  n.fileInput = make(doc, "input");
  n.fileInput.type = "file";
  n.fileInput.multiple = true;
  n.fileInput.hidden = true;
  n.slashButton = button(doc, "composer-icon", { label: "Slash commands" });
  setAttributes(n.slashButton, { "aria-haspopup": "listbox", "aria-expanded": "false", "aria-controls": n.slashPop.id });
  n.slashButton.append(icon(doc, "slash"));
  n.picker = setAttributes(make(doc, "select", "composer-chip composer-agent"), { "aria-label": "Subscription and model" });
  n.autoCommit = button(doc, "composer-icon composer-toggle composer-auto-commit", { label: "Auto-commit" });
  n.autoCommit.setAttribute("aria-pressed", "false");
  n.autoCommit.append(icon(doc, "branch"));
  n.web = make(doc, "span", "composer-web");
  n.webButton = button(doc, "composer-icon composer-toggle", { label: "Web options", title: "Web options" });
  setAttributes(n.webButton, { "aria-pressed": "false", "aria-haspopup": "dialog", "aria-controls": `${id}-web` });
  n.webButton.append(icon(doc, "globe"));
  n.webLabel = make(doc, "label", "web-check");
  n.webOn = make(doc, "input");
  n.webOn.type = "checkbox";
  n.webLabel.append(n.webOn, "Web");
  n.web.append(n.webButton, n.webLabel);
}

function buildComposerBar(ctx) {
  const { doc, n, make } = ctx;
  n.bar = make(doc, "div", "composer-bar composer-foot");
  n.tools = make(doc, "div", "composer-foot-group composer-tools");
  n.tools.append(n.attach, n.fileInput, n.slashButton, n.autoCommit, n.web, n.modeWrap);
  n.actions = make(doc, "div", "composer-foot-group composer-settings");
  n.actions.append(n.picker, n.effortWrap, n.contextWrap);
  n.bar.append(n.tools, n.actions);
}

// Two live regions, visually hidden: `status` waits, `alert` interrupts. The same words twice
// still count as a change (a no-break space comes and goes), so they are read again.
function buildAnnouncer(ctx) {
  const { doc, make, setAttributes } = ctx;
  const status = setAttributes(make(doc, "div", "acb-sr-only"), { role: "status", "aria-live": "polite" });
  const alert = setAttributes(make(doc, "div", "acb-sr-only"), { role: "alert" });
  function say(message, { isAlert = false } = {}) {
    const text = String(message ?? "").trim();
    if (!text) return;
    const region = isAlert ? alert : status;
    region.textContent = region.textContent === text ? `${text}\u00a0` : text;
  }
  return { status, alert, say };
}

function assembleComposer(ctx) {
  const { doc, container, n, make } = ctx;
  n.form = make(doc, "form", "composer acb-ui");
  n.form.noValidate = true;
  n.slot = make(doc, "div", "composer-slot");
  n.strip = make(doc, "div", "attachment-strip");
  n.strip.hidden = true;
  ctx.live = buildAnnouncer(ctx);
  n.form.append(ctx.live.status, ctx.live.alert, n.slot, n.strip, n.box, n.bar);
  ctx.webDialog = acb.buildWebDialog(ctx);
  container.replaceChildren(n.form, ctx.webDialog.dialog);
}

function renderPicker(ctx) {
  const { s, n, optionInfo, Models } = ctx;
  const groups = Models.pickerGroups(s.agents, {
    hidden: s.hidden, shown: s.shown, keep: s.keep, ...(s.valueFor ? { valueFor: s.valueFor } : {}),
  });
  optionInfo.clear();
  for (const group of groups) {
    for (const item of group.options) optionInfo.set(item.value, { agent: group.agent, model: item.model });
  }
  n.picker.title = s.pickerTitle || "";
  Models.fillPicker(n.picker, groups, s.pickerEmptyText || Models.pickerEmptyText(s.agents));
  const values = new Set([...n.picker.options].map((item) => item.value));
  n.picker.value = values.has(s.value) ? s.value : n.picker.options[0]?.value || "";
  s.value = n.picker.value;
}

function renderAutoCommit(ctx) {
  const { s, n } = ctx;
  n.autoCommit.hidden = s.autoCommit === null || s.autoCommit === undefined;
  const isOn = Boolean(s.autoCommit);
  n.autoCommit.setAttribute("aria-pressed", String(isOn));
  n.autoCommit.title = isOn
    ? "Auto-commit is on — the agent commits, syncs and merges at the end of each request. Click to turn it off"
    : "Auto-commit is off — click so the agent commits, syncs and merges at the end of each request";
}

function renderSend(ctx) {
  const { s, n, win } = ctx;
  n.stop.hidden = !s.isStreaming;
  const title = s.sendTitle || "Send";
  n.sendButton.title = title;
  n.sendButton.setAttribute("aria-label", s.sendTitle || "Send message");
  n.sendButton.disabled = !s.canSend || !n.picker.value;
  n.input.placeholder = s.placeholder || (isTouchKeyboard(win) ? TOUCH_PLACEHOLDER : DEFAULT_PLACEHOLDER);
}

function renderTools(ctx) {
  const { s, n } = ctx;
  n.attach.disabled = !s.canAttach;
  n.attach.title = s.canAttach
    ? "Attach files — or paste / drop them into the message"
    : "This assistant doesn't take file attachments";
  n.slashButton.disabled = !s.slashCommands;
  n.slashButton.title = s.slashCommands
    ? "Slash commands — or type / first in the message"
    : "This assistant doesn't have slash commands";
}

function attachmentThumb(ctx, item) {
  const { doc, s, make } = ctx;
  if (!item.preview) return make(doc, "span", "attachment-icon", "📄");
  const thumb = make(doc, "img", "attachment-thumb");
  thumb.src = item.preview;
  thumb.alt = item.file.name || "";
  if (s.onPreview) {
    thumb.classList.add("clickable");
    thumb.title = "Click to preview";
    thumb.addEventListener("click", (event) => {
      event.preventDefault();
      s.onPreview(item.preview, item.file.name);
    });
  }
  return thumb;
}

function renderPending(ctx) {
  const { doc, n, make, button } = ctx;
  n.strip.hidden = !ctx.pending.length;
  n.strip.replaceChildren(...ctx.pending.map((item) => {
    const chip = make(doc, "div", "attachment-chip");
    const remove = button(doc, "attachment-remove", { title: "Remove", label: `Remove ${item.file.name || "file"}`, text: "✕" });
    remove.addEventListener("click", () => {
      revoke(ctx, [item]);
      setPending(ctx, ctx.pending.filter((candidate) => candidate !== item));
    });
    chip.append(attachmentThumb(ctx, item), make(doc, "span", "attachment-name", item.file.name || "file"), make(doc, "span", "attachment-size", formatSize(item.file.size || 0)), remove);
    return chip;
  }));
}

function render(ctx) {
  renderPicker(ctx);
  acb.renderEffort(ctx);
  acb.renderPermission(ctx);
  renderAutoCommit(ctx);
  acb.renderWeb(ctx);
  acb.renderContext(ctx);
  renderTools(ctx);
  renderSend(ctx);
  renderPending(ctx);
  if (ctx.slash.isOpen && acb.slashTarget(ctx)?.key !== ctx.slash.key) acb.closeSlash(ctx);
}

function revoke(ctx, items) {
  for (const item of items) if (item.preview) ctx.win?.URL?.revokeObjectURL?.(item.preview);
}

function setPending(ctx, items) {
  ctx.pending = items;
  renderPending(ctx);
  ctx.s.onFilesChange(ctx.pending.map((item) => item.file));
}

function addFiles(ctx, files) {
  const { s, win } = ctx;
  if (!s.canAttach) return;
  const { accepted, notes } = acceptFiles(ctx.pending.map((item) => item.file), [...(files || [])], {
    maxCount: s.maxAttachments, maxBytes: s.maxAttachmentBytes, maxTotal: s.maxTotalBytes,
  });
  for (const note of notes) {
    s.toast(note);
    if (s.shouldAnnounce) ctx.live.say(note, { isAlert: true });
  }
  const createUrl = win?.URL?.createObjectURL;
  setPending(ctx, [...ctx.pending, ...accepted.map((file) => ({
    file, preview: INLINE_IMAGE_TYPES.has(file.type) && createUrl ? win.URL.createObjectURL(file) : null,
  }))]);
}

function wireAttachments(ctx) {
  const { n, s } = ctx;
  n.attach.addEventListener("click", () => n.fileInput.click());
  n.fileInput.addEventListener("change", () => {
    addFiles(ctx, n.fileInput.files);
    n.fileInput.value = "";
  });
  n.input.addEventListener("paste", (event) => {
    const files = [...(event.clipboardData?.files || [])];
    if (!files.length || !s.canAttach) return;
    event.preventDefault();
    addFiles(ctx, files);
  });
  n.form.addEventListener("dragover", (event) => {
    if (!s.canAttach || !event.dataTransfer?.types?.includes("Files")) return;
    event.preventDefault();
    n.form.classList.add("dragging");
  });
  n.form.addEventListener("dragleave", () => n.form.classList.remove("dragging"));
  n.form.addEventListener("drop", (event) => {
    n.form.classList.remove("dragging");
    if (!s.canAttach || !event.dataTransfer?.files?.length) return;
    event.preventDefault();
    addFiles(ctx, event.dataTransfer.files);
  });
}

function resetHeight(ctx) {
  ctx.n.input.style.height = "";
  ctx.n.resizer.removeAttribute("aria-valuenow");
}

// The message leaves the box before any await, so a second Enter is empty. If onSend throws,
// the words and files come back (unless the owner already typed something new).
async function send(ctx) {
  const { s, n } = ctx;
  const raw = n.input.value;
  const text = raw.trim();
  const sent = ctx.pending;
  if ((!text && !sent.length) || n.sendButton.disabled) return false;
  const payload = { text, files: sent.map((item) => item.file), ...selection(ctx) };
  const height = n.input.style.height;
  n.input.value = "";
  resetHeight(ctx);
  acb.closeSlash(ctx);
  setPending(ctx, []);
  try {
    await s.onSend(payload);
    revoke(ctx, sent);
    return true;
  } catch (error) {
    restoreSend(ctx, raw, height, sent);
    const message = error?.message || String(error);
    s.toast(message);
    if (s.shouldAnnounce) ctx.live.say(message, { isAlert: true });
    return false;
  }
}

function restoreSend(ctx, raw, height, sent) {
  const { n } = ctx;
  if (!n.input.value) {
    n.input.value = raw;
    n.input.style.height = height;
  }
  if (!ctx.pending.length) setPending(ctx, sent);
}

function wireSend(ctx) {
  ctx.n.form.addEventListener("submit", (event) => {
    event.preventDefault();
    send(ctx);
  });
  ctx.n.stop.addEventListener("click", () => ctx.s.onStop());
}

function wirePicker(ctx) {
  ctx.n.picker.addEventListener("change", () => {
    ctx.s.value = ctx.n.picker.value;
    acb.renderEffort(ctx);
    acb.renderPermission(ctx);
    renderSend(ctx);
    ctx.s.onAgentChange(ctx.n.picker.value, selection(ctx));
  });
}

function wireAutoCommit(ctx) {
  ctx.n.autoCommit.addEventListener("click", () => {
    ctx.s.autoCommit = !ctx.s.autoCommit;
    renderAutoCommit(ctx);
    ctx.s.onAutoCommitChange(ctx.s.autoCommit);
  });
}

function wireResize(ctx) {
  const { doc, win, n } = ctx;
  let startY = 0;
  let startHeight = 0;
  const applyHeight = (deltaY) => {
    const height = nextComposerHeight(startHeight, deltaY, win?.innerHeight || 800);
    n.input.style.height = `${height}px`;
    n.resizer.setAttribute("aria-valuenow", String(height));
  };
  const onMove = (event) => applyHeight(event.clientY - startY);
  const onUp = () => {
    win?.removeEventListener?.("pointermove", onMove);
    win?.removeEventListener?.("pointerup", onUp);
    n.resizer.classList.remove("dragging");
    doc.body?.classList.remove("composer-resizing");
  };
  ctx.onUp = onUp;
  n.resizer.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    startY = event.clientY;
    startHeight = n.input.getBoundingClientRect().height;
    n.resizer.classList.add("dragging");
    doc.body?.classList.add("composer-resizing");
    win?.addEventListener?.("pointermove", onMove);
    win?.addEventListener?.("pointerup", onUp);
  });
  n.resizer.addEventListener("dblclick", () => resetHeight(ctx));
  n.resizer.addEventListener("keydown", (event) => {
    const step = event.key === "ArrowUp" ? -16 : event.key === "ArrowDown" ? 16 : 0;
    if (!step) return;
    event.preventDefault();
    startHeight = n.input.getBoundingClientRect().height;
    applyHeight(step);
  });
}

function wireComposer(ctx) {
  wireAttachments(ctx);
  wireSend(ctx);
  acb.wireSlash(ctx);
  wirePicker(ctx);
  acb.wireMode(ctx);
  acb.wireEffort(ctx);
  wireAutoCommit(ctx);
  acb.wireWeb(ctx);
  acb.wireContext(ctx);
  acb.wireDismiss(ctx);
  wireResize(ctx);
}

function updateComposer(ctx, patch = {}) {
  const wasStreaming = ctx.s.isStreaming;
  Object.assign(ctx.s, patch);
  if ("web" in patch && ctx.s.web) ctx.s.web = acb.normalizeWeb(ctx.s.web);
  render(ctx);
  if (ctx.s.shouldAnnounce && wasStreaming && !ctx.s.isStreaming) ctx.live.say(ctx.s.replyReadyText);
}

function setComposerText(ctx, text) {
  ctx.n.input.value = String(text ?? "");
  ctx.s.onInput(ctx.n.input.value);
}

function clearComposerFiles(ctx) {
  revoke(ctx, ctx.pending);
  setPending(ctx, []);
}

function closePopovers(ctx) {
  acb.closeSlash(ctx);
  acb.closeContext(ctx);
  acb.closeMode(ctx);
  acb.closeEffort(ctx);
}

function destroyComposer(ctx) {
  ctx.onUp();
  ctx.doc.removeEventListener("click", ctx.onDocumentClick);
  ctx.doc.removeEventListener("keydown", ctx.onDocumentKey);
  revoke(ctx, ctx.pending);
  ctx.container.replaceChildren();
}

function composerElements(ctx) {
  const n = ctx.n;
  return {
    form: n.form, slot: n.slot, box: n.box, input: n.input, bar: n.bar, tools: n.tools, actions: n.actions,
    picker: n.picker, effort: n.effort, effortPop: n.effortPop, effortTrack: n.effortTrack, ultracode: n.ultracode,
    permission: n.permission, modePop: n.modePop, attach: n.attach, slash: n.slashButton, autoCommit: n.autoCommit,
    webOn: n.webOn, webButton: n.webButton, webDialog: ctx.webDialog.dialog, meter: n.meter, stop: n.stop,
    send: n.sendButton, status: ctx.live.status, alert: ctx.live.alert,
  };
}

function composerController(ctx) {
  return {
    form: ctx.n.form,
    elements: composerElements(ctx),
    update: (patch) => updateComposer(ctx, patch),
    announce: (message, options) => ctx.live.say(message, options),
    selection: () => selection(ctx),
    send: () => send(ctx),
    getText: () => ctx.n.input.value,
    setText: (text) => setComposerText(ctx, text),
    focus: () => ctx.n.input.focus(),
    getFiles: () => ctx.pending.map((item) => item.file),
    addFiles: (files) => addFiles(ctx, files),
    clearFiles: () => clearComposerFiles(ctx),
    resetHeight: () => resetHeight(ctx),
    closePopovers: () => closePopovers(ctx),
    destroy: () => destroyComposer(ctx),
  };
}

// Mounts the chat box in `container` (its content is replaced) and returns its controller.
function mountComposer(env, container, options = {}) {
  const ctx = createComposerState(env, container, options);
  buildMessageBox(ctx);
  buildToolRow(ctx);
  acb.buildEffortControls(ctx);
  acb.buildContextControls(ctx);
  acb.buildModeControls(ctx);
  buildComposerBar(ctx);
  assembleComposer(ctx);
  wireComposer(ctx);
  render(ctx);
  return composerController(ctx);
}

Object.assign(acb, {
  COMPOSER_MIN_HEIGHT, composerHeightLimit, nextComposerHeight,
  formatTokenCount, contextMeterModel,
  MAX_ATTACHMENTS, MAX_ATTACHMENT_BYTES, MAX_TOTAL_BYTES, formatSize, acceptFiles, encodeAttachments,
  DEFAULT_PLACEHOLDER,
  selection, offeredPermissions, effortProfileFor, isUltracodeOffered, send, mountComposer,
});
}
