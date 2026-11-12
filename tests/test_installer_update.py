"""The in-app updater (``update.sh`` / ``--update``) and the files the wizard writes.

GitHub is a fake ``fetch``: a latest-release JSON, its SHA256SUMS and the snapshot archive.
"""
from __future__ import annotations

import hashlib
import io
import json
import plistlib
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest
from installer_helpers import COMMIT, REPO, Recorder, answers, run_install

from bridge_installer import INSTALL_DIR_ENV, MANIFEST_NAME
from bridge_installer.layout import Layout, SetupError, gateway_env_text, write_launchers
from bridge_installer.manifest import Manifest
from bridge_installer.release import snapshot_name
from bridge_installer.system import (
    launch_agent_bytes,
    run_value_command,
    systemd_unit_text,
)
from bridge_installer.update import API, safe_extract, update

URL = "https://github.com/owner/AgentCliBridge/releases/download/v{v}/{name}"


def snapshot_bytes(version: str, *, repo: str = REPO, extra: tarfile.TarInfo | None = None) -> bytes:
    files = {
        MANIFEST_NAME: Manifest(version, COMMIT, repo).as_json().encode(),
        "README.md": f"snapshot {version}\n".encode(),
        "install.sh": b"#!/bin/bash\nexit 0\n",
        "stop.sh": b"#!/bin/bash\nexit 0\n",
    }
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755 if name.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
        if extra is not None:
            tar.addfile(extra, io.BytesIO(b"x" * extra.size) if extra.isfile() else None)
    return out.getvalue()


class FakeGitHub:
    def __init__(self, version: str, archive: bytes, *, sums_digest: str | None = None) -> None:
        name = snapshot_name(version)
        digest = sums_digest or hashlib.sha256(archive).hexdigest()
        self.files = {
            API.format(repo=REPO): json.dumps({"tag_name": f"v{version}", "assets": [
                {"name": n, "browser_download_url": URL.format(v=version, name=n)} for n in (name, "SHA256SUMS")
            ]}).encode(),
            URL.format(v=version, name="SHA256SUMS"): f"{digest}  {name}\n".encode(),
            URL.format(v=version, name=name): archive,
        }
        self.fetched: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.fetched.append(url)
        return self.files[url]


@pytest.fixture
def installed(tmp_path, fake_uv) -> Layout:
    run_install(tmp_path, fake_uv, answers(tmp_path / "inst"), version="1.0.0")
    return Layout(tmp_path / "inst")


def run_update(layout: Layout, github: FakeGitHub, fake_uv: Path, **options: object) -> int:
    return update(layout, fetch=github, uv=fake_uv, python=Path(sys.executable), runner=Recorder(),
                  is_up=lambda _port: True, **options)


def test_update_installs_a_newer_release_after_checking_its_digest(installed, fake_uv):
    github = FakeGitHub("1.2.0", snapshot_bytes("1.2.0"))
    assert run_update(installed, github, fake_uv) == 0
    assert "snapshot 1.2.0" in (installed.app / "README.md").read_text(encoding="utf-8")
    assert json.loads(installed.record.read_text(encoding="utf-8"))["version"] == "1.2.0"
    assert list(installed.temp.iterdir()) == []  # the download folder is gone


def test_update_check_only_downloads_nothing(installed, fake_uv, capsys):
    github = FakeGitHub("1.2.0", snapshot_bytes("1.2.0"))
    assert run_update(installed, github, fake_uv, check_only=True) == 0
    assert github.fetched == [API.format(repo=REPO)]
    assert "1.2.0 is available" in capsys.readouterr().out


@pytest.mark.parametrize("latest", ["1.0.0", "0.9.0", "1.0.0-rc.1"])
def test_update_leaves_an_install_that_is_up_to_date(installed, fake_uv, latest, capsys):
    github = FakeGitHub(latest, snapshot_bytes(latest))
    assert run_update(installed, github, fake_uv) == 0
    assert "up to date" in capsys.readouterr().out
    assert len(github.fetched) == 1


def test_update_refuses_an_archive_that_does_not_match_sha256sums(installed, fake_uv):
    github = FakeGitHub("1.2.0", snapshot_bytes("1.2.0"), sums_digest="0" * 64)
    with pytest.raises(SetupError, match="does not match SHA256SUMS"):
        run_update(installed, github, fake_uv)
    assert "snapshot 1.0.0" in (installed.app / "README.md").read_text(encoding="utf-8")


def test_update_refuses_a_snapshot_of_another_repo(installed, fake_uv):
    github = FakeGitHub("1.2.0", snapshot_bytes("1.2.0", repo="someone/else"))
    with pytest.raises(SetupError, match="is not owner/AgentCliBridge 1.2.0"):
        run_update(installed, github, fake_uv)


def test_update_needs_an_install(tmp_path, fake_uv):
    with pytest.raises(SetupError, match="no install.json"):
        run_update(Layout(tmp_path), FakeGitHub("1.2.0", b""), fake_uv)


@pytest.mark.parametrize("name", ["../evil", "/abs/path", "a/../../b", "c:\\x"])
def test_safe_extract_refuses_a_path_outside_the_target(tmp_path, name):
    info = tarfile.TarInfo(name)
    info.size = 1
    with pytest.raises(SetupError, match="unsafe path"):
        safe_extract(snapshot_bytes("1.0.0", extra=info), tmp_path / "out")
    assert not (tmp_path / "evil").exists()


def test_safe_extract_refuses_a_link(tmp_path):
    info = tarfile.TarInfo("link")
    info.type = tarfile.SYMTYPE
    info.linkname = "/etc/passwd"
    with pytest.raises(SetupError, match="link or a device"):
        safe_extract(snapshot_bytes("1.0.0", extra=info), tmp_path / "out")


def test_fetch_url_refuses_http():
    from bridge_installer.update import fetch_url

    with pytest.raises(SetupError, match="not HTTPS"):
        fetch_url("http://example.invalid/x")


# --- the files the wizard writes -------------------------------------------------------------------


def test_gateway_env_keeps_the_owners_lines_and_rewrites_its_own(tmp_path):
    previous = "# mine\nBRIDGE_WEB_SCOUT=0\nPORT=1\n\n# Written by the AgentCliBridge setup; lines below are rewritten.\nTMP=/x\n"
    text = gateway_env_text(answers(tmp_path, port=4801), previous)
    assert text.startswith("# mine\nBRIDGE_WEB_SCOUT=0\n\n# Written by the AgentCliBridge setup")
    assert text.count("PORT=") == 1 and "PORT=4801" in text and "TMP=/x" not in text
    assert gateway_env_text(answers(tmp_path, port=4801), text) == text  # stable on a re-run


def test_posix_launchers_run_the_snapshot_scripts_with_the_install_folder(tmp_path):
    layout = Layout(tmp_path)
    written = write_launchers(layout, Path("/opt/py/bin/python3.12"), is_windows=False)
    assert sorted(p.name for p in written) == ["kill.sh", "start.sh", "stop.sh", "uninstall.sh", "update.sh"]
    start = (tmp_path / "start.sh").read_text(encoding="utf-8")
    assert f'{INSTALL_DIR_ENV}="$here" exec /bin/bash "$here/app/install.sh" --start' in start
    update_sh = (tmp_path / "update.sh").read_text(encoding="utf-8")
    assert '"/opt/py/bin/python3.12" -m bridge_installer --update --dir "$here" "$@"' in update_sh
    for path in written:
        assert path.stat().st_mode & 0o111
        if shutil.which("sh"):
            assert subprocess.run(["sh", "-n", str(path)], check=False).returncode == 0


def test_windows_launchers_use_the_full_powershell_path(tmp_path):
    write_launchers(Layout(tmp_path), Path(r"C:\i\uv\python\python.exe"), is_windows=True)
    start = (tmp_path / "start.cmd").read_bytes().decode("utf-8")
    assert "\r\n" in start
    assert r'"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile' in start
    assert r'"%HERE%\app\install.ps1" -Start' in start
    assert r'"C:\i\uv\python\python.exe" -m bridge_installer --uninstall --dir "%HERE%" %*' in (
        tmp_path / "uninstall.cmd").read_text(encoding="utf-8")


def test_the_systemd_unit_runs_start_sh_in_the_foreground(tmp_path):
    root = tmp_path / "my install"
    text = systemd_unit_text(Layout(root))
    assert f'Environment="{INSTALL_DIR_ENV}={root}"' in text
    assert f"WorkingDirectory={root / 'app'}\n" in text  # systemd takes this key verbatim: no quotes
    assert f'ExecStart=/bin/bash "{root / "app" / "start.sh"}"' in text
    analyze = shutil.which("systemd-analyze")
    if analyze and sys.platform == "linux":
        (root / "app").mkdir(parents=True)
        (root / "app" / "start.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        unit = tmp_path / "acb-test.service"
        unit.write_text(text, encoding="utf-8")
        done = subprocess.run([analyze, "--user", "verify", str(unit)], capture_output=True, text=True, check=False)
        assert str(unit) not in done.stderr, done.stderr


def test_the_launch_agent_is_interactive_and_logs_in_the_install(tmp_path):
    plist = plistlib.loads(launch_agent_bytes(Layout(tmp_path)))
    assert plist["ProcessType"] == "Interactive"
    assert plist["ProgramArguments"] == ["/bin/bash", str(tmp_path / "app" / "start.sh")]
    assert plist["EnvironmentVariables"] == {INSTALL_DIR_ENV: str(tmp_path)}
    assert plist["StandardOutPath"] == str(tmp_path / "logs" / "gateway.log")


def test_the_run_value_starts_install_ps1_hidden(tmp_path):
    command = run_value_command(Layout(tmp_path / "it's"))
    assert "-WindowStyle Hidden" in command and "install.ps1' -Start" in command
    assert "it''s" in command  # a quote in the folder stays inside the PowerShell string


def test_update_refuses_a_latest_release_tagged_dotnet_and_changes_nothing(installed, fake_uv):
    # C# releases on main are tagged dotnet-v*; the Python updater must never install one.
    github = FakeGitHub("1.2.0", snapshot_bytes("1.2.0"))
    github.files[API.format(repo=REPO)] = json.dumps({"tag_name": "dotnet-v0.1.0", "assets": []}).encode()
    before = sorted((p.relative_to(installed.root), p.read_bytes() if p.is_file() else b"")
                    for p in installed.root.rglob("*") if p.is_file())
    with pytest.raises(SetupError, match="no v<version> tag"):
        run_update(installed, github, fake_uv)
    after = sorted((p.relative_to(installed.root), p.read_bytes() if p.is_file() else b"")
                   for p in installed.root.rglob("*") if p.is_file())
    assert after == before
    assert github.fetched == [API.format(repo=REPO)]
