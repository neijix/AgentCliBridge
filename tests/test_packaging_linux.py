"""packaging/linux/build-deb.sh and agentclibridge-setup: the .deb (AC9).

The package is built for real with dpkg-deb from a small synthetic snapshot (and once from the repo's
own snapshot), then read back with ``dpkg-deb -c / -f / -x``. Nothing is installed: the package is
only listed and unpacked into tmp_path.
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from bridge_installer import MANIFEST_NAME, manifest

ROOT = Path(__file__).resolve().parents[1]
BUILD_DEB = ROOT / "packaging" / "linux" / "build-deb.sh"
LAUNCHER = ROOT / "packaging" / "linux" / "agentclibridge-setup"
SETUP_SH = ROOT / "packaging" / "setup.sh"

needs_dpkg = pytest.mark.skipif(
    shutil.which("dpkg-deb") is None or shutil.which("bash") is None or os.name == "nt",
    reason="dpkg-deb (and bash) is not installed",
)

EPOCH = "1700000000"
COMMIT = "0123456789abcdef0123456789abcdef01234567"


def _snapshot(
    path: Path, version: str = "1.0.0", extra: dict[str, bytes] | None = None, *, with_manifest: bool = True
) -> Path:
    """A small snapshot archive: the manifest, the wizard entry point, an executable and a data file."""
    files: dict[str, tuple[bytes, int]] = {
        "agent_cli_bridge/__init__.py": (b'__version__ = "1.0.0"\n', 0o644),
        "bridge_installer/__init__.py": (b"", 0o644),
        "bridge_installer/__main__.py": (b"print('wizard')\n", 0o600),
        "tools/run.sh": (b"#!/bin/sh\n", 0o750),
        "README.md": (b"hello\n", 0o664),
    }
    for name, data in (extra or {}).items():
        files[name] = (data, 0o644)
    if with_manifest:
        text = manifest.Manifest(version=version, commit=COMMIT, repo="owner/repo").as_json()
        files[MANIFEST_NAME] = (text.encode(), 0o644)
    with tarfile.open(path, "w:gz") as tar:
        for name, (data, mode) in sorted(files.items()):
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(data), mode, 1
            tar.addfile(info, io.BytesIO(data))
    return path


def _build(tmp: Path, snapshot: Path, out_name: str = "out", **env: str) -> subprocess.CompletedProcess[str]:
    environ = {**os.environ, "SOURCE_DATE_EPOCH": EPOCH, **env}
    return subprocess.run(
        ["bash", str(BUILD_DEB), "--snapshot", str(snapshot), "--out", str(tmp / out_name)],
        capture_output=True, text=True, env=environ, check=False,
    )


def _listing(deb: Path) -> dict[str, tuple[str, str]]:
    """``{path: (mode string, owner/group)}`` from ``dpkg-deb -c``."""
    text = subprocess.run(["dpkg-deb", "-c", str(deb)], capture_output=True, text=True, check=True).stdout
    found = {}
    for line in text.splitlines():
        mode, owner, _size, _date, _time, name = line.split(None, 5)
        found[name] = (mode, owner)
    return found


def _field(deb: Path, name: str) -> str:
    return subprocess.run(["dpkg-deb", "-f", str(deb), name], capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def built(tmp_path: Path) -> Path:
    done = _build(tmp_path, _snapshot(tmp_path / "snap.tar.gz"))
    assert done.returncode == 0, done.stderr
    return Path(done.stdout.strip())


@needs_dpkg
def test_deb_is_named_for_the_manifest_version_and_is_arch_all(built: Path, tmp_path: Path) -> None:
    assert built == (tmp_path / "out" / "agentclibridge-1.0.0-linux-all.deb").resolve()
    assert _field(built, "Package") == "agentclibridge"
    assert _field(built, "Version") == "1.0.0"
    assert _field(built, "Architecture") == "all"


@needs_dpkg
def test_deb_depends_on_bash_and_curl_or_wget(built: Path) -> None:
    depends = [part.strip() for part in _field(built, "Depends").split(",")]
    assert "bash" in depends
    assert "curl | wget" in depends  # setup.sh fetches uv with one of them


@needs_dpkg
def test_deb_holds_only_opt_agentclibridge_and_the_launcher_all_owned_by_root(built: Path) -> None:
    listing = _listing(built)
    names = [name.lstrip(".") for name in listing]
    assert {owner for _mode, owner in listing.values()} == {"root/root"}
    for name in names:
        assert (
            name in ("/", "/opt/", "/opt/agentclibridge/", "/usr/", "/usr/bin/", "/usr/bin/agentclibridge-setup")
            or name.startswith("/opt/agentclibridge/")
        ), name
    assert "/opt/agentclibridge/setup.sh" in names
    assert "/opt/agentclibridge/setup.ps1" not in names  # Windows only
    assert "/opt/agentclibridge/app/" + MANIFEST_NAME in names
    assert "/opt/agentclibridge/app/bridge_installer/__main__.py" in names


@needs_dpkg
def test_deb_modes_are_normalised_whatever_the_archive_said(built: Path) -> None:
    listing = _listing(built)
    mode = {name.lstrip("."): kind for name, (kind, _owner) in listing.items()}
    assert mode["/opt/agentclibridge/setup.sh"] == "-rwxr-xr-x"
    assert mode["/usr/bin/agentclibridge-setup"] == "-rwxr-xr-x"
    assert mode["/opt/agentclibridge/app/tools/run.sh"] == "-rwxr-xr-x"
    assert mode["/opt/agentclibridge/app/bridge_installer/__main__.py"] == "-rw-r--r--"  # 0600 in the archive
    assert mode["/opt/agentclibridge/app/README.md"] == "-rw-r--r--"  # 0664 in the archive
    assert all(kind.startswith("drwxr-xr-x") for name, kind in mode.items() if name.endswith("/"))


@needs_dpkg
def test_deb_has_no_maintainer_scripts_so_nothing_is_written_at_install(built: Path, tmp_path: Path) -> None:
    control = tmp_path / "control"
    subprocess.run(["dpkg-deb", "-e", str(built), str(control)], check=True)
    assert sorted(p.name for p in control.iterdir()) == ["control"]


@needs_dpkg
def test_deb_unpacks_the_snapshot_beside_the_twin_and_the_launcher_execs_it(built: Path, tmp_path: Path) -> None:
    root = tmp_path / "unpacked"
    subprocess.run(["dpkg-deb", "-x", str(built), str(root)], check=True)
    assert (root / "opt/agentclibridge/setup.sh").read_bytes() == SETUP_SH.read_bytes()
    assert (root / "opt/agentclibridge/app" / MANIFEST_NAME).is_file()
    launcher = root / "usr/bin/agentclibridge-setup"
    assert launcher.read_bytes() == LAUNCHER.read_bytes()
    assert launcher.read_text().splitlines()[0] == "#!/bin/sh"
    assert 'exec /opt/agentclibridge/setup.sh "$@"' in launcher.read_text()
    # Run it against a stand-in for /opt/agentclibridge/setup.sh: every argument arrives, spaces intact.
    stand_in = tmp_path / "setup.sh"
    stand_in.write_text('#!/bin/sh\nfor a in "$@"; do printf "[%s]" "$a"; done\n')
    stand_in.chmod(0o755)
    copy = tmp_path / "launcher"
    copy.write_text(launcher.read_text().replace("/opt/agentclibridge/setup.sh", str(stand_in)))
    done = subprocess.run(["sh", str(copy), "--dir", "a b", "--yes"], capture_output=True, text=True, check=True)
    assert done.stdout == "[--dir][a b][--yes]"


@needs_dpkg
def test_a_prerelease_sorts_before_its_release_in_the_control_file(tmp_path: Path) -> None:
    done = _build(tmp_path, _snapshot(tmp_path / "snap.tar.gz", version="1.2.0-rc.1"))
    assert done.returncode == 0, done.stderr
    deb = Path(done.stdout.strip())
    assert deb.name == "agentclibridge-1.2.0-rc.1-linux-all.deb"
    assert _field(deb, "Version") == "1.2.0~rc.1"
    assert subprocess.run(["dpkg", "--compare-versions", "1.2.0~rc.1", "lt", "1.2.0"], check=False).returncode == 0


@needs_dpkg
def test_same_snapshot_and_epoch_give_the_same_bytes(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path / "snap.tar.gz")
    first, second = _build(tmp_path, snap, "a"), _build(tmp_path, snap, "b")
    assert first.returncode == second.returncode == 0
    assert Path(first.stdout.strip()).read_bytes() == Path(second.stdout.strip()).read_bytes()


@needs_dpkg
def test_a_file_that_is_not_a_snapshot_is_refused_and_nothing_is_written(tmp_path: Path) -> None:
    done = _build(tmp_path, _snapshot(tmp_path / "snap.tar.gz", with_manifest=False))
    assert done.returncode != 0
    assert MANIFEST_NAME in done.stderr
    assert not list((tmp_path / "out").glob("*.deb"))


@needs_dpkg
def test_a_malformed_version_is_refused(tmp_path: Path) -> None:
    done = _build(tmp_path, _snapshot(tmp_path / "snap.tar.gz", version="../1.0"))
    assert done.returncode != 0
    assert "SemVer" in done.stderr
    assert not list((tmp_path / "out").glob("*.deb"))


@needs_dpkg
def test_a_parent_relative_path_listed_first_in_a_big_archive_is_still_refused(tmp_path: Path) -> None:
    """The listing outgrows a pipe buffer after the match: an early-exiting grep must not wave it through."""
    snap = tmp_path / "snap.tar.gz"
    data = manifest.Manifest(version="1.0.0", commit=COMMIT, repo="o/r").as_json().encode()
    with tarfile.open(snap, "w:gz") as tar:
        names = ["../escape", MANIFEST_NAME, *(f"pad/{'x' * 90}{i:05d}" for i in range(3000))]
        for name in names:
            body = data if name == MANIFEST_NAME else b""
            info = tarfile.TarInfo(name)
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
    done = _build(tmp_path, snap)
    assert done.returncode != 0
    assert "parent-relative" in done.stderr
    assert not list((tmp_path / "out").glob("*.deb"))


@needs_dpkg
def test_an_archive_with_a_parent_relative_path_is_refused(tmp_path: Path) -> None:
    snap = _snapshot(tmp_path / "snap.tar.gz")
    with tarfile.open(snap, "w:gz") as tar:
        for name in (MANIFEST_NAME, "../escape"):
            data = manifest.Manifest(version="1.0.0", commit=COMMIT, repo="o/r").as_json().encode()
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    done = _build(tmp_path, snap)
    assert done.returncode != 0
    assert "parent-relative" in done.stderr
    assert not list((tmp_path / "out").glob("*.deb"))


@needs_dpkg
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_without_a_snapshot_argument_the_script_builds_one_from_the_repo(tmp_path: Path) -> None:
    done = subprocess.run(
        ["bash", str(BUILD_DEB), "--repo", "owner/repo", "--out", str(tmp_path / "out")],
        capture_output=True, text=True, check=False, env={**os.environ, "PYTHON": sys.executable},
    )
    assert done.returncode == 0, done.stderr
    deb = Path(done.stdout.strip())
    assert deb.name == f"agentclibridge-{_field(deb, 'Version')}-linux-all.deb"
    names = {name.lstrip(".") for name in _listing(deb)}
    assert "/opt/agentclibridge/app/" + MANIFEST_NAME in names
    assert "/opt/agentclibridge/app/bridge_installer/__main__.py" in names
    assert not any(name.endswith("/.git/") or "/.git/" in name for name in names)
    # packaging/ is excluded, so the twin comes from the repo beside the script, not the snapshot.
    assert "/opt/agentclibridge/setup.sh" in names
    assert not any(name.startswith("/opt/agentclibridge/app/packaging") for name in names)


def test_build_script_uses_root_owner_group_and_never_fakeroot_or_installs() -> None:
    text = BUILD_DEB.read_text()
    assert "--root-owner-group" in text
    assert "fakeroot" not in text
    assert "dpkg -i" not in text and "apt " not in text and "sudo" not in text
    assert "SOURCE_DATE_EPOCH" in text


def test_the_manifest_file_name_in_the_script_matches_the_python_one() -> None:
    assert f'MANIFEST_NAME="{MANIFEST_NAME}"' in BUILD_DEB.read_text()


def test_launcher_is_one_exec_of_the_twin_in_opt() -> None:
    lines = [line for line in LAUNCHER.read_text().splitlines() if line and not line.startswith("#!")]
    assert [line for line in lines if not line.startswith("#")] == ['exec /opt/agentclibridge/setup.sh "$@"']
    assert os.access(LAUNCHER, os.X_OK) and os.access(BUILD_DEB, os.X_OK)
