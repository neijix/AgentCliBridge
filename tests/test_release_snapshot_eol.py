"""Release files are the same bytes on every OS: the snapshot whatever the git line-ending settings, SHA256SUMS with LF."""

from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from bridge_installer.release import build_snapshot, write_sums

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True)


def _source(repo: Path) -> None:
    (repo / "agent_cli_bridge").mkdir(parents=True)
    (repo / "agent_cli_bridge" / "__init__.py").write_bytes(b'__version__ = "1.0.0"\n')
    (repo / "README.md").write_bytes(b"line one\nline two\n")
    _git(repo, "init", "--quiet")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "add", ".")
    _git(repo, "commit", "--quiet", "-m", "init")


def _members(archive: Path) -> dict[str, bytes]:
    with tarfile.open(archive) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}


def test_a_crlf_checkout_setting_does_not_change_the_snapshot(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _source(repo)
    plain = build_snapshot(tmp_path / "plain", repo_dir=repo, repo="o/r")
    # A Windows runner checks out with core.autocrlf=true; git archive would follow it.
    _git(repo, "config", "core.autocrlf", "true")
    _git(repo, "config", "core.eol", "crlf")
    crlf = build_snapshot(tmp_path / "crlf", repo_dir=repo, repo="o/r")
    assert plain.read_bytes() == crlf.read_bytes()
    assert not any(b"\r\n" in data for data in _members(crlf).values())


def test_sha256sums_has_lf_line_endings_on_every_os(tmp_path: Path):
    asset = tmp_path / "a.deb"
    asset.write_bytes(b"x")
    out = write_sums([asset], tmp_path / "SHA256SUMS")
    assert out.read_bytes().endswith(b"  a.deb\n") and b"\r" not in out.read_bytes()
