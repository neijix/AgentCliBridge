// node --test tests/ui/wire_contract.test.cjs — run by tests/test_ui_assets.py when node is installed.
// Folds every shared fixture (tests/wire/*.json) with AgentStream.fold; the Python side is
// tests/test_wire.py::test_contract_fixture, so the two folds cannot drift apart.
const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const S = require("../../agent_cli_bridge/ui/stream.js");

const WIRE_DIR = path.join(__dirname, "..", "wire");
const files = fs.readdirSync(WIRE_DIR).filter((name) => name.endsWith(".json")).sort();

test("the shared fixtures exist", () => {
  assert.ok(files.length > 0, `no fixture in ${WIRE_DIR}`);
  assert.ok(files.includes("tool_extras.json"), "tool_extras.json is missing");
});

for (const file of files) {
  test(path.basename(file, ".json"), () => {
    const fixture = JSON.parse(fs.readFileSync(path.join(WIRE_DIR, file), "utf8"));
    const parts = [];
    for (const [name, data] of fixture.frames) S.fold(parts, name, data);
    assert.deepStrictEqual(parts, fixture.parts);
  });
}
