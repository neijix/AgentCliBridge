// Tags on a model: limited-time free, preview, graduated, and the price. Classic script.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

// Open Router's :free, -free and stealth ids are promotional: the lab may pull them.
// OpenCode Zen (`opencode/big-pickle`) is not — it does not wear this badge.
const isLimitedFreeModel = function isLimitedFreeModel(id) {
  const text = String(id || "").toLowerCase();
  if (text.includes("/stealth/")) return true;
  if (text.endsWith(":free")) return true;
  const name = text.includes("/") ? text.slice(text.lastIndexOf("/") + 1) : text;
  return name.endsWith("-free");
};

// Local models, run by the host itself: MLX weights already downloaded, and colibri.
const isLocalAgent = function isLocalAgent(agent) {
  return agent?.flavor === "mlx" || agent?.command === "mlx"
    || agent?.flavor === "colibri" || agent?.command === "colibri";
};

// OpenCode prices its models, and so does a company gateway Claude Code goes through.
// The other CLIs run on the owner's subscription.
const isPricedAgent = function isPricedAgent(agent) {
  if (isLocalAgent(agent)) return false;
  return agent?.flavor === "opencode" || Boolean(agent?.prices && Object.keys(agent.prices).length);
};

// Free = an Open Router promo id, or an OpenCode Zen model at no cost. A price of zero alone is
// not: Open Router's routers bill the model they pick.
const isFreeModel = function isFreeModel(id, price) {
  if (isLimitedFreeModel(id)) return true;
  if (!String(id || "").startsWith("opencode/")) return false;
  return !Array.isArray(price) || (!price[0] && !price[1]);
};

const formatUsd = function formatUsd(value) {
  if (value >= 100) return `$${Math.round(value)}`;
  if (value >= 1) return `$${value.toFixed(2)}`;
  return `$${Number(value.toPrecision(2))}`;
};

// { text, title, isFree } for the Price cell. `isPriced` false = a subscription CLI.
const modelPriceNote = function modelPriceNote(id, price, isPriced, isLocal) {
  const priced = isPriced === undefined ? true : isPriced;
  const local = isLocal === undefined ? false : isLocal;
  if (local) return { text: "Local", title: "Runs on this computer, no token charge", isFree: true };
  if (!priced) return { text: "Plan", title: "Included in your subscription", isFree: false };
  if (isFreeModel(id, price)) return { text: "Free", title: "No cost per token", isFree: true };
  if (!Array.isArray(price) || (!price[0] && !price[1])) {
    return { text: "—", title: "No fixed price (a router bills the model it picks)", isFree: false };
  }
  const input = price[0];
  const output = price[1];
  return {
    text: `${formatUsd(input)} / ${formatUsd(output)}`,
    title: `USD per million tokens — input ${formatUsd(input)}, output ${formatUsd(output)}`,
    isFree: false,
  };
};

const modelLimitedNote = function modelLimitedNote(id) {
  if (!isLimitedFreeModel(id)) return null;
  return {
    text: "limited",
    title: "Open Router is offering this free for a limited time; that endpoint may disappear.",
  };
};

// A lab preview, stealth, or alpha id — not yet graduated. Ranked Index models have been out.
const isPreviewModel = function isPreviewModel(id) {
  const text = String(id || "").toLowerCase();
  if (text.includes("/stealth/")) return true;
  const name = text.includes("/") ? text.slice(text.lastIndexOf("/") + 1) : text;
  if (name.includes("preview") || name.includes("-alpha") || name.startsWith("alpha-")) return true;
  return name.replace(/-free$/, "") === "space-bunny";
};

const modelPreviewNote = function modelPreviewNote(id) {
  if (!isPreviewModel(id)) return null;
  return {
    text: "preview",
    title: "This id has not graduated yet (a lab preview, stealth, or alpha). It may change or disappear.",
  };
};

// Open Router ids that match the Index: graduated. Other CLIs already have a short named list.
const isOpenRouterListedId = function isOpenRouterListedId(id) {
  const text = String(id || "").toLowerCase();
  return text.startsWith("openrouter/") || text.startsWith("opencode/");
};

const modelIndexNote = function modelIndexNote(id) {
  if (acb.modelMetrics(id).kind !== "ranked") return null;
  if (!isOpenRouterListedId(id)) return null;
  return {
    text: "graduated",
    title: "Graduated — this model has been on the Artificial Analysis Intelligence Index for a while, not a lab preview.",
  };
};

acb.isLimitedFreeModel = isLimitedFreeModel;
acb.isPricedAgent = isPricedAgent;
acb.isLocalAgent = isLocalAgent;
acb.isFreeModel = isFreeModel;
acb.formatUsd = formatUsd;
acb.modelPriceNote = modelPriceNote;
acb.modelLimitedNote = modelLimitedNote;
acb.isPreviewModel = isPreviewModel;
acb.modelPreviewNote = modelPreviewNote;
acb.modelIndexNote = modelIndexNote;
}
