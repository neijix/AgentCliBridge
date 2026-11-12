"""The hidden-console flag for a CLI a windowless host starts: a turn, or a version, model,
or sign-in probe. On POSIX the dict is empty."""

import os
import subprocess
from typing import Any


def background_process_options(os_name: str | None = None) -> dict[str, Any]:
    """Keep a spawned CLI off the Windows desktop; leave POSIX unchanged.

    ``os_name`` is the platform to answer for (``spawn_options`` passes the one it was
    asked about). Omitted, it is this process's ``os.name``.
    """
    if (os_name or os.name) != "nt":
        return {}
    # CREATE_NO_WINDOW exists only in Windows' subprocess (mypy checks every platform in CI).
    return {"creationflags": subprocess.CREATE_NO_WINDOW}  # type: ignore[attr-defined,unused-ignore]
