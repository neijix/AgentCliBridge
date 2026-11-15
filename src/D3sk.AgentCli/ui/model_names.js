// Names a CLI and a model show under. Classic script: registers on globalThis.__acbModels.
// models.js, loaded after the other model scripts, publishes window.AgentModels.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

const SEPARATOR = "::";

const modelKey = function modelKey(command, model) {
  return `${command}${SEPARATOR}${model}`;
};

// The owner pays for OpenRouter: the CLI is still `opencode`, the UI never says OpenCode.
// Claude on the owner's own subscription and Claude through the company's gateway read apart.
const ACCOUNT_TAGS = { personal: "personal", work: "work" };

const agentDisplayName = function agentDisplayName(agent) {
  if (!agent) return "";
  if (agent.command === "opencode") return "Open Router";
  const name = agent.name || agent.command || "";
  const tag = ACCOUNT_TAGS[agent.account?.kind];
  return tag ? `${name} (${tag})` : name;
};

// The name a company gateway gives one of Claude Code's models (`agent.labels`), or "".
// Only an own string counts — `labels` comes from another machine.
const modelLabel = function modelLabel(agent, model) {
  const labels = agent?.labels;
  if (!labels || typeof labels !== "object" || !Object.prototype.hasOwnProperty.call(labels, model)) return "";
  return typeof labels[model] === "string" ? labels[model] : "";
};

// OpenCode Zen ids are `opencode/<name>`. Show them as OpenRouter ids; the value sent to the CLI
// stays the real one. With its `agent`, a model its gateway names shows that name.
const modelDisplayName = function modelDisplayName(model, agent) {
  if (!model) return "";
  const id = String(model);
  const label = modelLabel(agent || null, id);
  if (label) return label;
  if (id.startsWith("opencode/")) return `openrouter/${id.slice("opencode/".length)}`;
  // A local MLX model shows its weights, not the HuggingFace org that published them.
  if (id.startsWith("mlx-community/")) return id.slice("mlx-community/".length);
  return id;
};

const make = function make(doc, tag, className, text) {
  const node = doc.createElement(tag);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};

acb.SEPARATOR = SEPARATOR;
acb.modelKey = modelKey;
acb.ACCOUNT_TAGS = ACCOUNT_TAGS;
acb.agentDisplayName = agentDisplayName;
acb.modelLabel = modelLabel;
acb.modelDisplayName = modelDisplayName;
acb.make = make;
}
