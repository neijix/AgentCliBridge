"""packaging/macos: the .pkg's Distribution, postinstall and build script (AC9).

pkgbuild and productbuild exist only on a Mac, so the build runs here up to them: --stage-only checks
the staged scripts folder, and stubs on PATH stand in for pkgbuild / productbuild to read the commands
the script would run. The postinstall runs for real against stubs for open, osascript and (in one test)
tar, with fake package paths; one test runs it with a real tar over a staged package. The real install
on a Mac is the owner's check (docs/plans/os-installers.md, row 22).
"""
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MAC = ROOT / "packaging" / "macos"
BUILD = MAC / "build-pkg.sh"
POSTINSTALL = MAC / "postinstall"
DISTRIBUTION = MAC / "distribution.xml"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="the macOS scripts run under sh")

SYSTEM_PATH = "/usr/bin:/bin"
VERSION = "1.2.3"
MANIFEST_NAME = "agentclibridge-snapshot.json"

# Installer's sandbox and temporary folders: a refused place for the setup folder.
REFUSED = [
    "/private/tmp/PKInstallSandbox.AbC123/Downloads/agentclibridge-1.2.3-macos-all.pkg",
    "/private/var/folders/zz/abcdef/T/agentclibridge-1.2.3-macos-all.pkg",
    "/var/folders/zz/abcdef/T/agentclibridge-1.2.3-macos-all.pkg",
    "/private/var/tmp/agentclibridge-1.2.3-macos-all.pkg",
    "/tmp/agentclibridge-1.2.3-macos-all.pkg",
]


def _script(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(0o755)


@pytest.fixture
def downloads():
    """A folder that is not temporary for the postinstall (pytest's tmp_path sits under /tmp, which it refuses)."""
    base = Path("/dev/shm")
    if not base.is_dir() or not os.access(base, os.W_OK):
        pytest.skip("/dev/shm is not writable: no folder outside /tmp to stand in for Downloads")
    folder = Path(tempfile.mkdtemp(prefix="agentclibridge-downloads-", dir=base))
    yield folder
    shutil.rmtree(folder, ignore_errors=True)


def _tree(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


@pytest.fixture
def stubs(tmp_path):
    """Stub commands on PATH; each records its arguments to <log>/<name>.calls."""
    bin_dir = tmp_path / "bin"
    log = tmp_path / "log"
    bin_dir.mkdir()
    log.mkdir()
    for name in ("open", "osascript"):
        _script(bin_dir / name, f'echo "$*" >> "{log}/{name}.calls"\n')
    # A tar that records its arguments and unpacks the minimal setup folder into the -C folder.
    _script(
        bin_dir / "tar",
        f'''echo "$*" >> "{log}/tar.calls"
dest=""
while [ $# -gt 0 ]; do
  if [ "$1" = "-C" ]; then dest="$2"; fi
  shift
done
mkdir -p "$dest/app"
printf '#!/bin/sh\\n' > "$dest/setup.sh"
printf '{{}}' > "$dest/app/{MANIFEST_NAME}"
''',
    )
    return bin_dir, log


@pytest.fixture
def package(tmp_path):
    """A scripts folder as build-pkg.sh stages it, with a placeholder setup.tar.gz."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(POSTINSTALL, scripts / "postinstall")
    (scripts / "VERSION").write_text(VERSION)
    (scripts / "setup.tar.gz").write_bytes(b"stub")
    return scripts


def _run_postinstall(scripts: Path, pkg_arg: str, bin_dir: Path | None, home: Path, *extra: str):
    path = f"{bin_dir}:{SYSTEM_PATH}" if bin_dir else SYSTEM_PATH
    env = {"PATH": path, "HOME": str(home)}
    return subprocess.run(
        ["/bin/sh", str(scripts / "postinstall"), pkg_arg, *extra],
        capture_output=True, text=True, env=env, check=False, cwd=str(home),
    )


# --- Distribution -------------------------------------------------------------------------------


def test_distribution_enables_only_the_current_user_home():
    root = ET.parse(DISTRIBUTION).getroot()
    domains = root.findall("domains")
    assert len(domains) == 1
    assert domains[0].attrib == {
        "enable_anywhere": "false",
        "enable_currentUserHome": "true",
        "enable_localSystem": "false",
    }


def test_distribution_names_the_component_and_asks_for_no_authorization():
    root = ET.parse(DISTRIBUTION).getroot()
    assert (root.findtext("title") or "").strip() == "AgentCliBridge"
    assert root.find("options").attrib["customize"] == "never"
    refs = [r for r in root.iter("pkg-ref") if (r.text or "").strip()]
    assert [(r.attrib["id"], r.text.strip(), r.attrib["auth"]) for r in refs] == [
        ("org.agentclibridge.setup", "AgentCliBridge-setup.pkg", "none")
    ]
    assert refs[0].attrib["version"] == "@VERSION@"  # build-pkg.sh fills it in


# --- postinstall ---------------------------------------------------------------------------------


def test_postinstall_unpacks_beside_the_package_and_opens_terminal(package, stubs, downloads, tmp_path):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    (home / "keep").write_text("x")
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    before_home = _tree(home)

    done = _run_postinstall(package, str(pkg), bin_dir, home, "/Users/me", "/", "/")

    assert done.returncode == 0, done.stderr
    target = downloads / "agentclibridge-1.2.3-setup"
    # The tar was told the stub archive from the scripts folder and the folder beside the .pkg.
    assert (log / "tar.calls").read_text().split() == [
        "-xzf", str(package / "setup.tar.gz"), "-C", str(target.resolve()), "--no-same-owner",
    ]
    assert (target / "setup.sh").is_file() and os.access(target / "setup.sh", os.X_OK)
    assert (target / "app" / MANIFEST_NAME).is_file()
    # Terminal opens on setup.sh through `open`, never through osascript (its Automation prompt).
    assert (log / "open.calls").read_text().split() == ["-a", "Terminal", str(target.resolve() / "setup.sh")]
    assert not (log / "osascript.calls").exists()
    # Nothing else in $HOME, and nothing next to the package but the setup folder.
    assert _tree(home) == before_home
    assert _tree(downloads) == [
        "agentclibridge-1.2.3-macos-all.pkg",
        "agentclibridge-1.2.3-setup",
        "agentclibridge-1.2.3-setup/app",
        f"agentclibridge-1.2.3-setup/app/{MANIFEST_NAME}",
        "agentclibridge-1.2.3-setup/setup.sh",
    ]
    assert "arguments: [" in done.stderr  # logged for install.log


@pytest.mark.parametrize("pkg_arg", REFUSED)
def test_postinstall_refuses_a_package_in_a_sandbox_or_temp_folder(package, stubs, tmp_path, pkg_arg):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()

    done = _run_postinstall(package, pkg_arg, bin_dir, home)

    assert done.returncode != 0
    assert "temporary or Installer sandbox" in done.stderr
    assert not (log / "tar.calls").exists()
    assert not (log / "open.calls").exists()
    assert _tree(home) == []


def test_postinstall_refuses_a_folder_that_resolves_into_a_temp_folder(package, stubs, downloads, tmp_path):
    """A Downloads link into /tmp is still /tmp: the check runs on the resolved folder too."""
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    real = tmp_path / "real-downloads"  # under /tmp
    real.mkdir()
    (real / "agentclibridge-1.2.3-macos-all.pkg").write_bytes(b"pkg")
    link = downloads / "Downloads"
    link.symlink_to(real)

    done = _run_postinstall(package, str(link / "agentclibridge-1.2.3-macos-all.pkg"), bin_dir, home)

    assert done.returncode != 0
    assert "resolves to" in done.stderr
    assert not (log / "tar.calls").exists()
    assert not (real / "agentclibridge-1.2.3-setup").exists()


@pytest.mark.parametrize(
    "pkg_arg",
    ["", "relative/agentclibridge-1.2.3-macos-all.pkg", "/dev/shm/not-a-package", "/dev/shm/gone/none.pkg"],
)
def test_postinstall_stops_when_it_cannot_tell_where_the_package_is(package, stubs, tmp_path, pkg_arg):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()

    done = _run_postinstall(package, pkg_arg, bin_dir, home)

    assert done.returncode != 0
    assert "ERROR" in done.stderr
    assert not (log / "tar.calls").exists()
    assert not (log / "open.calls").exists()


def test_postinstall_refuses_a_folder_that_is_not_a_setup_folder(package, stubs, downloads, tmp_path):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    other = downloads / "agentclibridge-1.2.3-setup"
    other.mkdir()
    (other / "precious").write_text("mine")

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    assert done.returncode != 0
    assert "not an AgentCliBridge setup folder" in done.stderr
    assert (other / "precious").read_text() == "mine"
    assert not (log / "tar.calls").exists()


def test_postinstall_reuses_its_own_setup_folder_and_keeps_uv(package, stubs, downloads, tmp_path):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    target = downloads / "agentclibridge-1.2.3-setup"
    (target / "uv" / "bin").mkdir(parents=True)
    (target / "uv" / "bin" / "uv").write_text("fetched")
    (target / "app").mkdir()
    (target / "app" / "stale").write_text("old")
    (target / "setup.sh").write_text("old")

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    assert done.returncode == 0, done.stderr
    assert (target / "uv" / "bin" / "uv").read_text() == "fetched"
    assert not (target / "app" / "stale").exists()
    assert (log / "open.calls").exists()


def test_postinstall_removes_a_half_unpacked_folder_it_made(package, stubs, downloads, tmp_path):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    _script(bin_dir / "tar", 'mkdir -p "$4/app"; exit 1\n')

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    assert done.returncode != 0
    assert not (downloads / "agentclibridge-1.2.3-setup").exists()
    assert not (log / "open.calls").exists()


def test_postinstall_stops_when_terminal_cannot_open(package, stubs, downloads, tmp_path):
    bin_dir, _log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    _script(bin_dir / "open", "exit 1\n")

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    assert done.returncode != 0
    assert "run setup.sh there" in done.stderr


@pytest.mark.parametrize("version", ["", "../../etc", "1.0 0", "1.0/x"])
def test_postinstall_rejects_a_version_that_is_not_semver(package, stubs, downloads, tmp_path, version):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    (package / "VERSION").write_text(version)

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    assert done.returncode != 0
    assert "SemVer" in done.stderr
    assert not (log / "tar.calls").exists()
    assert _tree(downloads) == ["agentclibridge-1.2.3-macos-all.pkg"]


def test_postinstall_as_root_gives_the_folder_to_the_console_user(package, stubs, downloads, tmp_path):
    """Installer may run the script as root: the folder goes to the logged-in user, Terminal opens in their session."""
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    _script(bin_dir / "id", 'case "$*" in "-u") echo 0 ;; "-u alice") echo 501 ;; "-gn alice") echo staff ;; esac\n')
    _script(bin_dir / "stat", "echo alice\n")
    _script(bin_dir / "chown", f'echo "$*" >> "{log}/chown.calls"\n')
    _script(bin_dir / "launchctl", f'echo "$*" >> "{log}/launchctl.calls"\n')
    _script(bin_dir / "sudo", f'echo "$*" >> "{log}/sudo.calls"\n')

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    target = (downloads / "agentclibridge-1.2.3-setup").resolve()
    assert done.returncode == 0, done.stderr
    assert (log / "chown.calls").read_text().split() == ["-R", "alice:staff", str(target)]
    assert (log / "launchctl.calls").read_text().split() == [
        "asuser", "501", "sudo", "-u", "alice", "open", "-a", "Terminal", str(target / "setup.sh"),
    ]
    assert not (log / "open.calls").exists()


def test_postinstall_as_root_with_no_console_user_writes_nothing(package, stubs, downloads, tmp_path):
    bin_dir, log = stubs
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / "agentclibridge-1.2.3-macos-all.pkg"
    pkg.write_bytes(b"pkg")
    _script(bin_dir / "id", 'case "$*" in "-u") echo 0 ;; esac\n')
    _script(bin_dir / "stat", "echo loginwindow\n")

    done = _run_postinstall(package, str(pkg), bin_dir, home)

    assert done.returncode != 0
    assert _tree(downloads) == ["agentclibridge-1.2.3-macos-all.pkg"]
    assert not (log / "tar.calls").exists()


# --- build-pkg.sh --------------------------------------------------------------------------------


def _fake_snapshot(folder: Path, version: str = VERSION) -> Path:
    src = folder / "snap-src"
    (src / "agent_cli_bridge").mkdir(parents=True)
    (src / "agent_cli_bridge" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (src / MANIFEST_NAME).write_text("{}")
    archive = folder / f"agentclibridge-{version}-any-all-snapshot.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for item in sorted(src.rglob("*")):
            tar.add(item, arcname=str(item.relative_to(src)), recursive=False)
    return archive


def _run_build(*args: str, env: dict[str, str] | None = None, path: str = SYSTEM_PATH):
    full = {"PATH": path, **(env or {})}
    return subprocess.run(["/bin/sh", str(BUILD), *args], capture_output=True, text=True, env=full, check=False)


def test_build_stages_the_scripts_folder(tmp_path):
    snapshot = _fake_snapshot(tmp_path)
    out = tmp_path / "out"

    done = _run_build("--snapshot", str(snapshot), "--out", str(out), "--stage-only")

    assert done.returncode == 0, done.stderr
    stage = Path(done.stdout.strip())
    assert stage == (out / "pkg-stage").resolve()
    scripts = stage / "scripts"
    assert sorted(p.name for p in scripts.iterdir()) == ["VERSION", "postinstall", "setup.tar.gz"]
    assert (scripts / "VERSION").read_text() == VERSION
    assert (scripts / "postinstall").read_bytes() == POSTINSTALL.read_bytes()
    assert os.access(scripts / "postinstall", os.X_OK)
    with tarfile.open(scripts / "setup.tar.gz") as tar:
        names = tar.getnames()
        assert {"setup.sh", "setup.ps1", "app", f"app/{MANIFEST_NAME}", "app/agent_cli_bridge/__init__.py"} <= set(names)
        assert tar.getmember("setup.sh").mode & stat.S_IXUSR
        assert tar.extractfile("setup.sh").read() == (ROOT / "packaging" / "setup.sh").read_bytes()
        assert tar.extractfile("setup.ps1").read() == (ROOT / "packaging" / "setup.ps1").read_bytes()
        assert all(not n.startswith(("/", "..")) and "/._" not in n for n in names)
    distribution = (stage / "distribution.xml").read_text()
    assert "@VERSION@" not in distribution and f'version="{VERSION}"' in distribution
    assert not list(out.glob("*.pkg"))


def test_build_stages_and_the_postinstall_unpacks_a_real_archive(tmp_path, downloads):
    """The staged scripts folder and the real tar: setup.sh, setup.ps1 and app/ land in the setup folder."""
    snapshot = _fake_snapshot(tmp_path)
    done = _run_build("--snapshot", str(snapshot), "--out", str(tmp_path / "out"), "--stage-only")
    assert done.returncode == 0, done.stderr
    scripts = Path(done.stdout.strip()) / "scripts"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _script(bin_dir / "open", f'echo "$*" > "{tmp_path}/open.calls"\n')
    home = tmp_path / "home"
    home.mkdir()
    pkg = downloads / f"agentclibridge-{VERSION}-macos-all.pkg"
    pkg.write_bytes(b"pkg")

    ran = _run_postinstall(scripts, str(pkg), bin_dir, home)

    assert ran.returncode == 0, ran.stderr
    target = downloads / f"agentclibridge-{VERSION}-setup"
    assert sorted(p.name for p in target.iterdir()) == ["app", "setup.ps1", "setup.sh"]
    assert (target / "app" / MANIFEST_NAME).is_file()
    assert os.access(target / "setup.sh", os.X_OK)
    assert target.stat().st_uid == os.getuid()
    assert _tree(home) == []


@pytest.mark.parametrize(
    "name",
    ["snapshot.tar.gz", "agentclibridge-1.0 0-any-all-snapshot.tar.gz", "agentclibridge--any-all-snapshot.tar.gz"],
)
def test_build_refuses_a_misnamed_snapshot(tmp_path, name):
    bad = tmp_path / name
    bad.write_bytes(b"x")

    done = _run_build("--snapshot", str(bad), "--out", str(tmp_path / "out"), "--stage-only")

    assert done.returncode != 0
    assert "ERROR" in done.stderr


def test_build_refuses_an_archive_without_the_manifest(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "file").write_text("x")
    archive = tmp_path / "agentclibridge-1.2.3-any-all-snapshot.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(src / "file", arcname="file")

    done = _run_build("--snapshot", str(archive), "--out", str(tmp_path / "out"), "--stage-only")

    assert done.returncode != 0
    assert MANIFEST_NAME in done.stderr


def test_build_without_pkgbuild_stops_naming_it(tmp_path):
    snapshot = _fake_snapshot(tmp_path)

    done = _run_build("--snapshot", str(snapshot), "--out", str(tmp_path / "out"))

    assert done.returncode != 0
    assert "pkgbuild not found" in done.stderr
    assert not list((tmp_path / "out").glob("*.pkg"))


@pytest.fixture
def build_stubs(tmp_path):
    bin_dir = tmp_path / "tools"
    log = tmp_path / "toollog"
    bin_dir.mkdir()
    log.mkdir()
    # pkgbuild and productbuild record their arguments, one per line, and write their last argument.
    for name in ("pkgbuild", "productbuild"):
        _script(
            bin_dir / name,
            f'printf \'%s\\n\' "$@" > "{log}/{name}.args"\neval "last=\\${{$#}}"\nprintf built > "$last"\n',
        )
    return bin_dir, log


def test_build_runs_pkgbuild_then_productbuild_unsigned(tmp_path, build_stubs):
    bin_dir, log = build_stubs
    snapshot = _fake_snapshot(tmp_path)
    out = tmp_path / "out"

    done = _run_build("--snapshot", str(snapshot), "--out", str(out), path=f"{bin_dir}:{SYSTEM_PATH}")

    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == str(out.resolve() / f"agentclibridge-{VERSION}-macos-all.pkg")
    assert (out / f"agentclibridge-{VERSION}-macos-all.pkg").read_text() == "built"
    component = (log / "pkgbuild.args").read_text().splitlines()
    assert component[:1] == ["--nopayload"]
    assert component[component.index("--identifier") + 1] == "org.agentclibridge.setup"
    assert component[component.index("--version") + 1] == VERSION
    assert component[component.index("--scripts") + 1].endswith("/scripts")
    assert component[-1].endswith("/AgentCliBridge-setup.pkg")
    product = (log / "productbuild.args").read_text().splitlines()
    assert product[product.index("--distribution") + 1].endswith("/distribution.xml")
    assert product[product.index("--package-path") + 1] == str(Path(component[-1]).parent)
    assert product[-1] == str(out.resolve() / f"agentclibridge-{VERSION}-macos-all.pkg")
    for args in (component, product):
        assert "--sign" not in args
    assert "unsigned" in done.stderr


def test_build_signs_only_when_an_identity_is_given(tmp_path, build_stubs):
    bin_dir, log = build_stubs
    snapshot = _fake_snapshot(tmp_path)
    identity = "Developer ID Installer: Some One (ABCDE12345)"

    done = _run_build(
        "--snapshot", str(snapshot), "--out", str(tmp_path / "out"), path=f"{bin_dir}:{SYSTEM_PATH}",
        env={"AGENTCLIBRIDGE_PKG_SIGN_IDENTITY": identity, "AGENTCLIBRIDGE_PKG_SIGN_KEYCHAIN": "/keys/build.keychain-db"},
    )

    assert done.returncode == 0, done.stderr
    for name in ("pkgbuild", "productbuild"):
        args = (log / f"{name}.args").read_text().splitlines()
        assert args[args.index("--sign") + 1] == identity  # one argument, spaces kept
        assert args[args.index("--keychain") + 1] == "/keys/build.keychain-db"


# --- static checks -------------------------------------------------------------------------------


def test_scripts_are_executable_and_parse():
    for script in (BUILD, POSTINSTALL):
        assert os.access(script, os.X_OK), f"{script} is not executable"
        assert subprocess.run(["sh", "-n", str(script)], check=False).returncode == 0
        assert subprocess.run(["bash", "-n", str(script)], check=False).returncode == 0


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
def test_scripts_pass_shellcheck():
    done = subprocess.run(["shellcheck", str(BUILD), str(POSTINSTALL)], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stdout


def test_postinstall_writes_nothing_in_home_and_uses_no_osascript():
    source = POSTINSTALL.read_text()
    code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
    assert "$HOME" not in code and "~" not in code
    assert "osascript" not in code
    assert "open -a Terminal" in code
