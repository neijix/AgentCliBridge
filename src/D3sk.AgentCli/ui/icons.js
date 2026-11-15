// Icons and the DOM helpers the chat box and Settings pages share. Classic script: registers on
// globalThis.__acbUi. components.js, loaded after the other UI scripts, publishes window.AgentUI.
"use strict";
{

globalThis.__acbUi = globalThis.__acbUi || {};
const acb = globalThis.__acbUi;

const SVG_NS = "http://www.w3.org/2000/svg";
let mountCount = 0;

// The one `make`: model_names.js defines it and loads before this file (see ui_assets.UI_FILES).
if (!globalThis.__acbModels || !globalThis.__acbModels.make) {
  throw new Error("icons.js needs model_names.js loaded first");
}
const make = globalThis.__acbModels.make;

const setAttributes = function setAttributes(node, attributes = {}) {
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
};

const button = function button(doc, className, { label = "", title = "", text = "" } = {}) {
  const node = make(doc, "button", className, text);
  node.type = "button";
  if (title) node.title = title;
  if (label) node.setAttribute("aria-label", label);
  return node;
};

const option = function option(doc, value, label) {
  const node = doc.createElement("option");
  node.value = value;
  node.textContent = label;
  return node;
};

// The same strokes in every app. [tag, attributes, children?]; the svg itself is decorative
// (its button carries the label).

const STROKE = { fill: "none", stroke: "currentColor", "stroke-width": "1.8" };
const ICONS = {
  attach: { size: 18, shapes: [["path", { ...STROKE, "stroke-linecap": "round", d: "M12 5v14M5 12h14" }]] },
  slash: {
    size: 18,
    shapes: [
      ["rect", { x: 4, y: 4, width: 16, height: 16, rx: 3.5, ...STROKE }],
      ["path", { ...STROKE, "stroke-linecap": "round", d: "M14 8.5 10 15.5" }],
    ],
  },
  branch: {
    size: 17,
    shapes: [["g", { ...STROKE, "stroke-linecap": "round" }, [
      ["circle", { cx: 6, cy: 5.5, r: 2.2 }],
      ["circle", { cx: 6, cy: 18.5, r: 2.2 }],
      ["circle", { cx: 18, cy: 8, r: 2.2 }],
      ["path", { d: "M6 7.7v8.6M18 10.2c0 4-6 3.3-11 6.6" }],
    ]]],
  },
  globe: {
    size: 16,
    shapes: [["g", STROKE, [
      ["circle", { cx: 12, cy: 12, r: 9 }],
      ["path", { d: "M3 12h18M12 3c2.6 2.6 3.8 5.6 3.8 9s-1.2 6.4-3.8 9c-2.6-2.6-3.8-5.6-3.8-9S9.4 5.6 12 3z" }],
    ]]],
  },
  check: { size: 15, shapes: [["path", { ...STROKE, "stroke-width": "2.2", "stroke-linecap": "round", "stroke-linejoin": "round", d: "M5 12.5 10 17.5 19 7" }]] },
  stop: { size: 14, shapes: [["rect", { x: 5, y: 5, width: 14, height: 14, rx: 2.5, fill: "currentColor" }]] },
  send: {
    size: 16,
    shapes: [["path", { fill: "none", stroke: "currentColor", "stroke-width": "2.2", "stroke-linecap": "round", "stroke-linejoin": "round", d: "M12 19V5M5.5 11.5 12 5l6.5 6.5" }]],
  },
  context: {
    size: 18,
    viewBox: "0 0 32 32",
    shapes: [
      ["circle", { class: "context-ring-bg", cx: 16, cy: 16, r: 12, fill: "none", "stroke-width": 3 }],
      ["circle", { class: "context-ring", cx: 16, cy: 16, r: 12, fill: "none", "stroke-width": 3 }],
    ],
  },
};

const svgShape = function svgShape(doc, [tag, attributes, children = []]) {
  const node = setAttributes(doc.createElementNS(SVG_NS, tag), attributes);
  for (const child of children) node.append(svgShape(doc, child));
  return node;
};

const icon = function icon(doc, name) {
  const { size, viewBox = "0 0 24 24", shapes } = ICONS[name];
  const svg = setAttributes(doc.createElementNS(SVG_NS, "svg"), {
    viewBox, width: size, height: size, "aria-hidden": "true",
  });
  for (const shape of shapes) svg.append(svgShape(doc, shape));
  return svg;
};

// One id per mount, shared by the chat box and Settings so two copies on a page do not clash.
const takeMountId = function takeMountId(prefix) {
  mountCount += 1;
  return `${prefix}-${mountCount}`;
};

acb.make = make;
acb.setAttributes = setAttributes;
acb.button = button;
acb.option = option;
acb.icon = icon;
acb.takeMountId = takeMountId;
}
