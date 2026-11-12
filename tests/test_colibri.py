"""colibri: whether `coli setup` is ready, and its server's URL and model id, started on demand."""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from agent_cli_bridge import colibri

SERVED = "glm-5.3-colibri"


class _Models(BaseHTTPRequestHandler):
    owner = "colibri"

    def do_GET(self):  # noqa: N802 — http.server's name
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode()
        else:
            body = json.dumps({"object": "list", "data": [{"id": SERVED, "owned_by": self.owner}]}).encode()
        self.send_response(200 if self.path in ("/health", "/v1/models") else 404)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class _OtherServer(_Models):
    owner = "vllm"


@pytest.fixture
def models_server():
    """``start()`` → the port of a fake colibri answering ``/v1/models``; stopped after the test."""
    servers = []

    def start(port: int = 0, handler=_Models) -> int:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return server.server_address[1]

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _setup(tmp_path, monkeypatch, *, status="ready", port=8000, launcher=True) -> Path:
    home = tmp_path / "colibri-home"
    home.mkdir()
    coli = tmp_path / "colibri" / "c" / "coli"
    if launcher:
        coli.parent.mkdir(parents=True)
        coli.write_text("# colibri launcher\n")
    config = {
        "status": status,
        "model": {"id": "glm-5.3", "name": "GLM-5.3", "repo": "Justvugg/GLM-5.3-colibri-int4-g64"},
        "family": "glm",
        "launcher": str(coli),
        "host": "127.0.0.1",
        "port": port,
    }
    (home / "setup.json").write_text(json.dumps(config))
    monkeypatch.setenv("COLI_SETUP_HOME", str(home))
    return coli


def test_setup_counts_only_once_ready(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, status="pending")
    assert colibri.load_setup() is None  # the model is still downloading


def test_setup_without_its_launcher_is_not_installed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, launcher=False)
    assert colibri.load_setup() is None

def test_the_installed_model_is_listed_by_its_own_name(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config = colibri.load_setup()
    assert colibri.model_ids(config) == ["glm-5.3"]
    assert colibri.model_name(config) == "GLM-5.3"  # not the server's `glm-5.2-colibri`


def test_a_server_already_up_is_used_as_is(tmp_path, monkeypatch, models_server):
    port = models_server()
    _setup(tmp_path, monkeypatch, port=port)
    monkeypatch.setattr(colibri, "start_server", lambda config: pytest.fail("started a server already up"))
    assert colibri.ensure_served_model(colibri.load_setup()) == (f"http://127.0.0.1:{port}/v1", SERVED)


def test_a_stopped_server_is_started_once_then_used(tmp_path, monkeypatch, models_server):
    import socket

    with socket.socket() as probe:  # a free port nothing listens on yet
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    _setup(tmp_path, monkeypatch, port=port)
    started = []
    monkeypatch.setattr(colibri, "start_server", lambda config: started.append(models_server(port)))
    assert colibri.ensure_served_model(colibri.load_setup(), timeout=10)[1] == SERVED
    assert started == [port]


def test_another_server_on_colibris_port_is_never_used(tmp_path, monkeypatch, models_server):
    port = models_server(handler=_OtherServer)  # vLLM also defaults to 8000
    _setup(tmp_path, monkeypatch, port=port)
    assert colibri.served_model(f"http://127.0.0.1:{port}/v1") is None

    def refuse(config):
        raise RuntimeError("`coli start` exited with status 1: port taken")

    monkeypatch.setattr(colibri, "start_server", refuse)
    with pytest.raises(RuntimeError, match="port taken"):
        colibri.ensure_served_model(colibri.load_setup())


def test_base_url_reaches_a_wildcard_bind_on_loopback_and_never_another_machine():
    assert colibri.base_url({"host": "0.0.0.0", "port": 8123}) == "http://127.0.0.1:8123/v1"
    assert colibri.base_url({}) == "http://127.0.0.1:8000/v1"
    assert colibri.base_url({"host": "::1", "port": 8000}) == "http://[::1]:8000/v1"
    with pytest.raises(RuntimeError, match="only a server on this machine"):
        colibri.base_url({"host": "192.168.1.20", "port": 8000})


def test_a_server_that_moved_to_another_port_is_followed(tmp_path, monkeypatch, models_server):
    _setup(tmp_path, monkeypatch, port=9)
    setup = tmp_path / "colibri-home" / "setup.json"

    def start_elsewhere(config):  # `coli start` found its port taken and rewrote setup.json
        setup.write_text(json.dumps({**json.loads(setup.read_text()), "port": models_server()}))

    monkeypatch.setattr(colibri, "start_server", start_elsewhere)
    url, served = colibri.ensure_served_model(colibri.load_setup(), timeout=10)
    assert served == SERVED and url == f"http://127.0.0.1:{json.loads(setup.read_text())['port']}/v1"


def test_the_probe_uses_the_shared_get_and_names_its_limit(monkeypatch):
    seen: dict[str, object] = {}

    def fake(url, max_bytes, *, timeout, headers=None):
        seen.setdefault("urls", []).append(url)
        seen["max"] = max_bytes
        seen["timeout"] = timeout
        if url.endswith("/health"):
            return b'{"status": "ok"}'
        return b'{"data": [{"id": "glm-5.3-colibri", "owned_by": "colibri"}]}'

    monkeypatch.setattr(colibri, "get_bytes", fake)
    assert colibri.served_model("http://127.0.0.1:9/v1") == SERVED
    assert seen["urls"] == ["http://127.0.0.1:9/health", "http://127.0.0.1:9/v1/models"]
    assert seen["max"] == colibri._PROBE_MAX_BYTES
    assert seen["timeout"] == colibri._PROBE_TIMEOUT_SECONDS


def test_coli_start_gets_a_context_a_chat_fits_in(tmp_path, monkeypatch):
    coli = _setup(tmp_path, monkeypatch)
    seen = {}

    def run(argv, **kwargs):
        seen.update(argv=argv, **kwargs)
        return colibri.subprocess.CompletedProcess(argv, 0, "{}", "")

    monkeypatch.setattr(colibri.subprocess, "run", run)
    monkeypatch.delenv("CTX", raising=False)
    colibri.start_server(colibri.load_setup())
    assert seen["argv"][1:] == [str(coli), "start", "--background", "--json", "--no-browser"]
    assert seen["env"]["CTX"] == str(colibri.CONTEXT_TOKENS)
    assert seen["stdin"] is colibri.subprocess.DEVNULL
    monkeypatch.setenv("CTX", "65536")  # the owner's own choice wins
    colibri.start_server(colibri.load_setup())
    assert seen["env"]["CTX"] == "65536"


def test_opencode_never_waits_on_the_hosts_open_stdin(tmp_path):
    # `opencode run` reads piped stdin to its end: a host whose stdin is an open pipe hung the turn.
    script = "import sys\nsys.stdin.read()\nprint('{\"type\": \"text\", \"part\": {\"type\": \"text\", \"text\": \"done\"}}')\n"
    if sys.platform == "win32":
        (tmp_path / "reads_stdin.py").write_text(script)
        binary = tmp_path / "opencode.cmd"
        binary.write_text(f'@"{sys.executable}" "%~dp0reads_stdin.py" %*\n')
    else:
        binary = tmp_path / "opencode"
        binary.write_text(f"#!{sys.executable}\n{script}")
        binary.chmod(0o755)
    host = (
        "import asyncio, sys\n"
        "from agent_cli_bridge import run_agent\n"
        "async def main():\n"
        f"    async for e in run_agent('opencode', prompt='hi', binary={str(binary)!r}):\n"
        "        print(type(e).__name__, getattr(e, 'text', ''))\n"
        "asyncio.run(main())\n"
    )
    # The host's stdin stays an open pipe while it runs; a hang is killed after 30 s.
    proc = subprocess.Popen([sys.executable, "-c", host], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    watchdog = threading.Timer(30, proc.kill)
    watchdog.start()
    try:
        out = proc.stdout.read()
    finally:
        watchdog.cancel()
        proc.stdin.close()
        proc.wait()
    assert "TextDelta done" in out


@pytest.mark.parametrize("port", ["eighty", [8000], 70000, -1.5])
def test_a_bad_port_in_the_setup_is_a_runtime_error(port):
    with pytest.raises(RuntimeError, match="port"):
        colibri.base_url({"host": "127.0.0.1", "port": port})


def test_a_start_that_cannot_run_or_hangs_is_a_runtime_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    config = colibri.load_setup()

    def missing(argv, **kwargs):
        raise FileNotFoundError(2, "No such file", argv[1])

    monkeypatch.setattr(colibri.subprocess, "run", missing)
    with pytest.raises(RuntimeError, match="could not run"):
        colibri.start_server(config)

    def hang(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 120)

    monkeypatch.setattr(colibri.subprocess, "run", hang)
    with pytest.raises(RuntimeError, match="120s"):
        colibri.start_server(config)
    with pytest.raises(RuntimeError, match="launcher"):
        colibri.start_server({"status": "ready"})


def test_ensure_served_model_reports_every_start_failure_as_a_runtime_error(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, port=9)  # nothing listens there
    monkeypatch.setattr(colibri, "served_model", lambda url: None)

    def broken(argv, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(colibri.subprocess, "run", broken)
    with pytest.raises(RuntimeError, match="could not run"):
        colibri.ensure_served_model(colibri.load_setup(), timeout=1.0)
    with pytest.raises(RuntimeError, match="port"):
        colibri.ensure_served_model({"port": "x"}, timeout=1.0)


def test_a_probe_that_drops_the_connection_mid_answer_is_not_a_server(monkeypatch):
    def fake(url, limit, **kwargs):
        raise colibri.http.client.IncompleteRead(b"")

    monkeypatch.setattr(colibri, "get_bytes", fake)
    assert colibri.served_model("http://127.0.0.1:9/v1") is None
