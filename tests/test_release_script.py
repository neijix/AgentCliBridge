"""packaging/release.sh, ``make package`` and ``make release`` (AC9).

The script runs against a stub ``gh`` first on PATH: it records every call and serves a fake Release
(assets with bytes) from a folder, never the network. The source is a small throwaway git repo (so a tag
can be made and refused without touching this checkout); the real snapshot builder (row 3) runs on it.
The per-OS package builders are stubs in a copy of the script's folder, except in the one test that
builds a real ``.deb``.
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from bridge_installer import MANIFEST_NAME, release

ROOT = Path(__file__).resolve().parents[1]
RELEASE_SH = ROOT / "packaging" / "release.sh"
MAKEFILE = ROOT / "Makefile"
REPO = "owner/repo"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or os.name == "nt", reason="needs bash on POSIX")

GH_STUB = f'''#!{sys.executable}
"""A stand-in for gh: a Release served from $GH_STUB_STATE (release.json + assets/), calls in calls.jsonl."""
import fnmatch, json, os, shutil, sys
from pathlib import Path

state = Path(os.environ["GH_STUB_STATE"])
args = sys.argv[1:]
with (state / "calls.jsonl").open("a") as handle:
    handle.write(json.dumps(args) + "\\n")
assets, meta = state / "assets", state / "release.json"
VALUED = {{"--repo", "--pattern", "--dir", "--json", "--title", "--notes"}}
values: dict[str, list[str]] = {{}}
flags: set[str] = set()
positional: list[str] = []
i = 0
while i < len(args):
    if args[i] in VALUED:
        values.setdefault(args[i], []).append(args[i + 1])
        i += 2
    elif args[i].startswith("--"):
        flags.add(args[i])
        i += 1
    else:
        positional.append(args[i])
        i += 1


def fail(message: str, code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(code)


if positional[:1] != ["release"] or "--repo" not in values:
    fail("stub gh: only `gh release ... --repo R` is served", 2)
sub, tag, rest = positional[1], positional[2], positional[3:]
if sub == "view":
    if os.environ.get("GH_STUB_VIEW_FAIL"):
        fail("HTTP 502: Bad Gateway")
    if not meta.exists():
        fail("release not found")
    names = sorted(p.name for p in assets.iterdir())
    print(json.dumps({{"assets": [{{"name": n, "size": (assets / n).stat().st_size}} for n in names]}}))
elif sub == "create":
    if meta.exists():
        fail("a release with the tag already exists")
    meta.write_text(json.dumps({{"tag": tag, "prerelease": "--prerelease" in flags}}))
elif sub == "upload":
    if not meta.exists():
        fail("release not found")
    for path in rest:
        name = Path(path).name
        data = Path(path).read_bytes()
        if (assets / name).exists() and "--clobber" not in flags:
            fail(f'a release asset named "{{name}}" already exists')
        if name == "SHA256SUMS":
            counter = state / "sums-uploads"
            seen = int(counter.read_text()) if counter.exists() else 0
            counter.write_text(str(seen + 1))
            if seen < int(os.environ.get("GH_STUB_SUMS_LOSE", "0")):  # a concurrent writer wins
                data = b"".join(data.splitlines(keepends=True)[:-1])
            late = os.environ.get("GH_STUB_LATE_ASSET")
            if seen == 0 and late:  # another OS's job attaches its package after this run hashed the rest
                (assets / late).write_bytes(b"late package")
        (assets / name).write_bytes(data)
elif sub == "download":
    if not meta.exists():
        fail("release not found")
    target = Path(values["--dir"][0])
    target.mkdir(parents=True, exist_ok=True)
    found = [p for p in sorted(assets.iterdir()) if any(fnmatch.fnmatchcase(p.name, g) for g in values["--pattern"])]
    if not found:
        fail("no assets match the file pattern")
    for path in found:
        shutil.copyfile(path, target / path.name)
else:
    fail(f"stub gh: `release {{sub}}` must not be called", 2)
'''

# Builders: write the package named for the snapshot's version, print its path (as the real ones do).
BUILDER_STUB = """#!/bin/bash
set -eu
echo "$(basename "$0") $*" >> "$STUB_BUILD_LOG"
snapshot="" out=""
while [ $# -gt 0 ]; do
  case "$1" in
    --snapshot | -Archive) snapshot="$2"; shift 2 ;;
    --out | -OutDir) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
version="$(basename "$snapshot")"
version="${version#agentclibridge-}"
version="${version%-any-all-snapshot.tar.gz}"
mkdir -p "$out"
printf '%s %s' "${STUB_PACKAGE_CONTENT:-package}" "$version" > "$out/NAME_PLACEHOLDER"
echo "$out/NAME_PLACEHOLDER"
"""
BUILDERS = {  # relative path -> package name template ({v} = version)
    "linux/build-deb.sh": "agentclibridge-{v}-linux-all.deb",
    "macos/build-pkg.sh": "agentclibridge-{v}-macos-all.pkg",
}


def _executable(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _make_builder(path: Path, name_template: str) -> None:
    text = BUILDER_STUB.replace("NAME_PLACEHOLDER", name_template.replace("{v}", "${version}"))
    _executable(path, text)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false",
         "-c", "tag.gpgsign=false", "-C", str(repo), *args],
        capture_output=True, text=True, check=True,
    )
    return done.stdout.strip()


def _make_source(path: Path, version: str = "1.0.0", tags: tuple[str, ...] = ("v1.0.0",)) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q")
    (path / "agent_cli_bridge").mkdir()
    (path / "agent_cli_bridge" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (path / "bridge_installer").mkdir()
    (path / "bridge_installer" / "__init__.py").write_text("")
    (path / "bridge_installer" / "__main__.py").write_text("print('wizard')\n")  # build-deb.sh wants it
    (path / "README.md").write_text("hello\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", "init")
    for tag in tags:
        _git(path, "tag", tag)
    return path


def _verify_archive(archive: Path, sums_file: Path, version: str = "1.0.0") -> None:
    listed = release.parse_sums(sums_file.read_text(encoding="utf-8"))
    assert listed[archive.name] == release.sha256_of(archive)
    with tarfile.open(archive, "r:gz") as tar:
        member = tar.extractfile(MANIFEST_NAME)
        assert member is not None
        manifest_data = json.loads(member.read().decode("utf-8"))
    assert manifest_data["version"] == version


class Harness:
    """A throwaway source repo, a gh stub with its Release state, and a copy of release.sh with stub builders."""

    def __init__(self, tmp: Path, tags: tuple[str, ...] = ("v1.0.0",), version: str = "1.0.0") -> None:
        self.tmp = tmp
        self.source = _make_source(tmp / "source", version, tags)
        self.state = tmp / "gh-state"
        (self.state / "assets").mkdir(parents=True)
        self.bin = tmp / "bin"
        _executable(self.bin / "gh", GH_STUB)
        self.tool = tmp / "tool"
        self.script = self.tool / "packaging" / "release.sh"
        self.script.parent.mkdir(parents=True)
        shutil.copyfile(RELEASE_SH, self.script)
        for relative, name in BUILDERS.items():
            _make_builder(self.tool / "packaging" / relative, name)
        _make_builder(self.bin / "pwsh", "agentclibridge-{v}-windows-all-setup.exe")
        self.out = tmp / "dist"
        self.build_log = tmp / "builds.log"

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_REPOSITORY"}
        env.update(
            PATH=f"{self.bin}{os.pathsep}{os.environ['PATH']}", PYTHONPATH=str(ROOT), PYTHON=sys.executable,
            GH_STUB_STATE=str(self.state), STUB_BUILD_LOG=str(self.build_log), AGENTCLIBRIDGE_PACKAGE_OS="Linux",
        )
        env.update(extra)
        return env

    def run(self, mode: str, *args: str, script: Path | None = None, **env: str) -> subprocess.CompletedProcess[str]:
        command = ["bash", str(script or self.script), mode, "--repo", REPO, "--repo-dir", str(self.source),
                   "--out", str(self.out), *args]
        return subprocess.run(command, capture_output=True, text=True, env=self.env(**env), check=False, cwd=self.tmp)

    def calls(self, sub: str | None = None) -> list[list[str]]:
        log = self.state / "calls.jsonl"
        found = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [c for c in found if sub is None or c[1] == sub]

    def assets(self) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in sorted((self.state / "assets").iterdir())}

    def release_meta(self) -> dict:
        return json.loads((self.state / "release.json").read_text())

    def builds(self) -> list[str]:
        return self.build_log.read_text().splitlines() if self.build_log.exists() else []


@pytest.fixture
def harness(tmp_path: Path) -> Harness:
    return Harness(tmp_path)


def _lists(sums_text: str) -> dict[str, str]:
    return release.parse_sums(sums_text)


# --- release: the Release and its assets ---------------------------------------------------------


def test_release_is_created_when_missing_and_everything_uploaded(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0")
    assert done.returncode == 0, done.stderr
    assert harness.release_meta() == {"tag": "v1.0.0", "prerelease": False}
    snapshot, package = release.snapshot_name("1.0.0"), "agentclibridge-1.0.0-linux-all.deb"
    assets = harness.assets()
    assert set(assets) == {snapshot, package, "SHA256SUMS"}
    assert done.stdout.strip() == str(harness.out / package)
    create = harness.calls("create")[0]
    assert "--verify-tag" in create and "--prerelease" not in create
    _verify_archive(harness.out / snapshot, harness.state / "assets" / "SHA256SUMS")
    assert (harness.out / snapshot).read_bytes() == assets[snapshot]
    listed = _lists(assets["SHA256SUMS"].decode())
    assert set(listed) == {snapshot, package}
    assert listed[package] == release.sha256_of(harness.out / package)
    assert all(REPO in call and call[call.index("--repo") + 1] == REPO for call in harness.calls())


def test_the_snapshot_is_built_once_and_the_package_carries_it(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0")
    assert done.returncode == 0, done.stderr
    snapshot = harness.out / release.snapshot_name("1.0.0")
    [build] = harness.builds()
    assert build == f"build-deb.sh --snapshot {snapshot} --out {harness.out}"
    assert sorted(p.name for p in harness.out.glob("*.tar.gz")) == [snapshot.name]


def test_a_tag_with_a_suffix_is_a_prerelease(tmp_path: Path) -> None:
    harness = Harness(tmp_path, tags=("v0.0.0-test.1",))
    done = harness.run("release", "--tag", "v0.0.0-test.1")
    assert done.returncode == 0, done.stderr
    assert harness.release_meta() == {"tag": "v0.0.0-test.1", "prerelease": True}
    assert "--prerelease" in harness.calls("create")[0]
    assert "agentclibridge-0.0.0-test.1-linux-all.deb" in harness.assets()
    assert release.snapshot_name("0.0.0-test.1") in harness.assets()


def test_the_tag_at_head_is_used_when_none_is_given(harness: Harness) -> None:
    done = harness.run("release")
    assert done.returncode == 0, done.stderr
    assert harness.release_meta()["tag"] == "v1.0.0"


def test_no_tag_at_head_and_none_given_is_refused_before_any_call(tmp_path: Path) -> None:
    harness = Harness(tmp_path, tags=())
    done = harness.run("release")
    assert done.returncode != 0
    assert "no v* tag" in done.stderr
    assert harness.calls() == [] and harness.builds() == []


def test_a_release_tag_that_differs_from_the_version_is_refused_through_the_snapshot_builder(tmp_path: Path) -> None:
    harness = Harness(tmp_path, tags=("v2.0.0",), version="1.0.0")
    done = harness.run("release", "--tag", "v2.0.0")
    assert done.returncode != 0
    assert "v2.0.0" in done.stderr and "1.0.0" in done.stderr
    assert harness.calls() == [] and harness.builds() == []


def test_an_unknown_tag_is_refused(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.2.3")
    assert done.returncode != 0
    assert "unknown tag" in done.stderr
    assert harness.calls() == []


def test_a_failing_release_lookup_does_not_create_a_release(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0", GH_STUB_VIEW_FAIL="1")
    assert done.returncode != 0
    assert "502" in done.stderr
    assert harness.calls("create") == [] and harness.calls("upload") == []


def test_gh_missing_is_reported(harness: Harness) -> None:
    (harness.bin / "gh").unlink()
    with_python = harness.tmp / "pybin"
    with_python.mkdir()
    for tool in ("bash", "git", "sed", "tail", "tr", "cat", "mkdir", "rm", "mktemp", "dirname", "basename", "uname"):
        found = shutil.which(tool)
        assert found is not None
        (with_python / tool).symlink_to(found)
    (with_python / "python").symlink_to(sys.executable)
    done = harness.run("release", "--tag", "v1.0.0", PATH=f"{harness.bin}{os.pathsep}{with_python}")
    assert done.returncode != 0
    assert "gh is not installed" in done.stderr


# --- release: collisions ------------------------------------------------------------------------


def test_a_package_already_attached_is_refused_naming_it(harness: Harness) -> None:
    assert harness.run("release", "--tag", "v1.0.0").returncode == 0
    before = harness.assets()
    uploads = len(harness.calls("upload"))
    done = harness.run("release", "--tag", "v1.0.0", STUB_PACKAGE_CONTENT="rebuilt")
    assert done.returncode != 0
    assert "agentclibridge-1.0.0-linux-all.deb" in done.stderr and "--clobber" in done.stderr
    assert harness.assets() == before
    assert len(harness.calls("upload")) == uploads


def test_clobber_replaces_the_package_and_skips_the_equal_snapshot(harness: Harness) -> None:
    assert harness.run("release", "--tag", "v1.0.0").returncode == 0
    uploads = len(harness.calls("upload"))
    done = harness.run("release", "--tag", "v1.0.0", "--clobber", STUB_PACKAGE_CONTENT="rebuilt")
    assert done.returncode == 0, done.stderr
    assert harness.assets()["agentclibridge-1.0.0-linux-all.deb"] == b"rebuilt 1.0.0"
    package_upload = harness.calls("upload")[uploads]
    assert "--clobber" in package_upload
    assert not any(a.endswith("-snapshot.tar.gz") for a in package_upload), "the equal snapshot was uploaded again"
    assert "byte-equal" in done.stderr
    listed = _lists(harness.assets()["SHA256SUMS"].decode())
    assert listed["agentclibridge-1.0.0-linux-all.deb"] == release.sha256_of(
        harness.out / "agentclibridge-1.0.0-linux-all.deb"
    )


def test_a_different_snapshot_on_the_release_is_refused_even_with_clobber(harness: Harness) -> None:
    assert harness.run("release", "--tag", "v1.0.0").returncode == 0
    snapshot = harness.state / "assets" / release.snapshot_name("1.0.0")
    snapshot.write_bytes(b"another build")
    uploads = len(harness.calls("upload"))
    done = harness.run("release", "--tag", "v1.0.0", "--clobber")
    assert done.returncode != 0
    assert release.snapshot_name("1.0.0") in done.stderr and "different" in done.stderr
    assert snapshot.read_bytes() == b"another build"
    assert len(harness.calls("upload")) == uploads


def test_a_second_os_adds_its_package_and_sums_list_every_asset(harness: Harness) -> None:
    assert harness.run("release", "--tag", "v1.0.0").returncode == 0
    done = harness.run("release", "--tag", "v1.0.0", AGENTCLIBRIDGE_PACKAGE_OS="Darwin")
    assert done.returncode == 0, done.stderr
    assert set(_lists(harness.assets()["SHA256SUMS"].decode())) == {
        release.snapshot_name("1.0.0"),
        "agentclibridge-1.0.0-linux-all.deb",
        "agentclibridge-1.0.0-macos-all.pkg",
    }
    assert harness.assets()["agentclibridge-1.0.0-macos-all.pkg"] == b"package 1.0.0"


# --- release: SHA256SUMS ------------------------------------------------------------------------


def test_sums_are_rewritten_until_they_list_every_asset(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0", GH_STUB_SUMS_LOSE="2")
    assert done.returncode == 0, done.stderr
    sums_uploads = [c for c in harness.calls("upload") if any(a.endswith("SHA256SUMS") for a in c)]
    assert len(sums_uploads) == 3
    assert set(_lists(harness.assets()["SHA256SUMS"].decode())) == {
        release.snapshot_name("1.0.0"),
        "agentclibridge-1.0.0-linux-all.deb",
    }
    assert all("--clobber" in c for c in sums_uploads)


def test_sums_that_never_list_everything_fail_after_three_tries_naming_the_missing(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0", GH_STUB_SUMS_LOSE="99")
    assert done.returncode != 0
    sums_uploads = [c for c in harness.calls("upload") if any(a.endswith("SHA256SUMS") for a in c)]
    assert len(sums_uploads) == 3
    assert "agentclibridge-1.0.0-linux-all.deb" in done.stderr and "3 tries" in done.stderr


def test_an_asset_attached_after_the_download_is_hashed_on_the_next_try(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0", GH_STUB_LATE_ASSET="agentclibridge-1.0.0-windows-all-setup.exe")
    assert done.returncode == 0, done.stderr
    sums_uploads = [c for c in harness.calls("upload") if any(a.endswith("SHA256SUMS") for a in c)]
    assert len(sums_uploads) == 2
    assert "agentclibridge-1.0.0-windows-all-setup.exe" in done.stderr  # the first try named what it lacked
    assert set(_lists(harness.assets()["SHA256SUMS"].decode())) == {
        release.snapshot_name("1.0.0"),
        "agentclibridge-1.0.0-linux-all.deb",
        "agentclibridge-1.0.0-windows-all-setup.exe",
    }


def test_a_windows_python_path_runs_with_forward_slashes(harness: Harness) -> None:
    native = sys.executable.replace("/", "\\")
    done = harness.run("release", "--tag", "v1.0.0", PYTHON=native)
    assert done.returncode == 0, done.stderr


def test_no_sums_uploads_the_package_and_leaves_sums_to_the_sums_mode(harness: Harness) -> None:
    done = harness.run("release", "--tag", "v1.0.0", "--no-sums")
    assert done.returncode == 0, done.stderr
    assert set(harness.assets()) == {release.snapshot_name("1.0.0"), "agentclibridge-1.0.0-linux-all.deb"}
    assert not [c for c in harness.calls("upload") if any(a.endswith("SHA256SUMS") for a in c)]
    done = harness.run("release", "--tag", "v1.0.0", "--no-sums", AGENTCLIBRIDGE_PACKAGE_OS="Darwin")
    assert done.returncode == 0, done.stderr
    builds = len(harness.builds())
    done = harness.run("sums", "--tag", "v1.0.0")
    assert done.returncode == 0, done.stderr
    assert len(harness.builds()) == builds  # sums builds nothing
    uploads = harness.calls("upload")
    assert [a for a in uploads[-1] if a.endswith("SHA256SUMS")]  # its only upload is the sums file
    assert set(_lists(harness.assets()["SHA256SUMS"].decode())) == {
        release.snapshot_name("1.0.0"),
        "agentclibridge-1.0.0-linux-all.deb",
        "agentclibridge-1.0.0-macos-all.pkg",
    }
    _verify_archive(harness.out / release.snapshot_name("1.0.0"), harness.state / "assets" / "SHA256SUMS")


def test_sums_mode_retries_and_needs_a_tag(harness: Harness) -> None:
    assert harness.run("release", "--tag", "v1.0.0", "--no-sums").returncode == 0
    done = harness.run("sums", "--tag", "v1.0.0", GH_STUB_SUMS_LOSE="2")
    assert done.returncode == 0, done.stderr
    assert len([c for c in harness.calls("upload") if any(a.endswith("SHA256SUMS") for a in c)]) == 3
    assert harness.run("sums", "--tag", "v1.0.0", "--clobber").returncode != 0
    assert harness.run("package", "--no-sums").returncode != 0


# --- package: this OS's builder -----------------------------------------------------------------


def test_package_builds_without_touching_github(harness: Harness) -> None:
    done = harness.run("package")
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(harness.out / "agentclibridge-1.0.0-linux-all.deb")
    assert harness.calls() == []
    assert (harness.out / release.snapshot_name("1.0.0")).is_file()  # HEAD without a tag: __version__


@pytest.mark.parametrize(
    ("os_name", "builder", "package"),
    [
        ("Linux", "build-deb.sh", "agentclibridge-1.0.0-linux-all.deb"),
        ("Darwin", "build-pkg.sh", "agentclibridge-1.0.0-macos-all.pkg"),
        ("MINGW64_NT-10.0", "pwsh", "agentclibridge-1.0.0-windows-all-setup.exe"),
        ("MSYS_NT-10.0", "pwsh", "agentclibridge-1.0.0-windows-all-setup.exe"),
    ],
)
def test_package_dispatches_on_the_os(harness: Harness, os_name: str, builder: str, package: str) -> None:
    done = harness.run("package", AGENTCLIBRIDGE_PACKAGE_OS=os_name)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(harness.out / package)
    [build] = harness.builds()
    snapshot = harness.out / release.snapshot_name("1.0.0")
    if builder == "pwsh":
        assert build.startswith("pwsh -NoProfile -File ")
        assert build.endswith(f"build-exe.ps1 -Archive {snapshot} -OutDir {harness.out}")
    else:
        assert build == f"{builder} --snapshot {snapshot} --out {harness.out}"


def test_an_unsupported_os_is_refused(harness: Harness) -> None:
    done = harness.run("package", AGENTCLIBRIDGE_PACKAGE_OS="Plan9")
    assert done.returncode != 0 and "no installer package" in done.stderr
    assert harness.builds() == []


def test_a_real_deb_is_built_and_released(tmp_path: Path) -> None:
    if shutil.which("dpkg-deb") is None:
        pytest.skip("dpkg-deb is not installed")
    harness = Harness(tmp_path)
    done = harness.run("release", "--tag", "v1.0.0", script=RELEASE_SH, SOURCE_DATE_EPOCH="1700000000")
    assert done.returncode == 0, done.stderr
    package = harness.out / "agentclibridge-1.0.0-linux-all.deb"
    assert harness.assets()["agentclibridge-1.0.0-linux-all.deb"] == package.read_bytes()
    info = subprocess.run(
        ["dpkg-deb", "-f", str(package), "Package", "Version"], capture_output=True, text=True, check=True
    )
    assert "agentclibridge" in info.stdout and "1.0.0" in info.stdout
    _verify_archive(harness.out / release.snapshot_name("1.0.0"), harness.state / "assets" / "SHA256SUMS")


# --- Makefile and .gitignore --------------------------------------------------------------------


def test_makefile_targets_run_the_script() -> None:
    text = MAKEFILE.read_text()
    phony = next(line for line in text.splitlines() if line.startswith(".PHONY"))
    assert "package" in phony.split() and "release" in phony.split()
    assert "bash packaging/release.sh package" in text
    assert "bash packaging/release.sh release" in text
    assert "--clobber" in text and "CLOBBER" in text


@pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed")
def test_make_passes_the_variables_through() -> None:
    package = subprocess.run(
        ["make", "-n", "package", "TAG=v1.0.0", "REPO=o/r"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert "bash packaging/release.sh package --tag v1.0.0 --repo o/r" in package.stdout
    plain = subprocess.run(["make", "-n", "release"], cwd=ROOT, capture_output=True, text=True, check=True)
    assert "--clobber" not in plain.stdout
    clobber = subprocess.run(
        ["make", "-n", "release", "CLOBBER=1"], cwd=ROOT, capture_output=True, text=True, check=True
    )
    assert clobber.stdout.strip().endswith("--clobber")


def test_dist_is_ignored() -> None:
    assert "dist/" in (ROOT / ".gitignore").read_text().splitlines()
