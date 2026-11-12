"""Build the release snapshot archive, name the OS packages, and write ``SHA256SUMS``.

``python -m bridge_installer.release snapshot [--tag vX.Y.Z] [--out DIR] [--repo OWNER/REPO]``
writes the one archive every OS package wraps and the in-app updater downloads,
``agentclibridge-<version>-any-all-snapshot.tar.gz``: the repo files at the tag (or ``HEAD``)
through ``git archive``, minus what only serves a checkout or CI, plus the manifest. Member order,
times, owners and the gzip header are fixed, so the same commit gives the same bytes anywhere.

``version`` prints the version a build would carry; ``name OS ARCH SUFFIX`` prints an asset name;
``sums FILE... [--out PATH]`` writes a ``SHA256SUMS`` (``sha256sum`` format, sorted by name).
"""
from __future__ import annotations

import argparse
import fnmatch
import gzip
import hashlib
import io
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterable
from pathlib import Path

from bridge_installer import APP, MANIFEST_NAME
from bridge_installer.manifest import Manifest, is_valid_version

# Checkout-only and CI-only paths. The launchers (start.*, stop.*, kill.*, install.*) stay: an
# install runs them from <folder>/app with AGENT_CLI_BRIDGE_INSTALL_DIR set (install mode).
EXCLUDED_TOP_LEVEL = ("switchboard.json", "check.sh", "check.ps1", "Makefile")
EXCLUDED_TREES = (".git", ".github", ".githooks", "tests", "packaging")
SUMS_NAME = "SHA256SUMS"

# The asset-name contract: <app>-<version>-<os>-<arch><suffix>. The bridge is pure Python, so
# every package is "all" architectures; the snapshot is "any" OS.
ASSETS = {
    "deb": ("linux", "all", ".deb"),
    "pkg": ("macos", "all", ".pkg"),
    "exe": ("windows", "all", "-setup.exe"),
    "snapshot": ("any", "all", "-snapshot.tar.gz"),
}

_VERSION_LINE = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
_GITHUB_URL = re.compile(r"github\.com[:/]+([^/\s]+)/([^/\s]+?)(?:\.git)?/?$")
_NAME_PART = re.compile(r"^[a-z0-9]+$")
_REPO_ROOT = Path(__file__).resolve().parents[1]


class ReleaseError(Exception):
    """The build cannot go on; the message is the reason, printed as one line."""


def asset_name(version: str, os_name: str, arch: str, suffix: str) -> str:
    """``agentclibridge-<version>-<os>-<arch><suffix>``, after checking every part."""
    if not is_valid_version(version):
        raise ReleaseError(f"not a SemVer 2.0 version: {version!r}")
    for part in (os_name, arch):
        if not _NAME_PART.match(part):
            raise ReleaseError(f"an asset's os and arch are lowercase letters and digits: {part!r}")
    if not suffix.startswith((".", "-")):
        raise ReleaseError(f"an asset suffix starts with '.' or '-': {suffix!r}")
    return f"{APP}-{version}-{os_name}-{arch}{suffix}"


def package_name(version: str, kind: str) -> str:
    """The asset name of one of ``ASSETS`` (deb, pkg, exe, snapshot)."""
    return asset_name(version, *ASSETS[kind])


def snapshot_name(version: str) -> str:
    return package_name(version, "snapshot")


def _git(repo_dir: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    try:
        done = subprocess.run(["git", "-C", str(repo_dir), *args], capture_output=True, check=False)
    except FileNotFoundError as exc:
        raise ReleaseError("git is not installed") from exc
    if check and done.returncode != 0:
        detail = done.stderr.decode("utf-8", "replace").strip() or f"exit {done.returncode}"
        raise ReleaseError(f"git {' '.join(args)} failed: {detail}")
    return done


def _git_text(repo_dir: Path, *args: str) -> str:
    return _git(repo_dir, *args).stdout.decode("utf-8", "replace").strip()


def resolve_ref(repo_dir: Path, tag: str | None) -> tuple[str, str]:
    """``(ref, full commit id)``: the tag (which must exist, tree clean) or ``HEAD``."""
    if tag is None:
        return "HEAD", _git_text(repo_dir, "rev-parse", "--verify", "HEAD^{commit}")
    if not tag.startswith("v") or not is_valid_version(tag[1:]):
        raise ReleaseError(f"tag {tag!r} is not v<SemVer> (for example v1.0.0 or v0.0.0-test.1)")
    ref = f"refs/tags/{tag}"
    found = _git(repo_dir, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
    if found.returncode != 0:
        raise ReleaseError(f"unknown tag {tag!r}: no such tag in {repo_dir}")
    if _git_text(repo_dir, "status", "--porcelain", "--untracked-files=no"):
        raise ReleaseError(f"the working tree is dirty: commit or stash before building {tag}")
    return ref, found.stdout.decode().strip()


def dunder_version(repo_dir: Path, ref: str) -> str:
    """``__version__`` of ``agent_cli_bridge`` as committed at ``ref``."""
    source = _git(repo_dir, "show", f"{ref}:agent_cli_bridge/__init__.py").stdout.decode("utf-8", "replace")
    match = _VERSION_LINE.search(source)
    if match is None:
        raise ReleaseError(f"no __version__ in agent_cli_bridge/__init__.py at {ref}")
    return match.group(1)


def resolve_version(tag: str | None, dunder: str) -> str:
    """The tag without its ``v``, or ``__version__`` without a tag.

    A tag without a ``-`` suffix is a release and must equal ``v<__version__>``.
    """
    if tag is None:
        if not is_valid_version(dunder):
            raise ReleaseError(f"__version__ {dunder!r} is not a SemVer 2.0 version")
        return dunder
    version = tag[1:]
    if "-" not in version and version != dunder:
        raise ReleaseError(f"tag {tag} differs from v{dunder} (__version__ is {dunder!r}); bump it or fix the tag")
    return version


def resolve_repo(repo_dir: Path, repo: str | None) -> str:
    """The GitHub ``owner/repo`` the install updates from: ``--repo``, ``GITHUB_REPOSITORY``, else ``origin``."""
    chosen = repo or os.environ.get("GITHUB_REPOSITORY", "").strip()
    if chosen:
        return chosen
    url = _git(repo_dir, "remote", "get-url", "origin", check=False).stdout.decode().strip()
    match = _GITHUB_URL.search(url)
    if match is None:
        raise ReleaseError("cannot tell the GitHub repo: pass --repo OWNER/REPO (origin is not a github.com remote)")
    return f"{match.group(1)}/{match.group(2)}"


def is_excluded(name: str) -> bool:
    """True for a member the snapshot leaves out: a checkout-only file or tree."""
    parts = name.split("/")
    if parts[0] in EXCLUDED_TREES:
        return True
    return len(parts) == 1 and any(fnmatch.fnmatchcase(name, pattern) for pattern in EXCLUDED_TOP_LEVEL)


def _fixed_info(member: tarfile.TarInfo, name: str) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    if member.isdir():
        info.type, info.mode = tarfile.DIRTYPE, 0o755
    elif member.isfile():
        info.type, info.mode, info.size = tarfile.REGTYPE, 0o755 if member.mode & 0o111 else 0o644, member.size
    else:
        # No symlinks: a link in an archive the updater unpacks is a way out of its folder.
        raise ReleaseError(f"{name}: a {member.type!r} entry cannot go in a snapshot")
    return info


def _collect(archive: bytes) -> dict[str, tuple[tarfile.TarInfo, bytes]]:
    """Every kept member of the ``git archive`` tar by name, with its content."""
    kept: dict[str, tuple[tarfile.TarInfo, bytes]] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as source:
        for member in source:
            name = member.name.rstrip("/")
            if not name or member.type == tarfile.XGLTYPE or is_excluded(name):
                continue
            if name == MANIFEST_NAME:
                raise ReleaseError(f"{MANIFEST_NAME} is tracked in the repo; the build writes it")
            data = source.extractfile(member).read() if member.isfile() else b""  # type: ignore[union-attr]
            kept[name] = (_fixed_info(member, name), data)
    return kept


def _write_archive(kept: dict[str, tuple[tarfile.TarInfo, bytes]], manifest: Manifest, target: Path) -> None:
    text = manifest.as_json().encode("utf-8")
    info = tarfile.TarInfo(MANIFEST_NAME)
    info.mtime, info.mode, info.size = 0, 0o644, len(text)
    kept[MANIFEST_NAME] = (info, text)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp_name = tempfile.mkstemp(prefix=".snapshot-", suffix=".part", dir=target.parent)
    try:
        with (
            os.fdopen(handle, "wb") as raw,
            gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as packed,
            tarfile.open(fileobj=packed, mode="w", format=tarfile.PAX_FORMAT) as tar,
        ):
            for name in sorted(kept):
                member, data = kept[name]
                tar.addfile(member, io.BytesIO(data) if member.isfile() else None)
        os.chmod(tmp_name, 0o644)  # a release asset, not a secret: mkstemp's 0600 would follow it
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def build_snapshot(out_dir: Path, *, repo_dir: Path | None = None, tag: str | None = None, repo: str | None = None) -> Path:
    """Write the snapshot archive into ``out_dir`` and return its path."""
    root = Path(repo_dir) if repo_dir else _REPO_ROOT
    ref, commit = resolve_ref(root, tag)
    version = resolve_version(tag, dunder_version(root, ref))
    manifest = Manifest(version=version, commit=commit, repo=resolve_repo(root, repo))
    kept = _collect(_git(root, "archive", "--format=tar", ref).stdout)
    target = Path(out_dir) / snapshot_name(version)
    _write_archive(kept, manifest, target)
    return target


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def sums_text(files: Iterable[Path]) -> str:
    """``SHA256SUMS`` content (``<digest>  <file name>`` per line, sorted by name) for ``files``."""
    lines: dict[str, str] = {}
    for path in files:
        path = Path(path)
        if path.name in lines:
            raise ReleaseError(f"two files named {path.name} in the list")
        if not path.is_file():
            raise ReleaseError(f"{path} is not a file")
        lines[path.name] = f"{sha256_of(path)}  {path.name}\n"
    return "".join(lines[name] for name in sorted(lines))


def parse_sums(text: str) -> dict[str, str]:
    """``{file name: hex digest}`` from a ``SHA256SUMS`` text; other lines are skipped."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", line)
        if match:
            found[match.group(2)] = match.group(1).lower()
    return found


def write_sums(files: Iterable[Path], out: Path) -> Path:
    Path(out).write_text(sums_text(files), encoding="utf-8")
    return Path(out)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m bridge_installer.release", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("snapshot", "version"):
        one = sub.add_parser(name)
        one.add_argument("--tag", help="build this v<version> tag (default: HEAD, version from __version__)")
        one.add_argument("--repo-dir", type=Path, default=None, help="the git checkout to build from (default: this one)")
        if name == "snapshot":
            one.add_argument("--out", type=Path, default=Path("dist"), help="where the archive goes (default: dist)")
            one.add_argument("--repo", help="GitHub OWNER/REPO the install updates from (default: origin)")
    named = sub.add_parser("name", help="print the asset name of one package kind")
    named.add_argument("version")
    named.add_argument("kind", choices=sorted(ASSETS))
    sums = sub.add_parser("sums", help=f"write a {SUMS_NAME} for the files given")
    sums.add_argument("files", nargs="+", type=Path)
    sums.add_argument("--out", type=Path, default=Path(SUMS_NAME))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "sums":
            print(write_sums(args.files, args.out))
        elif args.command == "name":
            print(package_name(args.version, args.kind))
        elif args.command == "version":
            root = args.repo_dir or _REPO_ROOT
            ref, _commit = resolve_ref(root, args.tag)
            print(resolve_version(args.tag, dunder_version(root, ref)))
        else:
            print(build_snapshot(args.out, repo_dir=args.repo_dir, tag=args.tag, repo=args.repo))
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
