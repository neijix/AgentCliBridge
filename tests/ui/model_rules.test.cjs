// node --test tests/ui/model_rules.test.cjs — run by tests/test_ui_assets.py when node is installed.
const test = require("node:test");
const assert = require("node:assert/strict");
const M = require("../../agent_cli_bridge/ui/models.js");

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

  test("Open Router free ids rank by the same Index", () => {
    const { modelMetrics, formatModelIntelligence, formatModelSpeed, sortModelsByIntelligence } = M;
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
  });

  test("limited marks a promo endpoint; preview and graduated tag Open Router models", () => {
    const { isLimitedFreeModel, modelLimitedNote, isPreviewModel, modelPreviewNote, modelIndexNote } = M;
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
    assert.equal(modelIndexNote("opencode/muse-spark-1.3-contributor-free").text, "graduated");
    assert.equal(modelIndexNote("opencode/space-bunny-free"), null);
    assert.equal(isPreviewModel("opencode/space-bunny-free"), true);
  });

  test("a preview unknown sorts after Zen; the live Open Router table ranks strongest first", () => {
    const { sortModelsByIntelligence } = M;
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
  });

  test("the Open Router Settings table: graduated first, unknowns next, previews last", () => {
    const { sortModelsByIntelligence } = M;
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
