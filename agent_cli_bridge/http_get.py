"""One size-limited GET shared by the release, catalog, ranking, and Strata readers.

http and https only. A URL that carries a username or password is refused, and a redirect is
a failure rather than a second request. A loopback host is contacted directly: Python's proxy
settings, including the Windows system proxy, do not exempt ``127.0.0.1``. The caller names
how many bytes are enough; a longer body raises ValueError.
"""

import ipaddress
import urllib.request
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any, BinaryIO
from urllib.parse import urlsplit


class _RefuseRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect fails the read: the bytes must come from the host that was named."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _hostname(url: str) -> str:
    """The host of an http(s) URL, or ValueError when the URL is not one this GET may open."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise ValueError("not an http(s) URL")
    if parts.username is not None or parts.password is not None:
        raise ValueError("a URL with credentials in it is never read")
    return parts.hostname


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def urlopen(request: urllib.request.Request, timeout: float) -> Any:
    """Open ``request`` with redirects refused, and with no proxy when the host is loopback."""
    handlers: list[urllib.request.BaseHandler] = [_RefuseRedirects()]
    if _is_loopback(_hostname(request.full_url)):
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)


@contextmanager
def open_limited(
    url: str, *, timeout: float, headers: Mapping[str, str] | None = None
) -> Iterator[Any]:
    """Open one GET. A non-http(s) scheme, URL credentials, or a redirect fails the read."""
    _hostname(url)
    request = urllib.request.Request(url, headers=dict(headers or {}))
    with urlopen(request, timeout) as response:
        yield response


def read_bounded(response: Any, max_bytes: int, out: BinaryIO | None = None) -> tuple[int, bytes]:
    """The body, at most ``max_bytes``. A longer body raises ValueError and is not kept.

    When ``out`` is set, fitting chunks are written there and the returned bytes are empty, so a
    caller that streams to disk does not also hold the body.
    """
    kept: list[bytes] = []
    total = 0
    while total <= max_bytes:
        chunk = response.read(min(1024 * 1024, max_bytes + 1 - total))
        if not chunk:
            break
        if total + len(chunk) > max_bytes:
            raise ValueError(f"response is over the {max_bytes} byte limit")
        total += len(chunk)
        if out is None:
            kept.append(chunk)
        else:
            out.write(chunk)
    return total, b"".join(kept)


def get_bytes(
    url: str,
    max_bytes: int,
    *,
    timeout: float,
    headers: Mapping[str, str] | None = None,
) -> bytes:
    """GET ``url`` and return at most ``max_bytes``."""
    with open_limited(url, timeout=timeout, headers=headers) as response:
        _total, body = read_bounded(response, max_bytes)
    return body
