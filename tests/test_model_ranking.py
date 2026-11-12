"""The Python ranking (model_ranking.py) is the page's (ui/models.js), and reads the ids each CLI uses."""

import json
import shutil
import subprocess

import pytest

from agent_cli_bridge import model_ranking
from agent_cli_bridge.effort import CLAUDE_EFFORT_ALIASES
from agent_cli_bridge.ui_assets import UI_DIR

# effort.py is the only map for these four names. Ranking must not send them to an older id.
SHORT_NAME_ALIASES = {
    "opus": "claude-opus-5-5",
    "sonnet": "claude-sonnet-5-5",
    "haiku": "claude-haiku-5-5",
    "fable": "claude-fable-5-1",
}


def test_model_power_reads_the_ids_each_cli_uses():
    assert model_ranking.model_power("opus") == 54
    assert model_ranking.model_power("claude-opus-5-5-high") == 54
    assert model_ranking.model_power("claude-opus-5-5[1m]") == 54
    assert model_ranking.model_power("cursor-grok-4.6-high") == 44
    assert model_ranking.model_power("claude-opus-4-6-thinking") == 39
    assert model_ranking.model_power("gemini-4-argon-high") == 53
    assert model_ranking.model_power("gemini-4-argon-medium") == 53
    assert model_ranking.model_power("gemini-4-argon-low") == 53
    assert model_ranking.model_metrics("gemini-4-argon-high") == (53, 82)
    assert model_ranking.model_power("gemini-3.1-pro-preview") == 30
    assert model_ranking.model_power("openrouter/qwen/qwen3.8-27b:free") == 20
    assert model_ranking.model_power("auto") is None
    assert model_ranking.model_power("default") is None
    assert model_ranking.model_power("mystery-model") is None
    assert model_ranking.model_power(None) is None


def test_short_name_aliases_match_effort():
    assert CLAUDE_EFFORT_ALIASES == SHORT_NAME_ALIASES
    assert not (set(CLAUDE_EFFORT_ALIASES) & set(model_ranking.MODEL_FAMILY_ALIASES))
    for short, canonical in CLAUDE_EFFORT_ALIASES.items():
        ranked = model_ranking.model_metrics(short)
        assert ranked is not None
        assert ranked == model_ranking.model_metrics(canonical)
    # The older rows stay ranked on their own ids, and the short names do not use them.
    assert model_ranking.model_metrics("sonnet") != model_ranking.model_metrics("claude-sonnet-5")
    assert model_ranking.model_metrics("haiku") != model_ranking.model_metrics("claude-haiku-4-5")
    assert model_ranking.model_metrics("claude-sonnet") == model_ranking.model_metrics("claude-sonnet-5")
    assert model_ranking.model_metrics("claude-haiku") == model_ranking.model_metrics("claude-haiku-4-5")


def test_short_name_without_metrics_uses_the_unknown_model_path(monkeypatch):
    kept = {
        family: variants
        for family, variants in model_ranking.MODEL_METRICS.items()
        if family not in CLAUDE_EFFORT_ALIASES.values()
    }
    monkeypatch.setattr(model_ranking, "MODEL_METRICS", kept)
    try:
        model_ranking.clear_live_metrics()
        for short, canonical in CLAUDE_EFFORT_ALIASES.items():
            assert model_ranking.model_power(short) is None
            assert model_ranking.model_power(canonical) is None
        # Missing canonical rows must not fall through to these older families.
        assert model_ranking.model_power("claude-sonnet-5") == 32
        assert model_ranking.model_power("claude-haiku-4-5") == 17
        assert model_ranking.model_power("mystery-model") is None
    finally:
        model_ranking.clear_live_metrics()


def test_parse_leaderboard_models_and_live_metrics_overlay():
    rsc_payload = json.dumps({
        "models": [
            {
                "slug": "gemini-4-argon",
                "short_name": "Gemini 4 Argon (High)",
                "intelligence_index": 53.4,
                "timescaleData": {"median_output_speed": 82.1},
            },
            {
                "slug": "gpt-6-1-sol-max",
                "short_name": "GPT-6.1 Sol (Max)",
                "intelligence_index": 54.0,
                "timescaleData": {"median_output_speed": 61.2},
            },
            {
                "slug": "future-omega-2",
                "short_name": "Future Omega 2 (Low Effort)",
                "intelligence_index": 49.0,
                "timescaleData": {"median_output_speed": 140.0},
            },
        ]
    })
    html = f"<script>self.__next_f.push([1,{json.dumps(rsc_payload)}])</script>"
    parsed = model_ranking.parse_leaderboard_models(html)
    assert parsed["gemini-4-argon"]["high"] == [53, 82]
    assert parsed["gpt-6-1-sol"]["max"] == [54, 61]
    assert parsed["future-omega-2"]["low"] == [49, 140]

    try:
        model_ranking.update_live_metrics(parsed)
        # Canonical dot/hyphen matching maps `gpt-6.1-sol-max` to `gpt-6-1-sol`.
        assert model_ranking.model_metrics("gpt-6.1-sol-max") == (54, 61)
        assert model_ranking.model_metrics("future-omega-2-low") == (49, 140)
        assert model_ranking.model_power("future-omega-2") == 49
    finally:
        model_ranking.clear_live_metrics()


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_python_table_matches_the_one_the_settings_page_shows():
    script = (
        f"const m = require({json.dumps(str(UI_DIR / 'models.js'))});"
        "const out = {};"
        "for (const [k, v] of Object.entries(m.MODEL_METRICS))"
        "  out[k] = Object.fromEntries(Object.entries(v).map(([e, p]) => [e, p[0]]));"
        "console.log(JSON.stringify({metrics: out, aliases: m.MODEL_FAMILY_ALIASES}));"
    )
    data = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    assert data["metrics"] == model_ranking.MODEL_INTELLIGENCE
    assert data["aliases"] == model_ranking.MODEL_FAMILY_ALIASES
    # And the page ranks the same ids the same way.
    ids = ["opus", "cursor-grok-4.6-high", "claude-opus-4-6-thinking", "gemini-3.1-pro-preview", "auto", "mystery-model"]
    script = (
        f"const m = require({json.dumps(str(UI_DIR / 'models.js'))});"
        f"console.log(JSON.stringify({json.dumps(ids)}.map((id) => m.modelMetrics(id).intelligence ?? null)));"
    )
    page = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    assert page == [model_ranking.model_power(model) for model in ids]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_short_name_aliases_match_the_page():
    names = [*SHORT_NAME_ALIASES.keys(), *SHORT_NAME_ALIASES.values(), "claude-sonnet-5", "claude-haiku-4-5"]
    script = (
        f"const m = require({json.dumps(str(UI_DIR / 'models.js'))});"
        f"const names = {json.dumps(names)};"
        "const score = (id) => { const row = m.modelMetrics(id); return row.intelligence ?? null; };"
        "const before = Object.fromEntries(names.map((id) => [id, score(id)]));"
        "const familyHas = Object.fromEntries(Object.keys(m.CLAUDE_EFFORT_ALIASES).map("
        "(name) => [name, Object.prototype.hasOwnProperty.call(m.MODEL_FAMILY_ALIASES, name)]));"
        "for (const id of Object.values(m.CLAUDE_EFFORT_ALIASES)) delete m.MODEL_METRICS[id];"
        "const after = Object.fromEntries(names.map((id) => [id, {kind: m.modelMetrics(id).kind, intelligence: score(id)}]));"
        "console.log(JSON.stringify({aliases: m.CLAUDE_EFFORT_ALIASES, familyHas, before, after}));"
    )
    data = json.loads(subprocess.run(["node", "-e", script], capture_output=True, text=True, check=True).stdout)
    assert data["aliases"] == CLAUDE_EFFORT_ALIASES
    assert data["familyHas"] == {name: False for name in CLAUDE_EFFORT_ALIASES}
    for short, canonical in CLAUDE_EFFORT_ALIASES.items():
        assert data["before"][short] == model_ranking.model_power(short)
        assert data["before"][canonical] == model_ranking.model_power(canonical)
        assert data["after"][short] == {"kind": "unknown", "intelligence": None}
        assert data["after"][canonical] == {"kind": "unknown", "intelligence": None}
    assert data["after"]["claude-sonnet-5"]["intelligence"] == 32
    assert data["after"]["claude-haiku-4-5"]["intelligence"] == 17


def test_leaderboard_fetch_uses_the_shared_get_and_names_its_limit(monkeypatch):
    seen = {}

    def fake(url, max_bytes, *, timeout, headers=None):
        seen["url"] = url
        seen["max"] = max_bytes
        seen["timeout"] = timeout
        return (
            b'{"initialModels":[{"slug":"demo","intelligenceIndex":40,'
            b'"medianOutputTokensPerSecond":12}]}'
        )

    monkeypatch.setattr(model_ranking, "get_bytes", fake)
    assert model_ranking.fetch_leaderboard_metrics() == {"demo": {"high": [40, 12]}}
    assert seen == {
        "url": model_ranking.LEADERBOARD_URL,
        "max": model_ranking.LEADERBOARD_MAX_BYTES,
        "timeout": model_ranking.LEADERBOARD_TIMEOUT,
    }
