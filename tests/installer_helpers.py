"""Shared by the installer tests: a fake snapshot, a recording runner, answers, one install."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from bridge_installer import MANIFEST_NAME
from bridge_installer.apply import install
from bridge_installer.layout import Answers
from bridge_installer.manifest import Manifest

COMMIT = "0123456789abcdef0123456789abcdef01234567"
REPO = "owner/AgentCliBridge"


class Recorder:
    """A Runner: records each argv, answers 0 (or ``codes[first word]``)."""

    def __init__(self, codes: dict[str, int] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.codes = codes or {}

    def __call__(self, argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        self.calls.append([str(a) for a in argv])
        return subprocess.CompletedProcess(argv, self.codes.get(Path(argv[0]).name, 0), "", "")

    def scripts(self) -> list[str]:
        return [Path(call[1]).name for call in self.calls if len(call) > 1 and call[1].endswith((".sh", ".ps1"))]


def make_snapshot(folder: Path, version: str = "1.0.0") -> Path:
    folder.mkdir(parents=True)
    (folder / MANIFEST_NAME).write_text(Manifest(version, COMMIT, REPO).as_json(), encoding="utf-8")
    for name in ("install.sh", "stop.sh", "kill.sh", "start.sh"):
        (folder / name).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    (folder / "README.md").write_text(f"snapshot {version}\n", encoding="utf-8")
    return folder


def answers(root: Path, **changes: object) -> Answers:
    values: dict[str, object] = {"root": root, "settings_dir": root / "config", "port": 4799, "autostart": False}
    values.update(changes)
    return Answers(**values)  # type: ignore[arg-type]


def run_install(tmp_path: Path, uv: Path, target: Answers, version: str = "1.0.0", runner: Recorder | None = None) -> int:
    source = make_snapshot(tmp_path / f"snap-{version}-{len(list(tmp_path.glob('snap-*')))}", version)
    return install(target, source=source, uv=uv, python=Path(sys.executable),
                   runner=runner or Recorder(), is_up=lambda _port: True)
