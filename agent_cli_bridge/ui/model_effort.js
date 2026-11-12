// The composer's Effort and Ultracode. effort.py turns them into the CLI's flags. Classic script.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

// Offered only where the CLI takes them: Claude Code's --effort and ultracode setting, Copilot's
// --reasoning-effort. "auto" passes nothing, the CLI's own default.
const EFFORT_LABELS = {
  auto: "Auto", low: "Low", medium: "Medium", high: "High", xhigh: "Extra high", max: "Max",
};
const EFFORT_LEVELS = {
  claude: ["low", "medium", "high", "xhigh", "max"],
  copilot: ["low", "medium", "high"],
};
const EFFORT_ORDER = ["low", "medium", "high", "xhigh", "max"];

// Per Claude model, from Claude Code's own model table: which levels it takes and the one it
// recommends. Short names resolve through CLAUDE_EFFORT_ALIASES. Models older than effort take
// none; a model newer than this table takes all five with no default known.
const CLAUDE_NO_EFFORT = /^claude-(3-|haiku-4|sonnet-4(-[05])?$|opus-4(-[01])?$|mythos-5$)/;
const CLAUDE_EFFORT_CAPS = {
  "claude-opus-4-5": ["low", "medium", "high"],
  "claude-opus-4-6": ["low", "medium", "high", "max"],
  "claude-sonnet-4-6": ["low", "medium", "high", "max"],
};
const CLAUDE_EFFORT_DEFAULTS = {
  "claude-opus-4-5": "high",
  "claude-opus-4-6": "high",
  "claude-sonnet-4-6": "high",
  "claude-opus-4-7": "xhigh",
  "claude-opus-4-8": "high",
  "claude-opus-5": "high",
  "claude-opus-5-5": "medium",
  "claude-sonnet-5": "high",
  "claude-sonnet-5-5": "medium",
  "claude-haiku-5-5": "medium",
  "claude-fable-5": "high",
  "claude-fable-5-1": "high",
  "claude-mythos-5-1": "high",
};

const effortChoices = function effortChoices(flavor) {
  const levels = EFFORT_LEVELS[flavor];
  if (!levels) return [];
  const choices = [["auto", EFFORT_LABELS.auto]];
  for (const value of levels) choices.push([value, EFFORT_LABELS[value]]);
  return choices;
};

const claudeModelKey = function claudeModelKey(model) {
  // Bedrock / Vertex spellings too: us.anthropic.<id>-v1:0, <id>@20250805.
  const id = acb.normalizeModelId(model)
    .replace(/^(?:[a-z]+\.)?anthropic\./, "")
    .replace(/-v\d+(?::\d+)?$/, "")
    .replace(/[-@]\d{8}$/, "");
  return acb.CLAUDE_EFFORT_ALIASES[id] || id;
};

// { levels, recommended } for this CLI and model; null when it takes no effort.
const effortProfile = function effortProfile(flavor, model) {
  if (flavor === "copilot") return { levels: EFFORT_LEVELS.copilot.slice(), recommended: null };
  if (flavor !== "claude") return null;
  const key = claudeModelKey(model);
  if (CLAUDE_NO_EFFORT.test(key)) return null;
  const levels = CLAUDE_EFFORT_CAPS[key] || EFFORT_LEVELS.claude;
  return { levels: levels.slice(), recommended: CLAUDE_EFFORT_DEFAULTS[key] || null };
};

// The level that runs when `effort` was picked on another model. "auto" stays "auto".
const clampEffort = function clampEffort(profile, effort) {
  if (!profile || !effort || effort === "auto") return "auto";
  if (profile.levels.includes(effort)) return effort;
  const rank = EFFORT_ORDER.indexOf(effort);
  let chosen = "";
  for (const level of profile.levels) {
    if (EFFORT_ORDER.indexOf(level) <= rank) chosen = level;
  }
  return chosen || profile.levels[0];
};

// Ultracode is a Claude Code session setting the CLI ignores on a model without it (Haiku).
const canUltracode = function canUltracode(flavor, model) {
  return flavor === "claude" && !/haiku/i.test(String(model || ""));
};

acb.EFFORT_LABELS = EFFORT_LABELS;
acb.effortChoices = effortChoices;
acb.effortProfile = effortProfile;
acb.clampEffort = clampEffort;
acb.canUltracode = canUltracode;
}
