import json

from agent_cli_bridge.claude_account import claude_account, claude_gateway, claude_profile_dir, claude_profile_env


def _home(tmp_path, *, settings_env=None, organization=None):
    if settings_env is not None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(json.dumps({"env": settings_env}))
    if organization is not None:
        account = {"accountUuid": "u1", "organizationType": organization}
        (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    return tmp_path


def test_a_company_gateway_in_the_environment_is_the_work_account(tmp_path):
    home = _home(tmp_path, organization="claude_max")
    env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"}
    assert claude_account(home, env) == {"kind": "work", "detail": "127.0.0.1:4000"}


def test_a_gateway_in_claude_settings_counts_too(tmp_path):
    home = _home(tmp_path, settings_env={"ANTHROPIC_BASE_URL": "https://ai.example.com/anthropic"})
    assert claude_account(home, {}) == {"kind": "work", "detail": "ai.example.com"}


def test_anthropics_own_api_url_is_not_a_gateway(tmp_path):
    home = _home(tmp_path, organization="claude_max")
    env = {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
    assert claude_account(home, env) == {"kind": "personal", "detail": "Max"}


def test_a_cloud_provider_is_the_work_account(tmp_path):
    assert claude_account(tmp_path, {"CLAUDE_CODE_USE_BEDROCK": "1"}) == {"kind": "work", "detail": "Bedrock"}
    assert claude_account(tmp_path, {"CLAUDE_CODE_USE_VERTEX": "0"}) is None


def test_a_claude_ai_sign_in_is_personal_unless_its_organization_is_a_company(tmp_path):
    assert claude_account(_home(tmp_path, organization="claude_pro"), {}) == {"kind": "personal", "detail": "Pro"}
    (tmp_path / ".claude.json").unlink()
    assert claude_account(_home(tmp_path, organization="claude_enterprise"), {}) == {
        "kind": "work",
        "detail": "Enterprise",
    }


def test_no_sign_in_and_no_gateway_gives_no_tag(tmp_path):
    assert claude_account(tmp_path, {}) is None
    (tmp_path / ".claude.json").write_text("not json")
    assert claude_account(tmp_path, {}) is None


def test_the_gateway_is_the_base_url_claude_code_talks_to(tmp_path):
    assert claude_gateway(tmp_path, {"ANTHROPIC_BASE_URL": " http://127.0.0.1:4000 "}) == "http://127.0.0.1:4000"
    # Claude Code's settings.json env wins over the process's, as it does for Claude Code itself.
    home = _home(tmp_path, settings_env={"ANTHROPIC_BASE_URL": "https://ai.example.com/anthropic"})
    assert claude_gateway(home, {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000"}) == "https://ai.example.com/anthropic"


def test_anthropic_a_cloud_provider_or_a_url_that_is_not_http_has_no_gateway(tmp_path):
    assert claude_gateway(tmp_path, {}) is None
    assert claude_gateway(tmp_path, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}) is None
    bedrock = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:4000", "CLAUDE_CODE_USE_BEDROCK": "1"}
    assert claude_gateway(tmp_path, bedrock) is None
    assert claude_gateway(tmp_path, {"ANTHROPIC_BASE_URL": "file:///etc/hosts"}) is None
    assert claude_gateway(tmp_path, {"ANTHROPIC_BASE_URL": "ftp://files.example.com"}) is None


def test_a_port_that_is_not_a_number_is_no_gateway_and_no_crash(tmp_path):
    env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:port"}
    assert claude_gateway(tmp_path, env) is None
    assert claude_account(tmp_path, env) is None


def _profiles(home, root, config_dir):
    (home / ".claude-profiles").write_text(f"{root.resolve().as_posix()}\t{config_dir}\n", encoding="utf-8")


def test_a_session_inside_a_code_root_gets_its_claude_profile(tmp_path):
    root = tmp_path / "WorkCode"
    (root / "proj" / "sub").mkdir(parents=True)
    (tmp_path / "Code").mkdir()
    _profiles(tmp_path, root, "/profiles/work")
    assert claude_profile_dir(tmp_path, root / "proj" / "sub") == "/profiles/work"
    assert claude_profile_env({"A": "1"}, root / "proj", home=tmp_path) == {"A": "1", "CLAUDE_CONFIG_DIR": "/profiles/work"}
    # outside every root, and a sibling whose name only starts like the root: unchanged
    assert claude_profile_env({"A": "1"}, tmp_path / "Code", home=tmp_path) == {"A": "1"}
    (tmp_path / "WorkCodeOld").mkdir()
    assert claude_profile_dir(tmp_path, tmp_path / "WorkCodeOld") is None


def test_an_explicit_claude_config_dir_wins_over_the_profile(tmp_path):
    root = tmp_path / "WorkCode"
    root.mkdir()
    _profiles(tmp_path, root, "/profiles/work")
    env = {"CLAUDE_CONFIG_DIR": "/mine"}
    assert claude_profile_env(env, root, home=tmp_path) == env


def test_no_profile_record_changes_nothing(tmp_path):
    assert claude_profile_env({"A": "1"}, tmp_path, home=tmp_path) == {"A": "1"}


def test_the_account_follows_claude_config_dir(tmp_path):
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "settings.json").write_text(json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://gw.example"}}))
    (tmp_path / "home").mkdir()
    home = _home(tmp_path / "home", organization="claude_max")
    env = {"CLAUDE_CONFIG_DIR": str(profile)}
    assert claude_account(home, env) == {"kind": "work", "detail": "gw.example"}
    assert claude_gateway(home, env) == "https://gw.example"
    account = {"accountUuid": "u2", "organizationType": "claude_pro"}
    (profile / "settings.json").write_text("{}")
    (profile / ".claude.json").write_text(json.dumps({"oauthAccount": account}))
    assert claude_account(home, env) == {"kind": "personal", "detail": "Pro"}
