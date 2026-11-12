"""Environment of a CLI this process spawns."""

from collections.abc import Mapping

_BRIDGE_TOKENS = frozenset({"BRIDGE_TOKEN", "BRIDGE_OWNER_TOKEN"})


def child_env(env: Mapping[str, str]) -> dict[str, str]:
    """Copy of ``env`` for the child process, without the gateway bearer tokens."""
    return {key: value for key, value in env.items() if key not in _BRIDGE_TOKENS}
