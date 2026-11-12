"""Start records the gateway pid. Stop and kill signal only that process.

A program that is not the recorded gateway keeps the port. The PowerShell twin is
asserted from its source: this suite runs on Linux and macOS, where Windows
PowerShell 5.1 is not the host.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHELL_LAUNCHERS = ("start.sh", "start.command", "stop.sh", "stop.command", "kill.sh", "kill.command")
PATH_PREPEND = 'export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-}"'
DUMP_KEYS = ("PORT", "URL", "NOTE", "HASHY", "OK_KEY", "GOOD", "SPACED", "SKIP", "KEEP_ME")
STRIP_KEYS = set(DUMP_KEYS) | {"GATEWAY_IGNORE_TERM"}

FAKE_PYTHON = r"""#!/bin/bash
# Test double for the interpreter start.sh discovers. Never the real gateway.
set -euo pipefail
printf '%s\n' "$0" >> "${GATEWAY_FAKE_LOG:?}"
if [[ "${1:-}" == "-c" || "${1:-}" == "--version" ]]; then
  if [[ "${1:-}" == "--version" ]]; then
    printf '%s\n' "Python 3.12.0"
  fi
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "venv" ]]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python3"
  chmod +x "$3/bin/python3"
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "pip" ]]; then
  exit 0
fi
if [[ "${1:-}" == "-m" && "${2:-}" == "agent_cli_bridge.gateway" ]]; then
  code=$(cat <<'PY'
import os, signal, socket, sys, time
port = int(os.environ["PORT"])
dump = os.environ.get("GATEWAY_ENV_DUMP") or ""
wanted = [key for key in os.environ.get("GATEWAY_DUMP_KEYS", "").split(",") if key]
ignore = os.environ.get("GATEWAY_IGNORE_TERM") == "1"
if dump:
    with open(dump, "w", encoding="utf-8") as fh:
        for key in wanted:
            if key in os.environ:
                fh.write("%s=%s\n" % (key, os.environ[key]))
sock = socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind(("127.0.0.1", port))
sock.listen(1)
def on_term(signum, frame):
    if ignore:
        return
    raise SystemExit(0)
signal.signal(signal.SIGTERM, on_term)
while True:
    time.sleep(0.2)
PY
)
  # The marker is also the first line of -c so a truncated ps listing still matches.
  exec "${REAL_PYTHON:?}" -c "# agent_cli_bridge.gateway
$code" agent_cli_bridge.gateway
fi
printf 'unexpected python args: %s\n' "$*" >&2
exit 1
"""

DECOY = "import time\n# agent_cli_bridge.gateway\nwhile True:\n    time.sleep(0.2)\n"
STRANGER = (
    "import socket, sys, time\n"
    "sock = socket.socket()\n"
    "sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)\n"
    "sock.bind(('127.0.0.1', int(sys.argv[1])))\n"
    "sock.listen(1)\n"
    "while True:\n"
    "    time.sleep(0.2)\n"
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def alive(pid: int) -> bool:
    """True while the pid is a running process. A zombie left for its parent is gone."""
    result = subprocess.run(
        ["ps", "-o", "stat=", "-p", str(pid)],
        capture_output=True,
        text=True,
        check=False,
    )
    state = result.stdout.strip()
    return bool(state) and not state.startswith("Z")


def listener_pids(port: int) -> list[int]:
    result = subprocess.run(
        ["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"],
        capture_output=True,
        text=True,
        check=False,
    )
    return [int(line) for line in result.stdout.split() if line.isdigit()]


def wait_until(predicate, seconds: float = 8.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def ps_function(text: str, name: str) -> str:
    match = re.search(rf"function {name}\b", text)
    assert match, name
    start = text.find("{", match.end())
    assert start != -1, name
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"unclosed function {name}")


def uncommented(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#")]


class Launchers:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.app = tmp / "app"
        self.app.mkdir()
        self.fake_bin = tmp / "bin"
        self.fake_bin.mkdir()
        self.procs: list[subprocess.Popen[bytes]] = []
        self.logs: list[Path] = []
        self._handles: list[object] = []
        fake = self.fake_bin / "python3.13"
        fake.write_text(FAKE_PYTHON, encoding="utf-8")
        fake.chmod(0o755)
        for name in SHELL_LAUNCHERS:
            text = (ROOT / name).read_text(encoding="utf-8")
            if name == "start.sh":
                assert PATH_PREPEND in text
                # The stub must win over a Homebrew python3.13; the repo script still
                # prepends Homebrew for Finder. Only this copy is reordered.
                patched = (
                    f'export PATH="{self.fake_bin}:/opt/homebrew/bin:/usr/local/bin:${{PATH:-}}"'
                )
                text = text.replace(PATH_PREPEND, patched, 1)
            dest = self.app / name
            dest.write_text(text, encoding="utf-8")
            dest.chmod(0o755)

    def close(self) -> None:
        for proc in self.procs:
            if proc.poll() is None:
                with contextlib.suppress(OSError):
                    os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=5)
        for handle in self._handles:
            handle.close()

    def env(self, **extra: str) -> dict[str, str]:
        values = {key: value for key, value in os.environ.items() if key not in STRIP_KEYS}
        values["PATH"] = f"{self.fake_bin}{os.pathsep}{values.get('PATH', '')}"
        values["REAL_PYTHON"] = sys.executable
        values["GATEWAY_FAKE_LOG"] = str(self.tmp / "fake.log")
        values["GATEWAY_ENV_DUMP"] = str(self.tmp / "env.dump")
        values["GATEWAY_DUMP_KEYS"] = ",".join(DUMP_KEYS)
        values.update(extra)
        return values

    def spawn(self, argv: list[str], env: dict[str, str], cwd: Path | None = None) -> subprocess.Popen[bytes]:
        log_path = self.tmp / f"proc-{len(self.procs)}.log"
        handle = log_path.open("wb")
        self.logs.append(log_path)
        self._handles.append(handle)
        proc = subprocess.Popen(
            argv,
            cwd=cwd or self.app,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self.procs.append(proc)
        return proc

    def output(self) -> str:
        for handle in self._handles:
            handle.flush()
        return "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in self.logs)

    def recorded_pid(self) -> int | None:
        file = self.app / ".gateway.pid"
        if not file.exists():
            return None
        text = file.read_text(encoding="utf-8").strip()
        return int(text) if text.isdigit() else None

    def write_env(self, port: int, extra: str = "") -> None:
        (self.app / ".env").write_text(f"PORT={port}\n{extra}", encoding="utf-8")

    def start(self, launcher: str, env: dict[str, str], port: int) -> int:
        proc = self.spawn([str(self.app / launcher)], env)

        def ready() -> bool:
            recorded = self.recorded_pid()
            return recorded is not None and recorded in listener_pids(port) and alive(recorded)

        if not wait_until(ready):
            raise AssertionError(
                f"{launcher} exit={proc.poll()} recorded={self.recorded_pid()} "
                f"listeners={listener_pids(port)}\n{self.output()}"
            )
        recorded = self.recorded_pid()
        assert recorded is not None
        return recorded

    def run(self, script: str, env: dict[str, str] | None = None, timeout: float = 20) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.app / script)],
            cwd=self.app,
            env=env or self.env(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )


@pytest.fixture
def box(tmp_path: Path):
    launchers = Launchers(tmp_path)
    try:
        yield launchers
    finally:
        launchers.close()


def _python_invocations(log: Path) -> list[str]:
    assert log.exists(), "the discovered python was never invoked"
    return [line for line in log.read_text(encoding="utf-8").splitlines() if line]


@pytest.mark.parametrize("launcher", ["start.sh", "start.command"])
def test_start_records_the_listener_pid(launcher: str, box: Launchers):
    port = free_port()
    box.write_env(port)
    recorded = box.start(launcher, box.env(), port)
    assert set(listener_pids(port)) == {recorded}
    assert alive(recorded)
    invocations = _python_invocations(box.tmp / "fake.log")
    assert invocations
    for path in invocations:
        assert path.startswith("/"), path
    assert any(path.endswith("/python3.13") for path in invocations)
    assert any(path.endswith("/venv/bin/python3") for path in invocations)


def test_start_replaces_its_own_listener_pid(box: Launchers):
    port = free_port()
    box.write_env(port)
    env = box.env()
    first = box.start("start.sh", env, port)

    def replaced() -> bool:
        recorded = box.recorded_pid()
        return (
            recorded is not None
            and recorded != first
            and recorded in listener_pids(port)
            and alive(recorded)
            and not alive(first)
        )

    box.spawn([str(box.app / "start.sh")], env)
    assert wait_until(replaced, 8), box.output()


@pytest.mark.parametrize("script", ["stop.sh", "stop.command"])
def test_stop_signals_only_the_recorded_gateway_pid(script: str, box: Launchers):
    port = free_port()
    box.write_env(port)
    env = box.env()
    recorded = box.start("start.sh", env, port)
    decoy = box.spawn([sys.executable, "-c", DECOY], env)
    started = time.monotonic()
    result = box.run(script, env, timeout=10)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr
    assert "Stopped." in result.stdout
    assert elapsed < 3
    assert not alive(recorded)
    assert alive(decoy.pid)
    again = box.run(script, env, timeout=10)
    assert again.returncode == 0
    assert "not running" in again.stdout
    assert alive(decoy.pid)


@pytest.mark.parametrize("script", ["kill.sh", "kill.command"])
def test_kill_sigkills_only_the_recorded_pid_and_does_not_wait(script: str, box: Launchers):
    port = free_port()
    box.write_env(port)
    env = box.env(GATEWAY_IGNORE_TERM="1")
    recorded = box.start("start.sh", env, port)
    decoy = box.spawn([sys.executable, "-c", DECOY], env)
    started = time.monotonic()
    result = box.run(script, env, timeout=10)
    elapsed = time.monotonic() - started
    assert result.returncode == 0, result.stderr
    assert "Killed." in result.stdout
    assert elapsed < 2
    assert not alive(recorded)
    assert alive(decoy.pid)
    again = box.run(script, env, timeout=10)
    assert again.returncode == 0
    assert "not running" in again.stdout


def test_stop_exits_1_when_the_recorded_pid_is_still_the_gateway(box: Launchers):
    port = free_port()
    box.write_env(port)
    env = box.env(GATEWAY_IGNORE_TERM="1")
    recorded = box.start("start.sh", env, port)
    started = time.monotonic()
    result = box.run("stop.sh", env, timeout=15)
    elapsed = time.monotonic() - started
    assert result.returncode == 1, result.stdout + result.stderr
    assert "still running" in result.stdout
    assert 4.5 <= elapsed < 12
    assert alive(recorded)
    assert box.recorded_pid() == recorded


def test_stop_and_kill_exit_0_when_the_pid_is_missing_or_not_the_gateway(box: Launchers):
    env = box.env()
    sleeper = box.spawn(["sleep", "60"], env)
    for script in ("stop.sh", "kill.sh"):
        missing = box.run(script, env, timeout=10)
        assert missing.returncode == 0
        assert "not running" in missing.stdout
        (box.app / ".gateway.pid").write_text(f"{sleeper.pid}\n", encoding="utf-8")
        stale = box.run(script, env, timeout=10)
        assert stale.returncode == 0, stale.stderr
        assert "not running" in stale.stdout
        assert alive(sleeper.pid)


@pytest.mark.parametrize("launcher", ["start.sh", "start.command"])
def test_stranger_on_the_port_is_left_alone(launcher: str, box: Launchers):
    port = free_port()
    stranger = box.spawn([sys.executable, "-c", STRANGER, str(port)], box.env(), cwd=box.tmp)
    assert wait_until(lambda: stranger.pid in listener_pids(port))
    box.write_env(port)
    result = box.run(launcher, box.env(), timeout=20)
    assert result.returncode == 1
    assert "left alone" in result.stdout
    assert alive(stranger.pid)
    assert set(listener_pids(port)) == {stranger.pid}


def test_stranger_on_the_port_is_left_alone_by_the_powershell_start_script():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    body = ps_function(text, "Assert-GatewayPort")
    assert "left alone" in body
    assert "Test-GatewayProcess" in body
    assert "exit 1" in body
    assert "Stop-Process" not in body


def test_switchboard_lists_stop_and_kill():
    board = json.loads((ROOT / "switchboard.json").read_text(encoding="utf-8"))
    assert board["start"] == "./start.sh"
    assert board["stop"] == "./stop.sh"
    assert board["kill"] == "./kill.sh"
    assert board["port"] == 4747


def test_windows_scripts_signal_only_the_recorded_pid():
    start = (ROOT / "start.ps1").read_text(encoding="utf-8")
    stop = ps_function(start, "Stop-GatewayListener")
    kill = ps_function(start, "Stop-GatewayListenerForced")
    assert "AddSeconds(5)" in stop
    assert "/F" not in stop
    assert "exit 1" in stop
    assert "'/F'" in kill
    assert "AddSeconds" not in kill
    assert "Start-Sleep" not in kill
    gateway = ps_function(start, "Start-Gateway")
    assert "Write-RecordedPid -GatewayId $gateway.Id" in gateway
    assert ".gateway.pid" in start
    stop_script = (ROOT / "stop.ps1").read_text(encoding="utf-8")
    kill_script = (ROOT / "kill.ps1").read_text(encoding="utf-8")
    assert re.search(r"(?m)^Stop-GatewayListener\s*$", stop_script)
    assert "Stop-GatewayListenerForced" not in stop_script
    assert re.search(r"(?m)^Stop-GatewayListenerForced\s*$", kill_script)
    assert "Start-Sleep" not in kill_script


def test_dotenv_keeps_an_embedded_hash_and_drops_a_bad_key(box: Launchers):
    port = free_port()
    dotenv = "\n".join(
        (
            "# PORT=1",
            "  # SKIP=1",
            f"PORT={port}",
            "URL=http://x/y#frag",
            "NOTE=http://x/y # note",
            "HASHY=abc#def",
            "BAD-KEY=no",
            "1NOPE=no",
            "OK_KEY=from-file",
            "  GOOD=spaced",
            "SPACED = kept",
            "KEEP_ME=from-file",
            "",
        )
    )
    (box.app / ".env").write_text(dotenv, encoding="utf-8")
    box.start("start.sh", box.env(KEEP_ME="from-env"), port)
    values: dict[str, str] = {}
    for line in (box.tmp / "env.dump").read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    assert values["PORT"] == str(port)
    assert values["URL"] == "http://x/y#frag"
    assert values["NOTE"] == "http://x/y"
    assert values["HASHY"] == "abc#def"
    assert values["OK_KEY"] == "from-file"
    assert values["GOOD"] == "spaced"
    assert values["SPACED"] == "kept"
    assert values["KEEP_ME"] == "from-env"
    assert "SKIP" not in values
    ps1 = ps_function((ROOT / "start.ps1").read_text(encoding="utf-8"), "Import-DotEnv")
    assert "-split '#'" not in ps1
    assert r"^[A-Za-z_][A-Za-z0-9_]*$" in ps1
    assert r"\s+#" in ps1
    assert "StartsWith('#')" in ps1


def test_powershell_python_is_a_full_path_checks_version_and_rebuilds_older_venv():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    probe = ps_function(text, "Test-PythonAtLeast311")
    assert "(3, 11)" in probe
    assert "Invoke-Native -FilePath $PythonPath" in probe
    found = ps_function(text, "Find-Python311")
    assert ".Source" in found
    assert "IsPathRooted" in found
    assert r"Programs\Python" in found
    venv = ps_function(text, "Ensure-Venv")
    assert "Test-PythonAtLeast311 $venvPy" in venv
    assert "Remove-Item" in venv
    assert "Invoke-Native -FilePath $Python" in venv
    for line in uncommented(text):
        assert not re.search(r"(^|[;&|])\s*python(\.exe)?\s+-m\s+venv\b", line.strip())


def test_winget_install_uses_the_resolved_full_path():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    winget = ps_function(text, "Get-WingetExe")
    assert "Get-Command winget" in winget
    assert "winget.exe" in winget
    assert "Invoke-Native -FilePath $winget" in ps_function(text, "Initialize-GatewayVenv")
    for line in uncommented(text):
        stripped = line.strip()
        assert not re.match(r"winget(\.exe)?\s+install\b", stripped)
        assert not re.match(r"&\s*winget(\.exe)?\b", stripped)


def test_native_command_error_is_avoided_on_the_first_run_path():
    text = (ROOT / "start.ps1").read_text(encoding="utf-8")
    body = ps_function(text, "Invoke-Native")
    assert "NativeCommandError" in body
    assert "$ErrorActionPreference = 'Continue'" in body
    assert "PSNativeCommandUseErrorActionPreference = $false" in body
    assert "ProcessStartInfo" in body
    assert "ExitCode" in body
    assert "& $" not in body
    for name in ("Test-PythonAtLeast311", "Ensure-Venv", "Initialize-GatewayVenv"):
        assert "Invoke-Native" in ps_function(text, name)
    for line in uncommented(text):
        assert not line.strip().startswith("& ")


def _install(box: Launchers, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """install.sh --start from the box: it sources the box's start.sh (fake python first on PATH)."""
    dest = box.app / "install.sh"
    dest.write_text((ROOT / "install.sh").read_text(encoding="utf-8"), encoding="utf-8")
    dest.chmod(0o755)
    return subprocess.run(
        [str(dest), "--start"], cwd=box.app, env=env, capture_output=True, text=True, timeout=30, check=False,
    )


def test_install_start_starts_the_gateway_in_the_background(box: Launchers):
    port = free_port()
    box.write_env(port)
    result = _install(box, box.env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "starting on" in result.stdout

    def listening() -> bool:
        recorded = box.recorded_pid()
        return recorded is not None and recorded in listener_pids(port) and alive(recorded)

    try:
        assert wait_until(listening), (box.app / "gateway.log").read_text(encoding="utf-8", errors="replace")
        assert (box.app / "gateway.log").exists()
    finally:
        recorded = box.recorded_pid()
        if recorded is not None:
            with contextlib.suppress(OSError):
                os.kill(recorded, signal.SIGKILL)


def test_install_start_leaves_a_port_that_already_answers(box: Launchers):
    port = free_port()
    box.write_env(port)
    server = box.spawn([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], box.env(), cwd=box.tmp)
    assert wait_until(lambda: server.pid in listener_pids(port)), (server.poll(), listener_pids(port))
    result = _install(box, box.env())
    assert result.returncode == 0, result.stdout + result.stderr
    assert "already answers" in result.stdout
    assert box.recorded_pid() is None
    assert not (box.app / "gateway.log").exists()


def test_powershell_install_shares_start_and_checks_the_port_first():
    text = (ROOT / "install.ps1").read_text(encoding="utf-8")
    assert ". (Join-Path $PSScriptRoot 'start.ps1')" in text
    assert "Initialize-GatewayVenv" in text
    lines = "\n".join(uncommented(text))
    assert lines.index("Test-PortAnswers $listenPort") < lines.index("Start-Process")
    assert "-WindowStyle Hidden" in lines
    start = (ROOT / "start.ps1").read_text(encoding="utf-8")
    assert "$venvPy = Initialize-GatewayVenv" in ps_function(start, "Start-Gateway")
