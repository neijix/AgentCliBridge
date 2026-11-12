"""The snapshot manifest and SemVer 2.0 version order.

A release snapshot (``release.py``) carries ``MANIFEST_NAME`` at its root: the version, the commit
and the GitHub repo the install updates from. An install folder keeps the snapshot in ``app/``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from bridge_installer import MANIFEST_NAME

MANIFEST_KIND = "agentclibridge-snapshot"
MANIFEST_FORMAT = 1
_MAX_BYTES = 64 * 1024

_SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_REPO = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


class ManifestError(ValueError):
    """A manifest that exists but cannot be trusted; the message says why."""


@dataclass(frozen=True)
class Manifest:
    version: str
    commit: str
    repo: str  # GitHub "owner/repo" the install updates from

    def as_json(self) -> str:
        data = {"commit": self.commit, "format": MANIFEST_FORMAT, "kind": MANIFEST_KIND,
                "repo": self.repo, "version": self.version}
        return json.dumps(data, indent=2, sort_keys=True) + "\n"


def parse_version(text: str) -> tuple[int, int, int, tuple[str, ...]]:
    """``(major, minor, patch, prerelease identifiers)``; build metadata dropped."""
    match = _SEMVER.match(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError(f"not a SemVer 2.0 version: {text!r}")
    pre = tuple(match["pre"].split(".")) if match["pre"] else ()
    return int(match["major"]), int(match["minor"]), int(match["patch"]), pre


def is_valid_version(text: str) -> bool:
    try:
        parse_version(text)
    except ValueError:
        return False
    return True


def _key(identifier: str) -> tuple[int, int, str]:
    # Numeric identifiers rank below alphanumeric ones and compare as numbers (SemVer 2.0 §11).
    return (0, int(identifier), "") if identifier.isdigit() else (1, 0, identifier)


def compare_versions(a: str, b: str) -> int:
    """-1, 0 or 1 by SemVer 2.0 precedence: a release is above its prereleases."""
    *core_a, pre_a = parse_version(a)
    *core_b, pre_b = parse_version(b)
    if core_a != core_b:
        return -1 if core_a < core_b else 1
    if pre_a == pre_b:
        return 0
    if not pre_a or not pre_b:
        return 1 if not pre_a else -1
    return -1 if [_key(i) for i in pre_a] < [_key(i) for i in pre_b] else 1


def parse_manifest(text: str) -> Manifest:
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ManifestError(f"not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != MANIFEST_KIND:
        raise ManifestError(f"'kind' is not {MANIFEST_KIND!r}")
    if data.get("format") != MANIFEST_FORMAT:
        raise ManifestError(f"unsupported 'format' {data.get('format')!r}")
    version, commit, repo = data.get("version"), data.get("commit"), data.get("repo")
    if not isinstance(version, str) or not is_valid_version(version):
        raise ManifestError(f"'version' is not a SemVer 2.0 version: {version!r}")
    if not isinstance(commit, str) or not _COMMIT.match(commit):
        raise ManifestError(f"'commit' is not a full git commit id: {commit!r}")
    if not isinstance(repo, str) or not _REPO.match(repo):
        raise ManifestError(f"'repo' is not a GitHub owner/repo: {repo!r}")
    return Manifest(version=version, commit=commit, repo=repo)


def read_manifest(root: Path) -> Manifest | None:
    """The manifest at ``root`` (a snapshot's root); ``None`` when absent, ``ManifestError`` when bad."""
    path = Path(root) / MANIFEST_NAME
    try:
        if not path.is_file():
            return None
        with path.open("rb") as handle:
            raw = handle.read(_MAX_BYTES + 1)
    except OSError as exc:
        raise ManifestError(f"cannot read {path}: {exc.strerror or exc}") from exc
    if len(raw) > _MAX_BYTES:
        raise ManifestError(f"{path} is larger than {_MAX_BYTES} bytes")
    try:
        return parse_manifest(raw.decode("utf-8"))
    except (UnicodeDecodeError, ManifestError) as exc:
        raise ManifestError(f"{path}: {exc}") from exc
