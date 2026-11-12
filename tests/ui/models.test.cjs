// node --test tests/ui/models.test.cjs — run by tests/test_ui_assets.py when node is installed.
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../../agent_cli_bridge/ui/models.js");

// Just enough of a document for fillPicker and renderModelTables.
class FakeNode {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.className = "";
    this.textContent = "";
    this.style = {};
    this.listeners = {};
    this.ownerDocument = fakeDocument;
    this.classList = { add: (name) => { this.className = `${this.className} ${name}`.trim(); } };
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  get childElementCount() { return this.children.length; }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  setAttribute(name, value) { this[name] = String(value); }
  find(predicate) {
    if (predicate(this)) return this;
    for (const child of this.children) {
      const hit = child instanceof FakeNode ? child.find(predicate) : null;
      if (hit) return hit;
    }
    return null;
  }
  findAll(predicate, found = []) {
    if (predicate(this)) found.push(this);
    for (const child of this.children) if (child instanceof FakeNode) child.findAll(predicate, found);
    return found;
  }
}
const fakeDocument = { createElement: (tag) => new FakeNode(tag) };

test("a new model stays out of the picker until ticked; a curated one until hidden", () => {
  const key = "grok::grok-4.7";
  assert.equal(M.isModelInPicker({ isNew: true, key }), false);
  assert.equal(M.isModelInPicker({ isNew: true, key, shown: new Set([key]) }), true);
  assert.equal(M.isModelInPicker({ isNew: false, key }), true);
  assert.equal(M.isModelInPicker({ isNew: false, key, hidden: new Set([key]) }), false);
});

test("new models are announced once, until they were seen", () => {
  const agents = [
    { command: "grok", name: "Grok CLI", models: ["grok-4.6", "grok-4.7"], new_models: ["grok-4.7"] },
    { command: "agy", name: "Google Antigravity", models: ["default", "gemini-3.8-flash-high"], new_models: ["gemini-3.8-flash-high"] },
    { command: "claude", name: "Claude Code", models: ["sonnet"] },
  ];
  const note = M.newModelsNote(agents);
  assert.equal(note.text, "2 new models available");
  assert.deepEqual(note.detail, ["New: Grok CLI · grok-4.7", "New: Google Antigravity · gemini-3.8-flash-high"]);
  assert.equal(M.newModelsNote(agents, new Set(["grok::grok-4.7"])).text, "New model: gemini-3.8-flash-high");
  assert.equal(M.newModelsNote(agents, new Set(note.keys)), null);
  assert.equal(M.newModelsNote([]), null);
});

test("Settings names the machines that list a model the others do not", () => {
  const machines = [
    { name: "WORK-MAC", hub: null, agents: [
      { command: "claude", name: "Claude Code", models: ["sonnet", "fable", "opus", "haiku"], new_models: [] },
      { command: "grok", name: "Grok CLI", models: ["grok-4.6", "grok-4.7"], new_models: ["grok-4.7"] },
    ] },
    { name: "my-mac", hub: "h1", agents: [
      { command: "claude", name: "Claude Code", models: ["sonnet", "fable", "opus", "claude-opus-5-5", "haiku"], new_models: [] },
    ] },
  ];
  const catalog = M.modelCatalog(machines, (machine) => (machine.hub ? "OFFICE-PC" : "WORK-MAC"));
  assert.deepEqual(catalog.map((group) => group.command), ["claude", "grok"]);
  const claude = catalog[0].models;
  // First-seen order across machines: a model another one adds comes after this one's own.
  assert.deepEqual(claude.map((row) => row.model), ["sonnet", "fable", "opus", "haiku", "claude-opus-5-5"]);
  const opus55 = claude.find((row) => row.model === "claude-opus-5-5");
  assert.equal(opus55.key, "claude::claude-opus-5-5");
  assert.deepEqual(opus55.offeredBy, ["OFFICE-PC"]);
  assert.deepEqual(opus55.onlyOn, ["OFFICE-PC"]);
  assert.deepEqual(claude.find((row) => row.model === "fable").onlyOn, []);
  // A CLI on one machine only is not "only on" it: every machine that has it lists the model.
  assert.deepEqual(catalog[1].models.map((row) => [row.model, row.isNew, row.onlyOn]), [["grok-4.6", false, []], ["grok-4.7", true, []]]);
  const note = M.modelWhereNote(opus55, "Claude Code");
  assert.equal(note.text, "OFFICE-PC only");
  assert.match(note.title, /Only OFFICE-PC lists claude-opus-5-5 for Claude Code/);
  assert.match(note.title, /models\.claude in that machine's agent_cli_bridge\.json/);
  assert.equal(M.modelWhereNote(claude[0], "Claude Code"), null);
  assert.deepEqual(M.modelCatalog([]), []);
});

test("the OpenCode CLI is labeled Open Router, and Claude by its account", () => {
  assert.equal(M.agentDisplayName({ command: "opencode", name: "OpenCode" }), "Open Router");
  assert.equal(M.agentDisplayName({ command: "claude", name: "Claude Code" }), "Claude Code");
  assert.equal(M.agentDisplayName({ command: "claude", name: "Claude Code", account: { kind: "personal" } }), "Claude Code (personal)");
  assert.equal(M.agentDisplayName({ command: "claude", name: "Claude Code", account: { kind: "work" } }), "Claude Code (work)");
  assert.equal(M.agentDisplayName({ command: "claude", name: "Claude Code", account: { kind: "other" } }), "Claude Code");
  assert.equal(M.modelDisplayName("opencode/big-pickle"), "openrouter/big-pickle");
  assert.equal(M.modelDisplayName("openrouter/stealth/union-alpha"), "openrouter/stealth/union-alpha");
  assert.equal(M.modelDisplayName("opus"), "opus");
  assert.equal(M.modelDisplayName(""), "");
  const catalog = M.modelCatalog([{
    name: "mac",
    agents: [{ command: "opencode", name: "OpenCode", models: ["openrouter/stealth/union-alpha", "opencode/big-pickle"] }],
  }]);
  assert.equal(catalog[0].name, "Open Router");
  assert.equal(catalog[0].command, "opencode");
  assert.equal(catalog[0].models[1].model, "opencode/big-pickle");  // the id sent to the CLI stays
  const note = M.newModelsNote([{ command: "opencode", name: "OpenCode", new_models: ["opencode/ling-3.0-flash-fin-free"] }]);
  assert.deepEqual(note.detail, ["New: Open Router · openrouter/ling-3.0-flash-fin-free"]);
});

test("a company gateway's names show in the picker, Settings, its search and the new-model note", () => {
  const agent = {
    command: "claude", name: "Claude Code", flavor: "claude", account: { kind: "work", detail: "127.0.0.1:4000" },
    models: ["opus", "claude-opus-5-5[1m]", "databricks-gpt-5-5", "databricks-glm-5-3"],
    new_models: ["databricks-glm-5-3"],
    prices: { "claude-opus-5-5[1m]": [3, 15], "databricks-gpt-5-5": [5, 30] },
    labels: { "claude-opus-5-5[1m]": "Claude Opus 5.5", "databricks-gpt-5-5": "GPT 5.5", "databricks-glm-5-3": "GLM 5.3", odd: 7 },
  };
  assert.equal(M.modelDisplayName("databricks-gpt-5-5", agent), "GPT 5.5");
  assert.equal(M.modelDisplayName("databricks-gpt-5-5"), "databricks-gpt-5-5");  // no agent, no name
  assert.equal(M.modelDisplayName("opus", agent), "opus");
  // Only an own string counts: labels come from another machine.
  assert.equal(M.modelLabel(agent, "odd"), "");
  assert.equal(M.modelLabel(agent, "constructor"), "");
  assert.equal(M.modelLabel({ labels: "GPT" }, "0"), "");
  // [1m] is the same model with a 1M-token window: it ranks like it.
  assert.deepEqual(M.modelMetrics("claude-opus-5-5[1m]"), M.modelMetrics("claude-opus-5-5"));

  const [group] = M.pickerGroups([agent]);
  assert.deepEqual(group.options.map((option) => option.label), [
    "Claude Code (work) · Claude Opus 5.5 · $3.00 / $15.00",
    "Claude Code (work) · opus",
    "Claude Code (work) · GPT 5.5 · $5.00 / $30.00",
  ]);
  assert.equal(group.options[0].value, "claude::claude-opus-5-5[1m]");  // the id the CLI gets stays

  const container = new FakeNode("div");
  const catalog = M.modelCatalog([{ name: "pc", agents: [agent] }]);
  const gpt = catalog[0].models.find((row) => row.model === "databricks-gpt-5-5");
  assert.equal(gpt.label, "GPT 5.5");
  M.renderModelTables(container, catalog, {});
  const names = () => container.findAll((node) => node.className === "model-name");
  assert.deepEqual(names().map((node) => [node.textContent, node.title]), [
    ["Claude Opus 5.5", "claude-opus-5-5[1m]"],
    ["opus", "opus"],
    ["GLM 5.3", "databricks-glm-5-3"],
    ["GPT 5.5", "databricks-gpt-5-5"],
  ]);
  M.renderModelTables(container, catalog, { query: "gpt 5" });
  assert.deepEqual(names().map((node) => node.textContent), ["GPT 5.5"]);
  M.renderModelTables(container, catalog, { query: "databricks-glm" });  // the id still finds it
  assert.deepEqual(names().map((node) => node.textContent), ["GLM 5.3"]);
  // "Free models only" keeps a new model listed: the note below sends the owner here to tick it.
  M.renderModelTables(container, catalog, { freeOnly: true });
  assert.deepEqual(names().map((node) => node.textContent), ["Claude Opus 5.5", "opus", "GLM 5.3", "GPT 5.5"]);

  const note = M.newModelsNote([agent]);
  assert.equal(note.text, "New model: GLM 5.3");
  assert.deepEqual(note.detail, ["New: Claude Code (work) · GLM 5.3"]);
  const where = M.modelWhereNote({ ...gpt, onlyOn: ["OFFICE-PC"] }, "Claude Code (work)");
  assert.match(where.title, /Only OFFICE-PC lists GPT 5\.5 for Claude Code \(work\)/);
});

test("models rank by Artificial Analysis intelligence, then speed", () => {
  const ranked = (id) => M.modelMetrics(id);
  const intelligence = {
    "claude-opus-5-5": 54, fable: 51, sonnet: 47, haiku: 38, "cursor-grok-4.6-high": 44,
    "gemini-4-argon-high": 53, "gemini-4-argon-medium": 53, "gemini-4-argon-low": 53, "gemini-3.8-flash-low": 33,
  };
  for (const [id, score] of Object.entries(intelligence)) assert.equal(ranked(id).intelligence, score, id);
  assert.equal(ranked("claude-opus-5-5").kind, "ranked");
  assert.equal(ranked("auto").kind, "picker");
  assert.equal(ranked("default").kind, "picker");
  assert.equal(ranked("composer-2.5").kind, "unknown");
  assert.equal(ranked("cursor-grok-4.6-high").speed, 66);
  assert.equal(ranked("gemini-4-argon-high").speed, 82);
  assert.equal(M.formatModelIntelligence(ranked("claude-opus-5-5")), "54");
  assert.equal(M.formatModelSpeed(ranked("claude-opus-5-5")), "82 t/s");
  assert.equal(M.formatModelIntelligence(ranked("auto")), "—");
  assert.equal(M.formatModelSpeed(ranked("composer-2.5")), "—");
  const names = (models) => M.sortModelsByIntelligence(models.map((model) => ({ model }))).map((row) => row.model);
  // Latest opus alias and the pinned 5.5 id share the high row; name breaks the tie.
  assert.deepEqual(names(["haiku", "sonnet", "opus", "fable", "claude-opus-5-5"]), ["claude-opus-5-5", "opus", "fable", "sonnet", "haiku"]);
  assert.deepEqual(names(["composer-2.5", "auto", "gpt-5.6-sol-high", "cursor-grok-4.6-high"]), ["auto", "gpt-5.6-sol-high", "cursor-grok-4.6-high", "composer-2.5"]);
  const saved = {};
  for (const id of Object.values(M.CLAUDE_EFFORT_ALIASES)) { saved[id] = M.MODEL_METRICS[id]; delete M.MODEL_METRICS[id]; }
  try {
    for (const id of [...Object.keys(M.CLAUDE_EFFORT_ALIASES), ...Object.values(M.CLAUDE_EFFORT_ALIASES)]) assert.equal(ranked(id).kind, "unknown", id);
    assert.equal(ranked("claude-sonnet-5").intelligence, 32);
    assert.equal(ranked("claude-haiku-4-5").intelligence, 17);
    assert.equal(M.MODEL_FAMILY_ALIASES.sonnet, undefined);
    assert.equal(M.MODEL_FAMILY_ALIASES.haiku, undefined);
  } finally { Object.assign(M.MODEL_METRICS, saved); }
});

test("live metrics from the host rank newly released models in the picker and Settings tables", () => {
  try {
    const agy = {
      command: "agy",
      name: "Google Antigravity",
      flavor: "antigravity",
      models: ["gemini-3.1-pro-preview", "gemini-5-ultra-high"],
      metrics: { "gemini-5-ultra-high": [62, 145] },
    };
    const [group] = M.pickerGroups([agy]);
    // gemini-5-ultra-high (62) ranks ahead of gemini-3.1-pro-preview (30).
    assert.deepEqual(group.options.map((opt) => opt.model), ["gemini-5-ultra-high", "gemini-3.1-pro-preview"]);
    assert.deepEqual(M.modelMetrics("gemini-5-ultra-high"), { kind: "ranked", intelligence: 62, speed: 145 });
    // Stem fallback also ranks other effort tiers of the same live family.
    assert.deepEqual(M.modelMetrics("gemini-5-ultra-low"), { kind: "ranked", intelligence: 62, speed: 145 });
  } finally {
    M.clearLiveModelMetrics();
  }
});

test("Open Router free ids rank by the same Index; limited, preview and graduated tag them", () => {
  assert.equal(M.modelMetrics("openrouter/meta/muse-spark-1.3-contributor-free").intelligence, 48);
  assert.equal(M.modelMetrics("openrouter/google/gemma-4-31b-it:free").intelligence, 19);
  assert.equal(M.modelMetrics("opencode/big-pickle").kind, "unknown");
  assert.equal(M.isLimitedFreeModel("openrouter/google/gemma-4-31b-it:free"), true);
  assert.equal(M.isLimitedFreeModel("opencode/big-pickle"), false);
  assert.equal(M.modelLimitedNote("openrouter/qwen/qwen3.8-27b:free").text, "limited");
  assert.equal(M.isPreviewModel("openrouter/longcat-2.5-preview-free"), true);
  assert.equal(M.isPreviewModel("openrouter/mimo-v2.6-flash-free"), false);
  assert.equal(M.modelPreviewNote("opencode/big-pickle"), null);
  assert.equal(M.modelIndexNote("openrouter/muse-spark-1.3-contributor-free").text, "graduated");
  assert.equal(M.modelIndexNote("claude-opus-5-5"), null);  // a short list of named models: no badge
  assert.equal(M.modelIndexNote("openrouter/stealth/space-bunny-alpha"), null);
});

test("Open Router models carry their price; paid ones stay out of the picker until ticked", () => {
  const key = "opencode::openrouter/meta/muse-spark-1.3";
  assert.equal(M.isModelInPicker({ isOptional: true, key }), false);
  assert.equal(M.isModelInPicker({ isOptional: true, key, shown: new Set([key]) }), true);
  assert.equal(M.modelPriceNote("openrouter/meta/muse-spark-1.3", [1.25, 4.25]).text, "$1.25 / $4.25");
  assert.equal(M.modelPriceNote("opencode/big-pickle", [0, 0]).text, "Free");
  // A router reports 0: it bills whatever model it picks — not free.
  assert.equal(M.isFreeModel("openrouter/openrouter/auto", [0, 0]), false);
  assert.equal(M.modelPriceNote("openrouter/openrouter/auto", [0, 0]).text, "—");
  assert.notEqual(M.modelMetrics("openrouter/openrouter/auto").kind, "picker");
  assert.equal(M.modelPriceNote("opus", null, false).text, "Plan");
  assert.equal(M.isPricedAgent({ flavor: "opencode" }), true);
  assert.equal(M.isPricedAgent({ flavor: "claude" }), false);
});

test("a signed-out CLI's error offers to sign that CLI in, and nothing else does", () => {
  const error = "Error: Authentication required. Please run 'agent login' first, or set CURSOR_API_KEY environment variable.";
  assert.equal(M.signInCommandFor(error, "cursor-agent", ["claude", "cursor-agent"]), "cursor-agent");
  assert.equal(M.signInCommandFor(error, undefined, ["claude", "agent"]), "agent");
  assert.equal(M.signInCommandFor("rate limited", "cursor-agent", ["cursor-agent"]), "");
  const oauth = "Failed to authenticate: OAuth session expired and could not be refreshed";
  assert.equal(M.signInCommandFor(oauth, "claude", []), "claude");
  assert.equal(M.signInCommandFor(`${oauth}\n\n${"x".repeat(500)}`, "claude", ["claude"]), "");
  assert.equal(M.signInCommandFor("You are not authenticated. Run `grok login`.", "grok", ["grok", "claude"]), "grok");
  assert.equal(M.signInTextFrom({ content: "", parts: [{ type: "text", text: oauth }] }), oauth);
  assert.equal(M.shouldOfferSignIn({ command: "grok", can_sign_in: false }), true);
  assert.equal(M.shouldOfferSignIn({ command: "agy" }), false);
  assert.equal(M.shouldOfferSignInCode("claude", { isBusy: true }), true);
  assert.equal(M.shouldOfferSignInCode("grok", { isBusy: true }), false);
  assert.equal(M.signInPastePrompt("opencode"), "Paste your OpenRouter API key");
});

const AGENTS = [
  { command: "claude", name: "Claude Code", flavor: "claude", models: ["haiku", "sonnet", "opus"], account: { kind: "work" } },
  {
    command: "opencode", name: "OpenCode", flavor: "opencode",
    models: ["opencode/big-pickle", "openrouter/meta/muse-spark-1.3", "openrouter/mimo-v2.6-flash-free"],
    optional_models: ["openrouter/meta/muse-spark-1.3"],
    prices: { "opencode/big-pickle": [0, 0], "openrouter/meta/muse-spark-1.3": [1.25, 4.25] },
  },
  { command: "grok", name: "Grok CLI", flavor: "grok", models: ["grok-4.6", "grok-4.7"], new_models: ["grok-4.7"] },
];

test("the picker offers one group per agent, strongest model first, tagged like Settings", () => {
  const groups = M.pickerGroups(AGENTS);
  assert.deepEqual(groups.map((group) => group.label), ["Claude Code (work)", "Open Router", "Grok CLI"]);
  assert.deepEqual(groups[0].options.map((option) => option.value), ["claude::opus", "claude::sonnet", "claude::haiku"]);
  assert.equal(groups[0].options[0].label, "Claude Code (work) · opus");
  // The paid optional model and the new Grok one stay out until ticked; the free ones are in.
  assert.deepEqual(groups[1].options.map((option) => option.label), [
    "Open Router · openrouter/mimo-v2.6-flash-free · graduated · limited",
    "Open Router · openrouter/big-pickle",
  ]);
  assert.deepEqual(groups[2].options.map((option) => option.model), ["grok-4.6"]);
});

test("the picker follows the owner's ticks, keeps the open chat's model, and sends the host's value", () => {
  const groups = M.pickerGroups(AGENTS, {
    hidden: new Set(["claude::haiku", "claude::sonnet"]),
    shown: new Set(["opencode::openrouter/meta/muse-spark-1.3", "grok::grok-4.7"]),
    keep: "claude|sonnet",
    valueFor: (agent, model) => `${agent.flavor}|${model}`,
  });
  assert.deepEqual(groups[0].options.map((option) => option.value), ["claude|opus", "claude|sonnet"]);
  assert.equal(groups[0].options[1].key, "claude::sonnet");
  const paid = groups[1].options.find((option) => option.model === "openrouter/meta/muse-spark-1.3");
  assert.equal(paid.label, "Open Router · openrouter/meta/muse-spark-1.3 · graduated · $1.25 / $4.25");
  assert.deepEqual(groups[2].options.map((option) => option.model), ["grok-4.7", "grok-4.6"]);
  // An agent with every model hidden drops out of the picker.
  assert.deepEqual(M.pickerGroups([AGENTS[2]], { hidden: new Set(["grok::grok-4.6"]) }), []);
  assert.equal(M.pickerEmptyText([AGENTS[2]]), "Every model hidden — enable one in Settings");
  assert.equal(M.pickerEmptyText([]), "No subscriptions on this machine");
});

test("fillPicker writes optgroups, or one empty option that says why", () => {
  const select = new FakeNode("select");
  M.fillPicker(select, M.pickerGroups(AGENTS.slice(0, 1)));
  assert.equal(select.children.length, 1);
  assert.equal(select.children[0].tagName, "OPTGROUP");
  assert.equal(select.children[0].label, "Claude Code (work)");
  assert.deepEqual(select.children[0].children.map((option) => [option.value, option.textContent]), [
    ["claude::opus", "Claude Code (work) · opus"],
    ["claude::sonnet", "Claude Code (work) · sonnet"],
    ["claude::haiku", "Claude Code (work) · haiku"],
  ]);
  M.fillPicker(select, [], "No agent installed");
  assert.deepEqual(select.children.map((option) => [option.tagName, option.value, option.textContent]), [["OPTION", "", "No agent installed"]]);
});

test("Settings › Models draws a table per CLI, a tick per model, and saves the owner's choice", () => {
  const container = new FakeNode("div");
  const toggles = [];
  const catalog = M.modelCatalog([{ name: "this-pc", agents: AGENTS }]);
  M.renderModelTables(container, catalog, {
    hidden: new Set(["claude::haiku"]),
    onToggle: (key, isVisible) => toggles.push([key, isVisible]),
  });
  assert.equal(container.children.length, 3);
  const claude = container.children[0];
  assert.equal(claude.find((node) => node.className === "settings-sublabel").textContent, "Claude Code (work)");
  assert.equal(claude.find((node) => node.className === "model-group-count").textContent, "2 of 3 in the dropdown");
  const boxes = claude.findAll((node) => node.tagName === "INPUT");
  assert.deepEqual(boxes.map((box) => box.checked), [true, true, false]);  // opus, sonnet, haiku (hidden)
  boxes[2].checked = true;
  boxes[2].listeners.change();
  assert.deepEqual(toggles, [["claude::haiku", true]]);
  // Strongest first: muse-spark (48, paid and unticked, still listed), mimo (38), big-pickle (unranked).
  const priced = container.children[1].findAll((node) => node.tagName === "TD" && node.className.startsWith("num price"));
  assert.deepEqual(priced.map((cell) => cell.textContent), ["$1.25 / $4.25", "Free", "Free"]);
  assert.ok(container.children[2].find((node) => node.className === "model-new"));
});

test("Free models only leaves out the paid models nobody ticked, never a ticked one", () => {
  const container = new FakeNode("div");
  const catalog = M.modelCatalog([{ name: "this-pc", agents: AGENTS.slice(1, 2) }]);
  M.renderModelTables(container, catalog, { freeOnly: true });
  const names = container.findAll((node) => node.className === "model-name").map((node) => node.textContent);
  assert.deepEqual(names, ["openrouter/mimo-v2.6-flash-free", "openrouter/big-pickle"]);
  M.renderModelTables(container, catalog, { freeOnly: true, shown: new Set(["opencode::openrouter/meta/muse-spark-1.3"]) });
  assert.equal(container.findAll((node) => node.className === "model-name").length, 3);
  M.renderModelTables(container, [], { emptyText: "No agent CLI found." });
  assert.deepEqual(container.children.map((node) => [node.className, node.textContent]), [["settings-empty", "No agent CLI found."]]);
});

test("a CLI's version line says how far behind it is", () => {
  assert.equal(M.cliVersionText({ installed: "2.1.0", latest: "2.2.0", is_outdated: true }), "2.1.0 → 2.2.0");
  assert.equal(M.cliVersionText({ installed: "2.2.0", latest: "2.2.0", is_outdated: false }), "2.2.0 · up to date");
  assert.equal(M.cliVersionText({ installed: "2.2.0", is_outdated: null, error: "offline" }), "2.2.0 · offline");
  assert.equal(M.cliVersionText({ installed: "", is_outdated: null }), "version unknown");
});

test("a local MLX model shows its weights, costs nothing, and names the only computers that have it", () => {
  assert.equal(M.modelDisplayName("mlx-community/Qwen3-8B-4bit"), "Qwen3-8B-4bit");
  assert.equal(M.isLocalAgent({ command: "mlx", flavor: "mlx" }), true);
  assert.equal(M.isLocalAgent({ command: "claude", flavor: "claude" }), false);
  // Colibri runs OpenCode, but on this computer: Local, never an Open Router price.
  assert.equal(M.isLocalAgent({ command: "colibri", flavor: "colibri" }), true);
  assert.equal(M.isPricedAgent({ command: "colibri", flavor: "colibri" }), false);
  assert.deepEqual(M.modelPriceNote("mlx-community/Qwen3-8B-4bit", null, false, true),
    { text: "Local", title: "Runs on this computer, no token charge", isFree: true });
  const mlx = { command: "mlx", name: "Local MLX", flavor: "mlx", models: ["mlx-community/Qwen3-8B-4bit"] };
  const catalog = M.modelCatalog([{ name: "mac", agents: [mlx] }, { name: "pc", agents: [{ ...mlx, models: [] }] }]);
  assert.equal(catalog[0].isLocal, true);
  const row = catalog[0].models[0];
  assert.deepEqual(M.modelWhereNote(row, "Local MLX"), { text: "mac only", title: "Only mac has Qwen3-8B-4bit downloaded." });
  const container = new FakeNode("div");
  M.renderModelTables(container, catalog, {});
  const price = container.find((node) => node.tagName === "TD" && node.className.startsWith("num price"));
  assert.equal(price.textContent, "Local");
  assert.equal(price.className, "num price free");
});

test("a long table folds to what the picker offers; Show all opens it; a search looks through every model", () => {
  const models = Array.from({ length: 20 }, (_, index) => `gpt-tier-${String(index).padStart(2, "0")}`);
  const agents = [{ command: "agent", name: "Cursor Agent", flavor: "cursor", models, new_models: ["gpt-tier-19"] }];
  const catalog = M.modelCatalog([{ name: "pc", agents }]);
  const hidden = new Set(models.slice(2, 19).map((model) => `agent::${model}`));
  const container = new FakeNode("div");
  const names = () => container.findAll((node) => node.className === "model-name").map((node) => node.textContent);
  M.renderModelTables(container, catalog, { hidden });
  // Ticked ones (00, 01) and the new one (19, unticked) — not the 17 hidden ones.
  assert.deepEqual(names().sort(), ["gpt-tier-00", "gpt-tier-01", "gpt-tier-19"]);
  assert.equal(container.find((node) => node.className === "model-group-count").textContent, "2 of 20 in the dropdown");
  const toggle = container.find((node) => node.tagName === "BUTTON");
  assert.equal(toggle.textContent, "Show all 20");
  assert.match(toggle.className, /\bacb-btn\b/, "the shared button classes, not a host's");
  assert.equal(toggle["aria-expanded"], "false");
  toggle.listeners.click();
  assert.equal(names().length, 20);
  assert.equal(container.find((node) => node.tagName === "BUTTON").textContent, "Show fewer");
  // The open table stays open on the next draw of the same container (a tick redraws it).
  M.renderModelTables(container, catalog, { hidden });
  assert.equal(names().length, 20);
  container.find((node) => node.tagName === "BUTTON").listeners.click();
  assert.equal(names().length, 3);
  // A search unfolds and filters; no hit says so.
  M.renderModelTables(container, catalog, { hidden, query: "tier-1" });
  assert.equal(names().length, 10);
  assert.equal(container.find((node) => node.tagName === "BUTTON"), null);
  M.renderModelTables(container, catalog, { hidden, query: "nothing-like-it" });
  assert.deepEqual(container.children.map((node) => node.textContent), ["No model matches “nothing-like-it”."]);
});

test("a score sits inside its bar, or alone when the model has none", () => {
  const agents = [{ command: "claude", name: "Claude Code", flavor: "claude", models: ["opus", "mystery-model"] }];
  const container = new FakeNode("div");
  M.renderModelTables(container, M.modelCatalog([{ name: "pc", agents }]), {});
  const fills = container.findAll((node) => node.className === "model-bar-fill");
  assert.ok(fills.length >= 1);
  assert.equal(fills[0].children[0].className, "model-bar-value");
  const empty = container.findAll((node) => node.className === "model-bar-track empty");
  assert.ok(empty.every((track) => track.children[0].className === "model-bar-value" && track.children[0].textContent === "—"));
});

test("a tick moves a model between hidden and shown; opening Settings marks every new model seen", () => {
  const next = M.toggleModelSets(new Set(["a::x"]), new Set(), "a::x", true);
  assert.deepEqual([...next.hidden], []);
  assert.deepEqual([...next.shown], ["a::x"]);
  const back = M.toggleModelSets(next.hidden, next.shown, "a::x", false);
  assert.deepEqual([...back.hidden], ["a::x"]);
  assert.deepEqual([...back.shown], []);
  assert.deepEqual(M.newModelKeys([{ command: "grok", new_models: ["grok-4.7"] }, { command: "claude" }]), ["grok::grok-4.7"]);
});

test("Uninstall asks for a second click, then removes the CLI and keeps the new status", async () => {
  const calls = [];
  const updated = [];
  const toasts = [];
  let release = null;
  const api = {
    signInStatus: async () => ({ signed_in: null }),
    uninstall: async (target, command) => { calls.push(command); return { ok: true, status: { agents: [] } }; },
  };
  const cli = M.cliSettings({
    api, keyOf: () => "local", toast: (text) => toasts.push(text), onUpdated: (target, result) => updated.push(result),
    sleep: () => new Promise((resolve) => { release = resolve; }),
  });
  const row = { command: "grok", name: "Grok CLI", installed: "1.0", is_outdated: false };
  let item = cli.renderRow(fakeDocument, null, row);
  const button = item.find((node) => node.className === "cli-uninstall");
  assert.equal(button.textContent, "Uninstall");
  button.listeners.click();
  await tick();
  assert.deepEqual(calls, []);  // one click only arms it
  item = cli.renderRow(fakeDocument, null, row);
  const armed = item.find((node) => node.className === "cli-uninstall armed");
  assert.equal(armed.textContent, "Confirm uninstall");
  armed.listeners.click();
  await tick();
  assert.deepEqual(calls, ["grok"]);
  assert.deepEqual(toasts, ["Grok CLI uninstalled."]);
  assert.deepEqual(updated[0].status, { agents: [] });
  release();
  await tick();
  // Without the host's uninstall, no row offers it.
  const bare = M.cliSettings({ api: { signInStatus: async () => ({}) }, keyOf: () => "local" });
  assert.equal(bare.renderRow(fakeDocument, null, row).find((node) => node.className === "cli-uninstall"), null);
});

test("an armed Uninstall falls back after a few seconds without a second click", async () => {
  let release = null;
  const calls = [];
  const cli = M.cliSettings({
    api: { signInStatus: async () => ({}), uninstall: async (t, command) => { calls.push(command); return { ok: true }; } },
    keyOf: () => "local", sleep: () => new Promise((resolve) => { release = resolve; }),
  });
  const row = { command: "grok", name: "Grok CLI", installed: "1.0" };
  cli.renderRow(fakeDocument, null, row).find((node) => node.className === "cli-uninstall").listeners.click();
  await tick();
  release();
  await tick();
  assert.equal(cli.renderRow(fakeDocument, null, row).find((node) => node.className === "cli-uninstall").textContent, "Uninstall");
  assert.deepEqual(calls, []);
});

// Settings › Agents: the rows and the sign-in flow, against a fake host.
function fakeHost(answers = {}) {
  const calls = [];
  const statuses = [...(answers.statuses || [])];
  const api = {
    status: async () => answers.status || { agents: [] },
    update: async (target, command) => { calls.push(["update", target?.key, command]); return answers.update || { ok: true, status: { agents: [{ command, installed: "2.2.0" }] } }; },
    signInStatus: async (target, command) => { calls.push(["status", target?.key, command]); return statuses.length ? statuses.shift() : { signed_in: false, running: true }; },
    signIn: async (target, command) => { calls.push(["signIn", target?.key, command]); return answers.signIn || { url: "https://cursor.com/login", needs_code: false }; },
    signInCode: async (target, command, code) => { calls.push(["code", target?.key, command, code]); return {}; },
    signOut: async (target, command) => { calls.push(["signOut", target?.key, command]); return { signed_in: false }; },
  };
  return { api, calls };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("a CLI row shows its version, Update when behind, and asks once whether it is signed in", async () => {
  const { api, calls } = fakeHost({ statuses: [{ signed_in: true }] });
  let changes = 0;
  const toasts = [];
  const cli = M.cliSettings({ api, keyOf: (machine) => machine.key, whereOf: (machine) => machine.name, onChange: () => { changes += 1; }, toast: (text) => toasts.push(text) });
  const machine = { key: "hub::mac", name: "mac" };
  const row = { command: "agent", name: "Cursor Agent", installed: "2.1.0", latest: "2.2.0", is_outdated: true };
  let item = cli.renderRow(fakeDocument, machine, row);
  assert.equal(item.className, "cli-row outdated");
  assert.equal(item.find((node) => node.className === "cli-version").textContent, "2.1.0 → 2.2.0");
  const update = item.find((node) => node.textContent === "Update");
  assert.equal(update.title, "Update Cursor Agent on mac to 2.2.0");
  assert.ok(item.find((node) => node.textContent === "…"));  // asking the CLI
  await tick();
  assert.deepEqual(calls, [["status", "hub::mac", "agent"]]);
  item = cli.renderRow(fakeDocument, machine, row);
  assert.ok(item.find((node) => node.className === "cli-signed-in"));
  update.listeners.click();
  await tick();
  assert.deepEqual(calls.at(-1), ["update", "hub::mac", "agent"]);
  assert.deepEqual(toasts, ["Cursor Agent updated to 2.2.0 on mac."]);
  assert.ok(changes >= 3);
  // A CLI that cannot sign in from a page (Gemini) gets no control.
  const gemini = cli.renderRow(fakeDocument, machine, { command: "gemini", name: "Gemini CLI", installed: "1.0", is_outdated: false });
  assert.equal(gemini.find((node) => node.textContent === "Sign in"), null);
});

test("signing in opens the link, waits for the CLI, and asks for Claude's code", async () => {
  const { api, calls } = fakeHost({
    signIn: { url: "https://claude.ai/oauth", needs_code: false },
    statuses: [{ signed_in: false }, { signed_in: false, running: true }, { signed_in: true }],
  });
  const tab = { closed: false, location: {}, close() { this.closed = true; } };
  const toasts = [];
  let release = null;
  const cli = M.cliSettings({
    api, keyOf: () => "local", toast: (text) => toasts.push(text),
    openWindow: () => tab,
    sleep: () => new Promise((resolve) => { release = resolve; }),
  });
  const row = { command: "claude", name: "Claude Code", installed: "2.1.0", is_outdated: false };
  cli.renderRow(fakeDocument, null, row);
  await tick();
  const signing = cli.signIn(null, row);
  await tick();
  assert.equal(tab.location.href, "https://claude.ai/oauth");
  assert.equal(tab.opener, null);
  // Claude's page shows a code: the field is offered without waiting for the host to say so.
  const item = cli.renderRow(fakeDocument, null, row);
  const form = item.find((node) => node.className === "cli-login-code");
  assert.ok(form);
  assert.equal(form.find((node) => node.tagName === "INPUT").placeholder, "Paste the code from the sign-in page");
  form.find((node) => node.tagName === "INPUT").value = " abc#123 ";
  form.listeners.submit({ preventDefault() {} });
  await tick();
  assert.deepEqual(calls.at(-1), ["code", undefined, "claude", "abc#123"]);
  while (release) {
    const next = release;
    release = null;
    next();
    await tick();
  }
  await signing;
  assert.deepEqual(calls.filter(([kind]) => kind === "signIn"), [["signIn", undefined, "claude"]]);
  assert.equal(cli.loginOf(null, "claude").isBusy, undefined);
  assert.ok(toasts.includes("Claude Code is signed in — send your message again."));
  assert.ok(cli.renderRow(fakeDocument, null, row).find((node) => node.className === "cli-signed-in"));
});

test("a sign-in that ends without logging in, or fails to start, says why", async () => {
  const { api } = fakeHost({ statuses: [{ signed_in: false, running: false, output: "cancelled" }] });
  const cli = M.cliSettings({ api, openWindow: () => null, sleep: async () => {} });
  const row = { command: "grok", name: "Grok CLI" };
  await cli.signIn(null, row);
  assert.deepEqual(cli.loginOf(null, "grok"), { ok: false, note: "The sign-in ended without logging in. cancelled" });
  const failing = M.cliSettings({ api: { ...api, signIn: async () => { throw new Error("no binary"); } }, openWindow: () => null });
  await failing.signIn(null, row);
  assert.deepEqual(failing.loginOf(null, "grok"), { ok: false, note: "no binary" });
});

test("Check again forgets one computer's sign-ins only", async () => {
  const { api, calls } = fakeHost();
  const cli = M.cliSettings({ api, keyOf: (machine) => machine.key });
  const row = { command: "agent", name: "Cursor Agent" };
  cli.renderRow(fakeDocument, { key: "a" }, row);
  cli.renderRow(fakeDocument, { key: "b" }, row);
  await tick();
  cli.forget({ key: "a" });
  cli.renderRow(fakeDocument, { key: "a" }, row);
  cli.renderRow(fakeDocument, { key: "b" }, row);
  await tick();
  assert.deepEqual(calls.map(([, key]) => key), ["a", "b", "a"]);
  cli.setSignedIn({ key: "b" }, "agent", true);
  assert.ok(cli.renderRow(fakeDocument, { key: "b" }, row).find((node) => node.className === "cli-signed-in"));
});

// ── The rules as D3SKHAND tested them before it took them from here (its hubs are machines) ──
{
  const { isModelInPicker, newModelsNote } = M;

  test("a new model stays out of the picker until ticked; a curated one until hidden", () => {
    const key = "grok::grok-4.7";
    assert.equal(isModelInPicker({ isNew: true, key }), false);
    assert.equal(isModelInPicker({ isNew: true, key, shown: new Set([key]) }), true);
    assert.equal(isModelInPicker({ isNew: false, key }), true);
    assert.equal(isModelInPicker({ isNew: false, key, hidden: new Set([key]) }), false);
  });

  test("the chat foot announces new models once, until they were seen", () => {
    const agents = [
      { command: "grok", name: "Grok CLI", models: ["grok-4.6", "grok-4.7"], new_models: ["grok-4.7"] },
      { command: "agy", name: "Google Antigravity", models: ["default", "gemini-3.8-flash-high"], new_models: ["gemini-3.8-flash-high"] },
      { command: "claude", name: "Claude Code", models: ["sonnet"] },
    ];
    const note = newModelsNote(agents);
    assert.equal(note.text, "2 new models available");
    assert.deepEqual(note.detail, ["New: Grok CLI · grok-4.7", "New: Google Antigravity · gemini-3.8-flash-high"]);
    assert.equal(newModelsNote(agents, new Set(["grok::grok-4.7"])).text, "New model: gemini-3.8-flash-high");
    assert.equal(newModelsNote(agents, new Set(note.keys)), null);
    assert.equal(newModelsNote([]), null);
  });

  test("Settings names the hubs that list a model the others do not — ticking it there changes nothing here", () => {
    const { modelCatalog, modelWhereNote } = M;
    const machines = [
      { name: "WORK-MAC", hub: null, agents: [
        { command: "claude", name: "Claude Code", models: ["sonnet", "fable", "opus", "haiku"], new_models: [] },
        { command: "grok", name: "Grok CLI", models: ["grok-4.6", "grok-4.7"], new_models: ["grok-4.7"] },
      ] },
      { name: "my-mac", hub: "h1", agents: [
        { command: "claude", name: "Claude Code", models: ["sonnet", "fable", "opus", "claude-opus-5-5", "haiku"], new_models: [] },
      ] },
    ];
    const catalog = modelCatalog(machines, (machine) => (machine.hub ? "OFFICE-PC" : "WORK-MAC"));
    assert.deepEqual(catalog.map((group) => group.command), ["claude", "grok"]);
    const claude = catalog[0].models;
    // First-seen order across hubs: a model another hub adds comes after this hub's own.
    assert.deepEqual(claude.map((row) => row.model), ["sonnet", "fable", "opus", "haiku", "claude-opus-5-5"]);
    const opus55 = claude.find((row) => row.model === "claude-opus-5-5");
    assert.equal(opus55.key, "claude::claude-opus-5-5");
    assert.deepEqual(opus55.offeredBy, ["OFFICE-PC"]);
    assert.deepEqual(opus55.onlyOn, ["OFFICE-PC"]);
    assert.deepEqual(claude.find((row) => row.model === "fable").onlyOn, []);
    // A CLI on one hub only is not "only on" it: every hub that has it lists the model.
    assert.deepEqual(catalog[1].models.map((row) => [row.model, row.isNew, row.onlyOn]), [["grok-4.6", false, []], ["grok-4.7", true, []]]);
    const note = modelWhereNote(opus55, "Claude Code");
    assert.equal(note.text, "OFFICE-PC only");
    assert.match(note.title, /Only OFFICE-PC lists claude-opus-5-5 for Claude Code/);
    assert.match(note.title, /models\.claude in that machine's agent_cli_bridge\.json/);
    assert.equal(modelWhereNote(claude[0], "Claude Code"), null);
    assert.deepEqual(modelCatalog([]), []);
  });

  test("the OpenCode CLI is labeled Open Router in Settings, even if a node still says OpenCode", () => {
    const { agentDisplayName, modelDisplayName, modelCatalog, newModelsNote } = M;
    assert.equal(agentDisplayName({ command: "opencode", name: "OpenCode" }), "Open Router");
    assert.equal(agentDisplayName({ command: "claude", name: "Claude Code" }), "Claude Code");
    assert.equal(agentDisplayName({ command: "claude", name: "Claude Code", account: { kind: "personal" } }), "Claude Code (personal)");
    assert.equal(agentDisplayName({ command: "claude", name: "Claude Code", account: { kind: "work" } }), "Claude Code (work)");
    assert.equal(agentDisplayName({ command: "claude", name: "Claude Code", account: { kind: "other" } }), "Claude Code");
    assert.equal(modelDisplayName("opencode/big-pickle"), "openrouter/big-pickle");
    assert.equal(modelDisplayName("openrouter/stealth/union-alpha"), "openrouter/stealth/union-alpha");
    assert.equal(modelDisplayName("opus"), "opus");
    assert.equal(modelDisplayName("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"), "Qwen2.5-Coder-32B-Instruct-4bit");
    assert.equal(modelDisplayName(""), "");
    const catalog = modelCatalog([{
      name: "mac",
      agents: [{ command: "opencode", name: "OpenCode", models: ["openrouter/stealth/union-alpha", "opencode/big-pickle"] }],
    }]);
    assert.equal(catalog[0].name, "Open Router");
    assert.equal(catalog[0].command, "opencode");
    assert.equal(catalog[0].models[1].model, "opencode/big-pickle");  // the id sent to the CLI stays
    assert.equal(modelDisplayName(catalog[0].models[1].model), "openrouter/big-pickle");
    const note = newModelsNote([{ command: "opencode", name: "OpenCode", new_models: ["opencode/ling-3.0-flash-fin-free"] }]);
    assert.deepEqual(note.detail, ["New: Open Router · openrouter/ling-3.0-flash-fin-free"]);
    assert.equal(note.text, "New model: openrouter/ling-3.0-flash-fin-free");
  });

  test("Settings ranks each CLI's models by Artificial Analysis intelligence, then speed", () => {
    const {
      modelMetrics, formatModelIntelligence, formatModelSpeed, sortModelsByIntelligence,
    } = M;
    const ranked = (id) => modelMetrics(id);
    assert.equal(ranked("claude-opus-5-5").kind, "ranked");
    assert.equal(ranked("claude-opus-5-5").intelligence, 54); // alias with no effort → high
    assert.equal(ranked("fable").intelligence, 51);
    assert.equal(ranked("sonnet").intelligence, 47); // claude-sonnet-5-5 high
    assert.equal(ranked("haiku").intelligence, 38); // claude-haiku-5-5 high
    assert.equal(ranked("auto").kind, "picker");
    assert.equal(ranked("default").kind, "picker");
    assert.equal(ranked("composer-2.5").kind, "unknown");
    assert.equal(ranked("cursor-grok-4.6-high").intelligence, 44);
    assert.equal(ranked("cursor-grok-4.6-high").speed, 66);
    assert.equal(ranked("gemini-3.8-flash-high").intelligence, 41);
    assert.equal(ranked("gemini-3.8-flash-low").intelligence, 33);
    assert.equal(ranked("gpt-5.6-sol-high").intelligence, 47);
    assert.equal(formatModelIntelligence(ranked("claude-opus-5-5")), "54");
    assert.equal(formatModelSpeed(ranked("claude-opus-5-5")), "82 t/s");
    assert.equal(formatModelIntelligence(ranked("auto")), "—");
    assert.equal(formatModelSpeed(ranked("composer-2.5")), "—");
    const order = sortModelsByIntelligence([
      { model: "haiku" },
      { model: "sonnet" },
      { model: "opus" },
      { model: "fable" },
      { model: "claude-opus-5-5" },
    ]).map((row) => row.model);
    // Latest opus alias and the pinned 5.5 id share the high row; name breaks the tie.
    assert.deepEqual(order, ["claude-opus-5-5", "opus", "fable", "sonnet", "haiku"]);
    const agy = sortModelsByIntelligence([
      { model: "default" },
      { model: "gemini-3.8-flash-low" },
      { model: "gemini-3.8-flash-high" },
      { model: "gemini-3.7-flash-high" },
      { model: "gemini-3.7-flash-medium" },
    ]).map((row) => row.model);
    // auto/default stay first; 3.7 medium (40) outranks 3.7 high (39) on the Index.
    assert.deepEqual(agy, [
      "default",
      "gemini-3.8-flash-high",
      "gemini-3.7-flash-medium",
      "gemini-3.7-flash-high",
      "gemini-3.8-flash-low",
    ]);
    const cursor = sortModelsByIntelligence([
      { model: "composer-2.5" },
      { model: "auto" },
      { model: "gpt-5.6-sol-high" },
      { model: "cursor-grok-4.6-high" },
    ]).map((row) => row.model);
    assert.deepEqual(cursor, ["auto", "gpt-5.6-sol-high", "cursor-grok-4.6-high", "composer-2.5"]);
  });

  test("Open Router free ids rank by the same Index, and limited marks a promo endpoint", () => {
    const {
      modelMetrics, formatModelIntelligence, formatModelSpeed, sortModelsByIntelligence,
      isLimitedFreeModel, modelLimitedNote, isPreviewModel, modelPreviewNote, modelIndexNote,
    } = M;
    assert.equal(modelMetrics("openrouter/meta/muse-spark-1.3-contributor-free").intelligence, 48);
    assert.equal(modelMetrics("openrouter/mimo-v2.6-flash-free").intelligence, 38);
    assert.equal(modelMetrics("openrouter/thinkingmachines/inkling-small:free").intelligence, 28);
    assert.equal(modelMetrics("openrouter/thinkingmachines/inkling:free").intelligence, 25);
    assert.equal(modelMetrics("openrouter/inclusionai/ling-3.0-flash-sante:free").intelligence, 25);
    assert.equal(modelMetrics("openrouter/nvidia/nemotron-3-ultra-550b-a55b:free").intelligence, 23);
    assert.equal(modelMetrics("openrouter/inclusionai/ling-3.0-flash-fin:free").intelligence, 23);
    assert.equal(modelMetrics("opencode/ling-3.0-flash-fin-free").intelligence, 23);
    assert.equal(modelMetrics("openrouter/qwen/qwen3.8-27b:free").intelligence, 20);
    assert.equal(modelMetrics("openrouter/google/gemma-4-31b-it:free").intelligence, 19);
    assert.equal(modelMetrics("openrouter/google/gemma-4-26b-a4b-it:free").intelligence, 17);
    assert.equal(modelMetrics("openrouter/nvidia/nemotron-3.5-lightning:free").intelligence, 13);
    assert.equal(modelMetrics("openrouter/nvidia/nemotron-3-super-120b-a12b:free").intelligence, 13);
    assert.equal(modelMetrics("openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free").intelligence, 10);
    assert.equal(modelMetrics("openrouter/cohere/north-mini-code:free").intelligence, 10);
    assert.equal(modelMetrics("openrouter/liquid/lfm-2.5-2.6b:free").intelligence, 8);
    assert.equal(modelMetrics("opencode/big-pickle").kind, "unknown");
    assert.equal(modelMetrics("openrouter/stealth/space-bunny-alpha").kind, "unknown");
    assert.equal(formatModelSpeed(modelMetrics("openrouter/mimo-v2.6-flash-free")), "59 t/s");
    assert.equal(formatModelIntelligence(modelMetrics("opencode/big-pickle")), "—");
    const order = sortModelsByIntelligence([
      { model: "openrouter/liquid/lfm-2.5-2.6b:free" },
      { model: "opencode/big-pickle" },
      { model: "openrouter/thinkingmachines/inkling-small:free" },
      { model: "openrouter/stealth/union-alpha" },
      { model: "openrouter/meta/muse-spark-1.3-contributor-free" },
    ]).map((row) => row.model);
    assert.deepEqual(order, [
      "openrouter/meta/muse-spark-1.3-contributor-free",
      "openrouter/thinkingmachines/inkling-small:free",
      "openrouter/liquid/lfm-2.5-2.6b:free",
      "opencode/big-pickle",
      "openrouter/stealth/union-alpha",
    ]);
    assert.equal(isLimitedFreeModel("openrouter/google/gemma-4-31b-it:free"), true);
    assert.equal(isLimitedFreeModel("opencode/ling-3.0-flash-fin-free"), true);
    assert.equal(isLimitedFreeModel("openrouter/stealth/space-bunny-alpha"), true);
    assert.equal(isLimitedFreeModel("opencode/big-pickle"), false);
    assert.equal(isLimitedFreeModel("claude-opus-5-5"), false);
    assert.equal(modelLimitedNote("openrouter/qwen/qwen3.8-27b:free").text, "limited");
    assert.equal(modelLimitedNote("opencode/big-pickle"), null);
    assert.equal(isPreviewModel("openrouter/longcat-2.5-preview-free"), true);
    assert.equal(isPreviewModel("openrouter/dots-studio/dots-3-note-preview:free"), true);
    assert.equal(isPreviewModel("openrouter/stealth/space-bunny-alpha"), true);
    assert.equal(isPreviewModel("opencode/space-bunny-free"), true);
    assert.equal(isPreviewModel("opencode/big-pickle"), false);
    assert.equal(isPreviewModel("openrouter/mimo-v2.6-flash-free"), false);
    assert.equal(modelPreviewNote("openrouter/longcat-2.5-preview-free").text, "preview");
    assert.equal(modelPreviewNote("opencode/big-pickle"), null);
    // graduated = on the Intelligence Index for a while. Open Router only; previews and Zen don't wear it.
    assert.equal(modelIndexNote("openrouter/muse-spark-1.3-contributor-free").text, "graduated");
    assert.equal(modelIndexNote("opencode/mimo-v2.6-flash-free").text, "graduated");
    assert.equal(modelIndexNote("openrouter/google/gemma-4-31b-it:free").text, "graduated");
    assert.equal(modelIndexNote("opencode/big-pickle"), null);
    assert.equal(modelIndexNote("openrouter/longcat-2.5-preview-free"), null);
    assert.equal(modelIndexNote("openrouter/stealth/space-bunny-alpha"), null);
    assert.equal(modelIndexNote("claude-opus-5-5"), null);
    // A preview unknown sorts after Zen (graduated enough to keep, not a lab preview).
    assert.deepEqual(
      sortModelsByIntelligence([
        { model: "openrouter/aaa-preview-free" },
        { model: "opencode/big-pickle" },
      ]).map((row) => row.model),
      ["opencode/big-pickle", "openrouter/aaa-preview-free"],
    );
    // The live Open Router table (ids as Settings shows them): strongest first, then unknowns;
    // every promo row is limited, Zen big-pickle is not.
    const live = sortModelsByIntelligence([
      { model: "opencode/big-pickle" },
      { model: "opencode/ling-3.0-flash-fin-free" },
      { model: "opencode/longcat-2.5-preview-free" },
      { model: "opencode/mimo-v2.6-flash-free" },
      { model: "opencode/muse-spark-1.3-contributor-free" },
      { model: "openrouter/google/gemma-4-31b-it:free" },
      { model: "openrouter/liquid/lfm-2.5-2.6b:free" },
      { model: "openrouter/stealth/space-bunny-alpha" },
      { model: "openrouter/thinkingmachines/inkling-small:free" },
    ]).map((row) => row.model);
    assert.deepEqual(live, [
      "opencode/muse-spark-1.3-contributor-free",
      "opencode/mimo-v2.6-flash-free",
      "openrouter/thinkingmachines/inkling-small:free",
      "opencode/ling-3.0-flash-fin-free",
      "openrouter/google/gemma-4-31b-it:free",
      "openrouter/liquid/lfm-2.5-2.6b:free",
      "opencode/big-pickle",
      "opencode/longcat-2.5-preview-free",
      "openrouter/stealth/space-bunny-alpha",
    ]);
    // The live Open Router Settings table (ids as the owner's screenshot listed them):
    // strongest graduated first, unknowns (Zen, unlisted) next, previews last.
    const desk = sortModelsByIntelligence([
      { model: "opencode/big-pickle" },
      { model: "opencode/ling-3.0-flash-fin-free" },
      { model: "opencode/longcat-2.5-preview-free" },
      { model: "opencode/mimo-v2.6-flash-free" },
      { model: "opencode/muse-spark-1.3-contributor-free" },
      { model: "opencode/nemotron-3-ultra-free" },
      { model: "opencode/nemotron-3.5-lightning-free" },
      { model: "opencode/space-bunny-free" },
      { model: "openrouter/cohere/north-mini-code:free" },
      { model: "openrouter/dots-studio/dots-3-note-preview:free" },
      { model: "openrouter/google/gemma-4-26b-a4b-it:free" },
      { model: "openrouter/google/gemma-4-31b-it:free" },
      { model: "openrouter/inclusionai/ling-3.0-flash-fin:free" },
      { model: "openrouter/inclusionai/ling-3.0-flash-sante:free" },
      { model: "openrouter/liquid/lfm-2.5-2.6b:free" },
      { model: "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free" },
      { model: "openrouter/nvidia/nemotron-3-super-120b-a12b:free" },
      { model: "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free" },
      { model: "openrouter/nvidia/nemotron-3.5-content-safety:free" },
      { model: "openrouter/nvidia/nemotron-3.5-lightning:free" },
      { model: "openrouter/poolside/laguna-s-2.1:free" },
      { model: "openrouter/poolside/laguna-xs-2.1:free" },
      { model: "openrouter/qwen/qwen3.8-27b:free" },
      { model: "openrouter/stealth/space-bunny-alpha" },
      { model: "openrouter/thinkingmachines/inkling-small:free" },
      { model: "openrouter/thinkingmachines/inkling:free" },
    ]).map((row) => row.model);
    assert.deepEqual(desk, [
      "opencode/muse-spark-1.3-contributor-free",
      "opencode/mimo-v2.6-flash-free",
      "openrouter/thinkingmachines/inkling-small:free",
      "openrouter/inclusionai/ling-3.0-flash-sante:free",
      "openrouter/thinkingmachines/inkling:free",
      "opencode/nemotron-3-ultra-free",
      "openrouter/nvidia/nemotron-3-ultra-550b-a55b:free",
      "opencode/ling-3.0-flash-fin-free",
      "openrouter/inclusionai/ling-3.0-flash-fin:free",
      "openrouter/qwen/qwen3.8-27b:free",
      "openrouter/google/gemma-4-31b-it:free",
      "openrouter/google/gemma-4-26b-a4b-it:free",
      "opencode/nemotron-3.5-lightning-free",
      "openrouter/nvidia/nemotron-3.5-lightning:free",
      "openrouter/nvidia/nemotron-3-super-120b-a12b:free",
      "openrouter/nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
      "openrouter/cohere/north-mini-code:free",
      "openrouter/liquid/lfm-2.5-2.6b:free",
      "opencode/big-pickle",
      "openrouter/nvidia/nemotron-3.5-content-safety:free",
      "openrouter/poolside/laguna-s-2.1:free",
      "openrouter/poolside/laguna-xs-2.1:free",
      "opencode/longcat-2.5-preview-free",
      "opencode/space-bunny-free",
      "openrouter/dots-studio/dots-3-note-preview:free",
      "openrouter/stealth/space-bunny-alpha",
    ]);
    assert.equal(modelIndexNote("opencode/muse-spark-1.3-contributor-free").text, "graduated");
    assert.equal(modelIndexNote("opencode/space-bunny-free"), null);
    assert.equal(isPreviewModel("opencode/space-bunny-free"), true);
  });

  // ── composer box height (drag the top edge; CSS max-height uses the same numbers) ──
  test("a signed-out CLI's error offers to sign that CLI in, and nothing else does", () => {
    const { signInCommandFor, signInTextFrom } = M;
    const error = "Error: Authentication required. Please run 'agent login' first, or set CURSOR_API_KEY environment variable.";
    assert.equal(signInCommandFor(error, "cursor-agent", ["claude", "cursor-agent"]), "cursor-agent");
    assert.equal(signInCommandFor(error, "agent", ["agent"]), "agent");
    // A live error carries no agent: the machine's Cursor CLI is the one.
    assert.equal(signInCommandFor(error, undefined, ["claude", "agent"]), "agent");
    assert.equal(signInCommandFor(error, "cursor-agent", ["claude"]), "cursor-agent");  // the reply named Cursor
    assert.equal(signInCommandFor("rate limited", "cursor-agent", ["cursor-agent"]), "");
    assert.equal(signInCommandFor("", "cursor-agent", ["cursor-agent"]), "");
    const oauth = "Failed to authenticate: OAuth session expired and could not be refreshed";
    assert.equal(signInCommandFor(oauth, "claude", ["claude", "cursor-agent"]), "claude");
    assert.equal(signInCommandFor("Login expired · Please run /login", "claude", ["claude"]), "claude");
    assert.equal(signInCommandFor(oauth, "claude", ["cursor-agent"]), "claude");  // the reply named Claude
    assert.equal(signInCommandFor(oauth, "claude", []), "claude");  // agents not loaded yet
    // A long reply that merely quotes the phrase is not a sign-in error.
    assert.equal(signInCommandFor(`${oauth}\n\n${"x".repeat(500)}`, "claude", ["claude"]), "");
    assert.equal(signInCommandFor("You are not authenticated. Run `grok login`.", "grok", ["grok", "claude"]), "grok");
    assert.equal(signInCommandFor("No auth credentials found", "opencode", ["opencode"]), "opencode");
    assert.equal(signInCommandFor("rate limited", "grok", ["grok"]), "");
    assert.equal(signInTextFrom({ content: oauth }), oauth);
    assert.equal(signInTextFrom({
      content: "",
      parts: [{ type: "text", text: oauth }],
    }), oauth);
    assert.equal(signInTextFrom({ parts: [{ type: "thinking", text: "x" }] }), "");
  });

  test("Settings offers Sign in for Grok and Open Router even if can_sign_in is missing", () => {
    const { canSignInCommand, shouldOfferSignIn } = M;
    assert.equal(canSignInCommand("grok"), true);
    assert.equal(canSignInCommand("opencode"), true);
    assert.equal(canSignInCommand("claude"), true);
    assert.equal(canSignInCommand("agent"), true);
    assert.equal(canSignInCommand("copilot"), true);
    assert.equal(M.signInCommandFor("Error: No authentication information found.", "copilot", ["copilot"]), "copilot");
    assert.equal(M.signInNeedsCode("copilot"), false);  // GitHub's device page finishes it
    assert.equal(canSignInCommand("agy"), false);
    assert.equal(canSignInCommand("gemini"), false);
    // A 10-minute cli-status cache from before those CLIs could sign in omits the flag
    // or still has can_sign_in: false — still offer Sign in / Signed in.
    assert.equal(shouldOfferSignIn({ command: "grok" }), true);
    assert.equal(shouldOfferSignIn({ command: "opencode" }), true);
    assert.equal(shouldOfferSignIn({ command: "agy" }), false);
    assert.equal(shouldOfferSignIn({ command: "agy", can_sign_in: false }), false);
    assert.equal(shouldOfferSignIn({ command: "agy", can_sign_in: true }), true);
    assert.equal(shouldOfferSignIn({ command: "grok", can_sign_in: false }), true);
    assert.equal(shouldOfferSignIn({ command: "opencode", can_sign_in: false }), true);
    assert.equal(shouldOfferSignIn({ command: "grok", can_sign_in: true }), true);
  });

  test("Claude's waiting sign-in always offers the code field, even without needs_code", () => {
    const { signInNeedsCode, shouldOfferSignInCode, signInPastePrompt } = M;
    assert.equal(signInNeedsCode("claude"), true);
    assert.equal(signInNeedsCode("opencode"), true);
    assert.equal(signInNeedsCode("cursor-agent"), false);
    assert.equal(signInNeedsCode("agent"), false);
    assert.equal(signInNeedsCode("grok"), false);
    assert.equal(signInPastePrompt("opencode"), "Paste your OpenRouter API key");
    assert.equal(signInPastePrompt("claude"), "Paste the code from the sign-in page");
    // The live Settings screenshot: Claude is waiting, the node omitted needs_code, no paste field.
    assert.equal(shouldOfferSignInCode("claude", { isBusy: true }), true);
    assert.equal(shouldOfferSignInCode("claude", { isBusy: true, needs_code: true }), true);
    assert.equal(shouldOfferSignInCode("claude", { isBusy: false }), false);
    assert.equal(shouldOfferSignInCode("claude", { isBusy: true, ok: true }), false);
    assert.equal(shouldOfferSignInCode("opencode", { isBusy: true }), true);
    assert.equal(shouldOfferSignInCode("cursor-agent", { isBusy: true }), false);
    assert.equal(shouldOfferSignInCode("cursor-agent", { isBusy: true, needs_code: true }), true);
    assert.equal(shouldOfferSignInCode("grok", { isBusy: true }), false);
  });

  test("Open Router models carry their price, paid ones stay out of the picker until ticked", () => {
    const { isModelInPicker, modelCatalog, modelPriceNote, isFreeModel, isPricedAgent } = M;
    const key = "opencode::openrouter/meta/muse-spark-1.3";
    assert.equal(isModelInPicker({ isOptional: true, key }), false);
    assert.equal(isModelInPicker({ isOptional: true, key, shown: new Set([key]) }), true);

    assert.deepEqual(modelPriceNote("openrouter/meta/muse-spark-1.3", [1.25, 4.25]).text, "$1.25 / $4.25");
    assert.equal(modelPriceNote("openrouter/meta/muse-spark-1.3-contributor", [0.1, 0.2]).text, "$0.1 / $0.2");
    assert.equal(modelPriceNote("openrouter/qwen/qwen3.8-27b:free", [0, 0]).isFree, true);
    assert.equal(modelPriceNote("opencode/big-pickle", [0, 0]).text, "Free");
    assert.equal(modelPriceNote("opencode/some-zen-pro", [2, 8]).isFree, false);
    // A router reports 0: it bills whatever model it picks — not free.
    assert.equal(isFreeModel("openrouter/openrouter/auto", [0, 0]), false);
    assert.equal(modelPriceNote("openrouter/openrouter/auto", [0, 0]).text, "—");
    const { modelMetrics } = M;
    assert.notEqual(modelMetrics("openrouter/openrouter/auto").kind, "picker");  // sorts with the others
    assert.equal(modelMetrics("auto").kind, "picker");
    assert.equal(modelPriceNote("opus", null, false).text, "Plan");
    assert.equal(modelPriceNote("mlx-community/Qwen2.5-Coder-32B-Instruct-4bit", null, false, true).text, "Local");
    assert.equal(isPricedAgent({ flavor: "opencode" }), true);
    assert.equal(isPricedAgent({ flavor: "claude" }), false);
    assert.equal(isPricedAgent({ flavor: "mlx" }), false);

    const catalog = modelCatalog([{ name: "mac", agents: [{
      command: "opencode", flavor: "opencode",
      models: ["opencode/big-pickle", "openrouter/meta/muse-spark-1.3"],
      optional_models: ["openrouter/meta/muse-spark-1.3"],
      prices: { "opencode/big-pickle": [0, 0], "openrouter/meta/muse-spark-1.3": [1.25, 4.25] },
    }, { command: "claude", flavor: "claude", models: ["opus"] }] }]);
    assert.equal(catalog[0].isPriced, true);
    assert.equal(catalog[1].isPriced, false);
    assert.deepEqual(catalog[0].models.map((row) => [row.model, row.isOptional, row.price]), [
      ["opencode/big-pickle", false, [0, 0]],
      ["openrouter/meta/muse-spark-1.3", true, [1.25, 4.25]],
    ]);
  });

  test("Settings draws intelligence and speed as bars scaled on the largest figure", () => {
    const { modelBarPercent } = M;
    assert.equal(modelBarPercent(54, 54), 100);
    assert.equal(modelBarPercent(27, 54), 50);
    assert.equal(modelBarPercent(200, 100), 100);
    assert.equal(modelBarPercent(undefined, 54), null);
    assert.equal(modelBarPercent(10, 0), null);
  });
}

test("Effort is offered only for a CLI that takes it, Ultracode only on Claude models that have it", () => {
  assert.deepEqual(M.effortChoices("claude").map(([value]) => value), ["auto", "low", "medium", "high", "xhigh", "max"]);
  assert.deepEqual(M.effortChoices("copilot"), [["auto", "Auto"], ["low", "Low"], ["medium", "Medium"], ["high", "High"]]);
  assert.deepEqual(M.effortChoices("gemini"), []);
  assert.deepEqual(M.effortChoices(""), []);
  assert.equal(M.canUltracode("claude", "opus"), true);
  assert.equal(M.canUltracode("claude", ""), true);
  assert.equal(M.canUltracode("claude", "claude-haiku-4-5-20251001"), false);
  assert.equal(M.canUltracode("copilot", "claude-opus-5-5"), false);
});

test("each Claude model offers the effort levels Claude Code gives it, and its recommended one", () => {
  const all = ["low", "medium", "high", "xhigh", "max"];
  assert.deepEqual(M.effortProfile("claude", "claude-opus-5-5"), { levels: all, recommended: "medium" });
  assert.deepEqual(M.effortProfile("claude", "opus"), { levels: all, recommended: "medium" });
  assert.deepEqual(M.effortProfile("claude", "claude-opus-4-7"), { levels: all, recommended: "xhigh" });
  assert.deepEqual(M.effortProfile("claude", "claude-opus-4-6"), { levels: ["low", "medium", "high", "max"], recommended: "high" });
  assert.deepEqual(M.effortProfile("claude", "claude-opus-4-5-20251101"), { levels: ["low", "medium", "high"], recommended: "high" });
  assert.deepEqual(M.effortProfile("claude", "us.anthropic.claude-sonnet-4-6"), { levels: ["low", "medium", "high", "max"], recommended: "high" });
  // Bedrock and Vertex spell the same models with a version or an @date.
  assert.deepEqual(M.effortProfile("claude", "us.anthropic.claude-opus-4-6-v1"), { levels: ["low", "medium", "high", "max"], recommended: "high" });
  assert.equal(M.effortProfile("claude", "us.anthropic.claude-sonnet-4-5-20250929-v1:0"), null);
  assert.equal(M.effortProfile("claude", "claude-opus-4-1@20250805"), null);
  // Older than effort: none.
  for (const model of ["claude-haiku-4-5-20251001", "claude-sonnet-4-5", "claude-opus-4-1", "claude-3-7-sonnet", "claude-mythos-5"]) {
    assert.equal(M.effortProfile("claude", model), null, model);
  }
  // Newer than the table: every level, no recommended one known (Auto stays a step).
  assert.deepEqual(M.effortProfile("claude", "claude-opus-6"), { levels: all, recommended: null });
  assert.deepEqual(M.effortProfile("copilot", "gpt-5.5"), { levels: ["low", "medium", "high"], recommended: null });
  assert.equal(M.effortProfile("gemini", "gemini-3-pro"), null);
  assert.equal(M.effortProfile("grok", "grok-4.7"), null);
});

test("an effort a model lacks runs as the strongest level below it", () => {
  const opus45 = M.effortProfile("claude", "claude-opus-4-5");
  const opus46 = M.effortProfile("claude", "claude-opus-4-6");
  assert.equal(M.clampEffort(opus45, "max"), "high");
  assert.equal(M.clampEffort(opus46, "xhigh"), "high");
  assert.equal(M.clampEffort(opus46, "max"), "max");
  assert.equal(M.clampEffort(opus46, "auto"), "auto");
  assert.equal(M.clampEffort(null, "high"), "auto");
  assert.equal(M.clampEffort(opus45, "nonsense"), "low");
});

test("Install lists the missing CLIs, installs one and keeps the new status", async () => {
  const calls = [];
  const updated = [];
  const toasts = [];
  const api = {
    signInStatus: async () => ({ signed_in: null }),
    install: async (target, command) => { calls.push(command); return { ok: true, status: { agents: [], missing: [] } }; },
  };
  const cli = M.cliSettings({ api, keyOf: () => "local", toast: (text) => toasts.push(text), onUpdated: (target, result) => updated.push(result) });
  const status = { agents: [], missing: [{ command: "gemini", name: "Gemini CLI" }] };
  const list = cli.renderMissingList(fakeDocument, null, status);
  const button = list.find((node) => node.textContent === "Install");
  assert.ok(button);
  button.listeners.click();
  await tick();
  assert.deepEqual(calls, ["gemini"]);
  assert.deepEqual(toasts, ["Gemini CLI installed — sign in to use it."]);
  assert.deepEqual(updated[0].status, { agents: [], missing: [] });
  // Without the host's install, or with nothing missing, there is no list.
  const bare = M.cliSettings({ api: { signInStatus: async () => ({}) }, keyOf: () => "local" });
  assert.equal(bare.renderMissingList(fakeDocument, null, status), null);
  assert.equal(cli.renderMissingList(fakeDocument, null, { agents: [] }), null);
});

test("A turned-off CLI that is installed offers Turn on", async () => {
  const calls = [];
  const toasts = [];
  const api = {
    signInStatus: async () => ({ signed_in: null }),
    install: async (target, command) => { calls.push(command); return { ok: true, how: "turned on", status: { agents: [], missing: [] } }; },
  };
  const cli = M.cliSettings({ api, keyOf: () => "local", toast: (text) => toasts.push(text) });
  const status = { agents: [], missing: [{ command: "copilot", name: "GitHub Copilot", is_disabled: true, is_installed: true }] };
  const list = cli.renderMissingList(fakeDocument, null, status);
  assert.ok(list.find((node) => node.textContent === "turned off"));
  assert.ok(!list.find((node) => node.textContent === "Install"));
  list.find((node) => node.textContent === "Turn on").listeners.click();
  await tick();
  assert.deepEqual(calls, ["copilot"]);
  assert.deepEqual(toasts, ["GitHub Copilot turned on."]);
});
