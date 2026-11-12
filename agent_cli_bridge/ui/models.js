// Assembles window.AgentModels from the model scripts a host loads first.
// Classic script, no build step: under node the tests require() this file, which loads the
// pieces; in a page they are separate script tags and this file only publishes the API.
"use strict";
{

if (typeof module !== "undefined" && module.exports && typeof require === "function") {
  require("./model_names.js");
  require("./model_ranking.js");
  require("./model_tags.js");
  require("./model_picker.js");
  require("./model_catalog.js");
  require("./model_effort.js");
  require("./model_agents.js");
}

const acb = globalThis.__acbModels;
const pickModelEffortFromVariants = acb && acb.pickModelEffortFromVariants;
if (!acb || typeof pickModelEffortFromVariants !== "function" || typeof acb.modelKey !== "function") {
  throw new Error("models.js needs the model scripts loaded first (model_names.js through model_agents.js)");
}

const AgentModels = Object.freeze({
  SEPARATOR: acb.SEPARATOR,
  modelKey: acb.modelKey,
  ACCOUNT_TAGS: acb.ACCOUNT_TAGS,
  agentDisplayName: acb.agentDisplayName,
  modelLabel: acb.modelLabel,
  modelDisplayName: acb.modelDisplayName,
  isModelInPicker: acb.isModelInPicker,
  MODEL_METRICS: acb.MODEL_METRICS,
  MODEL_FAMILY_ALIASES: acb.MODEL_FAMILY_ALIASES,
  CLAUDE_EFFORT_ALIASES: acb.CLAUDE_EFFORT_ALIASES,
  normalizeModelId: acb.normalizeModelId,
  parseModelId: acb.parseModelId,
  rememberModelMetrics: acb.rememberModelMetrics,
  clearLiveModelMetrics: acb.clearLiveModelMetrics,
  modelMetrics: acb.modelMetrics,
  formatModelIntelligence: acb.formatModelIntelligence,
  formatModelSpeed: acb.formatModelSpeed,
  modelBarPercent: acb.modelBarPercent,
  compareModelsByIntelligence: acb.compareModelsByIntelligence,
  sortModelsByIntelligence: acb.sortModelsByIntelligence,
  isLimitedFreeModel: acb.isLimitedFreeModel,
  isPricedAgent: acb.isPricedAgent,
  isLocalAgent: acb.isLocalAgent,
  isFreeModel: acb.isFreeModel,
  formatUsd: acb.formatUsd,
  modelPriceNote: acb.modelPriceNote,
  modelLimitedNote: acb.modelLimitedNote,
  isPreviewModel: acb.isPreviewModel,
  modelPreviewNote: acb.modelPreviewNote,
  modelIndexNote: acb.modelIndexNote,
  modelCatalog: acb.modelCatalog,
  modelWhereNote: acb.modelWhereNote,
  newModelsNote: acb.newModelsNote,
  EFFORT_LABELS: acb.EFFORT_LABELS,
  effortChoices: acb.effortChoices,
  effortProfile: acb.effortProfile,
  clampEffort: acb.clampEffort,
  canUltracode: acb.canUltracode,
  pickerGroups: acb.pickerGroups,
  pickerEmptyText: acb.pickerEmptyText,
  fillPicker: acb.fillPicker,
  renderModelTables: acb.renderModelTables,
  MODEL_TABLE_FOLD: acb.MODEL_TABLE_FOLD,
  toggleModelSets: acb.toggleModelSets,
  newModelKeys: acb.newModelKeys,
  cliVersionText: acb.cliVersionText,
  cliSettings: acb.cliSettings,
  signInTextFrom: acb.signInTextFrom,
  signInCommandFor: acb.signInCommandFor,
  SIGN_IN_COMMANDS: acb.SIGN_IN_COMMANDS,
  canSignInCommand: acb.canSignInCommand,
  shouldOfferSignIn: acb.shouldOfferSignIn,
  signInNeedsCode: acb.signInNeedsCode,
  signInPastePrompt: acb.signInPastePrompt,
  shouldOfferSignInCode: acb.shouldOfferSignInCode,
});

if (typeof module !== "undefined" && module.exports) module.exports = AgentModels;
globalThis.AgentModels = AgentModels;
if (typeof window !== "undefined") window.AgentModels = AgentModels;
}
