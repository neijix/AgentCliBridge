// Just enough of a browser document for the shared components (components.js) under node --test:
// elements with classes, attributes, events that bubble, simple selectors, <select> values and
// <dialog>. No layout — getBoundingClientRect reads an inline height.

class FakeEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = Boolean(init.bubbles);
    Object.assign(this, init);
    this.defaultPrevented = false;
    this.isPropagationStopped = false;
    this.isImmediateStopped = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.isPropagationStopped = true; }
  stopImmediatePropagation() { this.isPropagationStopped = true; this.isImmediateStopped = true; }
}

class FakeTarget {
  constructor() { this.listeners = {}; }
  addEventListener(type, listener) { (this.listeners[type] ||= []).push(listener); }
  removeEventListener(type, listener) {
    this.listeners[type] = (this.listeners[type] || []).filter((item) => item !== listener);
  }
  fire(event) {
    for (const listener of [...(this.listeners[event.type] || [])]) {
      listener.call(this, event);
      if (event.isImmediateStopped) break;
    }
  }
}

// One compound selector: tag, #id, .class (several), [attr] or [attr="value"].
function parseSelector(text) {
  const parts = { tag: "", id: "", classes: [], attrs: [] };
  const re = /([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g;
  let match;
  while ((match = re.exec(text))) {
    if (match[1]) parts.tag = match[1].toUpperCase();
    else if (match[2]) parts.id = match[2];
    else if (match[3]) parts.classes.push(match[3]);
    else parts.attrs.push([match[4], match[5]]);
  }
  return parts;
}

function matchesOne(node, selector) {
  const { tag, id, classes, attrs } = parseSelector(selector);
  if (tag && node.tagName !== tag) return false;
  if (id && node.id !== id) return false;
  if (classes.some((name) => !node.classList.contains(name))) return false;
  for (const [name, value] of attrs) {
    const actual = node.getAttribute(name);
    if (actual === null || (value !== undefined && actual !== value)) return false;
  }
  return true;
}

class FakeElement extends FakeTarget {
  constructor(doc, tag) {
    super();
    this.ownerDocument = doc;
    this.tagName = tag.toUpperCase();
    this.childNodes = [];
    this.parentNode = null;
    this.attributes = new Map();
    this.style = {};
    this.dataset = {};
    this.hidden = false;
    this.disabled = false;
    this.checked = false;
    this.open = false;
    this.selected = false;
    this._value = "";
    this.selectionStart = 0;
    this.selectionEnd = 0;
    const self = this;
    this.classList = {
      add: (...names) => { for (const name of names) if (!self.classList.contains(name)) self.className = `${self.className} ${name}`.trim(); },
      remove: (...names) => { self.className = self.className.split(/\s+/).filter((name) => name && !names.includes(name)).join(" "); },
      toggle: (name, force) => {
        const isOn = force === undefined ? !self.classList.contains(name) : Boolean(force);
        if (isOn) self.classList.add(name);
        else self.classList.remove(name);
        return isOn;
      },
      contains: (name) => self.className.split(/\s+/).includes(name),
    };
    this.className = "";
  }

  get id() { return this.getAttribute("id") || ""; }
  set id(value) { this.setAttribute("id", value); }
  get children() { return this.childNodes.filter((node) => node instanceof FakeElement); }
  get childElementCount() { return this.children.length; }
  get firstElementChild() { return this.children[0] || null; }

  get textContent() {
    return this.childNodes.map((node) => (node instanceof FakeElement ? node.textContent : String(node))).join("");
  }
  set textContent(text) { this.replaceChildren(...(text === "" || text === null ? [] : [String(text)])); }

  get value() {
    if (this.tagName === "SELECT") {
      const options = this.options;
      return (options.find((option) => option.selected) || options[0])?.value ?? "";
    }
    if (this.tagName === "OPTION" && !this.attributes.has("value")) return this.textContent;
    if (this.tagName === "OPTION") return this.getAttribute("value");
    return this._value;
  }
  set value(value) {
    if (this.tagName === "SELECT") {
      for (const option of this.options) option.selected = option.value === String(value);
      return;
    }
    if (this.tagName === "OPTION") { this.setAttribute("value", value); return; }
    this._value = String(value);
    this.selectionStart = this.selectionEnd = this._value.length;
  }
  get options() { return this.findAll((node) => node.tagName === "OPTION"); }

  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  // As in a browser, an input's type and value show up as attributes once set.
  getAttribute(name) {
    if (this.attributes.has(name)) return this.attributes.get(name);
    if (name === "type" && this.type) return this.type;
    if (name === "value" && this.tagName === "INPUT" && this._value) return this._value;
    return null;
  }
  hasAttribute(name) { return this.attributes.has(name); }
  removeAttribute(name) { this.attributes.delete(name); }

  adopt(nodes) {
    return nodes.map((node) => {
      if (node instanceof FakeElement) {
        node.remove();
        node.parentNode = this;
      }
      return node;
    });
  }
  append(...nodes) { this.childNodes.push(...this.adopt(nodes)); }
  prepend(...nodes) { this.childNodes.unshift(...this.adopt(nodes)); }
  replaceChildren(...nodes) {
    for (const node of this.childNodes) if (node instanceof FakeElement) node.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.childNodes = this.parentNode.childNodes.filter((node) => node !== this);
    this.parentNode = null;
  }
  contains(node) {
    for (let current = node; current; current = current.parentNode) if (current === this) return true;
    return false;
  }

  matches(selector) { return selector.split(",").some((part) => matchesOne(this, part.trim())); }
  closest(selector) {
    for (let node = this; node instanceof FakeElement; node = node.parentNode) if (node.matches(selector)) return node;
    return null;
  }
  findAll(predicate, found = []) {
    for (const child of this.children) {
      if (predicate(child)) found.push(child);
      child.findAll(predicate, found);
    }
    return found;
  }
  // Descendant selectors ("a b") match the last part, then check an ancestor matches the rest.
  querySelectorAll(selector) {
    return this.findAll((node) => selector.split(",").some((alternative) => {
      const steps = alternative.trim().split(/\s+/);
      if (!node.matches(steps[steps.length - 1])) return false;
      let ancestor = node.parentNode;
      for (let index = steps.length - 2; index >= 0; index -= 1) {
        while (ancestor && ancestor !== this && !(ancestor instanceof FakeElement && ancestor.matches(steps[index]))) ancestor = ancestor.parentNode;
        if (!ancestor || ancestor === this) return false;
        ancestor = ancestor.parentNode;
      }
      return true;
    }));
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }

  // As a browser does, the bubbling path is fixed before any handler runs: a handler that
  // redraws (detaching the clicked node) does not stop the click reaching the document.
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    const path = [];
    for (let node = this; node; node = node.parentNode) path.push(node);
    const top = path.at(-1);
    const isInDocument = top === this.ownerDocument.documentElement || top === this.ownerDocument.body;
    for (const node of event.bubbles ? path : [this]) {
      event.currentTarget = node;
      node.fire(event);
      if (event.isPropagationStopped) break;
    }
    if (event.bubbles && !event.isPropagationStopped && isInDocument) this.ownerDocument.dispatchEvent(event);
    return !event.defaultPrevented;
  }
  click() {
    if (this.disabled) return;
    if (this.tagName === "INPUT" && (this.type === "checkbox" || this.type === "radio")) {
      this.checked = this.type === "radio" ? true : !this.checked;
      this.dispatchEvent(new FakeEvent("click", { bubbles: true }));
      this.dispatchEvent(new FakeEvent("change", { bubbles: true }));
      return;
    }
    this.dispatchEvent(new FakeEvent("click", { bubbles: true }));
    if (this.type === "submit") this.closest("form")?.dispatchEvent(new FakeEvent("submit", { bubbles: true }));
  }
  focus() { this.ownerDocument.activeElement = this; }
  setSelectionRange(start, end) { this.selectionStart = start; this.selectionEnd = end; }
  scrollIntoView() {}
  showModal() { this.open = true; }
  close() { this.open = false; this.fire(new FakeEvent("close")); }
  getBoundingClientRect() {
    const height = parseFloat(this.style.height) || 52;
    return { top: 0, left: 0, width: 600, height, bottom: height, right: 600 };
  }
}

class FakeDocument extends FakeTarget {
  constructor() {
    super();
    this.defaultView = new FakeTarget();
    this.defaultView.innerHeight = 900;
    this.defaultView.document = this;
    this.body = new FakeElement(this, "body");
    this.activeElement = this.body;
  }
  createElement(tag) { return new FakeElement(this, tag); }
  createElementNS(namespace, tag) { return new FakeElement(this, tag); }
  dispatchEvent(event) {
    if (!event.target) event.target = this;
    this.fire(event);
    return !event.defaultPrevented;
  }
}

// A key press on `node`: keydown that bubbles, as a browser sends it.
function press(node, key, init = {}) {
  const event = new FakeEvent("keydown", { bubbles: true, key, ...init });
  node.dispatchEvent(event);
  return event;
}

// Typing: set the value, then the input event.
function type(node, text) {
  node.value = text;
  node.dispatchEvent(new FakeEvent("input", { bubbles: true }));
}

function select(node, value) {
  node.value = value;
  node.dispatchEvent(new FakeEvent("change", { bubbles: true }));
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

module.exports = { FakeDocument, FakeElement, FakeEvent, press, type, select, tick };
