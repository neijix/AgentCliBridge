"""Claude download guards, called for real: host allow-list, size limit, signature check.

A ``download=`` or ``verify=`` stand-in that skips the check would still pass if the guard
were deleted. These tests call ``_download_claude_release`` and ``verify_claude_signature``.
"""

import subprocess
from pathlib import Path

import pytest

from agent_cli_bridge.cli_status import (
    ANTHROPIC_SIGN_ID,
    ANTHROPIC_TEAM_ID,
    CLAUDE_RELEASE_HOST,
    CLAUDE_RELEASE_MAX_BYTES,
    CLAUDE_RELEASE_MIN_BYTES,
    DOWNLOAD_NAME,
    ClaudeReleaseError,
    _download_claude_release,
    install_published_claude,
    verify_claude_signature,
)

_GOOD_URL = f"https://{CLAUDE_RELEASE_HOST}/claude-code-releases/2.1.281/linux-x64/claude"
_ELF = b"\x7fELF"
_MACHO = b"\xcf\xfa\xed\xfe"
_REFUSED_URLS = (
    "http://downloads.claude.ai/claude-code-releases/2.1.281/linux-x64/claude",
    "https://evil.example/claude-code-releases/2.1.281/linux-x64/claude",
    "https://downloads.claude.ai.evil.example/claude",
    "https://notdownloads.claude.ai/claude",
    "https://downloads.claude.ai@evil.example/claude",
    "https://evil.example/https://downloads.claude.ai/claude",
    "file:///tmp/claude",
)
_VERIFY_ARGV = ["/usr/bin/codesign", "--verify", "--strict"]
_IDENTITY_ARGV = ["/usr/bin/codesign", "-d", "--verbose=4"]


class _Response:
    def __init__(self, body: bytes, content_length: str | None, reads: list[int]) -> None:
        self._body = body
        self._pos = 0
        self._reads = reads
        self.headers: dict[str, str] = {}
        if content_length is not None:
            self.headers["Content-Length"] = content_length

    def read(self, size: int = -1) -> bytes:
        self._reads.append(size)
        if self._pos >= len(self._body):
            return b""
        end = len(self._body) if size < 0 else self._pos + size
        chunk = self._body[self._pos : end]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _patch_urlopen(monkeypatch, body: bytes, content_length: str | None):
    seen: list[tuple[str, float]] = []
    reads: list[int] = []

    def urlopen(request, timeout=120.0):
        seen.append((request.full_url, timeout))
        return _Response(body, content_length, reads)

    monkeypatch.setattr("agent_cli_bridge.http_get.urlopen", urlopen)
    return seen, reads


def _cask(tmp_path: Path) -> Path:
    real = tmp_path / "Caskroom" / "claude-code@latest" / "2.1.280" / "claude"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"old-claude")
    return real


def _codesign_run(calls: list[list[str]], *, verify_code: int, detail: str):
    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        if list(argv[:3]) == _VERIFY_ARGV:
            stderr = "" if verify_code == 0 else "code object is not signed"
            return subprocess.CompletedProcess(argv, verify_code, "", stderr)
        return subprocess.CompletedProcess(argv, 0, "", detail)

    return fake_run


def _arm_darwin(monkeypatch, calls: list[list[str]], *, verify_code: int = 0, detail: str = "") -> None:
    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Darwin")
    monkeypatch.setattr(
        "agent_cli_bridge.cli_status.subprocess.run",
        _codesign_run(calls, verify_code=verify_code, detail=detail),
    )


def test_release_text_uses_the_shared_get_and_names_its_limit(monkeypatch):
    from agent_cli_bridge.cli_status import _MAX_BYTES, fetch_text

    seen = {}

    def fake(url, max_bytes, *, timeout, headers=None):
        seen["url"] = url
        seen["max"] = max_bytes
        seen["timeout"] = timeout
        return b"2.1.281\n"

    monkeypatch.setattr("agent_cli_bridge.cli_status.get_bytes", fake)
    assert fetch_text("https://registry.npmjs.org/claude", timeout=3) == b"2.1.281\n"
    assert seen == {"url": "https://registry.npmjs.org/claude", "max": _MAX_BYTES, "timeout": 3}


def test_claude_release_download_refuses_a_host_outside_the_allow_list(tmp_path, monkeypatch):
    def urlopen(request, timeout=120.0):
        raise AssertionError(f"allow-list let a download through: {request.full_url}")

    monkeypatch.setattr("agent_cli_bridge.http_get.urlopen", urlopen)
    dest = tmp_path / "claude"
    for url in _REFUSED_URLS:
        with pytest.raises(ClaudeReleaseError, match=r"not https://downloads\.claude\.ai"):
            _download_claude_release(url, dest)
        assert not dest.exists()


def test_claude_release_download_allows_the_anthropic_host_then_enforces_the_announced_minimum(
    tmp_path, monkeypatch
):
    assert CLAUDE_RELEASE_HOST == "downloads.claude.ai"
    assert CLAUDE_RELEASE_MIN_BYTES == 20 * 1024 * 1024
    seen, reads = _patch_urlopen(monkeypatch, b"x", str(CLAUDE_RELEASE_MIN_BYTES - 1))
    dest = tmp_path / "claude"
    with pytest.raises(ClaudeReleaseError, match="not a release"):
        _download_claude_release(_GOOD_URL, dest)
    assert seen == [(_GOOD_URL, 120.0)]
    assert reads == []
    assert not dest.exists()


def test_claude_release_download_rejects_an_announced_size_above_the_maximum(tmp_path, monkeypatch):
    assert CLAUDE_RELEASE_MAX_BYTES == 400 * 1024 * 1024
    seen, reads = _patch_urlopen(monkeypatch, b"x", str(CLAUDE_RELEASE_MAX_BYTES + 1))
    dest = tmp_path / "claude"
    with pytest.raises(ClaudeReleaseError, match="not a release"):
        _download_claude_release(_GOOD_URL, dest)
    assert seen == [(_GOOD_URL, 120.0)]
    assert reads == []
    assert not dest.exists()


def test_claude_release_download_accepts_an_announced_size_on_either_bound(tmp_path, monkeypatch):
    """The announced floor and cap are exclusive on the outside: the exact bounds still download."""
    dest = tmp_path / "claude"
    for announced in (CLAUDE_RELEASE_MIN_BYTES, CLAUDE_RELEASE_MAX_BYTES):
        _patch_urlopen(monkeypatch, b"x", str(announced))
        with pytest.raises(ClaudeReleaseError, match="only 1 bytes"):
            _download_claude_release(_GOOD_URL, dest)


def test_claude_release_download_rejects_a_body_under_the_minimum(tmp_path, monkeypatch):
    _patch_urlopen(monkeypatch, b"x" * 64, None)
    dest = tmp_path / "claude"
    with pytest.raises(ClaudeReleaseError, match="only 64 bytes"):
        _download_claude_release(_GOOD_URL, dest)


def test_claude_release_download_stops_when_the_body_passes_the_maximum(tmp_path, monkeypatch):
    # The real cap is 400 MiB (locked above). Lower it here so the loop's own check runs
    # without allocating that much; removing the check lets this 64-byte body finish.
    monkeypatch.setattr("agent_cli_bridge.cli_status.CLAUDE_RELEASE_MAX_BYTES", 32)
    _patch_urlopen(monkeypatch, b"x" * 64, None)
    dest = tmp_path / "claude"
    with pytest.raises(ClaudeReleaseError, match="larger than expected"):
        _download_claude_release(_GOOD_URL, dest)
    assert dest.read_bytes() == b""


def test_claude_release_signature_rejects_a_file_that_is_not_an_executable(tmp_path):
    path = tmp_path / "claude"
    path.write_bytes(b"not-a-binary")
    with pytest.raises(
        ClaudeReleaseError,
        match="not a Linux executable|not a macOS executable|no Claude signature check",
    ):
        verify_claude_signature(str(path))


def test_claude_release_signature_on_linux_accepts_elf_and_rejects_anything_else(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Linux")

    def fail_run(*args, **kwargs):
        raise AssertionError("the Linux signature check must not spawn a process")

    monkeypatch.setattr("agent_cli_bridge.cli_status.subprocess.run", fail_run)
    elf = tmp_path / "elf"
    elf.write_bytes(_ELF)
    verify_claude_signature(str(elf))
    other = tmp_path / "other"
    other.write_bytes(_MACHO)
    with pytest.raises(ClaudeReleaseError, match="not a Linux executable"):
        verify_claude_signature(str(other))


def test_claude_release_signature_on_macos_rejects_a_non_mach_o_before_codesign(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    _arm_darwin(monkeypatch, calls)
    path = tmp_path / "claude"
    path.write_bytes(b"not-a-binary")
    with pytest.raises(ClaudeReleaseError, match="not a macOS executable"):
        verify_claude_signature(str(path))
    assert calls == []


def test_claude_release_signature_on_macos_rejects_a_binary_codesign_will_not_verify(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    _arm_darwin(monkeypatch, calls, verify_code=1)
    path = tmp_path / "claude"
    path.write_bytes(_MACHO)
    with pytest.raises(ClaudeReleaseError, match="signature check failed"):
        verify_claude_signature(str(path))
    assert calls == [_VERIFY_ARGV + [str(path)]]


@pytest.mark.parametrize(
    ("identifier", "team"),
    [
        ("com.example.other", ANTHROPIC_TEAM_ID),
        (ANTHROPIC_SIGN_ID, "NOTOURS123"),
    ],
)
def test_claude_release_signature_rejects_a_binary_not_signed_by_anthropic(
    tmp_path, monkeypatch, identifier, team
):
    calls: list[list[str]] = []
    detail = f"Identifier={identifier}\nTeamIdentifier={team}\n"
    _arm_darwin(monkeypatch, calls, detail=detail)
    path = tmp_path / "claude"
    path.write_bytes(_MACHO)
    with pytest.raises(ClaudeReleaseError, match="not signed by Anthropic"):
        verify_claude_signature(str(path))
    assert calls == [_VERIFY_ARGV + [str(path)], _IDENTITY_ARGV + [str(path)]]


def test_claude_release_signature_accepts_anthropics_macos_signature(tmp_path, monkeypatch):
    calls: list[list[str]] = []
    detail = f"Identifier={ANTHROPIC_SIGN_ID}\nTeamIdentifier={ANTHROPIC_TEAM_ID}\n"
    _arm_darwin(monkeypatch, calls, detail=detail)
    path = tmp_path / "claude"
    path.write_bytes(_MACHO)
    verify_claude_signature(str(path))
    assert calls == [_VERIFY_ARGV + [str(path)], _IDENTITY_ARGV + [str(path)]]


def test_claude_release_signature_has_no_windows_bypass(tmp_path, monkeypatch):
    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Windows")
    path = tmp_path / "claude"
    path.write_bytes(_ELF)
    with pytest.raises(ClaudeReleaseError, match="no Claude signature check for Windows"):
        verify_claude_signature(str(path))


def test_claude_release_install_runs_the_real_signature_check(tmp_path, monkeypatch):
    """``verify`` is left unset, so install reaches ``verify_claude_signature`` itself."""
    monkeypatch.setattr("agent_cli_bridge.cli_status.platform.system", lambda: "Linux")
    real = _cask(tmp_path)

    def download_junk(url, dest):
        assert url.startswith(f"https://{CLAUDE_RELEASE_HOST}/")
        dest.write_bytes(b"not-a-binary")

    with pytest.raises(ClaudeReleaseError, match="not a Linux executable"):
        install_published_claude(
            str(real), "2.1.281", system="Linux", machine="x86_64", download=download_junk
        )
    assert real.read_bytes() == b"old-claude"
    assert not real.with_name(DOWNLOAD_NAME).exists()

    def download_elf(url, dest):
        dest.write_bytes(_ELF)

    note = install_published_claude(
        str(real), "2.1.281", system="Linux", machine="x86_64", download=download_elf
    )
    assert real.read_bytes() == _ELF
    assert "2.1.281" in note
    assert not real.with_name(DOWNLOAD_NAME).exists()
