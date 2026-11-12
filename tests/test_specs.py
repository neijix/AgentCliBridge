"""Binary resolution for vendor CLI layouts, including Windows agy.exe."""
import os
from pathlib import Path

from agent_cli_bridge.specs import resolve_binary


def _touch_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    if os.name != "nt":
        path.chmod(0o755)
    return path


def test_resolve_binary_finds_official_windows_agy_layout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    local = tmp_path / "localapp"
    binary = _touch_executable(local / "agy" / "bin" / "agy.exe")
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("agent_cli_bridge.specs.shutil.which", lambda alias: None)
    assert resolve_binary("agy") == str(binary)


def test_resolve_binary_finds_agy_exe_next_to_unix_layout(tmp_path, monkeypatch):
    home = tmp_path / "home"
    binary = _touch_executable(home / ".antigravity" / "Antigravity" / "bin" / "agy.exe")
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("agent_cli_bridge.specs.shutil.which", lambda alias: None)
    assert resolve_binary("agy") == str(binary)


def test_resolve_binary_which_wins_over_well_known_dirs(tmp_path, monkeypatch):
    home = tmp_path / "home"
    _touch_executable(home / ".antigravity" / "Antigravity" / "bin" / "agy")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr("agent_cli_bridge.specs.shutil.which", lambda alias: "/opt/agy")
    assert resolve_binary("agy") == "/opt/agy"


def test_claude_spec_offers_opus_5_5_by_full_id():
    from agent_cli_bridge.argv import model_args
    from agent_cli_bridge.specs import cli_agent_spec

    spec = cli_agent_spec("claude")
    assert "claude-opus-5-5" in spec.models
    # A full id reaches the CLI verbatim — no alias to drift on the next release.
    assert model_args("claude", "claude-opus-5-5") == ["--model", "claude-opus-5-5"]


def test_opencode_is_labeled_open_router():
    from agent_cli_bridge.specs import cli_agent_spec

    spec = cli_agent_spec("opencode")
    assert spec.command == "opencode"
    assert spec.name == "Open Router"


def _found(*agents):
    return lambda: [dict(a) for a in agents]


def test_available_agents_keeps_only_runnable_ones(monkeypatch):
    from agent_cli_bridge import specs

    monkeypatch.setattr(
        specs,
        "discover_agents",
        _found(
            {"command": "claude", "flavor": "claude", "path": "/opt/homebrew/bin/claude", "binary_found": True},
            {"command": "agy", "flavor": "antigravity", "path": None, "binary_found": False},
            {"command": "grok", "flavor": "grok", "path": "/Users/me/.grok/bin/grok", "binary_found": True},
        ),
    )
    assert [a["flavor"] for a in specs.available_agents()] == ["claude", "grok"]


def test_cursor_alias_resolving_to_grok_is_a_collision(monkeypatch):
    from agent_cli_bridge import specs

    cursor_is_grok = {"command": "agent", "flavor": "cursor", "path": "C:\\Users\\me\\.grok\\bin\\agent.exe", "binary_found": True}
    cursor = {"command": "agent", "flavor": "cursor", "path": "/Users/me/.local/bin/agent", "binary_found": True}
    grok = {"command": "grok", "flavor": "grok", "path": "/Users/me/.grok/bin/grok", "binary_found": True}
    assert specs.is_cursor_grok_collision(cursor_is_grok)
    assert not specs.is_cursor_grok_collision(cursor) and not specs.is_cursor_grok_collision(grok)
    monkeypatch.setattr(specs, "discover_agents", _found(cursor_is_grok, grok))
    assert [a["flavor"] for a in specs.available_agents()] == ["grok"]


def _fake_checkout(folder: Path) -> Path:
    """A folder that looks like an AgentCliBridge checkout: the package beside its pyproject.toml."""
    (folder / "agent_cli_bridge").mkdir(parents=True)
    (folder / "agent_cli_bridge" / "specs.py").write_text("", encoding="utf-8")
    (folder / "pyproject.toml").write_text('[project]\nname = "AgentCliBridge"\n', encoding="utf-8")
    return folder


def _old_apps_config(root: Path, content: str) -> Path:
    source = root / "AgentCliBridge" / "agent_cli_bridge.json"
    source.parent.mkdir(parents=True)
    source.write_text(content, encoding="utf-8")
    return source


def test_config_local_none_reads_only_the_home_file_else_defaults(tmp_path, monkeypatch):
    """A friend's view: no shared settings; the local-only home file if any, else built-in defaults."""
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    checkout = _fake_checkout(tmp_path / "AgentCliBridge")
    monkeypatch.setattr(specs, "bridge_checkout", lambda: checkout)
    monkeypatch.setattr(specs, "_migration_tried", set())
    monkeypatch.setenv("APPS_CONFIG_DIR", str(tmp_path / "Sync"))
    _old_apps_config(tmp_path / "Sync", '{"disabled_agents": ["gemini"]}')
    for value in ("none", "", " none "):
        monkeypatch.setenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL", value)
        assert specs.config_local_dir() is None
        assert specs.config_path() == tmp_path / "home" / ".agent_cli_bridge.json"
        assert specs.load_config() == {}
    assert not (checkout / "config.local").exists()  # pinned: no migration


def test_config_local_folder_is_read_first_and_written_back(tmp_path, monkeypatch):
    import json

    from agent_cli_bridge import specs

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    folder = tmp_path / "shared"
    monkeypatch.setenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL", str(folder))
    (home / ".agent_cli_bridge.json").write_text('{"disabled_agents": ["grok"]}', encoding="utf-8")
    assert specs.config_local_dir() == folder
    assert specs.config_path() == home / ".agent_cli_bridge.json"  # no shared file yet: the home one
    shared = folder / "agent_cli_bridge.json"
    folder.mkdir()
    shared.write_text('{"disabled_agents": ["gemini", "copilot"], "models": {"grok": ["g"]}}', encoding="utf-8")
    assert specs.config_path() == shared
    assert specs.disabled_agents() == {"gemini", "copilot"}
    specs.enable_agents({"gemini"})  # written back where it was read, the home file untouched
    assert json.loads(shared.read_text(encoding="utf-8")) == {"disabled_agents": ["copilot"], "models": {"grok": ["g"]}}
    assert json.loads((home / ".agent_cli_bridge.json").read_text(encoding="utf-8")) == {"disabled_agents": ["grok"]}
    assert sorted(p.name for p in folder.iterdir()) == ["agent_cli_bridge.json"]  # no temp file left


def test_checkout_config_local_gets_the_old_apps_config_file_once(tmp_path, monkeypatch):
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    checkout = _fake_checkout(tmp_path / "AgentCliBridge")
    monkeypatch.setattr(specs, "bridge_checkout", lambda: checkout)
    monkeypatch.setattr(specs, "_migration_tried", set())
    monkeypatch.delenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL")
    monkeypatch.setenv("APPS_CONFIG_DIR", str(tmp_path / "Sync"))
    source = _old_apps_config(tmp_path / "Sync", '{"disabled_agents": ["gemini"]}')
    target = checkout / "config.local" / "agent_cli_bridge.json"
    assert specs.config_path() == target
    assert specs.load_config() == {"disabled_agents": ["gemini"]}
    assert source.read_text(encoding="utf-8") == '{"disabled_agents": ["gemini"]}'  # the source stays
    source.write_text('{"disabled_agents": ["grok"]}', encoding="utf-8")
    monkeypatch.setattr(specs, "_migration_tried", set())  # a new process: never over config.local
    assert specs.load_config() == {"disabled_agents": ["gemini"]}
    assert sorted(p.name for p in target.parent.iterdir()) == ["agent_cli_bridge.json"]


def test_no_old_settings_creates_no_config_local(tmp_path, monkeypatch):
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    checkout = _fake_checkout(tmp_path / "AgentCliBridge")
    monkeypatch.setattr(specs, "bridge_checkout", lambda: checkout)
    monkeypatch.setattr(specs, "_migration_tried", set())
    monkeypatch.delenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL")
    (tmp_path / "Sync" / "AgentCliBridge").mkdir(parents=True)  # the folder, but no settings file
    monkeypatch.setenv("APPS_CONFIG_DIR", str(tmp_path / "Sync"))
    assert specs.config_path() == tmp_path / "home" / ".agent_cli_bridge.json"
    assert specs.load_config() == {}
    assert not (checkout / "config.local").exists()


def test_failed_migration_falls_back_and_never_raises(tmp_path, monkeypatch):
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    checkout = _fake_checkout(tmp_path / "AgentCliBridge")
    monkeypatch.setattr(specs, "bridge_checkout", lambda: checkout)
    monkeypatch.setattr(specs, "_migration_tried", set())
    monkeypatch.delenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL")

    def fail(target):
        raise OSError("Resource deadlock avoided")

    monkeypatch.setattr(specs, "migrate_legacy_settings", fail)
    assert specs.config_path() == tmp_path / "home" / ".agent_cli_bridge.json"


def test_bridge_checkout_is_its_own_then_the_apps_sibling_then_the_code_root(tmp_path, monkeypatch):
    from agent_cli_bridge import specs

    assert specs._is_bridge_checkout(Path(__file__).resolve().parents[1])  # this repo counts
    monkeypatch.setattr(specs, "_package_checkout", lambda: tmp_path / "venv" / "site-packages")
    monkeypatch.setattr(specs.sys, "prefix", str(tmp_path / "Code" / "D3SKHAND" / ".venv"))
    monkeypatch.setenv("AI_CODE_ROOT", str(tmp_path / "Other"))
    assert specs.bridge_checkout() is None
    _fake_checkout(tmp_path / "Other" / "AgentCliBridge")
    assert specs.bridge_checkout() == tmp_path / "Other" / "AgentCliBridge"
    sibling = tmp_path / "Code" / "AgentCliBridge"
    sibling.mkdir(parents=True)  # a folder of that name is not enough
    assert specs.bridge_checkout() == tmp_path / "Other" / "AgentCliBridge"
    sibling.rmdir()
    _fake_checkout(sibling)
    assert specs.bridge_checkout() == sibling  # the app's own code root wins
    assert specs.config_local_dir() is None  # conftest pins local only
    monkeypatch.delenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL")
    assert specs.config_local_dir() == sibling / "config.local"


def test_code_root_uses_home_code_and_home_CODE(tmp_path, monkeypatch):
    """Unset ``AI_CODE_ROOT`` searches ``~/Code`` and then ``~/CODE``. An explicit root replaces both."""
    from agent_cli_bridge import specs

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setattr(specs, "_package_checkout", lambda: tmp_path / "site-packages")
    monkeypatch.setattr(specs.sys, "prefix", str(tmp_path / "app" / ".venv"))
    monkeypatch.delenv("AI_CODE_ROOT", raising=False)

    upper = _fake_checkout(home / "CODE" / "AgentCliBridge")
    assert specs.bridge_checkout() == upper
    lower = _fake_checkout(home / "Code" / "AgentCliBridge")
    assert specs.bridge_checkout() == lower
    monkeypatch.setenv("AI_CODE_ROOT", str(tmp_path / "Other"))
    assert specs.bridge_checkout() is None
    pinned = _fake_checkout(tmp_path / "Other" / "AgentCliBridge")
    assert specs.bridge_checkout() == pinned


def test_apps_config_dir_reads_the_marker_file_and_can_be_disabled(tmp_path, monkeypatch):
    from agent_cli_bridge import specs

    home = tmp_path / "home"
    (tmp_path / "Sync" / "AgentCliBridge").mkdir(parents=True)
    home.mkdir()
    (home / ".apps-config-dir").write_text(f"{tmp_path / 'Sync'}\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv("APPS_CONFIG_DIR")
    assert specs.apps_config_dir() == tmp_path / "Sync" / "AgentCliBridge"
    monkeypatch.setenv("APPS_CONFIG_DIR", "none")  # explicitly disabled
    assert specs.apps_config_dir() is None


def test_no_env_var_and_no_marker_file_falls_back_to_the_home_file(tmp_path, monkeypatch):
    """A fresh machine: neither $APPS_CONFIG_DIR nor ~/.apps-config-dir exists."""
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.delenv("APPS_CONFIG_DIR")
    assert specs.apps_config_dir() is None
    assert specs.config_path() == tmp_path / ".agent_cli_bridge.json"
    assert specs.load_config() == {}
    (tmp_path / ".apps-config-dir").write_text(str(tmp_path / "gone"), encoding="utf-8")
    assert specs.apps_config_dir() is None  # marker pointing at a missing folder


def test_unreadable_or_bad_settings_mean_defaults(tmp_path, monkeypatch):
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert specs.load_config() == {}
    (tmp_path / ".agent_cli_bridge.json").write_text("not json", encoding="utf-8")
    assert specs.load_config() == {}
    (tmp_path / ".agent_cli_bridge.json").write_text("[1, 2]", encoding="utf-8")
    assert specs.load_config() == {}


def test_enable_agents_drops_them_from_disabled_and_keeps_the_rest(tmp_path, monkeypatch):
    import json

    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("APPS_CONFIG_DIR", "none")
    path = tmp_path / ".agent_cli_bridge.json"
    path.write_text('{"disabled_agents": ["copilot", "gemini", "mlx"], "models": {"grok": ["g"]}}', encoding="utf-8")
    specs.enable_agents({"gemini", "gemini-flavor"})
    assert json.loads(path.read_text(encoding="utf-8")) == {"disabled_agents": ["copilot", "mlx"], "models": {"grok": ["g"]}}
    before = path.stat().st_mtime_ns
    specs.enable_agents({"claude"})  # not listed: the file is left alone
    assert path.stat().st_mtime_ns == before
    assert specs.disabled_agents() == {"copilot", "mlx"}


def _bad_settings(tmp_path, monkeypatch, text):
    from agent_cli_bridge import specs

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("APPS_CONFIG_DIR", "none")
    monkeypatch.setenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL", "none")
    (tmp_path / ".agent_cli_bridge.json").write_text(text, encoding="utf-8")
    monkeypatch.setattr(specs, "resolve_binary", lambda command: f"/bin/{command}")
    return specs


def test_malformed_setting_values_are_skipped_not_raised(tmp_path, monkeypatch):
    specs = _bad_settings(
        tmp_path, monkeypatch, '{"disabled_agents": ["grok", 7, ["x"], {"a": 1}], "models": ["claude"]}'
    )
    assert specs.disabled_agents() == {"grok"}
    found = {agent["command"]: agent for agent in specs.discover_agents()}
    assert "grok" not in found and found["claude"]["models"]  # the built-in list stands
    specs.enable_agents({"grok"})  # rewrites without raising
    assert specs.disabled_agents() == set()


def test_disabled_agents_that_is_not_a_list_disables_nothing(tmp_path, monkeypatch):
    specs = _bad_settings(tmp_path, monkeypatch, '{"disabled_agents": "grok", "models": {"claude": "opus"}}')
    assert specs.disabled_agents() == set()
    found = {agent["command"]: agent for agent in specs.discover_agents()}
    assert "grok" in found and found["claude"]["models"] != "opus"


def test_custom_models_keep_only_names_and_fall_back_from_command_to_flavor(tmp_path, monkeypatch):
    specs = _bad_settings(tmp_path, monkeypatch, '{"models": {"claude": ["opus", 3, "", null, "sonnet"]}}')
    found = {agent["command"]: agent for agent in specs.discover_agents()}
    assert found["claude"]["models"] == ["opus", "sonnet"]
