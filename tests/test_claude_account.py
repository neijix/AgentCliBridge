import json

from agent_cli_bridge.claude_account import (
    claude_account,
    claude_gateway,
    claude_profile_accounts,
    claude_profile_dir,
    claude_profile_env,
)


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
    env = {"CLAUDE_CONFIG_DIR": "/mine", "ANTHROPIC_BASE_URL": ""}
    # inherited={} — this spawn set the dir; the process's own value must not matter
    assert claude_profile_env(env, root, home=tmp_path, inherited={}) == env


def test_an_inherited_config_dir_does_not_pin_every_project_to_one_login(tmp_path, monkeypatch):
    # The office node inherited the work profile and the company gateway. A personal folder
    # must not keep either; a work folder keeps the profile that names the gateway.
    work_root, personal_root = tmp_path / "WorkCode", tmp_path / "Code"
    (work_root / "proj").mkdir(parents=True)
    personal_root.mkdir()
    work_dir, personal_dir = tmp_path / "work-profile", tmp_path / "personal-profile"
    work_dir.mkdir()
    personal_dir.mkdir()
    (work_dir / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://gw.example"}}), encoding="utf-8",
    )
    account = {"accountUuid": "person", "organizationType": "claude_max"}
    (personal_dir / ".claude.json").write_text(json.dumps({"oauthAccount": account}), encoding="utf-8")
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": account}), encoding="utf-8")
    (tmp_path / ".claude-profiles").write_text(
        f"{work_root.resolve().as_posix()}\t{work_dir}\n{personal_root.resolve().as_posix()}\t{personal_dir}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(work_dir))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "office-token")
    inherited = {
        "CLAUDE_CONFIG_DIR": str(work_dir),
        "ANTHROPIC_BASE_URL": "https://gw.example",
        "ANTHROPIC_AUTH_TOKEN": "office-token",
    }

    inside = claude_profile_env(dict(inherited), work_root / "proj", home=tmp_path)
    assert inside["CLAUDE_CONFIG_DIR"] == str(work_dir)
    assert inside["ANTHROPIC_BASE_URL"] == "https://gw.example"
    assert inside["ANTHROPIC_AUTH_TOKEN"] == "office-token"

    personal = claude_profile_env(dict(inherited), personal_root / "app", home=tmp_path)
    assert personal["CLAUDE_CONFIG_DIR"] == str(personal_dir)
    assert personal["ANTHROPIC_BASE_URL"] == ""
    assert personal["ANTHROPIC_AUTH_TOKEN"] == ""

    # A spawn that names its own login (a D3SKHAND account) keeps it, even inside the work root.
    account_env = {**inherited, "CLAUDE_CONFIG_DIR": "/accounts/personal/.claude", "ANTHROPIC_BASE_URL": ""}
    assert claude_profile_env(account_env, work_root, home=tmp_path)["CLAUDE_CONFIG_DIR"] == "/accounts/personal/.claude"
    assert claude_profile_env(account_env, work_root, home=tmp_path)["ANTHROPIC_BASE_URL"] == ""


def test_without_a_profile_record_the_inherited_login_stays(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "/only")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gw.example")
    env = {"CLAUDE_CONFIG_DIR": "/only", "ANTHROPIC_BASE_URL": "https://gw.example"}
    assert claude_profile_env(env, tmp_path, home=tmp_path) == env


def test_profile_accounts_tell_personal_and_work_apart(tmp_path):
    work_root = tmp_path / "WorkCode"
    work_root.mkdir()
    work_dir = tmp_path / "work-profile"
    work_dir.mkdir()
    (work_dir / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BASE_URL": "https://gw.example"}}), encoding="utf-8",
    )
    account = {"accountUuid": "person", "organizationType": "claude_pro"}
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": account}), encoding="utf-8")
    _profiles(tmp_path, work_root, str(work_dir))
    found = claude_profile_accounts(tmp_path)
    assert found is not None
    assert found["default"] == {"kind": "personal", "detail": "Pro"}
    assert found["roots"] == [
        {"root": work_root.resolve().as_posix(), "account": {"kind": "work", "detail": "gw.example"}},
    ]
    assert claude_profile_accounts(tmp_path / "empty") is None


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
