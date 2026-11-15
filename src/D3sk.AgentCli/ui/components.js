// Assembles window.AgentUI from the UI scripts a host loads first.
// Classic script, no build step: under node the tests require() this file, which loads the
// pieces; in a page they are separate script tags and this file only publishes the API.
// Needs models.js (window.AgentModels) and the composer scripts, then icons.js,
// permission_modes.js, settings_models.js and settings_agents.js.
"use strict";
{

if (typeof module !== "undefined" && module.exports && typeof require === "function") {
  if (!globalThis.AgentModels) require("./models.js");
  require("./icons.js");
  require("./permission_modes.js");
  require("./settings_models.js");
  require("./settings_agents.js");
  require("./composer_menu.js");
  require("./composer.js");
}

const acb = globalThis.__acbUi;
const Composer = globalThis.__acbComposer;
const Models = globalThis.AgentModels;

if (!Models) throw new Error("components.js needs models.js (window.AgentModels) loaded first");
if (!acb || typeof acb.icon !== "function" || typeof acb.mountModelsSettings !== "function" || typeof acb.mountAgentsSettings !== "function" || !acb.permissions) {
  throw new Error("components.js needs the UI scripts loaded first (icons.js, permission_modes.js, settings_models.js, settings_agents.js)");
}
if (!Composer || typeof Composer.mountComposer !== "function" || typeof Composer.slashQuery !== "function") {
  throw new Error("components.js needs the composer scripts loaded first (composer_menu.js, composer.js)");
}

const pageRoot = function pageRoot() {
  if (typeof window !== "undefined") return window;
  if (typeof globalThis !== "undefined") return globalThis;
  return null;
};

const mountComposer = function mountComposer(container, options = {}) {
  return Composer.mountComposer({
    root: pageRoot(),
    make: acb.make,
    setAttributes: acb.setAttributes,
    button: acb.button,
    option: acb.option,
    icon: acb.icon,
    Models,
    takeMountId: acb.takeMountId,
    permissions: acb.permissions,
  }, container, options);
};

const AgentUI = Object.freeze({
  PERMISSION_MODES: acb.PERMISSION_MODES,
  DEFAULT_PERMISSION: acb.DEFAULT_PERMISSION,
  PERMISSION_DESCRIPTIONS: acb.PERMISSION_DESCRIPTIONS,
  allowedPermissions: acb.allowedPermissions,
  flavorPermissions: acb.flavorPermissions,
  effectivePermission: acb.effectivePermission,
  slashQuery: Composer.slashQuery,
  filterSlashCommands: Composer.filterSlashCommands,
  applySlashCommand: Composer.applySlashCommand,
  slashSourceLabel: Composer.slashSourceLabel,
  COMPOSER_MIN_HEIGHT: Composer.COMPOSER_MIN_HEIGHT,
  composerHeightLimit: Composer.composerHeightLimit,
  nextComposerHeight: Composer.nextComposerHeight,
  formatTokenCount: Composer.formatTokenCount,
  contextMeterModel: Composer.contextMeterModel,
  WEB_MODES: Composer.WEB_MODES,
  WEB_MODE_TITLES: Composer.WEB_MODE_TITLES,
  WEB_ENGINES: Composer.WEB_ENGINES,
  clampSearches: Composer.clampSearches,
  normalizeWeb: Composer.normalizeWeb,
  webSummary: Composer.webSummary,
  MAX_ATTACHMENTS: Composer.MAX_ATTACHMENTS,
  MAX_ATTACHMENT_BYTES: Composer.MAX_ATTACHMENT_BYTES,
  MAX_TOTAL_BYTES: Composer.MAX_TOTAL_BYTES,
  formatSize: Composer.formatSize,
  acceptFiles: Composer.acceptFiles,
  encodeAttachments: Composer.encodeAttachments,
  DEFAULT_PLACEHOLDER: Composer.DEFAULT_PLACEHOLDER,
  mountComposer,
  MODELS_LEDE: acb.MODELS_LEDE,
  mountModelsSettings: acb.mountModelsSettings,
  AGENTS_LEDE: acb.AGENTS_LEDE,
  mountAgentsSettings: acb.mountAgentsSettings,
});

if (typeof module !== "undefined" && module.exports) module.exports = AgentUI;
const root = pageRoot();
if (root) root.AgentUI = AgentUI;
}
