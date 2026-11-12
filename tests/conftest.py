"""Every test starts without the owner's shared settings (AGENT_CLI_BRIDGE_CONFIG_LOCAL=none: this
checkout's config.local/ is never read, and the retired apps-config folder is off) and without
this machine's D3SKWEBSCOUT checkout (D3SKWEBSCOUT_DIR points nowhere); security stops go to a
per-test log file, never the owner's.

The bridge home and ``BRIDGE_WORKDIR`` are temp directories from the moment this file is imported,
before any test module imports the library, so the suite does not create or read
``~/.agent-cli-bridge``.
"""
import os
import sys
import tempfile
from itertools import count
from pathlib import Path

import pytest

# Import time, not a fixture: test modules import the library during collection.
os.environ["AGENT_CLI_BRIDGE_HOME"] = tempfile.mkdtemp(prefix="acb-bridge-home-")
os.environ["BRIDGE_WORKDIR"] = tempfile.mkdtemp(prefix="acb-bridge-workdir-")


@pytest.fixture(autouse=True)
def _no_apps_config(monkeypatch):
    monkeypatch.setenv("AGENT_CLI_BRIDGE_CONFIG_LOCAL", "none")
    monkeypatch.setenv("APPS_CONFIG_DIR", "none")


@pytest.fixture(autouse=True)
def _no_web_scout_checkout(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("D3SKWEBSCOUT_DIR", str(tmp_path_factory.mktemp("no-scout") / "D3SKWEBSCOUT"))


@pytest.fixture(autouse=True)
def _private_security_log(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("AGENT_CLI_BRIDGE_SECURITY_LOG", str(tmp_path_factory.mktemp("security") / "log.jsonl"))


FAKE_CLI = """import sys
sys.stdout.buffer.write(open({stream!r}, "rb").read())
sys.stdout.flush()
sys.exit({returncode})
"""


@pytest.fixture
def fake_cli(tmp_path):
    """``fake_cli(stream, returncode=0)`` → a binary that prints ``stream`` to stdout and exits.

    ``stream`` is a ``Path`` to replay or the output itself (``str`` / ``bytes``). Works on every
    OS: a shebang script on POSIX, a ``.cmd`` running the same script with this Python on Windows
    (no shebangs there)."""
    serial = count()

    def make(stream: Path | str | bytes, returncode: int = 0) -> str:
        index = next(serial)
        if not isinstance(stream, Path):
            path = tmp_path / f"fake-stream-{index}.out"
            path.write_bytes(stream if isinstance(stream, bytes) else stream.encode())
            stream = path
        script = FAKE_CLI.format(stream=str(stream), returncode=returncode)
        if sys.platform == "win32":
            (tmp_path / f"fake_cli_{index}.py").write_text(script)
            launcher = tmp_path / f"fake-cli-{index}.cmd"
            launcher.write_text(f'@"{sys.executable}" "%~dp0fake_cli_{index}.py" %*\n')
            return str(launcher)
        launcher = tmp_path / f"fake-cli-{index}"
        launcher.write_text(f"#!{sys.executable}\n{script}")
        launcher.chmod(0o755)
        return str(launcher)

    return make
