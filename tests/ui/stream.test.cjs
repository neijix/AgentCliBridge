// node --test tests/ui/stream.test.cjs — run by tests/test_ui_assets.py when node is installed.
// The fold semantics are covered by the shared fixtures (tests/wire/*.json, wire_contract.test.cjs).
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const S = require("../../agent_cli_bridge/ui/stream.js");

// ── parser ──

function parseChunks(chunks, options) {
  const events = [];
  const parser = S.createParser((name, data) => events.push([name, data]), options);
  for (const chunk of chunks) parser.push(chunk);
  return events;
}

const WHOLE = 'event: text\ndata: {"v":1,"text":"Hi"}\n\nevent: done\ndata: {"v":1,"returncode":0}\n\n';
const WHOLE_EVENTS = [["text", { v: 1, text: "Hi" }], ["done", { v: 1, returncode: 0 }]];

test("the parser dispatches whole frames", () => {
  assert.deepEqual(parseChunks([WHOLE]), WHOLE_EVENTS);
});

test("the parser gives the same frames whatever the chunking", () => {
  for (let size = 1; size <= WHOLE.length; size += 1) {
    const chunks = [];
    for (let at = 0; at < WHOLE.length; at += size) chunks.push(WHOLE.slice(at, at + size));
    assert.deepEqual(parseChunks(chunks), WHOLE_EVENTS, `chunks of ${size}`);
  }
});

test("the parser splits mid-line and mid-field", () => {
  const chunks = ["eve", "nt: te", 'xt\nda', 'ta: {"v":1,', '"text":"a"}', "\n", "\n"];
  assert.deepEqual(parseChunks(chunks), [["text", { v: 1, text: "a" }]]);
});

test("the parser reads CRLF line breaks", () => {
  assert.deepEqual(parseChunks(['event: text\r\ndata: {"a":1}\r\n\r\n']), [["text", { a: 1 }]]);
});

test("the parser reads bare CR line breaks", () => {
  assert.deepEqual(parseChunks(['event: text\rdata: {"a":1}\r\r']), [["text", { a: 1 }]]);
});

test("the parser treats a CR then an LF in the next chunk as one line break", () => {
  // Two breaks would make the blank line after "event: text" dispatch nothing, then data would
  // arrive without a frame end: one break each way gives exactly one frame.
  assert.deepEqual(parseChunks(["event: text\r", '\ndata: {"a":1}\r', "\n\r", "\n"]), [["text", { a: 1 }]]);
  assert.deepEqual(parseChunks(['data: {"a":1}\r', "\n", "\r", "\n"]), [["message", { a: 1 }]]);
});

test("a CR then a lone LF chunk is one break and the next LF chunk is a real one", () => {
  // The lone "\n" is swallowed as the second half of "\r\n"; it must also spend the flag, so the
  // following "\n" chunk ends the line (and the frame) instead of being swallowed too.
  assert.deepEqual(parseChunks(['data: {"a":1}', "\r", "\n", "\n", 'data: {"b":2}\n\n']),
    [["message", { a: 1 }], ["message", { b: 2 }]]);
  assert.deepEqual(parseChunks(['data: {"a":1}\r', "\n", "\n", 'data: {"b":2}\n\n']),
    [["message", { a: 1 }], ["message", { b: 2 }]]);
});

test("an empty chunk does not spend the CR flag", () => {
  assert.deepEqual(parseChunks(['data: {"a":1}\r', "", "\n", "\n"]), [["message", { a: 1 }]]);
});

test("the parser gives the same frames at every chunk size over a mixed CRLF/LF/CR stream", () => {
  const mixed = 'event: text\r\ndata: {"a":1}\r\n\r\nevent: text\ndata: {"b":2}\n\n'
    + 'data: {"c":3}\r\r: keepalive\r\n\r\ndata: {"d":4}\n\r\n';
  const expected = parseChunks([mixed]);
  assert.equal(expected.length, 4);
  for (let size = 1; size <= mixed.length; size += 1) {
    const chunks = [];
    for (let at = 0; at < mixed.length; at += size) chunks.push(mixed.slice(at, at + size));
    assert.deepEqual(parseChunks(chunks), expected, `chunks of ${size}`);
  }
});

test("a bare CR followed by an LF-less chunk is still a break", () => {
  assert.deepEqual(parseChunks(['data: {"a":1}\r', "\rdata: {\"b\":2}\n\n"]), [["message", { a: 1 }], ["message", { b: 2 }]]);
});

test("the parser joins several data lines with a newline", () => {
  const events = parseChunks(["event: text\ndata: {\ndata:  \"a\": 1\ndata: }\n\n"]);
  assert.deepEqual(events, [["text", { a: 1 }]]);
});

test("the parser ignores comment lines (keepalives)", () => {
  const events = parseChunks([": keepalive\n\n", 'event: text\n: mid-frame comment\ndata: {"a":1}\n\n: keepalive\n\n']);
  assert.deepEqual(events, [["text", { a: 1 }]]);
});

test("a frame without a data line dispatches nothing and resets the event name", () => {
  const events = parseChunks(["event: text\n\n", 'data: {"a":1}\n\n']);
  assert.deepEqual(events, [["message", { a: 1 }]]);
});

test("the parser accepts a field without the space after the colon", () => {
  assert.deepEqual(parseChunks(['event:text\ndata:{"a":1}\n\n']), [["text", { a: 1 }]]);
});

test("the parser drops only one space after the colon", () => {
  assert.deepEqual(parseChunks(['event:  x\ndata:  {"a":1}\n\n']), [[" x", { a: 1 }]]);
});

test("the parser ignores unknown fields, id and retry", () => {
  assert.deepEqual(parseChunks(['id: 7\nretry: 100\nfoo: bar\nevent: text\ndata: {"a":1}\n\n']), [["text", { a: 1 }]]);
});

test("the parser names a frame without an event line message", () => {
  assert.deepEqual(parseChunks(['data: {"a":1}\n\n']), [["message", { a: 1 }]]);
});

test("invalid JSON calls onInvalid and dispatches nothing", () => {
  const events = [];
  const invalid = [];
  const parser = S.createParser((name, data) => events.push([name, data]), {
    onInvalid: (name, raw, error) => invalid.push([name, raw, error instanceof Error]),
  });
  parser.push("event: text\ndata: {not json\n\n");
  parser.push('data: {"a":1}\n\n');
  assert.deepEqual(invalid, [["text", "{not json", true]]);
  assert.deepEqual(events, [["message", { a: 1 }]]);
});

test("invalid JSON without onInvalid is skipped and push does not throw", () => {
  assert.deepEqual(parseChunks(["data: {not json\n\n", 'data: {"a":1}\n\n']), [["message", { a: 1 }]]);
});

test("an unterminated frame is not dispatched", () => {
  assert.deepEqual(parseChunks(['data: {"a":1}\n']), []);
});

test("reset drops a half-read frame", () => {
  const events = [];
  const parser = S.createParser((name, data) => events.push([name, data]));
  parser.push("event: text\ndata: {\"a\"");
  parser.reset();
  parser.push('data: {"b":2}\n\n');
  assert.deepEqual(events, [["message", { b: 2 }]]);
});

// ── consume ──

const encoder = new TextEncoder();

function responseOf(chunks, init = {}) {
  const stream = new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
  return new Response(stream, init);
}

async function consumeAll(response, options) {
  const events = [];
  await S.consume(response, (name, data) => events.push([name, data]), options);
  return events;
}

test("consume reads the body to the end", async () => {
  const events = await consumeAll(responseOf([WHOLE.slice(0, 20), WHOLE.slice(20)]));
  assert.deepEqual(events, WHOLE_EVENTS);
});

test("consume decodes a multi-byte character split across chunks", async () => {
  const bytes = encoder.encode('data: {"text":"é€"}\n\n');
  const stream = new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
      controller.close();
    },
  });
  assert.deepEqual(await consumeAll(new Response(stream)), [["message", { text: "é€" }]]);
});

test("consume discards an unterminated final frame", async () => {
  const events = await consumeAll(responseOf(['event: text\ndata: {"a":1}\n\n', "event: text\ndata: {}"]));
  assert.deepEqual(events, [["text", { a: 1 }]]);
});

test("consume resolves with no events on a null body", async () => {
  const response = { ok: true, status: 200, body: null };
  assert.deepEqual(await consumeAll(response), []);
});

test("consume rejects with the status on a non-ok response", async () => {
  await assert.rejects(consumeAll(new Response("nope", { status: 404 })), (error) => {
    assert.equal(error.status, 404);
    assert.ok(error instanceof Error);
    return true;
  });
});

test("consume rejects an already-aborted signal at once, without reading", async () => {
  let isRead = false;
  const response = { ok: true, status: 200, body: { getReader() { isRead = true; } } };
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(consumeAll(response, { signal: controller.signal }), { name: "AbortError" });
  assert.equal(isRead, false);
});

test("consume stops and rejects AbortError when the signal aborts mid-read", async () => {
  let isCancelled = false;
  const stream = new ReadableStream({
    start(controller) { controller.enqueue(encoder.encode('data: {"a":1}\n\n')); },
    pull() { return new Promise(() => {}); }, // the server went quiet
    cancel() { isCancelled = true; },
  });
  const controller = new AbortController();
  const events = [];
  const pending = S.consume(new Response(stream), (name, data) => {
    events.push([name, data]);
    setImmediate(() => controller.abort());
  }, { signal: controller.signal });
  await assert.rejects(pending, { name: "AbortError" });
  assert.deepEqual(events, [["message", { a: 1 }]]);
  assert.equal(isCancelled, true);
});

test("consume propagates a stream failure", async () => {
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(encoder.encode('data: {"a":1}\n\n'));
      controller.error(new TypeError("network error"));
    },
  });
  await assert.rejects(consumeAll(new Response(stream)), TypeError);
});

// ── follow ──

test("follow sends Accept: text/event-stream to fetch and reads the response", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push([url, init]);
    return responseOf([WHOLE]);
  });
  const controller = new AbortController();
  const events = [];
  await S.follow("/events", (name, data) => events.push([name, data]), {
    signal: controller.signal,
    headers: { "X-Test": "1" },
  });
  assert.deepEqual(events, WHOLE_EVENTS);
  assert.equal(calls.length, 1);
  const [url, init] = calls[0];
  assert.equal(url, "/events");
  assert.equal(init.headers.Accept, "text/event-stream");
  assert.equal(init.headers["X-Test"], "1");
  assert.equal(init.cache, "no-store");
  assert.equal(init.signal, controller.signal);
});

test("follow rejects with the status of a non-ok response", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response("", { status: 503 }));
  await assert.rejects(S.follow("/events", () => {}), { status: 503 });
});

// ── fold (only what the shared fixtures cannot express) ──

test("fold mutates parts in place and returns undefined", () => {
  const parts = [];
  const result = S.fold(parts, "text", { v: 1, text: "a" });
  assert.equal(result, undefined);
  assert.deepEqual(parts, [{ type: "text", text: "a" }]);
});

test("fold leaves plain JSON behind", () => {
  const parts = [];
  S.fold(parts, "tool_call", { v: 1, call_id: "c1", name: "Read", arguments: { file_path: "a" }, scout: true });
  S.fold(parts, "tool_result", { v: 1, call_id: "c1", output: "ok", is_error: false });
  assert.deepEqual(JSON.parse(JSON.stringify(parts)), parts);
});

test("fold keeps a __proto__ key from the data as a plain key", () => {
  const parts = [];
  S.fold(parts, "tool_call", JSON.parse('{"call_id":"c1","name":"X","arguments":{},"__proto__":{"polluted":1}}'));
  assert.equal(parts[0].polluted, undefined);
  assert.equal(Object.getPrototypeOf(parts[0]), Object.prototype);
});

test("fold ignores a frame whose data is not an object", () => {
  const parts = [];
  S.fold(parts, "text", null);
  S.fold(parts, "text", "text");
  assert.deepEqual(parts, []);
});

// ── the global ──

test("WIRE_VERSION is 1 and the export is frozen", () => {
  assert.equal(S.WIRE_VERSION, 1);
  assert.equal(Object.isFrozen(S), true);
});

test("the script defines window.AgentStream in a page", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "agent_cli_bridge", "ui", "stream.js"), "utf8");
  const window = {};
  const context = vm.createContext({ window });
  vm.runInContext(source, context);
  assert.deepEqual(Object.keys(window.AgentStream).sort(), Object.keys(S).sort());
  const events = [];
  window.AgentStream.createParser((name, data) => events.push(name)).push('data: {"a":1}\n\n');
  assert.deepEqual(events, ["message"]);
});

test("the script defines globalThis.AgentStream when there is no window", () => {
  const source = fs.readFileSync(path.join(__dirname, "..", "..", "agent_cli_bridge", "ui", "stream.js"), "utf8");
  const context = vm.createContext({});
  vm.runInContext(source, context);
  assert.equal(vm.runInContext("typeof AgentStream.follow", context), "function");
});
