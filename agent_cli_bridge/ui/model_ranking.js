// Ranking: Artificial Analysis Intelligence Index and median output speed. Classic script.
// Snapshot of https://artificialanalysis.ai/leaderboards/models (Index v4.3.2), overlaid with
// live figures from the host (`agent.metrics`). `auto` / `default` stay first. Unknown ids sink
// to the bottom. Speed is tokens/s; a missing figure is null.
"use strict";
{

globalThis.__acbModels = globalThis.__acbModels || {};
const acb = globalThis.__acbModels;

const PICKER_MODEL_IDS = new Set(["auto", "default"]);
const MODEL_EFFORT_RANK = { max: 5, xhigh: 4, high: 3, medium: 2, low: 1 };
const MODEL_EFFORT_RE = /(?:-thinking)?-(max|xhigh|high|medium|low)$/;
const MODEL_METRICS = {
  "claude-opus-5-5": { max: [58, null], xhigh: [56, 89], high: [54, 82], medium: [51, 81], low: [42, 80] },
  "claude-sonnet-5-5": { max: [56, 133], xhigh: [52, 109], high: [47, 106], medium: [41, 106], low: [36, 105] },
  "claude-fable-5-1": { max: [53, 69], xhigh: [53, 66], high: [51, 57], medium: [49, 58], low: [47, 58] },
  "claude-opus-5": { max: [51, 60] },
  "claude-haiku-5-5": { max: [43, 235], xhigh: [41, 190], high: [38, 182], medium: [34, 178], low: [29, 176] },
  "claude-opus-4-8": { max: [42, 53] },
  "claude-opus-4-6": { high: [39, 37] },
  "claude-sonnet-5": { max: [38, 84], xhigh: [34, 70], high: [32, 66], medium: [28, 66], low: [24, 60] },
  "claude-sonnet-4-6": { high: [25, 44] },
  "claude-haiku-4-5": { high: [17, 82] },
  "gpt-6-astra": { max: [53, 57], xhigh: [52, 54], high: [51, 53], medium: [50, 50], low: [46, 53] },
  "gpt-6.1-sol": { max: [52, 55], xhigh: [51, 50], high: [50, 49], medium: [48, 48], low: [42, 48] },
  "gpt-6-sol": { max: [48, 86], xhigh: [44, 83], high: [43, 84], medium: [40, null], low: [34, 82] },
  "gpt-5.6-sol": { max: [47, 96], high: [47, 96] },
  "gpt-5.6-terra": { max: [42, 125], xhigh: [38, 107], high: [34, 103], medium: [30, 106], low: [27, 108] },
  "gpt-6-luna": { max: [38, 136], xhigh: [35, 126], high: [33, 123], medium: [30, 92], low: [22, 111] },
  "gpt-5.3-codex": { xhigh: [33, 118], high: [33, 118] },
  "gpt-oss-120b": { high: [12, 206], low: [10, 216] },
  "grok-4.7": { xhigh: [46, 82], high: [46, 83], low: [42, 78] },
  "grok-4.6": { xhigh: [44, 78], high: [44, 66], medium: [43, 69], low: [35, 62] },
  "grok-4.5": { high: [39, 63] },
  "gemini-4-argon": { high: [53, 82] },
  "gemini-3.8-flash": { high: [41, 306], medium: [40, null], low: [33, null] },
  "gemini-3.7-flash": { medium: [40, 291], high: [39, 283], low: [37, 306] },
  "gemini-3.6-flash": { high: [34, 212] },
  "gemini-3.5-flash": { high: [33, 204] },
  "gemini-3.5-flash-lite": { high: [22, 349] },
  "gemini-3.1-pro": { high: [30, 119] },
  "gemini-2.5-pro": { high: [16, 139] },
  // Open Router :free / -free / stealth ids share these families after the suffix is stripped.
  "muse-spark-1.3": { max: [48, 221], xhigh: [45, 196] },
  "mimo-v2.6-pro": { high: [45, 55] },
  "muse-wonder": { high: [42, 234] },
  "mimo-v2.6-flash": { high: [38, 59] },
  "inkling-small": { high: [28, 210] },
  "inkling": { high: [25, 194] },
  "ling-3.0-flash": { high: [25, 373] },
  "ling-3.0-flash-fin": { high: [23, 161] },
  "nemotron-3-ultra": { high: [23, 214] },
  "qwen3.8-27b": { xhigh: [34, 47], high: [20, 55], medium: [28, 54], low: [26, 56] },
  "gemma-4-31b": { high: [19, 35] },
  "gemma-4-26b-a4b": { high: [17, null] },
  "nemotron-3.5-lightning": { high: [13, 292] },
  "nemotron-3-super": { high: [13, 166] },
  "nemotron-3-nano-omni": { high: [10, 263] },
  "north-mini-code": { high: [10, 83] },
  "lfm-2.5-2.6b": { high: [8, null] },
};
const CLAUDE_EFFORT_ALIASES = {
  opus: "claude-opus-5-5",
  sonnet: "claude-sonnet-5-5",
  haiku: "claude-haiku-5-5",
  fable: "claude-fable-5-1",
};
const MODEL_FAMILY_ALIASES = {
  "claude-haiku": "claude-haiku-4-5",
  "claude-sonnet": "claude-sonnet-5",
  "gemini-3.1-pro-preview": "gemini-3.1-pro",
};
const LIVE_MODEL_METRICS = Object.create(null);
const LIVE_FAMILY_METRICS = Object.create(null);

const canonicalStem = function canonicalStem(text) {
  return String(text || "").replace(/(\d)\.(\d)/g, "$1-$2");
};

const normalizeModelId = function normalizeModelId(id) {
  // Claude Code's `[1m]` is the same model with a 1M-token window (`claude-opus-5-5[1m]`).
  let text = String(id || "").trim().toLowerCase().replace(/\[1m\]$/, "");
  const slash = text.lastIndexOf("/");
  if (slash >= 0) text = text.slice(slash + 1);
  if (text.startsWith("cursor-")) text = text.slice("cursor-".length);
  // Open Router's promotional ids (`gemma-4-31b-it:free`, `mimo-v2.6-flash-free`).
  if (text.endsWith(":free")) text = text.slice(0, -":free".length);
  if (text.endsWith("-free")) text = text.slice(0, -"-free".length);
  return text;
};

const parseModelId = function parseModelId(id) {
  const raw = normalizeModelId(id);
  let stem = raw.replace(/-thinking$/, "");
  let effort = "";
  const match = stem.match(MODEL_EFFORT_RE);
  if (match) {
    effort = match[1];
    stem = stem.slice(0, -match[0].length);
  }
  return { raw, stem, effort };
};

const pinnedFamily = function pinnedFamily(stem) {
  if (Object.prototype.hasOwnProperty.call(CLAUDE_EFFORT_ALIASES, stem)) return CLAUDE_EFFORT_ALIASES[stem];
  const targets = Object.values(CLAUDE_EFFORT_ALIASES);
  if (targets.includes(stem) || targets.includes(canonicalStem(stem))) return stem;
  return "";
};

const familyInTable = function familyInTable(table, pinned) {
  if (table[pinned]) return pinned;
  const canonical = canonicalStem(pinned);
  if (table[canonical]) return canonical;
  return "";
};

const longestFamilyKey = function longestFamilyKey(table, canonical) {
  let best = "";
  for (const key of Object.keys(table)) {
    const candidate = canonicalStem(key);
    const matches = canonical === candidate
      || canonical.startsWith(`${candidate}-`)
      || candidate.startsWith(`${canonical}-`)
      || candidate.endsWith(`-${canonical}`);
    if (matches && key.length > best.length) best = key;
  }
  return best;
};

const familyOfModel = function familyOfModel(stem, table) {
  const metrics = table || MODEL_METRICS;
  if (metrics[stem]) return stem;
  const pinned = pinnedFamily(stem);
  // A pinned id with no row stays unknown: never prefix-match an older Claude family.
  if (pinned) return familyInTable(metrics, pinned);
  const alias = MODEL_FAMILY_ALIASES[stem];
  if (alias && metrics[alias]) return alias;
  if (alias && metrics[canonicalStem(alias)]) return canonicalStem(alias);
  return longestFamilyKey(metrics, canonicalStem(stem));
};

const pickModelEffortFromVariants = function pickModelEffortFromVariants(variants, effort) {
  if (!variants) return null;
  if (effort && variants[effort]) return variants[effort];
  const order = ["high", "medium", "max", "xhigh", "low"];
  for (const key of order) {
    if (variants[key]) return variants[key];
  }
  const first = Object.keys(variants)[0];
  return first ? variants[first] : null;
};

const validMetricPair = function validMetricPair(pair) {
  if (!Array.isArray(pair)) return null;
  const intelligence = Number.isFinite(pair[0]) && pair[0] > 0 ? Math.round(pair[0]) : null;
  if (intelligence === null) return null;
  const speed = Number.isFinite(pair[1]) && pair[1] > 0 ? Math.round(pair[1]) : null;
  return [intelligence, speed];
};

const storeFamilyPair = function storeFamilyPair(family, effort, pair) {
  if (!LIVE_FAMILY_METRICS[family]) LIVE_FAMILY_METRICS[family] = Object.create(null);
  LIVE_FAMILY_METRICS[family][effort || "high"] = pair;
};

const rememberExactPair = function rememberExactPair(key, value) {
  const pair = validMetricPair(value);
  if (!pair) return;
  const raw = normalizeModelId(key);
  if (!raw) return;
  LIVE_MODEL_METRICS[raw] = pair;
  const parsed = parseModelId(key);
  if (!parsed.stem) return;
  if (!parsed.effort && familyOfModel(parsed.stem, MODEL_METRICS)) return;
  storeFamilyPair(canonicalStem(parsed.stem), parsed.effort, pair);
};

const rememberFamilyTable = function rememberFamilyTable(key, value) {
  const family = canonicalStem(normalizeModelId(key));
  if (!family) return;
  for (const effort of Object.keys(value)) {
    if (!Object.prototype.hasOwnProperty.call(value, effort)) continue;
    const pair = validMetricPair(value[effort]);
    if (!pair) continue;
    storeFamilyPair(family, effort, pair);
  }
};

// Live ratings from the host override the built-in snapshot.
const rememberModelMetrics = function rememberModelMetrics(metrics) {
  if (!metrics || typeof metrics !== "object") return;
  for (const key of Object.keys(metrics)) {
    if (!Object.prototype.hasOwnProperty.call(metrics, key)) continue;
    const value = metrics[key];
    if (Array.isArray(value)) rememberExactPair(key, value);
    else if (value && typeof value === "object") rememberFamilyTable(key, value);
  }
};

const clearLiveModelMetrics = function clearLiveModelMetrics() {
  for (const key of Object.keys(LIVE_MODEL_METRICS)) delete LIVE_MODEL_METRICS[key];
  for (const key of Object.keys(LIVE_FAMILY_METRICS)) delete LIVE_FAMILY_METRICS[key];
};

// { kind: picker | ranked | unknown, intelligence?, speed? }. Picker = auto/default.
const modelMetrics = function modelMetrics(id) {
  const raw = normalizeModelId(id);
  if (!raw) return { kind: "unknown" };
  // A CLI's own "let me pick" setting — not Open Router's routers (`openrouter/openrouter/auto`).
  if (PICKER_MODEL_IDS.has(raw) && !String(id).includes("/")) return { kind: "picker" };
  if (LIVE_MODEL_METRICS[raw]) {
    const pair = LIVE_MODEL_METRICS[raw];
    return { kind: "ranked", intelligence: pair[0], speed: pair[1] };
  }
  const parsed = parseModelId(id);
  const baseFamily = familyOfModel(parsed.stem, MODEL_METRICS);
  const liveFamily = familyOfModel(parsed.stem, LIVE_FAMILY_METRICS);
  if (!baseFamily && !liveFamily) return { kind: "unknown" };
  const variants = Object.assign(
    {},
    baseFamily ? MODEL_METRICS[baseFamily] : null,
    liveFamily ? LIVE_FAMILY_METRICS[liveFamily] : null,
  );
  const pair = pickModelEffortFromVariants(variants, parsed.effort);
  if (!pair) return { kind: "unknown" };
  return { kind: "ranked", intelligence: pair[0], speed: pair[1] };
};

const formatModelIntelligence = function formatModelIntelligence(metrics) {
  return Number.isFinite(metrics?.intelligence) ? String(metrics.intelligence) : "—";
};

const formatModelSpeed = function formatModelSpeed(metrics) {
  return Number.isFinite(metrics?.speed) ? `${Math.round(metrics.speed)} t/s` : "—";
};

const modelBarPercent = function modelBarPercent(value, max) {
  if (!Number.isFinite(value) || !Number.isFinite(max) || max <= 0) return null;
  return Math.max(0, Math.min(100, (value / max) * 100));
};

const modelSortRank = function modelSortRank(metrics, id) {
  if (metrics?.kind === "picker") return 0;
  if (metrics?.kind === "ranked") return 1;
  if (acb.isPreviewModel(id)) return 3;
  return 2;
};

const compareModelsByIntelligence = function compareModelsByIntelligence(left, right) {
  const a = modelMetrics(left?.model);
  const b = modelMetrics(right?.model);
  const rank = modelSortRank(a, left?.model) - modelSortRank(b, right?.model);
  if (rank) return rank;
  if (a.kind === "ranked") {
    const intelligence = (b.intelligence ?? -1) - (a.intelligence ?? -1);
    if (intelligence) return intelligence;
    const speed = (b.speed ?? -1) - (a.speed ?? -1);
    if (speed) return speed;
    const effort = (MODEL_EFFORT_RANK[parseModelId(right?.model).effort] || 0)
      - (MODEL_EFFORT_RANK[parseModelId(left?.model).effort] || 0);
    if (effort) return effort;
  }
  return String(left?.model || "").localeCompare(String(right?.model || ""));
};

const sortModelsByIntelligence = function sortModelsByIntelligence(models) {
  return [...(models || [])].sort(compareModelsByIntelligence);
};

acb.MODEL_METRICS = MODEL_METRICS;
acb.MODEL_FAMILY_ALIASES = MODEL_FAMILY_ALIASES;
acb.CLAUDE_EFFORT_ALIASES = CLAUDE_EFFORT_ALIASES;
acb.normalizeModelId = normalizeModelId;
acb.parseModelId = parseModelId;
acb.pickModelEffortFromVariants = pickModelEffortFromVariants;
acb.rememberModelMetrics = rememberModelMetrics;
acb.clearLiveModelMetrics = clearLiveModelMetrics;
acb.modelMetrics = modelMetrics;
acb.formatModelIntelligence = formatModelIntelligence;
acb.formatModelSpeed = formatModelSpeed;
acb.modelBarPercent = modelBarPercent;
acb.compareModelsByIntelligence = compareModelsByIntelligence;
acb.sortModelsByIntelligence = sortModelsByIntelligence;
}
