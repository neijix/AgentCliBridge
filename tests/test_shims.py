"""Launcher shims (shims.py): content per OS, permissions, rewrite only on change, PATH merge."""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_cli_bridge import shims


@pytest.mark.parametrize("is_windows", [False, True])
def test_the_shim_runs_the_module_with_every_argument(tmp_path, is_windows):
    folder = shims.ensure_shim("d3skwebscout", "/opt/scout/.venv/bin/python", "d3skwebscout",
                               folder=tmp_path, is_windows=is_windows)
    assert folder == tmp_path
    sh = (tmp_path / "d3skwebscout").read_text()
    assert sh == '#!/bin/sh\nexec "/opt/scout/.venv/bin/python" -m d3skwebscout "$@"\n'
    if is_windows:
        cmd = (tmp_path / "d3skwebscout.cmd").read_bytes().decode()
        assert cmd == '@"/opt/scout/.venv/bin/python" -m d3skwebscout %*\r\n'
    else:
        assert not (tmp_path / "d3skwebscout.cmd").exists()
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "d3skwebscout").stat().st_mode) == 0o755


def test_windows_paths_with_spaces_and_percent_signs():
    files = shims.shim_files("d3skhand", r"C:\Users\Jo Doe\100%\python.exe", "d3skhand.cli", is_windows=True)
    assert files["d3skhand.cmd"] == '@"C:\\Users\\Jo Doe\\100%%\\python.exe" -m d3skhand.cli %*\r\n'
    assert files["d3skhand"] == '#!/bin/sh\nexec "C:/Users/Jo Doe/100%/python.exe" -m d3skhand.cli "$@"\n'


def test_posix_quoting_keeps_the_path_literal():
    text = shims.posix_shim("/a b/$HOME/`x`/py\\", "m")
    assert text == '#!/bin/sh\nexec "/a b/\\$HOME/\\`x\\`/py\\\\" -m m "$@"\n'


@pytest.mark.skipif(os.name == "nt", reason="runs the POSIX shim")
def test_the_posix_shim_really_runs(tmp_path):
    (tmp_path / "mod_probe").mkdir()
    (tmp_path / "mod_probe" / "__main__.py").write_text("import sys; print(sys.argv[1:])")
    folder = shims.ensure_shim("probe", sys.executable, "mod_probe", folder=tmp_path / "bin")
    out = subprocess.run(
        ["probe", "fetch", "https://a.b/?x=1&y=2", "two words"],
        env={**shims.with_path(os.environ, folder), "PYTHONPATH": str(tmp_path)},
        capture_output=True, text=True, check=True,
    ).stdout
    assert out.strip() == "['fetch', 'https://a.b/?x=1&y=2', 'two words']"


def test_a_shim_is_rewritten_only_when_it_changes(tmp_path):
    shims.ensure_shim("tool", "/py/one", "tool", folder=tmp_path, is_windows=False)
    shim = tmp_path / "tool"
    os.utime(shim, (1_000_000, 1_000_000))
    shims.ensure_shim("tool", "/py/one", "tool", folder=tmp_path, is_windows=False)
    assert shim.stat().st_mtime == 1_000_000  # same content: untouched
    shims.ensure_shim("tool", "/py/two", "tool", folder=tmp_path, is_windows=False)
    assert "/py/two" in shim.read_text()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["tool"]  # no temp file left behind


@pytest.mark.parametrize("name,module,python", [
    ("../evil", "m", "/py"), ("a b", "m", "/py"), ("ok", "m; rm", "/py"), ("ok", "m", 'C:\\"x'),
    ("ok", "m", "/py\nrm -rf /"), ("ok", "m", ""),
])
def test_unsafe_names_and_paths_are_refused(tmp_path, name, module, python):
    with pytest.raises(ValueError):
        shims.ensure_shim(name, python, module, folder=tmp_path)


def test_with_path_puts_the_folder_first_once():
    env = {"PATH": "/usr/bin:/shims:/bin", "HOME": "/h"}
    merged = shims.with_path(env, "/shims", is_windows=False)
    assert merged == {"PATH": "/shims:/usr/bin:/bin", "HOME": "/h"}
    assert env["PATH"] == "/usr/bin:/shims:/bin"  # the input is not modified
    assert shims.with_path({}, "/shims", is_windows=False) == {"PATH": "/shims"}


def test_with_path_on_windows_keeps_the_key_case():
    merged = shims.with_path({"Path": r"C:\Windows;C:\Shims"}, r"c:\shims", is_windows=True)
    assert merged == {"Path": r"c:\shims;C:\Windows"}


def test_the_default_folder(tmp_path):
    assert shims.default_folder({"XDG_CACHE_HOME": str(tmp_path)}, is_windows=False) == tmp_path / "agent-cli-bridge" / "bin"
    assert shims.default_folder({}, is_windows=False) == Path.home() / ".cache" / "agent-cli-bridge" / "bin"
    assert shims.default_folder({"LOCALAPPDATA": str(tmp_path)}, is_windows=True) == tmp_path / "agent-cli-bridge" / "bin"
