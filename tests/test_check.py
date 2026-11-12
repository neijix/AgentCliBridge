"""check.sh and check.ps1 are the one gate. CI and the pre-push hook call them."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"

SKIPPED = "code-health: skill not installed, skipped"
HEALTH = ".agents/skills/code-health/scripts/code_health.py"


def uncommented(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def test_scripts_list_the_same_gate():
    shell = (ROOT / "check.sh").read_text(encoding="utf-8")
    powershell = (ROOT / "check.ps1").read_text(encoding="utf-8")
    for text in (shell, powershell):
        assert "ruff" in text and "agent_cli_bridge" in text
        assert "--isolated" in text
        assert "--with" in text and "mypy" in text
        assert "--with-editable" in text and ".[dev]" in text
        assert "--platform" in text
        for platform in ("linux", "darwin", "win32"):
            assert platform in text
        assert "pytest" in text and "tests/" in text
        assert "--test" in text and "tests/ui" in text
        assert "code_health.py" in text and "code-health" in text
        assert SKIPPED in text
        assert "Running the full gate." in text
        assert "Running the gate." in text
    assert "--full" in shell
    assert "param([switch]$Full)" in powershell
    assert HEALTH in shell
    assert r".agents\skills\code-health\scripts\code_health.py" in powershell
    assert shell.count("ruff check agent_cli_bridge bridge_installer tests") == 1
    assert "@('ruff', 'check', 'agent_cli_bridge', 'bridge_installer', 'tests')" in powershell
    # Tool lines are the discovered path, never a bare name on PATH.
    for line in uncommented(shell):
        stripped = line.strip()
        assert not re.match(r"(uvx|uv|node|python3?)(\s|$)", stripped)
    for line in uncommented(powershell):
        stripped = line.strip()
        assert not re.match(r"(uvx|uv|node|python)(\.exe)?\s", stripped)
    assert "command -v uvx" in shell and "command -v uv" in shell and "command -v node" in shell
    assert "Get-Command uvx" in powershell and "Get-Command uv" in powershell
    assert "Get-Command node" in powershell and ".Source" in powershell


def test_ci_runs_the_gate_on_github_hosted_runners_for_pushes_and_pull_requests():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    triggers = workflow.split("\non:")[1].split("concurrency:")[0]
    assert "push:" in triggers and "pull_request:" in triggers and "workflow_dispatch:" in triggers
    # A fork's pull request must never get a writable token or the repo's secrets.
    assert "pull_request_target" not in workflow
    assert "secrets." not in workflow
    assert "permissions:\n  contents: read" in workflow
    assert "persist-credentials: false" in workflow
    assert "runs-on: ${{ matrix.os }}" in workflow
    assert "os: [ubuntu-latest, macos-latest, windows-latest]" in workflow
    assert "self-hosted" not in workflow
    assert 'python: ["3.11", "3.13"]' in workflow
    assert "timeout-minutes: 30" in workflow
    assert "fail-fast: false" in workflow
    assert "group: ci-${{ github.ref }}" in workflow and "cancel-in-progress: true" in workflow
    assert "continue-on-error: ${{ matrix.os != 'ubuntu-latest' }}" in workflow
    assert "runner.os != 'Windows'" in workflow and "./check.sh --full" in workflow
    assert "runner.os == 'Windows'" in workflow and "./check.ps1 -Full" in workflow
    assert "uvx ruff" not in workflow and "pytest" not in workflow and "mypy" not in workflow
    assert not (ROOT / ".github/workflows/ci-other-os.yml").exists()


def _hook_repo(tmp: Path) -> Path:
    """A throwaway clone layout: the versioned hooks, a check.sh stub that logs its call."""
    repo = tmp / "repo"
    (repo / ".githooks").mkdir(parents=True)
    for name in ("pre-push", "pre-commit"):
        shutil.copy2(ROOT / ".githooks" / name, repo / ".githooks" / name)
    stub = repo / "check.sh"
    stub.write_text('#!/bin/sh\necho "check $*" >> "$CHECK_LOG"\nexit "${CHECK_EXIT:-0}"\n', encoding="utf-8")
    stub.chmod(0o755)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _hook(repo: Path, name: str, tmp: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "SKIP_CHECK"}
    env.update(CHECK_LOG=str(tmp / "log"), **extra)
    return subprocess.run(
        [str(repo / ".githooks" / name), "origin", "url"],
        cwd=repo,
        env=env,
        input="refs/heads/main abc refs/heads/main def\n",
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_pre_push_runs_the_fast_gate_and_fails_with_it(tmp_path: Path):
    repo = _hook_repo(tmp_path)
    assert _hook(repo, "pre-push", tmp_path).returncode == 0
    assert (tmp_path / "log").read_text(encoding="utf-8") == "check \n"
    assert _hook(repo, "pre-push", tmp_path, CHECK_EXIT="1").returncode == 1


def test_skip_check_skips_the_pre_push_gate(tmp_path: Path):
    repo = _hook_repo(tmp_path)
    result = _hook(repo, "pre-push", tmp_path, SKIP_CHECK="1", CHECK_EXIT="1")
    assert result.returncode == 0
    assert "SKIP_CHECK=1" in result.stdout
    assert not (tmp_path / "log").exists()


def test_pre_commit_still_runs_the_clone_local_hook(tmp_path: Path):
    repo = _hook_repo(tmp_path)
    assert _hook(repo, "pre-commit", tmp_path).returncode == 0  # none installed: passes
    local = repo / ".git/hooks/pre-commit"
    local.write_text('#!/bin/sh\necho "local $*" >> "$CHECK_LOG"\nexit 3\n', encoding="utf-8")
    local.chmod(0o755)
    assert _hook(repo, "pre-commit", tmp_path).returncode == 3
    assert (tmp_path / "log").read_text(encoding="utf-8") == "local origin url\n"


def _bindir(tmp: Path, *, with_node: bool) -> Path:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True)
    script = "#!/bin/sh\nprintf '%s\\n' \"$0 $*\" >> \"${CHECK_LOG:?}\"\n"
    names = ("uv", "uvx", "node") if with_node else ("uv", "uvx")
    for name in names:
        path = bin_dir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
    return bin_dir


def _commands(log: Path) -> list[str]:
    commands = []
    for line in log.read_text(encoding="utf-8").splitlines():
        tool, _, args = line.partition(" ")
        assert tool.startswith("/"), tool
        commands.append(args)
    return commands


def _run(tmp: Path, args: list[str], *, with_node: bool, with_health: bool) -> subprocess.CompletedProcess[str]:
    home = tmp / "home"
    home.mkdir(parents=True)
    if with_health:
        scripts = home / ".agents/skills/code-health/scripts"
        scripts.mkdir(parents=True)
        (scripts / "code_health.py").write_text("# stub\n", encoding="utf-8")
    env = os.environ.copy()
    # Stubs win over the OS dirs. The caller's PATH is left out so a real uv or node
    # cannot run the gate; dirname still has to resolve.
    env["PATH"] = os.pathsep.join((str(_bindir(tmp, with_node=with_node)), "/usr/bin", "/bin"))
    env["HOME"] = str(home)
    env["CHECK_LOG"] = str(tmp / "log")
    return subprocess.run(
        [BASH, str(ROOT / "check.sh"), *args],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )


def test_full_is_accepted_and_runs_the_same_commands(tmp_path: Path):
    plain = _run(tmp_path / "plain", [], with_node=True, with_health=False)
    full = _run(tmp_path / "full", ["--full"], with_node=True, with_health=False)
    assert plain.returncode == 0, plain.stderr
    assert full.returncode == 0, full.stderr
    assert "Running the gate." in plain.stdout
    assert "Running the full gate." in full.stdout
    assert SKIPPED in plain.stdout and SKIPPED in full.stdout
    plain_cmds = _commands(tmp_path / "plain" / "log")
    full_cmds = _commands(tmp_path / "full" / "log")
    assert plain_cmds == full_cmds
    assert plain_cmds[0] == "ruff check agent_cli_bridge bridge_installer tests"
    assert plain_cmds[1:4] == [
        "run --isolated --with mypy --with-editable .[dev] mypy --platform linux",
        "run --isolated --with mypy --with-editable .[dev] mypy --platform darwin",
        "run --isolated --with mypy --with-editable .[dev] mypy --platform win32",
    ]
    assert plain_cmds[4] == "run --isolated --with pyyaml --with-editable .[dev] python -m pytest tests/ -q"
    assert plain_cmds[5].startswith("--test ")
    assert "tests/ui/" in plain_cmds[5] and ".test.cjs" in plain_cmds[5]
    assert all("code_health.py" not in command for command in plain_cmds)


def test_code_health_runs_when_the_script_exists_and_node_can_be_absent(tmp_path: Path):
    present = _run(tmp_path / "health", ["--full"], with_node=False, with_health=True)
    assert present.returncode == 0, present.stderr
    assert "node: not installed, UI tests skipped" in present.stdout
    assert SKIPPED not in present.stdout
    commands = _commands(tmp_path / "health" / "log")
    assert not any(command.startswith("--test ") for command in commands)
    health = commands[-1]
    assert health.startswith("run -q ")
    assert health.endswith("code_health.py check")
    assert "/.agents/skills/code-health/scripts/code_health.py check" in health


def test_an_unknown_check_flag_is_rejected(tmp_path: Path):
    result = _run(tmp_path, ["--slow"], with_node=True, with_health=False)
    assert result.returncode == 2
    assert "usage: ./check.sh [--full]" in result.stderr
    assert not (tmp_path / "log").exists()
