// Permission modes: the same list and labels everywhere (Claude Code's modes). Classic script.
// Registers on globalThis.__acbUi. components.js publishes them on window.AgentUI.
"use strict";
{

globalThis.__acbUi = globalThis.__acbUi || {};
const acb = globalThis.__acbUi;

const PERMISSION_MODES = [
  ["plan", "Plan — read-only"],
  ["manual", "Ask"],
  ["acceptEdits", "Accept edits"],
  ["auto", "Auto"],
  ["dontAsk", "Don't ask"],
  ["bypassPermissions", "Bypass permissions"],
];
const DEFAULT_PERMISSION = "acceptEdits";

// Under each mode's name in the mode menu.
const PERMISSION_DESCRIPTIONS = {
  plan: "Create a plan before making changes",
  manual: "Ask before each edit and command",
  acceptEdits: "Automatically accept all file edits",
  auto: "The agent handles permission decisions",
  dontAsk: "Run only pre-approved tools, refuse the rest",
  bypassPermissions: "Run every tool without asking",
};

// The modes each CLI really tells apart (argv.py permission_args): two modes it runs the same
// way are offered once, as the lower one. A local model has no tools, so no mode; a flavor not
// listed (Claude Code, a host's own) offers every mode.
const FLAVOR_PERMISSIONS = {
  cursor: ["plan", "acceptEdits"],
  gemini: ["plan", "acceptEdits"],
  copilot: ["plan", "acceptEdits"],
  grok: ["plan", "acceptEdits", "auto", "bypassPermissions"],
  opencode: ["plan", "acceptEdits", "bypassPermissions"],
  antigravity: ["plan", "acceptEdits", "bypassPermissions"],
  mlx: [],
  colibri: [],
};
// Where a CLI's mode does more (or less) than its name says.
const FLAVOR_PERMISSION_NOTES = {
  cursor: { acceptEdits: "Edits files and runs commands without asking" },
  gemini: { acceptEdits: "Gemini runs every tool without asking (yolo)" },
  copilot: { acceptEdits: "Copilot may use every tool without asking" },
  grok: { acceptEdits: "Edits files; no shell, MCP tools or subagents", auto: "Grok runs every tool without asking" },
  opencode: { acceptEdits: "Edits inside the project without asking", bypassPermissions: "Also approves paths outside the project" },
};

// How much each mode lets run without asking. Not the menu's order: Don't ask refuses whatever
// is not pre-approved, so it must never fall into Auto, where the agent approves the rest
// itself (Grok); every CLI already ran it as its Accept edits (argv.py).
const PERMISSION_REACH = ["plan", "manual", "acceptEdits", "dontAsk", "auto", "bypassPermissions"];

// Every mode up to a machine's limit (all of them when the limit is unknown).
const allowedPermissions = function allowedPermissions(permissions, maxPermission) {
  const maxIndex = permissions.findIndex(([value]) => value === maxPermission);
  return maxIndex >= 0 ? permissions.slice(0, maxIndex + 1) : permissions.slice();
};

// Of `permissions`, the modes a CLI of that flavor tells apart.
const flavorPermissions = function flavorPermissions(permissions, flavor) {
  const offered = FLAVOR_PERMISSIONS[flavor];
  return offered ? permissions.filter(([value]) => offered.includes(value)) : permissions.slice();
};

const reachesAtMost = function reachesAtMost(values, rank) {
  return values.filter((value) => {
    const reach = PERMISSION_REACH.indexOf(value);
    return reach >= 0 && reach <= rank;
  });
};

// The mode that runs: the chosen one when offered, else the offered one reaching furthest
// without reaching further than it; an unknown mode runs as the most careful offered one.
const effectivePermission = function effectivePermission(offered, chosen) {
  const values = offered.map(([value]) => value);
  if (values.includes(chosen)) return chosen;
  const rank = PERMISSION_REACH.indexOf(chosen);
  if (rank < 0) return values[0] || "";
  const below = reachesAtMost(values, rank);
  const furthest = below.sort((a, b) => PERMISSION_REACH.indexOf(a) - PERMISSION_REACH.indexOf(b)).at(-1);
  return furthest || values[0] || "";
};

const permissionName = function permissionName(label) {
  return String(label).split(" — ")[0];
};

const permissionDescription = function permissionDescription(value, flavor) {
  return FLAVOR_PERMISSION_NOTES[flavor]?.[value] || PERMISSION_DESCRIPTIONS[value] || "";
};

acb.PERMISSION_MODES = PERMISSION_MODES;
acb.DEFAULT_PERMISSION = DEFAULT_PERMISSION;
acb.PERMISSION_DESCRIPTIONS = PERMISSION_DESCRIPTIONS;
acb.allowedPermissions = allowedPermissions;
acb.flavorPermissions = flavorPermissions;
acb.effectivePermission = effectivePermission;
acb.permissionName = permissionName;
acb.permissionDescription = permissionDescription;
acb.permissions = {
  modes: PERMISSION_MODES,
  defaultMode: DEFAULT_PERMISSION,
  allowed: allowedPermissions,
  forFlavor: flavorPermissions,
  effective: effectivePermission,
  name: permissionName,
  describe: permissionDescription,
};
}
