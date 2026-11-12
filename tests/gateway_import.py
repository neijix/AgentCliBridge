"""Shared fastapi import check for gateway tests: skip locally, fail when CI is set."""
import os
import sys
from pathlib import Path

import pytest


def require_fastapi(*, allow_module_level: bool = False) -> None:
    """Skip when fastapi is absent, unless CI asked for the gateway tests."""
    try:
        import fastapi  # noqa: F401
    except ImportError:
        if os.environ.get("CI"):
            pytest.fail("fastapi is required when CI is set")
        pytest.skip("fastapi is not installed", allow_module_level=allow_module_level)


def test_fastapi_required_when_ci_is_set(monkeypatch):
    import builtins

    source = Path(__file__).with_name("test_gateway.py").read_text(encoding="utf-8")
    assert "\nrequire_fastapi(allow_module_level=True)\n" in source
    for name in list(sys.modules):
        if name == "fastapi" or name.startswith("fastapi."):
            monkeypatch.delitem(sys.modules, name, raising=False)
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "fastapi" or name.startswith("fastapi."):
            raise ImportError("no fastapi")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(BaseException) as missing_under_ci:
        require_fastapi(allow_module_level=True)
    assert type(missing_under_ci.value).__name__ == "Failed"
    monkeypatch.delenv("CI")
    with pytest.raises(BaseException) as missing_locally:
        require_fastapi(allow_module_level=True)
    assert type(missing_locally.value).__name__ == "Skipped"
