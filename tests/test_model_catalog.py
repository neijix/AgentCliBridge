"""Each CLI's own model listing, merged into the curated list."""

import json
import threading
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agent_cli_bridge.model_catalog import (
    FAILURE_TTL,
    GATEWAY_MAX_BYTES,
    REVIEWABLE,
    ModelCatalog,
    fetch_json,
    is_listed,
    is_openrouter_promo,
    may_carry_credentials,
    offered,
    parse_gateway_models,
    parse_models,
    parse_verbose_models,
    read_opencode_catalog,
    run_list,
)

AGY_OUTPUT = """Fetching available models...
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
gemini-3.7-flash-high\tGemini 3.7 Flash (High)
gemini-3.1-pro-high\tGemini 3.1 Pro (High)
claude-opus-4-6-thinking\tClaude Opus 4.6 (Thinking)
"""
GROK_OUTPUT = """You are not authenticated.

Default model: grok-4.7

Available models:
  * grok-4.7 (default)
  - grok-4.7-build-fast
  - grok-4.6
  - grok-4.5
"""


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def agent(command, flavor, models, **extra):
    return {
        "command": command,
        "name": command.title(),
        "flavor": flavor,
        "models": models,
        "binary_found": True,
        "path": f"/bin/{command}",
        **extra,
    }


def test_ids_are_read_from_each_cli_s_own_listing():
    assert parse_models(AGY_OUTPUT) == [
        "gemini-3.8-flash-high",
        "gemini-3.7-flash-high",
        "gemini-3.1-pro-high",
        "claude-opus-4-6-thinking",
    ]
    assert parse_models(GROK_OUTPUT) == ["grok-4.7", "grok-4.7-build-fast", "grok-4.6", "grok-4.5"]
    assert parse_models("\x1b[1mopenrouter/z-ai/glm-5.2:free\x1b[0m\nopencode/big-pickle\n") == [
        "openrouter/z-ai/glm-5.2:free",
        "opencode/big-pickle",
    ]
    assert parse_models("Error: Authentication required. Run 'agent login'.\n") == []


def test_opencode_offers_only_free_and_zen_models_and_grok_efforts_count_as_listed():
    listed = [
        "openrouter/openai/gpt-6",
        "openrouter/z-ai/glm-5.2:free",
        "openrouter/muse-spark-1.3-contributor-free",
        "openrouter/stealth/space-bunny-alpha",
        "opencode/big-pickle",
    ]
    assert offered("opencode", listed) == [
        "openrouter/z-ai/glm-5.2:free",
        "openrouter/muse-spark-1.3-contributor-free",
        "openrouter/stealth/space-bunny-alpha",
        "opencode/big-pickle",
    ]
    assert offered("grok", listed) == listed
    assert is_openrouter_promo("openrouter/muse-spark-1.3-contributor-free")
    assert is_openrouter_promo("openrouter/google/gemma-4-31b-it:free")
    assert is_openrouter_promo("openrouter/stealth/space-bunny-alpha")
    assert not is_openrouter_promo("opencode/big-pickle")
    assert not is_openrouter_promo("openrouter/openai/gpt-6")
    assert is_listed("grok", "grok-4.6-high", {"grok-4.6"})
    assert not is_listed("cursor", "grok-4.6-high", {"grok-4.6"})
    assert is_listed("cursor", "auto", set())


def test_new_models_are_added_and_retired_ones_dropped(tmp_path):
    outputs = {"/bin/agy": AGY_OUTPUT, "/bin/grok": GROK_OUTPUT}
    catalog = ModelCatalog(tmp_path / "known.json", run=lambda argv: outputs[argv[0]])
    agy = agent("agy", "antigravity", ["default", "gemini-3.1-pro-high", "gemini-3.7-flash-high", "gemini-3.1-pro-low"])
    grok = agent("grok", "grok", ["grok-4.6", "grok-4.6-high"])
    claude = agent("claude", "claude", ["sonnet", "opus"])
    catalog.refresh([agy, grok, claude])

    assert catalog.merge(agy) == {
        # gemini-3.1-pro-low is no longer listed; "default" is a setting, never dropped.
        "models": [
            "default",
            "gemini-3.1-pro-high",
            "gemini-3.7-flash-high",
            "gemini-3.8-flash-high",
            "claude-opus-4-6-thinking",
        ],
        "new_models": ["gemini-3.8-flash-high", "claude-opus-4-6-thinking"],
    }
    assert catalog.merge(grok) == {
        "models": ["grok-4.6", "grok-4.6-high", "grok-4.7", "grok-4.7-build-fast", "grok-4.5"],
        "new_models": ["grok-4.7", "grok-4.7-build-fast", "grok-4.5"],
    }
    # Claude Code cannot list its models: its aliases already follow the newest release.
    assert catalog.merge(claude) == {"models": ["sonnet", "opus"], "new_models": []}


def test_a_long_catalog_is_the_baseline_and_only_later_arrivals_are_new(tmp_path):
    first = [f"model-{n}" for n in range(REVIEWABLE + 10)]
    rest = [m for m in first if m != "model-1"]
    listing = {"ids": first}
    cursor = agent("agent", "cursor", ["auto", "model-1"])
    catalog = ModelCatalog(tmp_path / "known.json", run=lambda argv: "\n".join(listing["ids"]))
    catalog.refresh([cursor])
    # The baseline is never announced, but each of its models can be ticked in Settings.
    assert catalog.merge(cursor) == {
        "models": ["auto", "model-1", *rest],
        "new_models": [],
        "optional_models": rest,
    }

    # The baseline survives a node restart; a model that appears later is new.
    listing["ids"] = [*first, "model-99"]
    later = ModelCatalog(tmp_path / "known.json", run=lambda argv: "\n".join(listing["ids"]))
    later.refresh([cursor])
    assert later.merge(cursor) == {
        "models": ["auto", "model-1", "model-99", *rest],
        "new_models": ["model-99"],
        "optional_models": rest,
    }
    assert json.loads((tmp_path / "known.json").read_text())["agent"] == first


def test_a_cli_that_fails_keeps_the_curated_list_and_is_retried_later(tmp_path):
    clock = Clock()
    calls = []

    def run(argv):
        calls.append(argv)
        raise OSError("not signed in")

    grok = agent("grok", "grok", ["grok-4.6"])
    catalog = ModelCatalog(tmp_path / "known.json", run=run, clock=clock)
    catalog.refresh([grok])
    catalog.refresh([grok])
    assert calls == [["/bin/grok", "models"]]  # cached for a while
    assert catalog.merge(grok) == {"models": ["grok-4.6"], "new_models": []}
    clock.now += 6 * 60
    catalog.refresh([grok])
    assert len(calls) == 2


def test_an_answer_is_cached_until_the_cli_is_updated(tmp_path):
    calls = []

    def run(argv):
        calls.append(argv)
        return GROK_OUTPUT

    grok = agent("grok", "grok", ["grok-4.6"])
    catalog = ModelCatalog(tmp_path / "known.json", run=run)
    catalog.refresh([grok])
    catalog.refresh([grok])
    assert len(calls) == 1
    catalog.forget("grok")
    catalog.refresh([grok])
    assert len(calls) == 2


OPENCODE_VERBOSE = """opencode/big-pickle
{
  "id": "big-pickle",
  "cost": {"input": 0, "output": 0, "cache": {"read": 0, "write": 0}},
  "capabilities": {"output": {"text": true}}
}
openrouter/meta/muse-spark-1.3
{
  "id": "meta/muse-spark-1.3",
  "cost": {"input": 1.25, "output": 4.25},
  "capabilities": {"output": {"text": true}}
}
openrouter/qwen/qwen3.8-27b:free
{
  "cost": {"input": 0, "output": 0}
}
openrouter/openrouter/auto
{
  "cost": {"input": 0, "output": 0}
}
openrouter/google/lyria-3-pro
{
  "cost": {"input": 0, "output": 0},
  "capabilities": {"output": {"text": false, "audio": true}}
}
"""


def test_opencode_prices_its_models_and_paid_ones_are_optional_not_new(tmp_path):
    ids, prices = parse_verbose_models(OPENCODE_VERBOSE)
    # A model that cannot write text (music) is not a chat model.
    assert ids == [
        "opencode/big-pickle",
        "openrouter/meta/muse-spark-1.3",
        "openrouter/qwen/qwen3.8-27b:free",
        "openrouter/openrouter/auto",
    ]
    assert prices["openrouter/meta/muse-spark-1.3"] == [1.25, 4.25]
    # A router's price of 0 does not make it free: it bills the model it picks.
    assert offered("opencode", ids, prices) == ["opencode/big-pickle", "openrouter/qwen/qwen3.8-27b:free"]

    calls = []

    def run(argv):
        calls.append(argv)
        return OPENCODE_VERBOSE

    opencode = agent("opencode", "opencode", ["opencode/big-pickle"])
    catalog = ModelCatalog(tmp_path / "known.json", run=run)
    catalog.refresh([opencode])
    assert calls == [["/bin/opencode", "models", "--verbose"]]
    merged = catalog.merge(opencode)
    assert merged["models"] == [
        "opencode/big-pickle",
        "openrouter/qwen/qwen3.8-27b:free",
        "openrouter/meta/muse-spark-1.3",
        "openrouter/openrouter/auto",
    ]
    assert merged["new_models"] == ["openrouter/qwen/qwen3.8-27b:free"]  # paid ones are never "new"
    assert merged["optional_models"] == ["openrouter/meta/muse-spark-1.3", "openrouter/openrouter/auto"]
    assert merged["prices"]["opencode/big-pickle"] == [0.0, 0.0]
    assert "openrouter/google/lyria-3-pro" not in merged["prices"]


def test_listing_models_clears_quarantine_before_the_cli_starts(tmp_path, monkeypatch):
    binary = tmp_path / "grok"
    binary.write_bytes(b"signed")
    events: list[str] = []

    def fake_run(argv, **kwargs):
        events.append("run")
        return type("Result", (), {"returncode": 0, "stdout": "grok-4\n", "stderr": ""})()

    monkeypatch.setattr("agent_cli_bridge.model_catalog.subprocess.run", fake_run)
    monkeypatch.setattr(
        "agent_cli_bridge.model_catalog.clear_macos_quarantine",
        lambda path: events.append(f"clear:{path}") or True,
    )
    assert "grok-4" in run_list([str(binary), "models"])
    assert events == [f"clear:{binary}", "run"]


OPENCODE_2_IDS = """opencode/big-pickle
opencode/muse-spark-1.3-contributor-free
openrouter/qwen/qwen3.8-27b:free
openrouter/openai/gpt-6
openrouter/stealth/space-bunny-alpha
"""


def test_opencode_2_lists_free_models_when_verbose_is_gone(tmp_path):
    # OpenCode 2.0: `models --verbose` exits 1 ("Unrecognized flag: --verbose").
    # The plain id list still has the free models; a retired curated id is dropped.
    calls = []

    def run(argv):
        calls.append(argv)
        if "--verbose" in argv:
            raise RuntimeError("exit 1: Unrecognized flag: --verbose in command opencode models")
        return OPENCODE_2_IDS

    ids, prices = read_opencode_catalog(run, "/bin/opencode")
    assert prices == {}
    assert "openrouter/qwen/qwen3.8-27b:free" in ids
    assert calls == [["/bin/opencode", "models", "--verbose"], ["/bin/opencode", "models"]]

    calls.clear()
    opencode = agent("opencode", "opencode", ["opencode/big-pickle", "openrouter/stealth/union-alpha"])
    catalog = ModelCatalog(tmp_path / "known.json", run=run)
    catalog.refresh([opencode])
    merged = catalog.merge(opencode)
    assert "openrouter/stealth/union-alpha" not in merged["models"]
    assert "opencode/muse-spark-1.3-contributor-free" in merged["new_models"]
    assert "openrouter/qwen/qwen3.8-27b:free" in merged["new_models"]
    assert "openrouter/stealth/space-bunny-alpha" in merged["new_models"]
    assert merged["optional_models"] == ["openrouter/openai/gpt-6"]
    assert "prices" not in merged


# A company gateway's /v1/models (the shape of an AI gateway desktop app on 127.0.0.1:4000).
GATEWAY_ANSWER = {
    "object": "list",
    "has_more": False,
    "data": [
        {
            "id": "claude-opus-5-5[1m]",
            "display_name": "Claude Opus 5.5",
            "type": "chat",
            "output_modalities": ["text"],
            "capabilities": {"tools": True},
            "info": {"input_cost_per_token": 3.0000075e-06, "output_cost_per_token": 1.4999985e-05},
        },
        {
            "id": "databricks-gpt-5-5",
            "display_name": "GPT\n5.5\x00",
            "type": "chat",
            "capabilities": {"tools": True},
            "info": {"input_cost_per_token": 5.00003e-06, "output_cost_per_token": 2.999997e-05},
        },
        {"id": "sonnet", "display_name": "Claude Sonnet (gateway)", "type": "chat"},
        {
            "id": "azr-gpt-6-luna",
            "display_name": "Azr Gpt 6 Luna",
            "type": "chat",
            "capabilities": {"tools": False},
            "info": {"input_cost_per_token": 7.5e-08, "output_cost_per_token": 3.75e-07},
        },
        {
            "id": "unpriced-model",
            "display_name": "unpriced-model",
            "info": {"input_cost_per_token": 0, "output_cost_per_token": 0},
        },
        {"id": "text-embedding-4", "type": "embedding"},
        {"id": "image-writer", "output_modalities": ["image"]},
        {"id": "--dangerously-skip-permissions", "display_name": "not a model id"},
        {"id": "claude-opus-5-5[1m]", "display_name": "a duplicate"},
        "not an entry",
    ],
}
GATEWAY = "http://127.0.0.1:4000"


def test_a_gateway_answer_gives_ids_labels_prices_and_the_models_without_tools():
    found = parse_gateway_models(GATEWAY_ANSWER)
    # Embeddings, image-only models, flag-like ids and duplicates are not chat models.
    assert found.ids == ["claude-opus-5-5[1m]", "databricks-gpt-5-5", "sonnet", "azr-gpt-6-luna", "unpriced-model"]
    # A name equal to its id is no label; control characters and line breaks are spaces.
    assert found.labels == {
        "claude-opus-5-5[1m]": "Claude Opus 5.5",
        "databricks-gpt-5-5": "GPT 5.5",
        "sonnet": "Claude Sonnet (gateway)",
        "azr-gpt-6-luna": "Azr Gpt 6 Luna",
    }
    # Per million tokens; a price of zero is "not priced", not free.
    assert found.prices == {
        "claude-opus-5-5[1m]": [3.0, 15.0],
        "databricks-gpt-5-5": [5.0, 30.0],
        "azr-gpt-6-luna": [0.075, 0.375],
    }
    assert found.toolless == ["azr-gpt-6-luna"]
    # OpenAI's and LiteLLM's shape (no names, no prices), and answers that are no list at all.
    assert parse_gateway_models({"data": [{"id": "gpt-6", "object": "model"}]}).ids == ["gpt-6"]
    assert parse_gateway_models({"data": "nope"}).ids == []
    assert parse_gateway_models(["claude-opus-5-5"]).ids == []
    assert len(parse_gateway_models({"data": [{"id": "m1", "display_name": "x" * 500}]}).labels["m1"]) == 100


def test_claude_code_through_a_gateway_offers_its_list_and_only_later_arrivals_are_new(tmp_path):
    answer = {"data": list(GATEWAY_ANSWER["data"])}
    urls = []

    def fetch(url):
        urls.append(url)
        return answer

    claude = agent("claude", "claude", ["sonnet", "opus"])
    catalog = ModelCatalog(tmp_path / "known.json", fetch=fetch)
    catalog.refresh([claude], claude_gateway=GATEWAY + "/")
    assert urls == ["http://127.0.0.1:4000/v1/models?limit=1000"]
    merged = catalog.merge(claude)
    # Claude Code's aliases stay first (it resolves them itself); the gateway's first read is
    # offered as usual, and a model that cannot call tools waits to be ticked in Settings.
    assert merged["models"] == [
        "sonnet", "opus", "claude-opus-5-5[1m]", "databricks-gpt-5-5", "unpriced-model", "azr-gpt-6-luna",
    ]
    assert merged["new_models"] == []
    assert merged["optional_models"] == ["azr-gpt-6-luna"]
    assert merged["labels"]["sonnet"] == "Claude Sonnet (gateway)"
    assert merged["labels"]["claude-opus-5-5[1m]"] == "Claude Opus 5.5"
    assert merged["prices"]["databricks-gpt-5-5"] == [5.0, 30.0]
    # The first read is kept per gateway, without the models that cannot call tools.
    known = json.loads((tmp_path / "known.json").read_text())
    assert known["claude@127.0.0.1:4000"] == ["claude-opus-5-5[1m]", "databricks-gpt-5-5", "sonnet", "unpriced-model"]

    # After a restart, what the company added since is new (announced, out of the picker until ticked).
    answer["data"].append({"id": "databricks-gemini-3-9-pro", "display_name": "Gemini 3.9 Pro", "type": "chat"})
    later = ModelCatalog(tmp_path / "known.json", fetch=fetch)
    later.refresh([claude], claude_gateway=GATEWAY)
    assert later.merge(claude)["new_models"] == ["databricks-gemini-3-9-pro"]
    assert later.merge(claude)["labels"]["databricks-gemini-3-9-pro"] == "Gemini 3.9 Pro"


def test_without_a_gateway_or_after_it_is_removed_claude_code_keeps_its_curated_list(tmp_path):
    urls = []

    def fetch(url):
        urls.append(url)
        return GATEWAY_ANSWER

    claude = agent("claude", "claude", ["sonnet", "opus"])
    catalog = ModelCatalog(tmp_path / "known.json", fetch=fetch)
    catalog.refresh([claude])
    assert urls == [] and catalog.merge(claude) == {"models": ["sonnet", "opus"], "new_models": []}
    catalog.refresh([claude], claude_gateway=GATEWAY)
    assert "databricks-gpt-5-5" in catalog.merge(claude)["models"]
    catalog.refresh([claude])  # ANTHROPIC_BASE_URL is gone: so is that gateway's list
    assert catalog.merge(claude) == {"models": ["sonnet", "opus"], "new_models": []}
    catalog.refresh([claude], claude_gateway="https://ai.example.com/anthropic")  # another one: read at once
    assert urls[-1] == "https://ai.example.com/anthropic/v1/models?limit=1000"


def test_a_gateway_not_up_yet_is_asked_again_a_minute_later_one_that_refuses_later(tmp_path):
    clock = Clock()
    failure = {"exc": urllib.error.URLError(ConnectionRefusedError(10061, "refused"))}
    calls = []

    def fetch(url):
        calls.append(url)
        raise failure["exc"]

    claude = agent("claude", "claude", ["sonnet"])
    catalog = ModelCatalog(tmp_path / "known.json", fetch=fetch, clock=clock)
    catalog.refresh([claude], claude_gateway=GATEWAY)
    catalog.refresh([claude], claude_gateway=GATEWAY)
    assert len(calls) == 1 and catalog.merge(claude) == {"models": ["sonnet"], "new_models": []}
    clock.now += 61
    failure["exc"] = urllib.error.HTTPError(GATEWAY, 401, "Unauthorized", {}, None)  # refuses: asked again later
    catalog.refresh([claude], claude_gateway=GATEWAY)
    assert len(calls) == 2
    clock.now += 61
    catalog.refresh([claude], claude_gateway=GATEWAY)
    assert len(calls) == 2
    clock.now += FAILURE_TTL
    catalog.refresh([claude], claude_gateway=GATEWAY)
    assert len(calls) == 3


class _Gateway(BaseHTTPRequestHandler):
    seen: list[tuple[str, dict[str, str]]] = []
    body = b"{}"

    def do_GET(self):  # noqa: N802 — http.server's name
        type(self).seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        if self.path.startswith("/moved"):
            self.send_response(302)
            self.send_header("Location", "/v1/models")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):
        pass


@pytest.fixture
def gateway():
    _Gateway.seen = []
    _Gateway.body = json.dumps(GATEWAY_ANSWER).encode()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Gateway)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_a_gateway_gets_only_the_headers_it_is_given_and_a_redirect_is_refused(gateway):
    assert fetch_json(f"{gateway}/v1/models?limit=1000")["data"][0]["id"] == "claude-opus-5-5[1m]"
    path, headers = _Gateway.seen[0]
    assert path == "/v1/models?limit=1000"
    assert not {"authorization", "x-api-key", "cookie", "proxy-authorization"} & set(headers)
    fetch_json(f"{gateway}/v1/models", headers={"Authorization": "Bearer t"})
    assert _Gateway.seen[1][1]["authorization"] == "Bearer t"
    with pytest.raises(urllib.error.HTTPError):
        fetch_json(f"{gateway}/moved", headers={"Authorization": "Bearer t"})
    # The redirect is never followed, so the token never reaches where it points.
    assert [seen[0] for seen in _Gateway.seen] == ["/v1/models?limit=1000", "/v1/models", "/moved"]


def test_the_catalog_reads_a_gateway_with_its_credentials_only_over_https_or_loopback(tmp_path):
    calls = []

    def fetch(url, headers=None):
        calls.append((url, headers))
        return GATEWAY_ANSWER

    claude = agent("claude", "claude", ["sonnet"])
    token = {"Authorization": "Bearer t"}
    for base in ("https://adb-1.azuredatabricks.net/ai-gateway/anthropic", "http://127.0.0.1:4000",
                 "http://localhost:4000", "http://ai.example.com"):
        ModelCatalog(tmp_path / "known.json", fetch=fetch).refresh(
            [claude], claude_gateway=base, claude_gateway_headers=token
        )
    assert calls == [
        ("https://adb-1.azuredatabricks.net/ai-gateway/anthropic/v1/models?limit=1000", token),
        ("http://127.0.0.1:4000/v1/models?limit=1000", token),
        ("http://localhost:4000/v1/models?limit=1000", token),
        ("http://ai.example.com/v1/models?limit=1000", None),  # cleartext across the network: no token
    ]
    assert may_carry_credentials("https://ai.example.com") and not may_carry_credentials("ftp://127.0.0.1")


def test_only_an_http_url_without_credentials_is_read_and_never_a_huge_answer(gateway):
    host = gateway.removeprefix("http://")
    for url in ("file:///etc/hosts", f"ftp://{host}/models", f"http://user:secret@{host}/v1/models"):
        with pytest.raises(ValueError):
            fetch_json(url)
    assert _Gateway.seen == []
    _Gateway.body = b" " * (GATEWAY_MAX_BYTES + 1)
    with pytest.raises(ValueError, match="over"):
        fetch_json(f"{gateway}/v1/models")


def test_a_loopback_gateway_is_read_even_when_a_proxy_is_set(gateway, monkeypatch):
    """The shared GET skips the proxy for a loopback host. A dead proxy must not be used."""
    dead = "http://127.0.0.1:9"
    for name in ("http_proxy", "https_proxy", "all_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, dead)
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    assert fetch_json(f"{gateway}/v1/models")["data"][0]["id"] == "claude-opus-5-5[1m]"


def test_the_shared_get_allows_https_and_stops_at_the_callers_limit(monkeypatch):
    from agent_cli_bridge.http_get import get_bytes

    class _Body:
        def __init__(self, payload: bytes) -> None:
            self._payload = payload

        def read(self, size: int = -1) -> bytes:
            if not self._payload:
                return b""
            take = len(self._payload) if size < 0 else size
            chunk, self._payload = self._payload[:take], self._payload[take:]
            return chunk

        def __enter__(self) -> "_Body":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

    opened: list[str] = []

    def fake(request, timeout):
        opened.append(request.full_url)
        assert timeout == 4
        return _Body(b"abcd")

    monkeypatch.setattr("agent_cli_bridge.http_get.urlopen", fake)
    assert get_bytes("https://example.com/board", 4, timeout=4) == b"abcd"
    assert opened == ["https://example.com/board"]
    with pytest.raises(ValueError, match="over"):
        get_bytes("https://example.com/board", 3, timeout=4)
    opened.clear()
    for url in ("https://user:secret@example.com/board", "file:///etc/hosts", "ftp://example.com/board"):
        with pytest.raises(ValueError):
            get_bytes(url, 10, timeout=4)
    assert opened == []


def test_rankings_refresh_with_models_and_whenever_a_cli_lists_new_models(tmp_path):
    from agent_cli_bridge.model_ranking import clear_live_metrics

    clock = Clock()
    cli_output = {"text": "gemini-4-argon-high\n"}
    ranking_calls = 0

    def run(argv):
        return cli_output["text"]

    def fetch_rankings():
        nonlocal ranking_calls
        ranking_calls += 1
        return {
            "gemini-4-argon": {"high": [53, 82]},
            "gemini-5-ultra": {"high": [61, 120]},
        }

    try:
        agy = agent("agy", "antigravity", ["gemini-4-argon-high"])
        catalog = ModelCatalog(
            tmp_path / "known.json",
            run=run,
            fetch_rankings=fetch_rankings,
            clock=clock,
        )
        catalog.refresh([agy])
        assert ranking_calls == 1
        merged = catalog.merge(agy)
        assert merged["metrics"]["gemini-4-argon-high"] == [53, 82]
        assert json.loads((tmp_path / "models-metrics.json").read_text(encoding="utf-8"))["gemini-5-ultra"] == {
            "high": [61, 120]
        }

        # While the cache is fresh and the CLI list has not changed, rankings are not re-fetched.
        catalog.refresh([agy])
        assert ranking_calls == 1

        # When a CLI updates and lists a new model after `forget`, rankings are re-fetched immediately.
        cli_output["text"] = "gemini-4-argon-high\ngemini-5-ultra-high\n"
        catalog.forget("agy")
        catalog.refresh([agy])
        assert ranking_calls == 2
        merged_after = catalog.merge(agy)
        assert merged_after["metrics"]["gemini-5-ultra-high"] == [61, 120]
    finally:
        clear_live_metrics()


def test_a_verbose_block_of_the_wrong_shape_is_skipped_not_raised():
    text = (
        'openrouter/a/one\n{"capabilities": ["text"], "cost": [1, 2]}\n'
        'openrouter/a/two\n{"capabilities": {"output": "text"}, "cost": {"input": 1, "output": 2}}\n'
        'openrouter/a/three\n[1, 2]\n'
    )
    ids, prices = parse_verbose_models(text)
    assert ids == ["openrouter/a/one", "openrouter/a/two", "openrouter/a/three"]
    assert prices == {"openrouter/a/two": [1.0, 2.0]}
