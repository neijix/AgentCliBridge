"""Update a packaged install from the latest GitHub Release of the repo in its manifest.

It downloads ``SHA256SUMS`` and the release's snapshot archive, checks the archive's digest,
unpacks it into ``<install>/temp`` (regular files and folders only, nothing outside), checks the
unpacked manifest names the version and repo it should, then installs it with the previous
answers: the same swap a setup run does.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from bridge_installer import DISPLAY_NAME
from bridge_installer.apply import install
from bridge_installer.layout import Layout, SetupError, answers_from_record, read_record
from bridge_installer.manifest import ManifestError, compare_versions, is_valid_version, read_manifest
from bridge_installer.release import SUMS_NAME, parse_sums, snapshot_name

API = "https://api.github.com/repos/{repo}/releases/latest"
MAX_DOWNLOAD = 64 * 1024 * 1024
Fetch = Callable[[str], bytes]


def fetch_url(url: str) -> bytes:
    """GET ``url`` over HTTPS (at most ``MAX_DOWNLOAD`` bytes)."""
    if not url.startswith("https://"):
        raise SetupError(f"refusing a download that is not HTTPS: {url}")
    request = urllib.request.Request(url, headers={"User-Agent": "agentclibridge-updater", "Accept": "*/*"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310 - HTTPS checked above
            data: bytes = response.read(MAX_DOWNLOAD + 1)
    except urllib.error.HTTPError as exc:
        hint = " (no release is published yet?)" if exc.code == 404 else ""
        raise SetupError(f"download failed: {url}: HTTP {exc.code}{hint}") from exc
    except OSError as exc:
        raise SetupError(f"download failed: {url}: {exc}") from exc
    if len(data) > MAX_DOWNLOAD:
        raise SetupError(f"{url} is larger than {MAX_DOWNLOAD} bytes")
    return data


def latest_release(repo: str, fetch: Fetch) -> tuple[str, dict[str, str]]:
    """``(version, {asset name: download URL})`` of the repo's latest release."""
    try:
        data = json.loads(fetch(API.format(repo=repo)).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SetupError(f"GitHub's answer for {repo} is not JSON") from exc
    tag = data.get("tag_name") if isinstance(data, dict) else None
    if not isinstance(tag, str) or not tag.startswith("v") or not is_valid_version(tag[1:]):
        raise SetupError(f"the latest release of {repo} has no v<version> tag: {tag!r}")
    assets: dict[str, str] = {}
    for asset in data.get("assets") or []:
        if isinstance(asset, dict) and isinstance(asset.get("name"), str) and isinstance(asset.get("browser_download_url"), str):
            assets[asset["name"]] = asset["browser_download_url"]
    return tag[1:], assets


def safe_extract(archive: bytes, target: Path) -> None:
    """Unpack a snapshot: regular files and folders, every path inside ``target``."""
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for member in tar:
            if member.type in (tarfile.XGLTYPE, tarfile.XHDTYPE):
                continue
            parts = PurePosixPath(member.name).parts
            if not parts or member.name.startswith("/") or ".." in parts or any("\\" in p or ":" in p for p in parts):
                raise SetupError(f"the snapshot holds an unsafe path: {member.name!r}")
            path = target.joinpath(*parts)
            if member.isdir():
                path.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                path.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                assert source is not None
                path.write_bytes(source.read())
                path.chmod(0o755 if member.mode & 0o111 else 0o644)
            else:
                raise SetupError(f"the snapshot holds a link or a device: {member.name!r}")


def _download_snapshot(repo: str, version: str, assets: dict[str, str], fetch: Fetch) -> bytes:
    name = snapshot_name(version)
    if name not in assets or SUMS_NAME not in assets:
        raise SetupError(f"release v{version} of {repo} lacks {name} or {SUMS_NAME}")
    expected = parse_sums(fetch(assets[SUMS_NAME]).decode("utf-8", "replace")).get(name)
    if expected is None:
        raise SetupError(f"{SUMS_NAME} of v{version} does not list {name}")
    data = fetch(assets[name])
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SetupError(f"{name} does not match {SUMS_NAME} (got {actual}, expected {expected}): nothing changed")
    return data


def update(layout: Layout, *, fetch: Fetch = fetch_url, check_only: bool = False, **install_options: object) -> int:
    """Install the latest release over this install when it is newer; 0 when done or up to date."""
    record = read_record(layout)
    if record is None:
        raise SetupError(f"{layout.root} is not an {DISPLAY_NAME} install (no install.json)")
    try:
        current = read_manifest(layout.app)
    except ManifestError as exc:
        raise SetupError(str(exc)) from exc
    if current is None:
        raise SetupError(f"{layout.app} holds no snapshot manifest: run the setup again")
    version, assets = latest_release(current.repo, fetch)
    if compare_versions(version, current.version) <= 0:
        print(f"{DISPLAY_NAME} {current.version} is up to date (latest release: {version}).")
        return 0
    print(f"{DISPLAY_NAME} {version} is available (installed: {current.version}).")
    if check_only:
        return 0
    data = _download_snapshot(current.repo, version, assets, fetch)
    layout.temp.mkdir(parents=True, exist_ok=True)
    unpacked = Path(tempfile.mkdtemp(prefix="update-", dir=layout.temp))
    try:
        safe_extract(data, unpacked)
        try:
            fresh = read_manifest(unpacked)
        except ManifestError as exc:
            raise SetupError(f"the downloaded snapshot is damaged: {exc}") from exc
        if fresh is None or fresh.version != version or fresh.repo != current.repo:
            raise SetupError(f"the downloaded snapshot is not {current.repo} {version}: nothing changed")
        return install(answers_from_record(layout, record), source=unpacked, **install_options)  # type: ignore[arg-type]
    finally:
        shutil.rmtree(unpacked, ignore_errors=True)
