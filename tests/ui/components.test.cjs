// node --test tests/ui/components.test.cjs — run by tests/test_ui_assets.py when node is installed.
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../../agent_cli_bridge/ui/models.js");
const UI = require("../../agent_cli_bridge/ui/components.js");
const { FakeDocument, FakeEvent, press, type, select, tick } = require("./fake-dom.cjs");

const AGENTS = [
  { command: "claude", flavor: "claude", name: "Claude Code", account: { kind: "work" }, models: ["claude-opus-5-5", "claude-haiku-4-5"] },
  { command: "grok", flavor: "grok", name: "Grok CLI", models: ["grok-4.7"] },
];

function mount(options = {}) {
  const doc = new FakeDocument();
  const container = doc.createElement("div");
  doc.body.append(container);
  const calls = [];
  const record = (name) => (...args) => { calls.push([name, ...args]); };
  const composer = UI.mountComposer(container, {
    agents: AGENTS,
    onSend: record("send"), onStop: record("stop"), onAgentChange: record("agent"),
    onPermissionChange: record("permission"), onEffortChange: record("effort"),
    onUltracodeChange: record("ultracode"), onWebChange: record("web"), onAutoCommitChange: record("autoCommit"),
    toast: record("toast"),
    ...options,
  });
  return { doc, container, composer, calls, el: composer.elements };
}

const file = (name, size, type = "text/plain") => ({ name, size, type });

// ── the composer ──

const modeRows = (el) => el.modePop.querySelectorAll(".mode-row");
const modeValues = (el) => modeRows(el).map((row) => row.dataset.value);
const effortStops = (el) => el.effortTrack.querySelectorAll(".effort-stop");
const effortStop = (el, value) => effortStops(el).find((stop) => stop.dataset.value === value);

test("the composer builds the same box everywhere: the message and Send in the box, the rest under it", () => {
  const { container, el } = mount({ value: "claude::claude-opus-5-5", permission: "bypassPermissions" });
  const form = container.querySelector("form.composer");
  assert.ok(form);
  assert.ok(form.querySelector(".composer-box .composer-resizer"));
  assert.equal(el.input.placeholder, "Ask anything… Enter to send, Shift+Enter for a new line");
  assert.equal(el.attach.title, "Attach files — or paste / drop them into the message");
  assert.equal(el.picker.value, "claude::claude-opus-5-5");
  const chosen = el.picker.options.find((option) => option.selected);
  assert.equal(chosen.textContent, "Claude Code (work) · claude-opus-5-5");
  assert.deepEqual(modeValues(el), UI.PERMISSION_MODES.map(([value]) => value));
  assert.equal(el.permission.textContent, "Bypass permissions");
  assert.equal(el.stop.hidden, true);
  assert.equal(el.send.disabled, false);
  // Hidden until the app passes them.
  assert.equal(el.autoCommit.hidden, true);
  assert.equal(form.querySelector(".composer-web").hidden, true);
  assert.equal(el.meter.hidden, true);
  // As in Claude Code: the box holds the message with Stop and Send at its right; under the box,
  // files, commands, branch, web and the mode on the left; the agent · model, effort, context right.
  const classesOf = (row) => row.children.map((node) => node.className.split(" ").slice(0, 2).join(" "));
  assert.deepEqual(classesOf(el.box), ["composer-resizer", "slash-pop", "composer-input-row"]);
  const [message, go] = el.box.children.at(-1).children;
  assert.equal(message, el.input);
  assert.deepEqual(classesOf(go), ["composer-go composer-stop", "composer-go composer-send"]);
  assert.equal(form.children.at(-1), el.bar);
  assert.deepEqual(el.bar.children, [el.tools, el.actions]);
  assert.deepEqual(classesOf(el.tools), [
    "composer-icon", "", "composer-icon", "composer-icon composer-toggle", "composer-web", "composer-pop-wrap",
  ]);
  assert.equal(el.tools.children.at(-1).firstElementChild, el.permission);
  assert.deepEqual(classesOf(el.actions), ["composer-chip composer-agent", "composer-pop-wrap", "context-wrap"]);
  assert.equal(el.actions.children[1].firstElementChild, el.effort);
});

test("Enter sends the message, the picked model and permission, and empties the box; Shift+Enter does not", async () => {
  const { composer, calls, el } = mount({ value: "grok::grok-4.7", permission: "plan" });
  type(el.input, "hello\n");
  const shift = press(el.input, "Enter", { shiftKey: true });
  assert.equal(shift.defaultPrevented, false);
  assert.equal(calls.filter(([name]) => name === "send").length, 0);
  const enter = press(el.input, "Enter");
  assert.equal(enter.defaultPrevented, true);
  await tick();
  const [, payload] = calls.find(([name]) => name === "send");
  assert.equal(payload.text, "hello");
  assert.equal(payload.value, "grok::grok-4.7");
  assert.equal(payload.command, "grok");
  assert.equal(payload.model, "grok-4.7");
  assert.equal(payload.agent.name, "Grok CLI");
  assert.equal(payload.permission, "plan");
  assert.equal(payload.effort, "auto");
  assert.equal(payload.ultracode, false);
  assert.deepEqual(payload.files, []);
  assert.equal(composer.getText(), "");
  // An empty box sends nothing.
  press(el.input, "Enter");
  await tick();
  assert.equal(calls.filter(([name]) => name === "send").length, 1);
});

test("a send the app rejects puts the words and files back and says why", async () => {
  const { composer, calls, el } = mount({ onSend: async () => { throw new Error("Hub offline"); } });
  composer.addFiles([file("notes.txt", 10)]);
  type(el.input, "draft");
  assert.equal(await composer.send(), false);
  assert.equal(composer.getText(), "draft");
  assert.equal(composer.getFiles().length, 1);
  assert.deepEqual(calls.find(([name]) => name === "toast"), ["toast", "Hub offline"]);
});

test("a screen reader hears nothing unless the host asks: no live text by default", async () => {
  const { composer, el } = mount({ isStreaming: true, onSend: async () => { throw new Error("Hub offline"); } });
  assert.equal(el.status.getAttribute("role"), "status");
  assert.equal(el.alert.getAttribute("role"), "alert");
  assert.ok(el.status.classList.contains("acb-sr-only"));
  composer.update({ isStreaming: false });
  type(el.input, "draft");
  await composer.send();
  assert.equal(el.status.textContent, "");
  assert.equal(el.alert.textContent, "");
});

test("shouldAnnounce: a finished turn says so once, errors interrupt, the host can announce", async () => {
  const { composer, el } = mount({ shouldAnnounce: true, onSend: async () => { throw new Error("Hub offline"); } });
  composer.update({ isStreaming: true });
  composer.update({ isStreaming: true, value: "claude::claude-opus-5-5" });  // a token, not an end
  assert.equal(el.status.textContent, "");
  composer.update({ isStreaming: false });
  assert.equal(el.status.textContent, "Reply ready");
  composer.update({ isStreaming: false });
  assert.equal(el.status.textContent, "Reply ready");  // no second end without a new turn
  composer.update({ isStreaming: true });
  composer.update({ isStreaming: false });
  assert.equal(el.status.textContent.trim(), "Reply ready");
  assert.notEqual(el.status.textContent, "Reply ready");  // changed, so it is read again
  type(el.input, "draft");
  await composer.send();
  assert.equal(el.alert.textContent, "Hub offline");
  composer.announce("Which folder?");
  assert.equal(el.status.textContent, "Which folder?");
  composer.announce("Quota reached", { isAlert: true });
  assert.equal(el.alert.textContent, "Quota reached");
  composer.addFiles([file("big.bin", 11 * 1024 * 1024)]);
  assert.equal(el.alert.textContent, "big.bin is larger than 10 MB.");
});

test("a touch keyboard's Return writes a new line; the button still sends", async () => {
  const { calls, el } = mount({ sendOnEnter: () => false });
  type(el.input, "two lines");
  press(el.input, "Enter");
  await tick();
  assert.equal(calls.filter(([name]) => name === "send").length, 0);
  el.send.click();
  await tick();
  assert.equal(calls.filter(([name]) => name === "send").length, 1);
});

test("while a reply runs, Stop shows beside Send and calls the app; nothing to send without a model", () => {
  const { composer, calls, el } = mount({ isStreaming: true, sendTitle: "Queue — sent as soon as this reply ends" });
  assert.equal(el.stop.hidden, false);
  assert.equal(el.send.title, "Queue — sent as soon as this reply ends");
  el.stop.click();
  assert.deepEqual(calls.at(-1), ["stop"]);
  composer.update({ agents: [] });
  assert.equal(el.picker.options[0].textContent, "No subscriptions on this machine");
  assert.equal(el.send.disabled, true);
});

test("the agent · model dropdown follows the owner's ticks; Effort and Ultracode follow the CLI", () => {
  const { composer, calls, el } = mount({ hidden: new Set(["claude::claude-haiku-4-5"]), value: "claude::claude-opus-5-5" });
  assert.deepEqual(el.picker.options.map((option) => option.value), ["claude::claude-opus-5-5", "grok::grok-4.7"]);
  assert.equal(el.effort.hidden, false);
  // Opus 5.5: Auto is its recommended Medium, as in Claude Code.
  assert.equal(el.effort.textContent, "Medium");
  assert.deepEqual(effortStops(el).map((stop) => stop.dataset.value), ["low", "medium", "high", "xhigh", "max"]);
  assert.deepEqual(el.effortPop.querySelectorAll(".effort-mark").map((mark) => mark.textContent), ["", "Recommended", "", "", ""]);
  assert.equal(el.ultracode.parentNode.hidden, false);
  el.effort.click();
  assert.equal(el.effortPop.hidden, false);
  effortStop(el, "high").click();
  assert.deepEqual(calls.at(-1), ["effort", "high"]);
  assert.equal(el.effort.textContent, "High");
  assert.equal(el.effortPop.hidden, false, "picking a step keeps the slider open");
  el.ultracode.click();
  assert.deepEqual(calls.at(-1), ["ultracode", true]);
  assert.equal(el.effort.textContent, "High · Ultracode");
  assert.equal(composer.selection().effort, "high");
  assert.equal(composer.selection().ultracode, true);
  select(el.picker, "grok::grok-4.7");
  const [name, value, selected] = calls.at(-1);
  assert.equal(name, "agent");
  assert.equal(value, "grok::grok-4.7");
  assert.equal(selected.agent.command, "grok");
  assert.equal(el.effort.hidden, true);
  assert.equal(el.ultracode.parentNode.hidden, true);
  assert.equal(el.effortPop.hidden, true);
  assert.equal(composer.selection().effort, "auto");
  assert.equal(composer.selection().ultracode, false);
});

test("the effort slider: arrows step, the recommended level is Auto, a level the model lacks runs lower", () => {
  const agents = [{
    command: "claude", flavor: "claude", name: "Claude Code",
    models: ["claude-opus-5-5", "claude-opus-4-6", "claude-opus-4-5", "claude-haiku-4-5"],
  }];
  const { doc, composer, calls, el } = mount({ agents, value: "claude::claude-opus-5-5", effort: "max" });
  assert.equal(el.effort.textContent, "Max");
  press(el.effortTrack, "ArrowLeft");
  assert.deepEqual(calls.at(-1), ["effort", "xhigh"]);
  press(el.effortTrack, "Home");
  assert.deepEqual(calls.at(-1), ["effort", "low"]);
  press(el.effortTrack, "ArrowRight");
  assert.deepEqual(calls.at(-1), ["effort", "auto"], "Opus 5.5's recommended Medium is stored as Auto");
  assert.equal(el.effort.textContent, "Medium");
  press(el.effortTrack, "End");
  assert.deepEqual(calls.at(-1), ["effort", "max"]);
  // Opus 4.5 takes up to High: Max runs as High there, and the choice comes back on Opus 4.6.
  select(el.picker, "claude::claude-opus-4-5");
  assert.deepEqual(effortStops(el).map((stop) => stop.dataset.value), ["low", "medium", "high"]);
  assert.equal(el.effort.textContent, "High");
  assert.equal(composer.selection().effort, "high");
  select(el.picker, "claude::claude-opus-4-6");
  assert.equal(composer.selection().effort, "max");
  // Haiku 4.5 takes no effort at all: no chip, no Ultracode.
  select(el.picker, "claude::claude-haiku-4-5");
  assert.equal(el.effort.hidden, true);
  assert.equal(composer.selection().effort, "auto");
  // Escape and a click outside close the slider.
  select(el.picker, "claude::claude-opus-5-5");
  el.effort.click();
  press(el.effortPop, "Escape");
  assert.equal(el.effortPop.hidden, true);
  el.effort.click();
  assert.equal(el.effortPop.hidden, false);
  doc.body.dispatchEvent(new FakeEvent("click", { bubbles: true }));
  assert.equal(el.effortPop.hidden, true);
});

test("Copilot's effort has no recommended level: Auto is its own step", () => {
  const agents = [{ command: "copilot", flavor: "copilot", name: "Copilot", models: ["gpt-5.5"] }];
  const { el } = mount({ agents, value: "copilot::gpt-5.5" });
  assert.deepEqual(effortStops(el).map((stop) => stop.dataset.value), ["auto", "low", "medium", "high"]);
  assert.equal(el.effort.textContent, "Auto");
  assert.equal(el.effortPop.querySelector(".effort-marks").hidden, true);
  assert.equal(el.ultracode.parentNode.hidden, true);
});

test("a host's own picker values (valueFor) still name the agent and model", () => {
  const { composer } = mount({ valueFor: (agent, model) => `${agent.flavor}|${model}`, value: "grok|grok-4.7" });
  const picked = composer.selection();
  assert.equal(picked.value, "grok|grok-4.7");
  assert.equal(picked.command, "grok");
  assert.equal(picked.model, "grok-4.7");
});

test("the mode menu: names, what each does, number keys; it stops at the machine's limit", () => {
  const { composer, calls, el } = mount({ maxPermission: "acceptEdits", permission: "bypassPermissions" });
  assert.deepEqual(modeValues(el), ["plan", "manual", "acceptEdits"]);
  assert.equal(el.permission.textContent, "Accept edits");
  assert.equal(el.modePop.hidden, true);
  el.permission.click();
  assert.equal(el.modePop.hidden, false);
  assert.equal(el.modePop.querySelector(".composer-pop-title").textContent, "Mode");
  const [plan, , accept] = modeRows(el);
  assert.equal(plan.querySelector(".mode-row-name").textContent, "Plan");
  assert.equal(plan.querySelector(".mode-row-desc").textContent, UI.PERMISSION_DESCRIPTIONS.plan);
  assert.equal(plan.querySelector(".mode-row-key").textContent, "1");
  assert.equal(accept.getAttribute("aria-checked"), "true");
  assert.ok(accept.querySelector(".mode-row-check svg"));
  plan.click();
  assert.deepEqual(calls.at(-1), ["permission", "plan"]);
  assert.equal(el.modePop.hidden, true);
  assert.equal(el.permission.textContent, "Plan");
  el.permission.click();
  press(el.modePop, "2");
  assert.deepEqual(calls.at(-1), ["permission", "manual"]);
  assert.equal(el.modePop.hidden, true);
  el.permission.click();
  press(el.modePop, "Escape");
  assert.equal(el.modePop.hidden, true);
  composer.update({ maxPermission: null });
  assert.equal(composer.selection().permission, "manual");
  assert.equal(modeValues(el).length, 6);
  assert.deepEqual(UI.allowedPermissions(UI.PERMISSION_MODES, "nope").length, 6);
});

test("the modes follow the agent: only the ones its CLI tells apart, the chosen one lowered to fit", async () => {
  const agents = [
    ...AGENTS,
    { command: "gemini", flavor: "gemini", name: "Gemini CLI", models: ["gemini-3-pro"] },
    { command: "mlx", flavor: "mlx", name: "MLX", models: ["qwen"] },
  ];
  const { composer, calls, el } = mount({ agents, value: "gemini::gemini-3-pro", permission: "bypassPermissions" });
  assert.deepEqual(modeValues(el), ["plan", "acceptEdits"]);
  assert.equal(el.permission.textContent, "Accept edits");
  assert.equal(composer.selection().permission, "acceptEdits");
  // The owner's choice is kept: back on Claude Code it is Bypass again.
  select(el.picker, "claude::claude-opus-5-5");
  assert.equal(composer.selection().permission, "bypassPermissions");
  select(el.picker, "grok::grok-4.7");
  assert.deepEqual(modeValues(el), ["plan", "acceptEdits", "auto", "bypassPermissions"]);
  // A model with no tools has no mode at all.
  select(el.picker, "mlx::qwen");
  assert.equal(el.permission.parentNode.hidden, true);
  type(el.input, "hi");
  el.send.click();
  await tick();
  assert.equal(calls.find(([name]) => name === "send")[1].permission, "bypassPermissions");
  assert.equal(UI.effectivePermission([["plan"], ["acceptEdits"]], "manual"), "plan");
  assert.equal(UI.effectivePermission([["plan"], ["acceptEdits"]], "nope"), "plan", "an unknown mode runs as the most careful one");
});

test("Don't ask never runs as a mode that approves more: on Grok it is Accept edits, not Auto", () => {
  const { composer } = mount({ value: "grok::grok-4.7", permission: "dontAsk" });
  assert.equal(composer.selection().permission, "acceptEdits");
  const grok = UI.flavorPermissions(UI.PERMISSION_MODES, "grok");
  assert.equal(UI.effectivePermission(grok, "dontAsk"), "acceptEdits");
  assert.equal(UI.effectivePermission(UI.flavorPermissions(UI.PERMISSION_MODES, "cursor"), "dontAsk"), "acceptEdits");
});

test("a redraw while the mode menu is open keeps the keyboard on the same row", () => {
  const { composer, doc, calls, el } = mount({ permission: "manual" });
  el.permission.click();
  assert.equal(doc.activeElement.dataset.value, "manual");
  composer.update({ isStreaming: true });
  assert.equal(el.modePop.hidden, false);
  assert.equal(doc.activeElement.dataset.value, "manual");
  assert.ok(el.modePop.contains(doc.activeElement));
  press(doc.activeElement, "3");
  assert.deepEqual(calls.at(-1), ["permission", "acceptEdits"]);
  // Ctrl+1 is the browser's, not a mode.
  el.permission.click();
  press(el.modePop, "1", { ctrlKey: true });
  assert.equal(el.modePop.hidden, false);
  assert.equal(el.permission.getAttribute("aria-label"), "Mode: Accept edits");
});

test("the branch button turns auto-commit on and off", () => {
  const { calls, el } = mount({ autoCommit: false });
  assert.equal(el.autoCommit.hidden, false);
  assert.equal(el.autoCommit.getAttribute("aria-pressed"), "false");
  el.autoCommit.click();
  assert.deepEqual(calls.at(-1), ["autoCommit", true]);
  assert.equal(el.autoCommit.getAttribute("aria-pressed"), "true");
  assert.match(el.autoCommit.title, /^Auto-commit is on/);
});

test("Web: the tick turns it off and back to the last mode; the globe's dialog picks source, engine, searches", () => {
  const { calls, el } = mount({ web: { mode: "combined", engine: "google", maxSearches: 5 } });
  assert.equal(el.webOn.checked, true);
  assert.match(el.webButton.title, /engine: Google · up to 5 searches/);
  el.webOn.click();
  assert.equal(calls.at(-1)[1].mode, "off");
  assert.equal(el.webButton.getAttribute("aria-pressed"), "false");
  el.webOn.click();
  assert.equal(calls.at(-1)[1].mode, "combined");
  el.webButton.click();
  assert.equal(el.webDialog.open, true);
  const scout = el.webDialog.querySelector('input[value="scout"]');
  scout.click();
  assert.equal(calls.at(-1)[1].mode, "scout");
  select(el.webDialog.querySelector("select"), "both");
  assert.equal(calls.at(-1)[1].engine, "both");
  select(el.webDialog.querySelector("input.web-count"), "99");
  assert.equal(calls.at(-1)[1].maxSearches, 20);
  assert.equal(UI.clampSearches("x"), 5);
  assert.equal(UI.clampSearches(""), 5);
  assert.equal(UI.normalizeWeb({ mode: "scout" }).maxSearches, 5);
});

test("Web locked by the chat: the tick cannot change it, the globe still shows its settings read-only", () => {
  const { el, composer } = mount({ web: { mode: "scout", maxSearches: 4, isLocked: true } });
  assert.equal(el.webOn.disabled, true);
  assert.equal(el.webButton.disabled, false);
  el.webButton.click();
  assert.equal(el.webDialog.open, true);
  assert.equal(el.webDialog.querySelector("fieldset").disabled, true);
  assert.equal(el.webDialog.querySelector("input.web-count").value, "4");
  assert.match(el.webDialog.querySelector(".web-choice-main small").textContent, /^Fixed for this chat/);
  composer.update({ pickerTitle: "Researches with its own web tools" });
  assert.equal(el.picker.title, "Researches with its own web tools");
});

test("the context meter shows the app's figure and its popover offers the app's action", () => {
  let actions = 0;
  const context = UI.contextMeterModel({ used: 150000, window: 200000, source: "claude" });
  const { doc, el } = mount({ context, onContextAction: () => { actions += 1; } });
  assert.equal(el.meter.hidden, false);
  assert.ok(el.meter.classList.contains("warn"));
  assert.equal(el.meter.querySelector(".context-meter-label").textContent, "75%");
  el.meter.click();
  const pop = el.form.querySelector(".context-pop");
  assert.equal(pop.hidden, false);
  assert.equal(pop.querySelector(".context-pop-label").textContent, "Context · 150.0k / 200.0k (75%)");
  pop.querySelector("button").click();
  assert.equal(actions, 1);
  assert.equal(pop.hidden, true);
  el.meter.click();
  doc.body.dispatchEvent(new FakeEvent("click", { bubbles: true }));
  assert.equal(pop.hidden, true);
});

test("attachments: files wait in a strip above the box, within the limits, and go with the message", async () => {
  const { composer, calls, el } = mount({ maxAttachments: 2 });
  composer.addFiles([file("a.txt", 10), file("big.bin", 11 * 1024 * 1024), file("b.txt", 20), file("c.txt", 30)]);
  assert.equal(composer.getFiles().length, 2);
  const notes = calls.filter(([name]) => name === "toast").map(([, text]) => text);
  assert.deepEqual(notes, ["big.bin is larger than 10 MB.", "At most 2 files per message."]);
  const strip = el.form.querySelector(".attachment-strip");
  assert.equal(strip.hidden, false);
  assert.equal(strip.querySelectorAll(".attachment-chip").length, 2);
  strip.querySelector(".attachment-remove").click();
  assert.deepEqual(composer.getFiles().map((item) => item.name), ["b.txt"]);
  el.send.click();
  await tick();
  assert.deepEqual(calls.find(([name]) => name === "send")[1].files.map((item) => item.name), ["b.txt"]);
  assert.equal(strip.hidden, true);
});

test("an app without attachments or slash commands shows the same icons, disabled", () => {
  const { composer, el } = mount({ canAttach: false });
  assert.equal(el.attach.disabled, true);
  assert.equal(el.attach.title, "This assistant doesn't take file attachments");
  assert.equal(el.slash.disabled, true);
  composer.addFiles([file("a.txt", 1)]);
  assert.equal(composer.getFiles().length, 0);
});

test("slash commands: '/' opens the app's list, typing filters it, Enter picks one", async () => {
  const asked = [];
  const commands = [
    { name: "review", description: "Review the diff", source: "project" },
    { name: "init", description: "Write CLAUDE.md", source: "builtin" },
  ];
  const { composer, calls, el } = mount({ slashCommands: async (selected) => { asked.push(selected.command); return commands; } });
  assert.equal(el.slash.disabled, false);
  el.slash.click();
  assert.equal(composer.getText(), "/");
  await tick();
  const pop = el.form.querySelector(".slash-pop");
  assert.equal(pop.hidden, false);
  assert.equal(pop.querySelectorAll(".slash-row").length, 2);
  assert.equal(pop.querySelector(".slash-source").textContent, "Project");
  type(el.input, "/in");
  assert.equal(pop.querySelectorAll(".slash-row").length, 1);
  const enter = press(el.input, "Enter");
  assert.equal(enter.defaultPrevented, true);
  assert.equal(composer.getText(), "/init ");
  assert.equal(pop.hidden, true);
  assert.equal(calls.filter(([name]) => name === "send").length, 0);
  // Asked once: the list is cached for a minute.
  type(el.input, "/");
  await tick();
  assert.deepEqual(asked, ["claude"]);
});

test("slash commands: an agent without any says so, and a failed listing shows its error", async () => {
  const { el, composer } = mount({ value: "grok::grok-4.7", slashCommands: async () => [] });
  type(el.input, "/");
  await tick();
  assert.equal(el.form.querySelector(".slash-empty").textContent, "Grok CLI has no slash commands here — they work with Claude Code.");
  composer.update({ slashCommands: async () => { throw new Error("Node offline"); }, value: "claude::claude-opus-5-5" });
  type(el.input, "hi");
  type(el.input, "/");
  await tick();
  assert.equal(el.form.querySelector(".slash-empty").textContent, "Node offline");
});

test("the box is dragged taller from its top edge, within the window, and send resets it", async () => {
  const { el } = mount();
  const resizer = el.form.querySelector(".composer-resizer");
  press(resizer, "ArrowUp");
  assert.equal(el.input.style.height, "68px");
  assert.equal(resizer.getAttribute("aria-valuenow"), "68");
  assert.equal(UI.nextComposerHeight(100, -1000, 900), UI.composerHeightLimit(900));
  assert.equal(UI.nextComposerHeight(100, 1000, 900), UI.COMPOSER_MIN_HEIGHT);
  type(el.input, "go");
  el.send.click();
  await tick();
  assert.equal(el.input.style.height, "");
});

test("slash helpers: the query, the ranking and the inserted command", () => {
  assert.equal(UI.slashQuery("/rev"), "rev");
  assert.equal(UI.slashQuery("/rev x"), null);
  const list = [{ name: "xreview" }, { name: "review" }, { name: "other", description: "review it" }];
  assert.deepEqual(UI.filterSlashCommands(list, "review").map((item) => item.name), ["review", "xreview", "other"]);
  assert.equal(UI.applySlashCommand("/re", "review"), "/review ");
  assert.equal(UI.applySlashCommand("  fix this", "review"), "/review fix this");
});

// ── Settings › Models ──

function mountModels(options = {}) {
  const doc = new FakeDocument();
  const container = doc.createElement("section");
  doc.body.append(container);
  const saved = [];
  const page = UI.mountModelsSettings(container, {
    machines: [{ name: "This PC", agents: AGENTS }],
    onToggle: (...args) => saved.push(["toggle", ...args]),
    onFreeOnlyChange: (isOn) => saved.push(["free", isOn]),
    ...options,
  });
  return { container, page, saved };
}

test("Settings › Models: a search, Free models only, the help, then one table per subscription", () => {
  const { container } = mountModels();
  assert.equal(container.querySelector(".settings-category-title").textContent, "Models");
  assert.equal(container.querySelector("button.model-refresh").textContent, "Refresh");
  assert.equal(container.querySelector(".settings-field span").textContent, "Find a model searches every subscription, ticked or not");
  assert.equal(container.querySelector("input.model-search").placeholder, "opus, grok-4.7, free…");
  assert.equal(container.querySelector(".settings-label").textContent, "Free models only");
  const help = container.querySelector("details.settings-help");
  assert.equal(help.querySelector("summary").textContent, "Reading the tables");
  assert.ok(help.querySelectorAll("em").length >= 5);
  const groups = container.querySelectorAll(".model-visibility .model-group");
  assert.equal(groups.length, 2);
  assert.equal(groups[0].querySelector(".settings-sublabel").textContent, "Claude Code (work)");
  assert.equal(groups[0].querySelector(".model-group-count").textContent, "2 of 2 in the dropdown");
  assert.deepEqual(groups[0].querySelectorAll("th").map((cell) => cell.textContent), ["Model", "Intelligence", "Speed", "Price"]);
});

test("Settings › Models: Refresh button reloads the catalog and live Artificial Analysis metrics", async () => {
  let refreshed = 0;
  const { container, page } = mountModels({
    onRefresh: async () => {
      refreshed += 1;
      assert.equal(page.elements.refresh.disabled, true);
      assert.equal(page.elements.refresh.textContent, "Refreshing…");
      return [
        {
          name: "This computer",
          agents: [
            {
              command: "agy",
              name: "Google Antigravity",
              flavor: "antigravity",
              models: ["gemini-5-ultra-high"],
              metrics: { "gemini-5-ultra-high": [63, 150] },
            },
          ],
        },
      ];
    },
  });
  try {
    await page.refresh();
    assert.equal(refreshed, 1);
    assert.equal(page.elements.refresh.disabled, false);
    assert.equal(page.elements.refresh.textContent, "Refresh");
    const groups = container.querySelectorAll(".model-visibility .model-group");
    assert.equal(groups.length, 1);
    assert.equal(groups[0].querySelector(".settings-sublabel").textContent, "Google Antigravity");
    const values = groups[0].querySelectorAll(".model-bar-value").map((node) => node.textContent);
    assert.deepEqual(values, ["63", "150 t/s"]);
  } finally {
    globalThis.AgentModels.clearLiveModelMetrics();
  }
});

test("Settings › Models: a tick saves the new sets; the search and the free switch redraw the tables", () => {
  const { container, page, saved } = mountModels();
  const box = container.querySelector('.model-visibility input[type="checkbox"]');
  box.click();
  const [, key, isVisible, sets] = saved.at(-1);
  assert.equal(key, "claude::claude-opus-5-5");
  assert.equal(isVisible, false);
  assert.ok(sets.hidden.has(key));
  assert.ok(page.hidden.has(key));
  assert.equal(container.querySelector(".model-group-count").textContent, "1 of 2 in the dropdown");
  type(container.querySelector("input.model-search"), "grok");
  assert.equal(container.querySelectorAll(".model-visibility .model-group").length, 1);
  type(container.querySelector("input.model-search"), "nothing-like-it");
  assert.equal(container.querySelector(".model-visibility .settings-empty").textContent, "No model matches “nothing-like-it”.");
  container.querySelector("input.settings-switch").click();
  assert.deepEqual(saved.at(-1), ["free", true]);
  page.update({ query: "", hidden: [] });
  assert.equal(container.querySelector(".model-group-count").textContent, "2 of 2 in the dropdown");
});

test("Settings › Models: no subscription says why; help: null drops the disclosure", () => {
  const { container } = mountModels({ machines: [], help: null, emptyText: "No hub online yet." });
  assert.equal(container.querySelector("details.settings-help"), null);
  assert.equal(container.querySelector(".model-visibility .settings-empty").textContent, "No hub online yet.");
});

// ── Settings › Agents ──

function mountAgents(options = {}) {
  const doc = new FakeDocument();
  const container = doc.createElement("section");
  doc.body.append(container);
  const calls = [];
  const statusOf = options.statusOf || (() => ({
    agents: [
      { command: "claude", name: "Claude Code", installed: "3.1.0", latest: "3.1.0", is_outdated: false },
      { command: "grok", name: "Grok CLI", installed: "1.0", latest: "1.2", is_outdated: true },
    ],
  }));
  const api = {
    status: async (target, { force }) => { calls.push(["status", target?.key ?? null, force]); return statusOf(target); },
    signInStatus: async (target, command) => { calls.push(["signInStatus", command]); return { signed_in: command === "claude" }; },
    update: async () => ({ ok: true }), signIn: async () => ({}), signInCode: async () => ({}), signOut: async () => ({ signed_in: false }),
  };
  const page = UI.mountAgentsSettings(container, { api, ...options });
  return { container, page, calls };
}

test("Settings › Agents: Check again, then each CLI with its dot, version, Update and sign-in", async () => {
  const { container, calls } = mountAgents();
  assert.equal(container.querySelector(".settings-category-title").textContent, "Agents");
  assert.equal(container.querySelector(".settings-group-title").textContent, "Installed");
  assert.equal(container.querySelector("button.cli-recheck").textContent, "Check again");
  assert.equal(container.querySelector(".cli-machine .settings-hint").textContent, "Checking versions…");
  await tick();
  await tick();
  assert.ok(container.querySelector(".settings-computers").classList.contains("single"));
  const rows = container.querySelectorAll(".cli-row");
  assert.equal(rows.length, 2);
  assert.ok(rows[0].querySelector(".cli-dot"));
  assert.equal(rows[0].querySelector(".cli-version").textContent, "3.1.0 · up to date");
  assert.equal(rows[0].querySelector(".cli-signed-in").textContent.startsWith("✓ Signed in"), true);
  assert.equal(rows[0].querySelector(".cli-sign-out").textContent, "Sign out");
  assert.ok(rows[1].classList.contains("outdated"));
  assert.equal(rows[1].querySelector(".cli-version").textContent, "1.0 → 1.2");
  const buttons = rows[1].querySelectorAll("button").map((node) => node.textContent);
  assert.deepEqual(buttons, ["Update", "Sign in"]);
  assert.ok(rows[1].querySelector("button").classList.contains("acb-btn-primary"));
  assert.deepEqual(calls.filter(([name]) => name === "status"), [["status", null, false]]);
});

test("Settings › Agents: Check again asks every machine again, forced; one section per machine", async () => {
  const machines = [{ key: "a", name: "Desk" }, { key: "b", name: "Laptop" }];
  const { container, calls, page } = mountAgents({ machines, focusKey: "b" });
  await tick();
  await tick();
  const sections = container.querySelectorAll(".cli-machine");
  assert.equal(sections.length, 2);
  assert.equal(container.querySelector(".settings-computers").classList.contains("single"), false);
  assert.equal(sections[0].querySelector(".settings-sublabel").textContent, "Desk");
  assert.ok(sections[1].classList.contains("focused"));
  container.querySelector("button.cli-recheck").click();
  await tick();
  await tick();
  assert.deepEqual(calls.filter(([name]) => name === "status").slice(-2), [["status", "a", true], ["status", "b", true]]);
  assert.ok(page.statusOf(machines[0]).agents.length);
});

test("Settings › Agents: a failed check says why; no machine says so", async () => {
  const { container, page } = mountAgents({ statusOf: () => { throw new Error("hub unreachable"); } });
  await tick();
  await tick();
  assert.equal(container.querySelector(".settings-hint.error-text").textContent, "Could not check: hub unreachable");
  page.update({ machines: [], emptyText: "No computer online." });
  assert.equal(container.querySelector(".settings-computers .settings-empty").textContent, "No computer online.");
});

test("Settings › Agents: the app's notice replaces the list until it is cleared", async () => {
  const { container, page, calls } = mountAgents({ notice: "Desk is offline." });
  const banner = container.querySelector(".settings-banner.warning");
  assert.equal(banner.textContent, "Desk is offline.");
  assert.equal(banner.hidden, false);
  assert.equal(container.querySelector(".settings-group").hidden, true);
  assert.equal(calls.length, 0);
  page.update({ notice: "" });
  assert.equal(banner.hidden, true);
  assert.equal(container.querySelector(".settings-group").hidden, false);
});

test("every piece wears the shared palette (acb-ui), so a host's theme cannot recolour it", () => {
  const { container, el, composer } = mount();
  assert.ok(el.form.classList.contains("acb-ui"));
  assert.ok(el.webDialog.classList.contains("acb-ui"));
  composer.destroy();
  assert.equal(container.children.length, 0);
  const models = mountModels();
  assert.ok(models.container.classList.contains("acb-ui"));
  assert.ok(models.container.classList.contains("acb-settings"));
  models.page.destroy();
  assert.equal(models.container.classList.contains("acb-ui"), false);
  const agents = mountAgents();
  assert.ok(agents.container.classList.contains("acb-ui"));
  agents.page.destroy();
  assert.equal(agents.container.className, "");
});

test("the components need models.js and a status api", () => {
  assert.equal(globalThis.AgentUI, UI);
  assert.equal(M.SEPARATOR, "::");
  const doc = new FakeDocument();
  assert.throws(() => UI.mountAgentsSettings(doc.createElement("div"), {}), /api.status/);
});
