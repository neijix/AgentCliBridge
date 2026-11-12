"""packaging/setup.sh and setup.ps1, the step before the wizard: folder checks, uv, Python, hand-off.

setup.sh runs for real against a staged setup folder (the real ``bridge_installer`` and a fake
snapshot) with a fake ``uv`` first on PATH, so nothing is downloaded. HOME is an empty temp folder
that must stay empty: the setup writes nothing in the user profile.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from installer_helpers import make_snapshot

from bridge_installer import MANIFEST_NAME, PYTHON_VERSION

ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
SETUP_SH = PACKAGING / "setup.sh"
SETUP_PS1 = PACKAGING / "setup.ps1"

posix_only = pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None, reason="needs a POSIX sh")

FAKE_UV = f"""#!/bin/sh
echo "uv $*" >> "$FAKEUV_LOG"
case "$1 $2" in
  "python find") echo "{sys.executable}" ;;
esac
exit 0
"""


def stage(tmp: Path) -> Path:
    folder = tmp / "agentclibridge-1.0.0-setup"
    app = make_snapshot(folder / "app")
    shutil.copytree(ROOT / "bridge_installer", app / "bridge_installer",
                    ignore=shutil.ignore_patterns("__pycache__"))
    for script in ("setup.sh", "setup.ps1"):
        shutil.copy2(PACKAGING / script, folder / script)
    return folder


def run_setup(tmp: Path, *args: str, home: Path | None = None) -> subprocess.CompletedProcess[str]:
    folder = tmp / "agentclibridge-1.0.0-setup"
    if not folder.exists():
        stage(tmp)
    bin_dir = tmp / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "uv").write_text(FAKE_UV, encoding="utf-8")
    (bin_dir / "uv").chmod(0o755)
    home = home or tmp / "home"
    home.mkdir(exist_ok=True)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("UV_", "AGENTCLIBRIDGE_"))}
    env.update(PATH=f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin", HOME=str(home), FAKEUV_LOG=str(tmp / "uv.log"),
               XDG_CONFIG_HOME=str(home / ".config"))
    return subprocess.run(["sh", str(folder / "setup.sh"), *args], cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=False, timeout=120)


@posix_only
def test_setup_sh_installs_with_flags_and_writes_nothing_in_home(tmp_path):
    target = tmp_path / "inst"
    done = run_setup(tmp_path, "--dir", str(target), "--port", "5011", "--no-start", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr
    record = json.loads((target / "install.json").read_text(encoding="utf-8"))
    assert record["port"] == 5011 and record["version"] == "1.0.0"
    assert (target / "temp").is_dir()
    for launcher in ("start.sh", "stop.sh", "kill.sh", "update.sh", "uninstall.sh"):
        assert (target / launcher).is_file(), launcher
    assert list((tmp_path / "home").iterdir()) == []
    uv_calls = (tmp_path / "uv.log").read_text(encoding="utf-8").splitlines()
    assert uv_calls[0] == f"uv python find --system {PYTHON_VERSION}"
    assert any(call.startswith("uv sync --frozen --extra server") for call in uv_calls)


@posix_only
def test_setup_sh_makes_a_relative_dir_absolute(tmp_path):
    done = run_setup(tmp_path, "--dir", "rel-inst", "--no-start", "--yes")
    assert done.returncode == 0, done.stdout + done.stderr
    assert (tmp_path / "rel-inst" / "install.json").is_file()


@posix_only
def test_setup_sh_refuses_a_folder_that_is_not_an_install_before_writing(tmp_path):
    busy = tmp_path / "busy"
    busy.mkdir()
    (busy / "mine.txt").write_text("x", encoding="utf-8")
    done = run_setup(tmp_path, "--dir", str(busy), "--yes")
    assert done.returncode != 0
    assert "is not empty and is not an AgentCliBridge install" in done.stderr
    assert sorted(p.name for p in busy.iterdir()) == ["mine.txt"]
    assert not (tmp_path / "uv.log").exists()


@posix_only
def test_setup_sh_refuses_a_folder_inside_the_setup_folder(tmp_path):
    folder = stage(tmp_path)
    done = run_setup(tmp_path, "--dir", str(folder / "inst"), "--yes")
    assert done.returncode != 0 and "inside the setup folder" in done.stderr


@posix_only
def test_setup_sh_without_a_folder_or_terminal_stops(tmp_path):
    done = run_setup(tmp_path, "--yes")
    assert done.returncode != 0
    assert "--dir <folder> or AGENTCLIBRIDGE_SETUP_DIR" in done.stderr


@posix_only
def test_setup_sh_help_needs_no_folder_and_fetches_nothing(tmp_path):
    done = run_setup(tmp_path, "--help")
    assert done.returncode == 0, done.stderr
    assert "--settings-dir" in done.stdout
    assert not (tmp_path / "uv.log").exists()


@posix_only
def test_setup_sh_uninstall_runs_on_an_existing_install(tmp_path):
    target = tmp_path / "inst"
    assert run_setup(tmp_path, "--dir", str(target), "--no-start", "--yes").returncode == 0
    done = run_setup(tmp_path, "--dir", str(target), "--uninstall", "--yes", "--remove-settings")
    assert done.returncode == 0, done.stdout + done.stderr
    assert not target.exists()


def test_the_scripts_name_the_same_manifest_and_python_as_the_wizard():
    for path in (SETUP_SH, SETUP_PS1, PACKAGING / "linux" / "build-deb.sh", PACKAGING / "macos" / "postinstall",
                 PACKAGING / "macos" / "build-pkg.sh", PACKAGING / "windows" / "build-exe.ps1"):
        text = path.read_text(encoding="utf-8")
        names = set(re.findall(r"agentclibridge-snapshot\.json|[a-z0-9]+-snapshot\.json", text))
        assert names <= {MANIFEST_NAME}, (path, names)
    for path, name in ((SETUP_SH, "PYTHON_VERSION"), (SETUP_PS1, r"\$PythonVersion")):
        line = rf"""{name}\s*=\s*["']{re.escape(PYTHON_VERSION)}["']"""
        assert re.search(line, path.read_text(encoding="utf-8")), path


def test_setup_ps1_parses_in_powershell():
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh is not installed")
    command = (f"$e=$null; [void][System.Management.Automation.Language.Parser]::ParseFile('{SETUP_PS1}',"
               " [ref]$null, [ref]$e); $e.Count")
    done = subprocess.run([pwsh, "-NoProfile", "-Command", command], capture_output=True, text=True, check=False)
    assert done.stdout.strip() == "0", done.stdout + done.stderr


def test_setup_scripts_pass_shellcheck():
    shellcheck = shutil.which("shellcheck")
    if shellcheck is None:
        pytest.skip("shellcheck is not installed")
    scripts = [SETUP_SH, PACKAGING / "release.sh", PACKAGING / "linux" / "build-deb.sh",
               PACKAGING / "linux" / "agentclibridge-setup", PACKAGING / "macos" / "build-pkg.sh",
               PACKAGING / "macos" / "postinstall"]
    done = subprocess.run([shellcheck, *map(str, scripts)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout


def test_the_wheel_ships_only_the_library_not_the_installer():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert config["tool"]["setuptools"]["packages"]["find"]["include"] == ["agent_cli_bridge*"]
    assert config["tool"]["mypy"]["files"] == ["agent_cli_bridge", "bridge_installer"]
