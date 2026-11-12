"""Proxy one chat completion to an OpenAI-compatible upstream.

The upstream status is known before a stream is returned. A 4xx or 5xx whose body is JSON
is returned with that status. A body that is not JSON, and any httpx.HTTPError, is HTTP 502.
The client waits 30s to connect and 300s of silence between bytes; every timeout field is set.
Its clients never read the proxy environment variables (``trust_env=False``): the upstream is a
loopback server, and an ``HTTP_PROXY`` must not redirect it. The caller's ``Authorization`` is
not forwarded.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from .gateway_openai import _error_json

log = logging.getLogger(__name__)

MODEL_PREFIX = "mlx"
CONNECT_TIMEOUT_SECONDS = 30.0
SILENCE_TIMEOUT_SECONDS = 300.0

_NOT_JSON = object()


def upstream_timeout() -> httpx.Timeout:
    """30s to connect, 300s of silence between bytes. No field is left unset."""
    return httpx.Timeout(
        connect=CONNECT_TIMEOUT_SECONDS,
        read=SILENCE_TIMEOUT_SECONDS,
        write=SILENCE_TIMEOUT_SECONDS,
        pool=CONNECT_TIMEOUT_SECONDS,
    )


def prepare_body(body: dict[str, Any]) -> dict[str, Any]:
    """Drop the bridge extension and the synthetic ``mlx:`` model prefix."""
    forwarded = dict(body)
    forwarded.pop("bridge", None)
    model = forwarded.get("model")
    prefix = f"{MODEL_PREFIX}:"
    if isinstance(model, str) and model.startswith(prefix):
        forwarded["model"] = model[len(prefix):]
    return forwarded


def _unreachable(base: str) -> JSONResponse:
    return JSONResponse(
        _error_json(
            f"Upstream OpenAI server unreachable at {base} — "
            "is your upstream OpenAI-compatible server running?",
            "upstream_unreachable",
        ),
        status_code=502,
    )


def _bad_body(status: int) -> JSONResponse:
    return JSONResponse(
        _error_json(
            f"Upstream returned HTTP {status} with a body that is not JSON.",
            "upstream_bad_response",
        ),
        status_code=502,
    )


def _open_client(transport: httpx.AsyncBaseTransport | None) -> httpx.AsyncClient:
    timeout = upstream_timeout()
    if transport is None:
        return httpx.AsyncClient(timeout=timeout, trust_env=False)
    return httpx.AsyncClient(timeout=timeout, transport=transport, trust_env=False)


def _payload(response: Any) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _NOT_JSON


async def _json_result(response: Any) -> JSONResponse:
    read = getattr(response, "aread", None)
    if read is not None:
        await read()
    payload = _payload(response)
    if payload is _NOT_JSON:
        return _bad_body(response.status_code)
    return JSONResponse(payload, status_code=response.status_code)


async def _aclose(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if close is not None:
        await close()


async def _relay(client: httpx.AsyncClient, response: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()
        await _aclose(client)


async def _read_error(client: httpx.AsyncClient, response: httpx.Response, base: str) -> JSONResponse:
    try:
        return await _json_result(response)
    except httpx.HTTPError as exc:
        log.warning("upstream chat failed for %s: %s", base, exc)
        return _unreachable(base)
    finally:
        await response.aclose()
        await _aclose(client)


async def _proxy_stream(
    client: httpx.AsyncClient, url: str, body: dict[str, Any], base: str
) -> JSONResponse | StreamingResponse:
    try:
        request = client.build_request("POST", url, json=body)
        response = await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        log.warning("upstream chat failed for %s: %s", base, exc)
        await _aclose(client)
        return _unreachable(base)
    if response.status_code >= 400:
        return await _read_error(client, response, base)
    return StreamingResponse(
        _relay(client, response),
        status_code=response.status_code,
        media_type="text/event-stream",
    )


async def proxy_chat(
    base: str,
    body: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> JSONResponse | StreamingResponse:
    """POST ``base``/chat/completions. The return status is the upstream's, or 502."""
    forwarded = prepare_body(body)
    url = f"{base.rstrip('/')}/chat/completions"
    client = _open_client(transport)
    if forwarded.get("stream"):
        return await _proxy_stream(client, url, forwarded, base)
    try:
        async with client:
            response = await client.post(url, json=forwarded)
            return await _json_result(response)
    except httpx.HTTPError as exc:
        log.warning("upstream chat failed for %s: %s", base, exc)
        return _unreachable(base)


async def fetch_models(base: str) -> list[dict[str, Any]] | None:
    """The upstream's ``/models`` entries that have an id, or None when it does not answer 200.

    Best effort: the gateway stays usable when the upstream is down.
    """
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            response = await client.get(f"{base}/models")
            if response.status_code != 200:
                return None
            data = response.json().get("data", [])
            return [m for m in data if isinstance(m, dict) and m.get("id")]
    except Exception:
        return None
