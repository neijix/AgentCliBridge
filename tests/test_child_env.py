"""A spawned CLI does not inherit the gateway's bearer tokens."""
import asyncio
import json
import os
import sys

from agent_cli_bridge import run_agent
from agent_cli_bridge.events import Completed

_DUMP = """\
import json, os
from pathlib import Path
Path(os.environ["ENV_DUMP"]).write_text(json.dumps({
    "has_bridge_token": "BRIDGE_TOKEN" in os.environ,
    "has_owner_token": "BRIDGE_OWNER_TOKEN" in os.environ,
    "kept": os.environ.get("KEPT_FOR_THE_CLI"),
}))
print("ok")
"""


def _binary(tmp_path):
    if sys.platform == "win32":
        script = tmp_path / "fake_cli.py"
        script.write_text(_DUMP)
        launcher = tmp_path / "fake-cli.cmd"
        launcher.write_text(f'@"{sys.executable}" "%~dp0fake_cli.py" %*\n')
        return str(launcher)
    launcher = tmp_path / "fake-cli"
    launcher.write_text(f"#!{sys.executable}\n{_DUMP}")
    launcher.chmod(0o755)
    return str(launcher)


def _run(tmp_path, monkeypatch, *, env=None, extra_env=None):
    dump = tmp_path / "child-env.json"
    if extra_env is not None:
        extra_env = {**extra_env, "ENV_DUMP": str(dump)}
    elif env is not None:
        env = {**env, "ENV_DUMP": str(dump)}
    else:
        monkeypatch.setenv("ENV_DUMP", str(dump))

    async def collect():
        kwargs = {"prompt": "hi", "binary": _binary(tmp_path), "cwd": str(tmp_path)}
        if env is not None:
            kwargs["env"] = env
        if extra_env is not None:
            kwargs["extra_env"] = extra_env
        return [event async for event in run_agent("agy", **kwargs)]

    events = asyncio.run(asyncio.wait_for(collect(), 15))
    assert isinstance(events[-1], Completed)
    assert events[-1].returncode == 0
    return json.loads(dump.read_text())


def _absent(dumped, kept):
    assert dumped == {
        "has_bridge_token": False,
        "has_owner_token": False,
        "kept": kept,
    }


def test_bridge_tokens_on_the_parent_do_not_reach_the_cli(tmp_path, monkeypatch):
    monkeypatch.setenv("BRIDGE_TOKEN", "client-secret")
    monkeypatch.setenv("BRIDGE_OWNER_TOKEN", "owner-secret")
    monkeypatch.setenv("KEPT_FOR_THE_CLI", "from-parent")
    _absent(_run(tmp_path, monkeypatch), "from-parent")


def test_a_replacement_environment_still_drops_bridge_tokens(tmp_path, monkeypatch):
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("BRIDGE_OWNER_TOKEN", raising=False)
    monkeypatch.delenv("KEPT_FOR_THE_CLI", raising=False)
    env = dict(os.environ)
    env["BRIDGE_TOKEN"] = "client-secret"
    env["BRIDGE_OWNER_TOKEN"] = "owner-secret"
    env["KEPT_FOR_THE_CLI"] = "from-env"
    _absent(_run(tmp_path, monkeypatch, env=env), "from-env")


def test_extra_env_cannot_pass_bridge_tokens_to_the_cli(tmp_path, monkeypatch):
    monkeypatch.delenv("BRIDGE_TOKEN", raising=False)
    monkeypatch.delenv("BRIDGE_OWNER_TOKEN", raising=False)
    monkeypatch.delenv("KEPT_FOR_THE_CLI", raising=False)
    _absent(_run(tmp_path, monkeypatch, extra_env={
        "BRIDGE_TOKEN": "client-secret",
        "BRIDGE_OWNER_TOKEN": "owner-secret",
        "KEPT_FOR_THE_CLI": "from-extra",
    }), "from-extra")
