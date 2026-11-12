"""The setup wizard (``python -m bridge_installer``): its non-interactive paths, end to end.

Each test installs a small fake snapshot (a manifest and stub gateway scripts) into a temp folder
with a fake uv and a runner that records commands, so nothing is downloaded or started.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from installer_helpers import COMMIT, REPO, Recorder, answers, make_snapshot, run_install

from bridge_installer import MANIFEST_NAME, apply, wizard
from bridge_installer.apply import install
from bridge_installer.layout import Layout, SetupError
from bridge_installer.uninstall import uninstall


def test_a_new_install_writes_every_file_under_its_folder(tmp_path, fake_uv):
    root = tmp_path / "inst"
    runner = Recorder()
    assert run_install(tmp_path, fake_uv, answers(root), runner=runner) == 0
    layout = Layout(root)
    for folder in (layout.app, layout.data, layout.work, layout.shim_dir, layout.logs, layout.state, root / "config"):
        assert folder.is_dir(), folder
    assert (layout.app / MANIFEST_NAME).is_file()
    record = json.loads(layout.record.read_text(encoding="utf-8"))
    assert record == {"app": "agentclibridge", "format": 1, "version": "1.0.0", "commit": COMMIT, "repo": REPO,
                      "settings_dir": str(root / "config"), "port": 4799, "autostart": False}
    env = layout.env_file.read_text(encoding="utf-8")
    assert f"PORT=4799\nAGENT_CLI_BRIDGE_HOME={layout.data}\n" in env
    assert f"AGENT_CLI_BRIDGE_SHIM_DIR={layout.shim_dir}" in env and f"BRIDGE_WORKDIR={layout.work}" in env
    if os.name != "nt":
        assert layout.env_file.stat().st_mode & 0o777 == 0o600
        assert layout.data.stat().st_mode & 0o777 == 0o700
    sync = next(call for call in runner.calls if call[0] == str(fake_uv))
    assert sync[1:5] == ["sync", "--frozen", "--extra", "server"]
    assert runner.scripts() == ["install.sh"]  # new folder: nothing to stop, then start


def test_the_uv_sync_runs_in_app_with_uv_pinned_to_the_install(tmp_path, fake_uv):
    seen: dict[str, object] = {}

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[0] == str(fake_uv):
            seen.update(kwargs)
        return subprocess.CompletedProcess(argv, 0, "", "")

    root = tmp_path / "inst"
    install(answers(root), source=make_snapshot(tmp_path / "snap"), uv=fake_uv, python=Path(sys.executable),
            runner=runner, should_start=False)
    env = seen["env"]
    assert isinstance(env, dict)
    assert seen["cwd"] == str(root / "app")
    assert env["UV_PROJECT_ENVIRONMENT"] == str(root / "venv")
    assert env["UV_CACHE_DIR"].startswith(str(root)) and env["TMPDIR"] == str(root / "temp")


def test_an_upgrade_stops_the_gateway_keeps_owner_lines_and_swaps_app(tmp_path, fake_uv):
    root = tmp_path / "inst"
    run_install(tmp_path, fake_uv, answers(root))
    layout = Layout(root)
    layout.env_file.write_text("MY_OWN=1\n" + layout.env_file.read_text(encoding="utf-8"), encoding="utf-8")
    runner = Recorder()
    assert run_install(tmp_path, fake_uv, answers(root, port=4800), version="1.1.0", runner=runner) == 0
    assert runner.scripts() == ["stop.sh", "install.sh"]
    env = layout.env_file.read_text(encoding="utf-8")
    assert env.startswith("MY_OWN=1\n") and "PORT=4800" in env and "PORT=4799" not in env
    assert "snapshot 1.1.0" in (layout.app / "README.md").read_text(encoding="utf-8")
    assert not (root / "app.new").exists() and not (root / "app.old").exists()


def test_a_folder_that_is_not_an_install_is_refused(tmp_path, fake_uv):
    root = tmp_path / "busy"
    root.mkdir()
    (root / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(SetupError, match="not empty"):
        run_install(tmp_path, fake_uv, answers(root))
    assert sorted(p.name for p in root.iterdir()) == ["notes.txt"]


def test_the_setup_scripts_own_uv_and_temp_leave_a_folder_new(tmp_path, fake_uv):
    root = tmp_path / "inst"
    (root / "uv").mkdir(parents=True)
    (root / "temp").mkdir()
    assert run_install(tmp_path, fake_uv, answers(root)) == 0


def test_a_snapshot_without_a_manifest_is_refused(tmp_path, fake_uv):
    source = tmp_path / "snap"
    source.mkdir()
    with pytest.raises(SetupError, match="no manifest"):
        install(answers(tmp_path / "inst"), source=source, uv=fake_uv, runner=Recorder())


def test_a_failed_uv_sync_stops_the_setup(tmp_path, fake_uv):
    with pytest.raises(SetupError, match="uv sync failed"):
        run_install(tmp_path, fake_uv, answers(tmp_path / "inst"), runner=Recorder({"uv": 2}))


def test_a_gateway_that_never_answers_fails_naming_the_log(tmp_path, fake_uv, monkeypatch, capsys):
    monkeypatch.setattr("bridge_installer.apply.wait_for_port", lambda _port, is_up: False)
    root = tmp_path / "inst"
    assert install(answers(root), source=make_snapshot(tmp_path / "snap"), uv=fake_uv, runner=Recorder()) == 1
    assert str(root / "logs" / "gateway.log") in capsys.readouterr().err


# --- main(): flags only, no terminal ---------------------------------------------------------------


@pytest.fixture
def wizard_env(tmp_path, fake_uv, monkeypatch):
    """main() installs the fake snapshot with the fake uv; its stub scripts start nothing."""
    monkeypatch.setattr(apply, "SOURCE", make_snapshot(tmp_path / "snapshot"))
    monkeypatch.setenv("AGENT_CLI_BRIDGE_SETUP_UV", str(fake_uv))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # no start-at-login entry is ever found


def test_main_installs_with_flags_and_no_terminal(tmp_path, wizard_env):
    root = tmp_path / "inst"
    settings = tmp_path / "settings"
    code = wizard.main(["--dir", str(root), "--settings-dir", str(settings), "--port", "5005",
                        "--no-autostart", "--no-start"], is_tty=False)
    assert code == 0
    record = json.loads((root / "install.json").read_text(encoding="utf-8"))
    assert record["port"] == 5005 and record["settings_dir"] == str(settings) and record["autostart"] is False
    assert settings.is_dir()


def test_main_without_dir_and_no_terminal_fails_without_writing(tmp_path, wizard_env, capsys):
    assert wizard.main(["--yes"], is_tty=False) == 1
    assert "--dir" in capsys.readouterr().err


@pytest.mark.parametrize(("flag", "value", "reason"), [
    ("--port", "80", "between 1024 and 65535"),
    ("--port", "http", "not a number"),
    ("--settings-dir", "/tmp/a#b", "characters the launchers cannot carry"),
])
def test_main_refuses_a_bad_answer(tmp_path, wizard_env, capsys, flag, value, reason):
    assert wizard.main(["--dir", str(tmp_path / "inst"), flag, value, "--no-start"], is_tty=False) == 1
    assert reason in capsys.readouterr().err
    assert not (tmp_path / "inst").exists()


def test_main_rerun_keeps_the_previous_answers(tmp_path, wizard_env):
    root = tmp_path / "inst"
    wizard.main(["--dir", str(root), "--port", "5006", "--no-start"], is_tty=False)
    assert wizard.main(["--dir", str(root), "--yes", "--no-start"], is_tty=False) == 0
    assert json.loads((root / "install.json").read_text(encoding="utf-8"))["port"] == 5006


def test_main_asks_each_question_when_interactive(tmp_path, wizard_env):
    root = tmp_path / "inst"
    replies = iter([str(root), "", "5007", "n"])
    questions: list[str] = []

    def ask(question: str) -> str:
        questions.append(question)
        return next(replies)

    assert wizard.main(["--no-start"], ask=ask, is_tty=True) == 0
    assert [q.split(" [")[0].split(" (")[0] for q in questions] == [
        "Install folder", "Settings folder", "Gateway port on 127.0.0.1", "Start the gateway at login?",
    ]
    record = json.loads((root / "install.json").read_text(encoding="utf-8"))
    assert record["port"] == 5007 and record["settings_dir"] == str(root / "config")


def test_main_uninstall_needs_yes_without_a_terminal(tmp_path, wizard_env, capsys):
    root = tmp_path / "inst"
    wizard.main(["--dir", str(root), "--no-start"], is_tty=False)
    assert wizard.main(["--dir", str(root), "--uninstall"], is_tty=False) == 1
    assert "--yes" in capsys.readouterr().err
    assert (root / "install.json").exists()


def test_main_uninstall_keeps_the_settings_folder_by_default(tmp_path, wizard_env):
    root = tmp_path / "inst"
    wizard.main(["--dir", str(root), "--no-start"], is_tty=False)
    (root / "config" / "agent_cli_bridge.json").write_text("{}", encoding="utf-8")
    assert wizard.main(["--dir", str(root), "--uninstall", "--yes"], is_tty=False) == 0
    assert sorted(p.name for p in root.iterdir()) == ["config"]
    assert (root / "config" / "agent_cli_bridge.json").exists()


def test_main_uninstall_with_remove_settings_removes_everything(tmp_path, wizard_env):
    root = tmp_path / "inst"
    outside = tmp_path / "settings"
    wizard.main(["--dir", str(root), "--settings-dir", str(outside), "--no-start"], is_tty=False)
    assert wizard.main(["--dir", str(root), "--uninstall", "--yes", "--remove-settings"], is_tty=False) == 0
    assert not root.exists() and not outside.exists()


def test_uninstall_refuses_a_folder_that_is_not_an_install(tmp_path):
    folder = tmp_path / "mine"
    folder.mkdir()
    (folder / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(SetupError, match="not an AgentCliBridge install"):
        uninstall(Layout(folder), runner=Recorder())
    assert (folder / "keep.txt").exists()


def test_uninstall_never_deletes_the_home_folder_as_settings(tmp_path, fake_uv, monkeypatch):
    home = tmp_path / "home"
    root = home / "inst"
    monkeypatch.setattr(Path, "home", lambda: home)
    run_install(tmp_path, fake_uv, answers(root, settings_dir=home))
    (home / "precious.txt").write_text("x", encoding="utf-8")
    assert uninstall(Layout(root), remove_settings=True, runner=Recorder()) == 0
    assert (home / "precious.txt").exists() and not root.exists()


def test_python_dash_m_runs_the_wizard_help():
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-m", "bridge_installer", "--help"], cwd=root,
                          capture_output=True, text=True, check=False, timeout=60)
    assert done.returncode == 0
    for flag in ("--dir", "--settings-dir", "--port", "--autostart", "--uninstall", "--update", "--yes"):
        assert flag in done.stdout
