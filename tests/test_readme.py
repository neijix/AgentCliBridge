"""README, pyproject.toml, and .env.example name the seven CLIs and the gateway facts."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIS = (
    "Claude Code",
    "Cursor Agent",
    "Gemini CLI",
    "Antigravity",
    "Grok",
    "Copilot",
    "OpenCode",
)
ENV_VARS = (
    "AGENT_CLI_BRIDGE_CONFIG_LOCAL",
    "D3SKWEBSCOUT_DIR",
    "AI_CODE_ROOT",
    "BRIDGE_WEB_SCOUT",
    "BRIDGE_WORKDIR",
    "AGENT_CLI_BRIDGE_HOME",
)
# A bearer value expanded by the shell becomes an argument visible in the process list.
_TOKEN_ON_ARGV = re.compile(
    r"Authorization:\s*Bearer\s+\$|Bearer\s+\$\(|\$\(cat\b|\$\(<|`cat\b|quota resets|2026-08-01",
    re.IGNORECASE,
)


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _bash_blocks(readme: str) -> list[str]:
    return re.findall(r"```bash\n(.*?)```", readme, re.S)


def _curl_command(block: str) -> str:
    lines = block.splitlines()
    for index, line in enumerate(lines):
        if re.search(r"\bcurl\b", line) is None:
            continue
        command = [line]
        while command[-1].endswith("\\"):
            command.append(lines[index + len(command)])
        return "\n".join(command)
    return ""


def test_readme_pyproject_and_env_example_list_all_seven_clis():
    for name in ("README.md", "pyproject.toml", ".env.example"):
        text = _text(name)
        missing = [cli for cli in CLIS if cli not in text]
        assert not missing, f"{name} missing {missing}"


def test_readme_drops_the_stale_copilot_reset_date():
    readme = _text("README.md")
    assert "2026-08-01" not in readme
    assert "quota resets" not in readme.lower()


def test_readme_documents_stop():
    readme = _text("README.md")
    assert "./stop.sh" in readme
    assert "SIGTERM" in readme


def test_plan_mode_is_not_called_a_guaranteed_read_only_sandbox():
    for name in ("README.md", "pyproject.toml", ".env.example"):
        lowered = _text(name).lower()
        assert "read-only sandbox" not in lowered
        assert "guaranteed read-only" not in lowered
    assert "Read-only by default" not in _text("README.md")
    assert "plan (read-only" not in _text(".env.example").lower()


def test_curl_example_keeps_the_token_off_the_process_command_line():
    readme = _text("README.md")
    assert _TOKEN_ON_ARGV.search(readme) is None
    blocks = [block for block in _bash_blocks(readme) if re.search(r"\bcurl\b", block)]
    assert len(blocks) == 1
    block = blocks[0]
    # Quoted heredoc: the shell does not expand the token into python's arguments.
    assert "<<'PY'" in block
    curl = _curl_command(block)
    assert "--config -" in curl
    assert "Authorization" not in curl
    assert "Bearer" not in curl
    assert "gateway-token" not in curl
    assert "$(" not in curl
    assert "`" not in curl


def test_dev_extra_includes_ruff_and_mypy():
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)
    dev = project["project"]["optional-dependencies"]["dev"]
    names = set()
    for item in dev:
        name = item.split("[", 1)[0].split(">", 1)[0].split("=", 1)[0].split("<", 1)[0]
        names.add(name.strip().lower())
    assert "ruff" in names
    assert "mypy" in names


def test_env_example_documents_the_named_variables():
    example = _text(".env.example")
    missing = [name for name in ENV_VARS if name not in example]
    assert not missing
