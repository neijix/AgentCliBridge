// Settings › Agents: version, update, install, uninstall, and sign-in. Classic script.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

const SIGN_IN_ERROR_MAX = 500;
const SIGN_IN_ERRORS = [
  { pattern: /OAuth session expired|could not be refreshed|Login expired|run ['"]?\/login['"]?|profile login expired/i, commands: ["claude"] },
  { pattern: /\bagent login\b|CURSOR_API_KEY/i, commands: ["cursor-agent", "agent"] },
  { pattern: /grok login|You are not authenticated/i, commands: ["grok"] },
  { pattern: /No auth credentials found|opencode auth login/i, commands: ["opencode"] },
  { pattern: /No authentication information found|\bcopilot login\b/i, commands: ["copilot"] },
];
const SIGN_IN_COMMANDS = ["claude", "agent", "cursor-agent", "grok", "opencode", "copilot"];
const CLI_LOGIN_POLL_MS = 3000;
const CLI_LOGIN_GIVE_UP_MS = 10 * 60 * 1000;
const CLI_UNINSTALL_ARM_MS = 5000;
const CLI_CLASSES = {
  primary: "acb-btn acb-btn-primary acb-btn-sm",
  secondary: "acb-btn acb-btn-secondary acb-btn-sm",
};

const cliVersionText = function cliVersionText(row) {
  let version = row.installed || "version unknown";
  if (row.is_outdated) version = `${row.installed} → ${row.latest}`;
  else if (row.is_outdated === false) version = `${row.installed} · up to date`;
  else if (row.error) version = `${version} · ${row.error}`;
  return version;
};

const signInTextFrom = function signInTextFrom(message) {
  const content = String(message?.content || "").trim();
  if (content) return content;
  const parts = Array.isArray(message?.parts) ? message.parts : [];
  const lines = [];
  for (const part of parts) {
    if (!part || part.type !== "text") continue;
    lines.push(String(part.text || ""));
  }
  return lines.join("\n").trim();
};

const signInCommandFor = function signInCommandFor(text, command, available) {
  const body = String(text || "").trim();
  if (!body || body.length > SIGN_IN_ERROR_MAX) return "";
  const known = new Set(available || []);
  for (const spec of SIGN_IN_ERRORS) {
    if (!spec.pattern.test(body)) continue;
    if (command && spec.commands.includes(command)) return command;
    for (const candidate of spec.commands) {
      if (known.has(candidate)) return candidate;
    }
    if (known.size === 0 && spec.commands.length) return spec.commands[0];
    return "";
  }
  return "";
};

const canSignInCommand = function canSignInCommand(command) {
  return SIGN_IN_COMMANDS.includes(command);
};

const shouldOfferSignIn = function shouldOfferSignIn(row) {
  if (!row) return false;
  if (canSignInCommand(row.command)) return true;
  return Boolean(row.can_sign_in);
};

const signInNeedsCode = function signInNeedsCode(command) {
  return command === "claude" || command === "opencode";
};

const signInPastePrompt = function signInPastePrompt(command) {
  return command === "opencode" ? "Paste your OpenRouter API key" : "Paste the code from the sign-in page";
};

const shouldOfferSignInCode = function shouldOfferSignInCode(command, login) {
  const state = login || {};
  if (!state.isBusy || state.ok) return false;
  return Boolean(state.needs_code) || signInNeedsCode(command);
};

const noop = function noop() {};

const defaultOpen = function defaultOpen(url, name, features) {
  return globalThis.open?.(url, name, features);
};

const defaultSleep = function defaultSleep(ms) {
  return new Promise(function (resolve) { setTimeout(resolve, ms); });
};

const cliKey = function cliKey(ctx, target, command) {
  return acb.modelKey(ctx.keyOf(target), command);
};

const cliOn = function cliOn(ctx, target) {
  return ctx.whereOf(target) ? ` on ${ctx.whereOf(target)}` : "";
};

const cliSettingsContext = function cliSettingsContext(options) {
  const given = options || {};
  return {
    api: given.api,
    keyOf: given.keyOf || function keyOf() { return ""; },
    whereOf: given.whereOf || function whereOf() { return ""; },
    onChange: given.onChange || noop,
    onUpdated: given.onUpdated || noop,
    toast: given.toast || noop,
    openWindow: given.openWindow || defaultOpen,
    sleep: given.sleep || defaultSleep,
    pollMs: given.pollMs === undefined ? CLI_LOGIN_POLL_MS : given.pollMs,
    giveUpMs: given.giveUpMs === undefined ? CLI_LOGIN_GIVE_UP_MS : given.giveUpMs,
    armMs: given.armMs === undefined ? CLI_UNINSTALL_ARM_MS : given.armMs,
    now: given.now || Date.now,
    classes: given.classes || CLI_CLASSES,
    updates: new Map(),
    signedIn: new Map(),
    logins: new Map(),
    removals: new Map(),
    installs: new Map(),
  };
};

const codeNote = function codeNote(command) {
  if (command === "opencode") return `${signInPastePrompt(command)} below.`;
  return "The sign-in page shows a code — paste it below.";
};

const loadSignedIn = async function loadSignedIn(ctx, target, command) {
  const key = cliKey(ctx, target, command);
  ctx.signedIn.set(key, "checking");
  try {
    const status = await ctx.api.signInStatus(target, command);
    ctx.signedIn.set(key, typeof status.signed_in === "boolean" ? status.signed_in : null);
  } catch {
    ctx.signedIn.set(key, null);
  }
  ctx.onChange();
};

const signInCodeField = function signInCodeField(ctx, doc, target, spec) {
  const form = acb.make(doc, "form", "cli-login-code");
  const input = doc.createElement("input");
  input.type = "text";
  input.autocomplete = "off";
  input.spellcheck = false;
  const prompt = signInPastePrompt(spec.command);
  input.placeholder = prompt;
  input.setAttribute("aria-label", prompt);
  const submit = acb.make(doc, "button", ctx.classes.primary, "Continue");
  submit.type = "submit";
  form.append(input, submit);
  form.addEventListener("submit", function (event) {
    event.preventDefault();
    submitCode(ctx, target, spec, input.value);
  });
  return form;
};

const appendSignInFollowup = function appendSignInFollowup(ctx, parent, target, spec) {
  const doc = parent.ownerDocument;
  const login = ctx.logins.get(cliKey(ctx, target, spec.command)) || {};
  if (login.user_code) {
    const code = acb.make(doc, "span", "cli-login-user-code");
    code.append("Enter this code: ", acb.make(doc, "strong", "", login.user_code));
    parent.append(code);
  }
  if (login.url) {
    const link = acb.make(doc, "a", "cli-login-link", "Open the sign-in page");
    link.href = login.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    parent.append(link);
  }
  if (shouldOfferSignInCode(spec.command, login)) parent.append(signInCodeField(ctx, doc, target, spec));
};

const signedInBox = function signedInBox(ctx, doc, target, row, login, name) {
  const box = acb.make(doc, "span", "cli-signed-in", "✓ Signed in");
  const out = acb.make(doc, "button", "cli-sign-out", login.isSigningOut ? "Signing out…" : "Sign out");
  out.type = "button";
  out.disabled = Boolean(login.isSigningOut);
  out.title = `Sign ${name} out${cliOn(ctx, target)}`;
  out.addEventListener("click", function () { signOutCli(ctx, target, row); });
  box.append(acb.make(doc, "span", "cli-sign-sep", "·"), out);
  return box;
};

const signInControls = function signInControls(ctx, doc, target, row) {
  const key = cliKey(ctx, target, row.command);
  const login = ctx.logins.get(key) || {};
  if (!ctx.signedIn.has(key)) loadSignedIn(ctx, target, row.command);
  const isSignedIn = ctx.signedIn.get(key) === true || (login.ok === true && !login.isBusy);
  const name = acb.agentDisplayName(row);
  if (isSignedIn) return [signedInBox(ctx, doc, target, row, login, name)];
  if (ctx.signedIn.get(key) === "checking" && !login.isBusy) {
    return [acb.make(doc, "span", "muted cli-signed-in", "…")];
  }
  const button = acb.make(doc, "button", ctx.classes.secondary, login.isBusy ? "Waiting for sign-in…" : "Sign in");
  button.type = "button";
  button.disabled = Boolean(login.isBusy && !login.url);
  button.title = `Start ${name}'s browser sign-in${cliOn(ctx, target)} and open its page here`;
  button.addEventListener("click", function () { signInCli(ctx, target, row); });
  return [button];
};

const appendUpdateButton = function appendUpdateButton(ctx, doc, item, target, row, update, name) {
  if (!row.is_outdated && !update.isBusy) return;
  const button = acb.make(doc, "button", ctx.classes.primary, update.isBusy ? "Updating…" : "Update");
  button.type = "button";
  button.disabled = Boolean(update.isBusy);
  button.title = `Update ${name}${cliOn(ctx, target)} to ${row.latest}`;
  button.addEventListener("click", function () { runCliUpdate(ctx, target, row); });
  item.append(button);
};

const appendCliDetail = function appendCliDetail(doc, item, show, isOpen, summary, text) {
  if (!show) return;
  const detail = acb.make(doc, "details", "cli-output");
  detail.open = isOpen;
  detail.append(acb.make(doc, "summary", "", summary), acb.make(doc, "pre", "", text));
  item.append(detail);
};

const removalSummary = function removalSummary(removal) {
  if (removal.hint) return "Can't uninstall it from here — do it on that computer";
  return "Uninstall failed — output";
};

const updateSummary = function updateSummary(update) {
  if (update.hint) return "Can't update it from here — run this on that computer";
  return update.ok ? "Update output" : "Update failed — output";
};

const installSummary = function installSummary(install) {
  if (install.hint) return "Can't install it from here — do it on that computer";
  return "Install failed — output";
};

const renderCliRow = function renderCliRow(ctx, doc, target, row) {
  const key = cliKey(ctx, target, row.command);
  const update = ctx.updates.get(key) || {};
  const login = ctx.logins.get(key) || {};
  const removal = ctx.removals.get(key) || {};
  const name = acb.agentDisplayName(row);
  const item = acb.make(doc, "li", `cli-row${row.is_outdated ? " outdated" : ""}`);
  const title = acb.make(doc, "span", "cli-title");
  title.append(acb.make(doc, "span", "cli-name", name), acb.make(doc, "span", "cli-version", cliVersionText(row)));
  item.append(acb.make(doc, "span", "cli-dot"), title, acb.make(doc, "span", "spacer"));
  appendUpdateButton(ctx, doc, item, target, row, update, name);
  if (shouldOfferSignIn(row)) item.append(...signInControls(ctx, doc, target, row));
  appendSignInFollowup(ctx, item, target, { command: row.command, name });
  if (login.note && !login.ok) {
    const noteClass = login.ok === false ? "error-text cli-login-note" : "muted cli-login-note";
    item.append(acb.make(doc, "span", noteClass, login.note));
  }
  if (typeof ctx.api.uninstall === "function") item.append(uninstallControl(ctx, doc, target, row));
  appendCliDetail(doc, item, removal.hint || (removal.output && !removal.ok), true, removalSummary(removal), removal.hint || removal.output);
  appendCliDetail(doc, item, update.hint || update.output, !update.ok, updateSummary(update), update.hint || update.output);
  return item;
};

const uninstallControl = function uninstallControl(ctx, doc, target, row) {
  const removal = ctx.removals.get(cliKey(ctx, target, row.command)) || {};
  const name = acb.agentDisplayName(row);
  const label = removal.isBusy ? "Uninstalling…" : removal.isArmed ? "Confirm uninstall" : "Uninstall";
  const button = acb.make(doc, "button", `cli-uninstall${removal.isArmed ? " armed" : ""}`, label);
  button.type = "button";
  button.disabled = Boolean(removal.isBusy);
  button.title = removal.isArmed ? `Click again to remove ${name}${cliOn(ctx, target)}` : `Remove ${name}${cliOn(ctx, target)}`;
  button.addEventListener("click", function () { uninstallCli(ctx, target, row); });
  return button;
};

const armUninstall = async function armUninstall(ctx, key) {
  const armed = { isArmed: true };
  ctx.removals.set(key, armed);
  ctx.onChange();
  await ctx.sleep(ctx.armMs);
  if (ctx.removals.get(key) === armed) {
    ctx.removals.delete(key);
    ctx.onChange();
  }
};

const finishUninstall = function finishUninstall(ctx, target, key, name, result, next) {
  if (!result) return;
  if (result.ok) {
    ctx.signedIn.delete(key);
    ctx.logins.delete(key);
    ctx.updates.delete(key);
    ctx.toast(`${name} uninstalled${cliOn(ctx, target)}.`);
    return;
  }
  if (!result.hint) ctx.toast(`${name} could not be uninstalled${cliOn(ctx, target)}.`);
};

const uninstallCli = async function uninstallCli(ctx, target, row) {
  const key = cliKey(ctx, target, row.command);
  const removal = ctx.removals.get(key) || {};
  if (removal.isBusy) return;
  const name = acb.agentDisplayName(row);
  if (!removal.isArmed) {
    await armUninstall(ctx, key);
    return;
  }
  ctx.removals.set(key, { isBusy: true });
  ctx.onChange();
  let next = { ok: false, output: "", hint: "" };
  let result = null;
  try {
    result = await ctx.api.uninstall(target, row.command);
    next = { ok: Boolean(result.ok), output: result.output || "", hint: result.hint || "" };
    ctx.onUpdated(target, result);
    finishUninstall(ctx, target, key, name, result, next);
  } catch (error) {
    next.output = error.message;
    ctx.toast(error.message);
  }
  if (next.ok) ctx.removals.delete(key);
  else ctx.removals.set(key, next);
  ctx.onChange();
};

const renderMissingRow = function renderMissingRow(ctx, doc, target, row) {
  const key = cliKey(ctx, target, row.command);
  const install = ctx.installs.get(key) || {};
  const name = acb.agentDisplayName(row);
  const isTurnOn = Boolean(row.is_installed);
  const item = acb.make(doc, "li", "cli-row missing");
  const title = acb.make(doc, "span", "cli-title");
  title.append(
    acb.make(doc, "span", "cli-name", name),
    acb.make(doc, "span", "cli-version", isTurnOn ? "turned off" : "not installed"),
  );
  item.append(acb.make(doc, "span", "cli-dot"), title, acb.make(doc, "span", "spacer"));
  const label = installButtonLabel(isTurnOn, install.isBusy);
  const button = acb.make(doc, "button", ctx.classes.secondary, label);
  button.type = "button";
  button.disabled = Boolean(install.isBusy);
  button.title = installButtonTitle(ctx, target, name, isTurnOn);
  button.addEventListener("click", function () { runCliInstall(ctx, target, row); });
  item.append(button);
  appendCliDetail(
    doc, item, install.hint || (install.output && !install.ok), true,
    installSummary(install), install.hint || install.output,
  );
  return item;
};

const installButtonLabel = function installButtonLabel(isTurnOn, isBusy) {
  if (isTurnOn) return isBusy ? "Turning on…" : "Turn on";
  return isBusy ? "Installing…" : "Install";
};

const installButtonTitle = function installButtonTitle(ctx, target, name, isTurnOn) {
  if (isTurnOn) return `Offer ${name}${cliOn(ctx, target)} again (it is installed, the settings file turned it off)`;
  return `Install ${name}${cliOn(ctx, target)} with its official installer`;
};

const renderMissingCliList = function renderMissingCliList(ctx, doc, target, status) {
  if (typeof ctx.api.install !== "function" || !(status?.missing || []).length) return null;
  const list = acb.make(doc, "ul", "cli-list cli-missing");
  for (const row of status.missing) list.append(renderMissingRow(ctx, doc, target, row));
  return list;
};

const toastInstall = function toastInstall(ctx, target, name, row, result) {
  if (result.ok && row.is_installed) ctx.toast(`${name} turned on${cliOn(ctx, target)}.`);
  else if (result.ok) ctx.toast(`${name} installed${cliOn(ctx, target)} — sign in to use it.`);
  else if (!result.hint) ctx.toast(`${name} could not be installed${cliOn(ctx, target)}.`);
};

const runCliInstall = async function runCliInstall(ctx, target, row) {
  const key = cliKey(ctx, target, row.command);
  if (ctx.installs.get(key)?.isBusy) return;
  const name = acb.agentDisplayName(row);
  ctx.installs.set(key, { isBusy: true });
  ctx.onChange();
  let next = { ok: false, output: "", hint: "" };
  try {
    const result = await ctx.api.install(target, row.command);
    next = { ok: Boolean(result.ok), output: result.output || "", hint: result.hint || "" };
    ctx.onUpdated(target, result);
    toastInstall(ctx, target, name, row, result);
  } catch (error) {
    next.output = error.message;
    ctx.toast(error.message);
  }
  if (next.ok) ctx.installs.delete(key);
  else ctx.installs.set(key, next);
  ctx.onChange();
};

const renderCliList = function renderCliList(ctx, doc, target, status) {
  const list = acb.make(doc, "ul", "cli-list");
  for (const row of status?.agents || []) list.append(renderCliRow(ctx, doc, target, row));
  if (!list.childElementCount) list.append(acb.make(doc, "li", "cli-row muted", "No agent CLI found on this computer."));
  return list;
};

const toastUpdate = function toastUpdate(ctx, target, name, row, result) {
  if (result.ok) {
    const fresh = (result.status?.agents || []).find(function (agent) { return agent.command === row.command; });
    ctx.toast(`${name} updated${fresh?.installed ? ` to ${fresh.installed}` : ""}${cliOn(ctx, target)}.`);
    return;
  }
  if (!result.hint) ctx.toast(`${name} could not be updated${cliOn(ctx, target)}.`);
};

const runCliUpdate = async function runCliUpdate(ctx, target, row) {
  const key = cliKey(ctx, target, row.command);
  if (ctx.updates.get(key)?.isBusy) return;
  const name = acb.agentDisplayName(row);
  ctx.updates.set(key, { isBusy: true });
  ctx.onChange();
  let next = { ok: false, output: "", hint: "" };
  try {
    const result = await ctx.api.update(target, row.command);
    next = { ok: Boolean(result.ok), output: result.output || "", hint: result.hint || "" };
    ctx.onUpdated(target, result);
    toastUpdate(ctx, target, name, row, result);
  } catch (error) {
    next.output = error.message;
    ctx.toast(error.message);
  }
  ctx.updates.set(key, next);
  ctx.onChange();
};

const signOutCli = async function signOutCli(ctx, target, row) {
  const key = cliKey(ctx, target, row.command);
  const name = acb.agentDisplayName(row);
  ctx.logins.set(key, { isSigningOut: true });
  ctx.onChange();
  try {
    const status = await ctx.api.signOut(target, row.command);
    ctx.signedIn.set(key, typeof status.signed_in === "boolean" ? status.signed_in : null);
    ctx.logins.delete(key);
    ctx.toast(`${name} is signed out${cliOn(ctx, target)}.`);
  } catch (error) {
    ctx.logins.set(key, { ok: false, note: error.message });
    ctx.toast(`${name}: ${error.message}`);
  }
  ctx.onChange();
};

const submitCode = async function submitCode(ctx, target, spec, raw) {
  const key = cliKey(ctx, target, spec.command);
  const previous = ctx.logins.get(key) || {};
  const code = String(raw || "").trim();
  if (!code) return;
  ctx.logins.set(key, { ...previous, note: "Checking the code…" });
  ctx.onChange();
  try {
    await ctx.api.signInCode(target, spec.command, code);
  } catch (error) {
    ctx.logins.set(key, { ...previous, ok: false, note: error.message });
    ctx.toast(`${spec.name}: ${error.message}`);
    ctx.onChange();
  }
};

const signInAlreadyRunning = function signInAlreadyRunning(ctx, previous) {
  if (previous?.isBusy && previous.url) {
    ctx.openWindow(previous.url, "_blank", "noopener");
    return true;
  }
  return Boolean(previous?.isBusy);
};

const requestSignIn = async function requestSignIn(ctx, target, command, key, name) {
  const tab = ctx.openWindow("", "_blank");
  ctx.logins.set(key, { isBusy: true, note: `Starting ${name}'s sign-in…` });
  ctx.onChange();
  try {
    const result = await ctx.api.signIn(target, command);
    return {
      tab,
      url: result.url || "",
      userCode: result.user_code || "",
      needsCode: Boolean(result.needs_code) || signInNeedsCode(command),
    };
  } catch (error) {
    if (tab) tab.close();
    ctx.logins.set(key, { ok: false, note: error.message });
    ctx.toast(`${name}: ${error.message}`);
    ctx.onChange();
    return null;
  }
};

const revealSignInTab = function revealSignInTab(tab, url) {
  if (url && tab) {
    tab.opener = null;
    tab.location.href = url;
    return;
  }
  if (tab) tab.close();
};

const signInWaitNote = function signInWaitNote(ctx, target, command, name, needsCode, userCode) {
  if (needsCode) return codeNote(command);
  if (userCode) return `Enter ${userCode} on the sign-in page that opened — ${name}${cliOn(ctx, target)} is waiting.`;
  return `Approve the sign-in in the page that opened — ${name}${cliOn(ctx, target)} is waiting.`;
};

const readSignInStatus = async function readSignInStatus(ctx, target, command) {
  try {
    return await ctx.api.signInStatus(target, command);
  } catch {
    return null;
  }
};

const noteFreshSignInCode = function noteFreshSignInCode(ctx, command, key, status) {
  const current = ctx.logins.get(key) || {};
  const isCodeNeeded = Boolean(status.needs_code) || signInNeedsCode(command);
  const codeChanged = status.user_code && status.user_code !== current.user_code;
  if (!((isCodeNeeded && !current.needs_code) || codeChanged)) return;
  ctx.logins.set(key, {
    ...current,
    isBusy: true,
    url: status.url || current.url,
    needs_code: isCodeNeeded,
    user_code: status.user_code || current.user_code || "",
    note: isCodeNeeded ? codeNote(command) : current.note,
  });
  ctx.onChange();
};

const settleSignInStatus = function settleSignInStatus(ctx, target, command, key, name, status) {
  if (status.signed_in) {
    ctx.signedIn.set(key, true);
    ctx.logins.delete(key);
    ctx.toast(`${name} is signed in${cliOn(ctx, target)} — send your message again.`);
    ctx.onChange();
    return true;
  }
  if (!status.running) {
    const output = status.output ? ` ${status.output}` : "";
    ctx.logins.set(key, { ok: false, note: `The sign-in ended without logging in.${output}` });
    ctx.onChange();
    return true;
  }
  noteFreshSignInCode(ctx, command, key, status);
  return false;
};

const pollSignIn = async function pollSignIn(ctx, target, command, key, name) {
  const giveUpAt = ctx.now() + ctx.giveUpMs;
  while (ctx.now() < giveUpAt) {
    await ctx.sleep(ctx.pollMs);
    const status = await readSignInStatus(ctx, target, command);
    if (!status) continue;
    if (settleSignInStatus(ctx, target, command, key, name, status)) return;
  }
  ctx.logins.set(key, { ok: false, note: "No sign-in after 10 minutes — try again." });
  ctx.onChange();
};

const signInCli = async function signInCli(ctx, target, spec) {
  const command = spec.command;
  const given = spec.name;
  const key = cliKey(ctx, target, command);
  const name = given || acb.agentDisplayName({ command });
  if (signInAlreadyRunning(ctx, ctx.logins.get(key))) return;
  const started = await requestSignIn(ctx, target, command, key, name);
  if (!started) return;
  revealSignInTab(started.tab, started.url);
  ctx.logins.set(key, {
    isBusy: true,
    url: started.url,
    needs_code: started.needsCode,
    user_code: started.userCode,
    note: signInWaitNote(ctx, target, command, name, started.needsCode, started.userCode),
  });
  ctx.toast(`Approve ${name}'s sign-in in the new tab.`);
  ctx.onChange();
  await pollSignIn(ctx, target, command, key, name);
};

const forgetCliSignIns = function forgetCliSignIns(ctx, target) {
  const prefix = acb.modelKey(ctx.keyOf(target), "");
  for (const key of [...ctx.signedIn.keys()]) {
    if (key.startsWith(prefix)) ctx.signedIn.delete(key);
  }
};

const cliLoginOf = function cliLoginOf(ctx, target, command) {
  return ctx.logins.get(cliKey(ctx, target, command)) || {};
};

const setCliSignedIn = function setCliSignedIn(ctx, target, command, value) {
  ctx.signedIn.set(cliKey(ctx, target, command), value);
};

const cliSettings = function cliSettings(options) {
  const ctx = cliSettingsContext(options);
  return {
    renderRow: renderCliRow.bind(null, ctx),
    renderList: renderCliList.bind(null, ctx),
    renderMissingList: renderMissingCliList.bind(null, ctx),
    appendSignInFollowup: appendSignInFollowup.bind(null, ctx),
    signIn: signInCli.bind(null, ctx),
    signOut: signOutCli.bind(null, ctx),
    update: runCliUpdate.bind(null, ctx),
    uninstall: uninstallCli.bind(null, ctx),
    install: runCliInstall.bind(null, ctx),
    forget: forgetCliSignIns.bind(null, ctx),
    loginOf: cliLoginOf.bind(null, ctx),
    setSignedIn: setCliSignedIn.bind(null, ctx),
  };
};

acb.cliVersionText = cliVersionText;
acb.cliSettings = cliSettings;
acb.signInTextFrom = signInTextFrom;
acb.signInCommandFor = signInCommandFor;
acb.SIGN_IN_COMMANDS = SIGN_IN_COMMANDS;
acb.canSignInCommand = canSignInCommand;
acb.shouldOfferSignIn = shouldOfferSignIn;
acb.signInNeedsCode = signInNeedsCode;
acb.signInPastePrompt = signInPastePrompt;
acb.shouldOfferSignInCode = shouldOfferSignInCode;
}
