// The chat event stream every host page shares — the SSE parser, the fetch reader and the fold
// that turns the frames into the stored message parts. The frames come from agent_cli_bridge/wire.py
// (`event: <name>` + one JSON data line, every data carrying "v"); `fold` here and `fold` there give
// the same parts (tests/wire/*.json, checked by both). No dependency.
// Plain script, no build step: served as /acb/stream.js it defines window.AgentStream; under
// node it is a CommonJS module (the tests) and globalThis.AgentStream.
(function (root) {
  "use strict";

  const WIRE_VERSION = 1;

  // ── parser ──

  // An incremental SSE parser (the WHATWG subset the wire uses). `push(text)` takes any slice of the
  // stream; every complete frame calls onEvent(name, data). A frame whose data is not JSON calls
  // onInvalid(name, rawData, error) when given and is otherwise skipped: push never throws for it.
  function createParser(onEvent, { onInvalid } = {}) {
    let pending = ""; // the unfinished last line
    let isAfterCarriageReturn = false; // the last chunk ended in "\r": a leading "\n" is the same break
    let eventName = "";
    let dataLines = [];

    function dispatch() {
      const name = eventName || "message";
      const lines = dataLines;
      eventName = "";
      dataLines = [];
      if (!lines.length) return;
      const raw = lines.join("\n");
      let data;
      try {
        data = JSON.parse(raw);
      } catch (error) {
        if (onInvalid) onInvalid(name, raw, error);
        return;
      }
      onEvent(name, data);
    }

    function handleLine(line) {
      if (line === "") return dispatch();
      if (line.startsWith(":")) return; // a comment: the keepalive
      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      let value = colon === -1 ? "" : line.slice(colon + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") eventName = value;
      else if (field === "data") dataLines.push(value);
      // id, retry and unknown fields are ignored
    }

    function push(text) {
      let chunk = String(text);
      if (!chunk) return;
      if (isAfterCarriageReturn) {
        // The first byte after a "\r" spends the flag, even when it is the "\n" that leaves nothing
        // to read: a "\n" opening the next chunk is then a real line break of its own.
        isAfterCarriageReturn = false;
        if (chunk.startsWith("\n")) chunk = chunk.slice(1);
        if (!chunk) return;
      }
      pending += chunk;
      const breaks = /\r\n|\r|\n/g;
      const lines = [];
      let start = 0;
      let match;
      while ((match = breaks.exec(pending)) !== null) {
        lines.push(pending.slice(start, match.index));
        start = match.index + match[0].length;
        if (match[0] === "\r" && start === pending.length) isAfterCarriageReturn = true;
      }
      pending = pending.slice(start);
      // After the buffer is settled, so a host callback that throws cannot replay a line.
      for (const line of lines) handleLine(line);
    }

    function reset() {
      pending = "";
      isAfterCarriageReturn = false;
      eventName = "";
      dataLines = [];
    }

    return { push, reset };
  }

  // ── fetch ──

  function abortError() {
    if (typeof DOMException === "function") return new DOMException("The stream was aborted.", "AbortError");
    const error = new Error("The stream was aborted.");
    error.name = "AbortError";
    return error;
  }

  // Reads a fetch Response body to its end, calling onEvent(name, data) for each frame. Resolves when
  // the body ends (an unterminated final frame is discarded); rejects with `.status` on a non-ok
  // response and with an AbortError when `signal` aborts.
  async function consume(response, onEvent, { signal } = {}) {
    if (signal?.aborted) throw abortError();
    if (!response.ok) {
      const error = new Error(`The stream answered HTTP ${response.status}.`);
      error.status = response.status;
      throw error;
    }
    if (!response.body) return;
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    const parser = createParser(onEvent);
    let onAbort = null;
    const aborted = new Promise((resolve, reject) => {
      onAbort = () => reject(abortError());
      signal?.addEventListener("abort", onAbort, { once: true });
    });
    aborted.catch(() => {}); // only ever raced below
    let isFinished = false;
    try {
      for (;;) {
        const { done, value } = await Promise.race([reader.read(), aborted]);
        if (signal?.aborted) throw abortError();
        if (done) break;
        parser.push(decoder.decode(value, { stream: true }));
      }
      parser.push(decoder.decode());
      isFinished = true;
    } finally {
      signal?.removeEventListener("abort", onAbort);
      if (!isFinished) await reader.cancel().catch(() => {});
    }
  }

  // fetch + consume: the page's one call to follow a stream.
  async function follow(url, onEvent, { signal, headers } = {}) {
    const response = await globalThis.fetch(url, {
      signal,
      headers: { Accept: "text/event-stream", ...headers },
      cache: "no-store",
    });
    return consume(response, onEvent, { signal });
  }

  // ── fold ──

  // Same semantics as agent_cli_bridge.wire.fold (tests/wire/*.json): the stored message shape.
  const NEVER_COPIED = { tool_call: ["v", "type", "done", "call_id", "name", "arguments"],
    tool_result: ["v", "type", "done", "call_id", "output", "is_error"] };

  // defineProperty, so a data key named "__proto__" stays a plain key instead of changing the part.
  function setOwn(target, key, value) {
    Object.defineProperty(target, key, { value, writable: true, enumerable: true, configurable: true });
  }

  function copyExtras(part, data, name) {
    const skipped = NEVER_COPIED[name];
    for (const key of Object.keys(data)) {
      if (!skipped.includes(key)) setOwn(part, key, data[key]);
    }
  }

  function fold(parts, name, data) {
    if (!data || typeof data !== "object") return;
    if (name === "text" || name === "thinking") {
      const text = data.text ?? "";
      const last = parts[parts.length - 1];
      if (last && last.type === name) last.text += text;
      else parts.push({ type: name, text });
    } else if (name === "tool_call") {
      const part = {
        type: "tool", call_id: data.call_id ?? null, name: data.name ?? null, arguments: data.arguments ?? null,
        output: "", is_error: false, done: false,
      };
      copyExtras(part, data, name);
      parts.push(part);
    } else if (name === "tool_result") {
      for (let index = parts.length - 1; index >= 0; index -= 1) {
        const part = parts[index];
        if (part.type !== "tool" || part.call_id !== (data.call_id ?? null)) continue;
        part.output = data.output ?? "";
        part.is_error = data.is_error ?? false;
        part.done = true;
        copyExtras(part, data, name);
        return;
      }
    }
    // every other name (session, error, done, approval_request, an app's own) changes nothing
  }

  const AgentStream = Object.freeze({ WIRE_VERSION, createParser, consume, follow, fold });
  if (typeof module !== "undefined" && module.exports) module.exports = AgentStream;
  if (root) root.AgentStream = AgentStream;
  // A page's window; else the global object (a vm-run page in a test, or node), so a host script
  // that reads AgentStream by name finds it there too.
})(typeof window !== "undefined" ? window : typeof globalThis !== "undefined" ? globalThis : null);
