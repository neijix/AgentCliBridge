"""packaging/windows: the Inno Setup script and the script that stages and compiles it (AC9).

Inno Setup runs on Windows only, so the .iss is read statically (the directives that keep the .exe
from writing anything but the setup folder), and build-exe.ps1 runs under pwsh with -StageOnly on a
small hand-made snapshot archive. The real compile and the profile listing around one run are the
owner's check on a Windows PC (the plan's row 23).
"""
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from bridge_installer import MANIFEST_NAME, manifest, release

ROOT = Path(__file__).resolve().parents[1]
ISS = ROOT / "packaging" / "windows" / "agentclibridge.iss"
BUILD = ROOT / "packaging" / "windows" / "build-exe.ps1"

PWSH = shutil.which("pwsh")
needs_pwsh = pytest.mark.skipif(PWSH is None or os.name == "nt", reason="PowerShell (pwsh) is not installed")


def parse_iss(text: str) -> dict[str, list[str]]:
    """``{section: [line, ...]}`` of the script, comments and preprocessor lines left out."""
    sections: dict[str, list[str]] = {}
    current = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "#")):
            continue
        header = re.fullmatch(r"\[(\w+)\]", line)
        if header:
            current = header.group(1).lower()
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return sections


def setup_directives() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in parse_iss(ISS.read_text(encoding="utf-8")).get("setup", []):
        key, _, value = line.partition("=")
        found[key.strip()] = value.strip()
    return found


# --- the Inno script ---------------------------------------------------------------------------


def test_iss_installs_nothing_but_the_setup_folder():
    setup = setup_directives()
    assert setup["PrivilegesRequired"] == "lowest"  # no administrator, no Program Files
    assert setup["Uninstallable"] == "no"  # no HKCU uninstall entry, no unins000.exe
    assert setup["CreateAppDir"] == "no"  # no Program Files / %LOCALAPPDATA%\Programs folder
    assert setup["DisableDirPage"] == "yes"  # the folder is the wizard's question, not Inno's
    assert setup["OutputBaseFilename"] == "agentclibridge-{#Version}-windows-all-setup"
    assert "PrivilegesRequiredOverridesAllowed" not in setup  # no elevation through the command line


@pytest.mark.parametrize("section", ["registry", "icons", "uninstalldelete", "installdelete", "dirs", "ini", "code"])
def test_iss_has_no_section_that_writes_elsewhere(section):
    assert section not in parse_iss(ISS.read_text(encoding="utf-8"))


def test_iss_never_uses_the_app_constant():
    # With CreateAppDir=no, {app} is the Windows folder.
    body = "\n".join(line for line in ISS.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(";"))
    assert "{app}" not in body
    assert "{autopf" not in body and "{localappdata}" not in body and "{userappdata}" not in body


def test_iss_unpacks_the_setup_folder_beside_the_exe():
    files = parse_iss(ISS.read_text(encoding="utf-8"))["files"]
    assert len(files) == 1
    assert 'Source: "{#StageDir}\\*"' in files[0]
    assert 'DestDir: "{src}\\{#SetupFolder}"' in files[0]
    assert "recursesubdirs" in files[0] and "createallsubdirs" in files[0]
    assert '#define SetupFolder "agentclibridge-" + Version + "-setup"' in ISS.read_text(encoding="utf-8")


def test_iss_runs_setup_ps1_in_a_visible_console_after_the_install():
    runs = parse_iss(ISS.read_text(encoding="utf-8"))["run"]
    assert len(runs) == 1
    run = runs[0]
    assert re.search(r'Filename: "[^"]*powershell\.exe"', run)
    assert "-NoProfile -ExecutionPolicy Bypass" in run
    assert '-File ""{src}\\{#SetupFolder}\\setup.ps1""' in run
    flags = re.search(r"Flags: ([\w ]+)", run).group(1).split()
    assert "postinstall" in flags  # a checked box on the last page: the wizard starts after the copy
    assert "skipifsilent" in flags  # an interactive wizard never starts under /SILENT
    assert "runhidden" not in flags  # the console is visible
    assert "nowait" not in flags  # Setup waits for the wizard to end


def test_iss_signs_only_when_a_sign_tool_is_passed_in():
    lines = ISS.read_text(encoding="utf-8").splitlines()
    at = next(i for i, line in enumerate(lines) if line.startswith("SignTool="))
    assert lines[at - 1].strip() == "#ifdef SignToolName"
    assert lines[at + 1].strip() == "#endif"


def test_iss_wants_its_defines_from_the_build_script():
    text = ISS.read_text(encoding="utf-8")
    for name in ("Version", "StageDir"):
        assert f"#ifndef {name}" in text
    build = BUILD.read_text(encoding="utf-8")
    for name in ("Version", "StageDir", "OutDir", "SignToolName"):
        assert f"/D{name}=" in build


# --- build-exe.ps1, read ------------------------------------------------------------------------


def test_build_script_keeps_windows_powershell_5_1_syntax():
    text = BUILD.read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "&&" not in code and "||" not in code
    assert "??" not in code
    assert "$IsWindows" not in code  # undefined in 5.1


def test_build_script_names_match_the_python_side():
    text = BUILD.read_text(encoding="utf-8")
    assert f"$manifestName = '{MANIFEST_NAME}'" in text
    assert release.snapshot_name("1.2.3") == "agentclibridge-1.2.3-any-all-snapshot.tar.gz"
    assert "agentclibridge-(?<v>" in text and "-any-all-snapshot\\.tar\\.gz$" in text


def test_build_script_signs_by_thumbprint_never_by_password():
    text = BUILD.read_text(encoding="utf-8")
    assert "AGENTCLIBRIDGE_WIN_SIGN_THUMBPRINT" in text
    assert "/sha1" in text
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"(?i)password|/p\s", code)


@needs_pwsh
def test_build_script_parses_in_powershell():
    probe = (
        "$errors = $null; $tokens = $null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{BUILD}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
    )
    done = subprocess.run([PWSH, "-NoProfile", "-Command", probe], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr


# --- build-exe.ps1 -StageOnly --------------------------------------------------------------------


def make_archive(
    path: Path,
    version: str = "1.2.3",
    *,
    manifest_version: str | None = None,
    wizard: bool = True,
    with_manifest: bool = True,
    extra: list[str] | None = None,
) -> Path:
    members = {"README.md": b"readme\n"}
    if wizard:
        members["bridge_installer/__main__.py"] = b"print('wizard')\n"
    if with_manifest:
        members[MANIFEST_NAME] = json.dumps({
            "format": manifest.MANIFEST_FORMAT,
            "kind": manifest.MANIFEST_KIND,
            "version": manifest_version or version,
            "commit": "0" * 40,
            "repo": "owner/repo",
        }).encode()
    for name in extra or []:
        members[name] = b"x"
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def run_build(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("AGENTCLIBRIDGE_WIN_SIGN")}
    return subprocess.run(
        [PWSH, "-NoProfile", "-File", str(BUILD), *args],
        capture_output=True, text=True, timeout=300, cwd=cwd, env=env,
    )


@needs_pwsh
def test_stage_only_lays_out_the_setup_folder(tmp_path):
    archive = make_archive(tmp_path / "agentclibridge-1.2.3-any-all-snapshot.tar.gz")
    out = tmp_path / "out"
    done = run_build("-Archive", str(archive), "-OutDir", str(out), "-StageOnly", cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    stage = out / "exe-stage" / "agentclibridge-1.2.3-setup"
    assert (stage / "setup.ps1").read_bytes() == (ROOT / "packaging" / "setup.ps1").read_bytes()
    assert (stage / "setup.sh").read_bytes() == (ROOT / "packaging" / "setup.sh").read_bytes()
    assert (stage / "app" / "bridge_installer" / "__main__.py").is_file()
    assert (stage / "app" / MANIFEST_NAME).is_file()
    assert sorted(p.name for p in stage.iterdir()) == ["app", "setup.ps1", "setup.sh"]
    assert sorted(p.name for p in out.iterdir()) == ["exe-stage"]  # no .exe without Inno


@needs_pwsh
def test_stage_only_replaces_a_stale_stage(tmp_path):
    archive = make_archive(tmp_path / "agentclibridge-1.2.3-any-all-snapshot.tar.gz")
    stale = tmp_path / "out" / "exe-stage" / "agentclibridge-0.9.0-setup"
    stale.mkdir(parents=True)
    done = run_build("-Archive", str(archive), "-OutDir", str(tmp_path / "out"), "-StageOnly", cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert [p.name for p in (tmp_path / "out" / "exe-stage").iterdir()] == ["agentclibridge-1.2.3-setup"]


@needs_pwsh
@pytest.mark.parametrize(
    ("kwargs", "name", "reason"),
    [
        ({"manifest_version": "9.9.9"}, "agentclibridge-1.2.3-any-all-snapshot.tar.gz", "manifest says 9.9.9"),
        ({"with_manifest": False}, "agentclibridge-1.2.3-any-all-snapshot.tar.gz", "not a snapshot"),
        ({"wizard": False}, "agentclibridge-1.2.3-any-all-snapshot.tar.gz", "no setup wizard"),
        ({"extra": ["../escape.txt"]}, "agentclibridge-1.2.3-any-all-snapshot.tar.gz", "outside its folder"),
        ({"extra": ["/abs.txt"]}, "agentclibridge-1.2.3-any-all-snapshot.tar.gz", "outside its folder"),
        ({}, "snapshot.tar.gz", "not named agentclibridge-<version>-any-all-snapshot.tar.gz"),
    ],
)
def test_stage_only_refuses_a_bad_archive(tmp_path, kwargs, name, reason):
    archive = make_archive(tmp_path / name, **kwargs)
    out = tmp_path / "out"
    done = run_build("-Archive", str(archive), "-OutDir", str(out), "-StageOnly", cwd=tmp_path)
    assert done.returncode == 1
    assert reason in done.stderr
    assert not (tmp_path / "escape.txt").exists()


@needs_pwsh
def test_stage_only_refuses_a_missing_archive(tmp_path):
    done = run_build(
        "-Archive", str(tmp_path / "nope.tar.gz"), "-OutDir", str(tmp_path / "out"), "-StageOnly", cwd=tmp_path
    )
    assert done.returncode == 1
    assert "is not a file" in done.stderr


@needs_pwsh
def test_compile_is_windows_only(tmp_path):
    archive = make_archive(tmp_path / "agentclibridge-1.2.3-any-all-snapshot.tar.gz")
    done = run_build("-Archive", str(archive), "-OutDir", str(tmp_path / "out"), cwd=tmp_path)
    assert done.returncode == 1
    assert "Inno Setup runs on Windows only" in done.stderr


@needs_pwsh
@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_stage_only_builds_the_snapshot_itself(tmp_path):
    out = tmp_path / "out"
    done = run_build(
        "-Python", sys.executable, "-Repo", "owner/repo", "-OutDir", str(out), "-StageOnly", cwd=tmp_path
    )
    assert done.returncode == 0, done.stdout + done.stderr
    archives = list(out.glob("agentclibridge-*-any-all-snapshot.tar.gz"))
    assert len(archives) == 1
    version = archives[0].name.removeprefix("agentclibridge-").removesuffix("-any-all-snapshot.tar.gz")
    stage = out / "exe-stage" / f"agentclibridge-{version}-setup"
    assert (stage / "app" / MANIFEST_NAME).is_file()
    assert (stage / "app" / "bridge_installer" / "__main__.py").is_file()
    assert (stage / "setup.ps1").is_file()
