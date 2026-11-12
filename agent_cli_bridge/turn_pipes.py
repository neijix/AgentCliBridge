"""Stdin for one CLI turn, and a stderr buffer that keeps only the tail."""

import asyncio
import contextlib

_STDERR_TAIL_BYTES = 256 * 1024
_READ_CHUNK = 64 * 1024


def turn_stdin(writes: bool) -> int:
    """PIPE when this turn writes a prompt or live control messages; otherwise DEVNULL.

    DEVNULL so a CLI that reads stdin cannot block on the host's still-open pipe.
    """
    return asyncio.subprocess.PIPE if writes else asyncio.subprocess.DEVNULL


def _retrieve(task: asyncio.Task[None]) -> None:
    if not task.cancelled():
        task.exception()


class _StderrTail:
    """Drains a stderr stream while the turn runs, keeping at most the last 256 KiB."""

    def __init__(self, stream: asyncio.StreamReader) -> None:
        self._buf = bytearray()
        self._task = asyncio.create_task(self._drain(stream))
        self._task.add_done_callback(_retrieve)

    async def _drain(self, stream: asyncio.StreamReader) -> None:
        with contextlib.suppress(Exception):
            while True:
                chunk = await stream.read(_READ_CHUNK)
                if not chunk:
                    break
                self._buf.extend(chunk)
                extra = len(self._buf) - _STDERR_TAIL_BYTES
                if extra > 0:
                    del self._buf[:extra]

    async def read(self) -> bytes:
        me = asyncio.current_task()
        try:
            await self._task
        except asyncio.CancelledError:
            if me is not None and me.cancelling():
                self._task.cancel()
                raise
        except Exception:
            pass
        return bytes(self._buf)


def stderr_tail(stream: asyncio.StreamReader | None) -> _StderrTail:
    """Start draining ``stream``. ``read`` later returns at most the last 256 KiB."""
    assert stream is not None
    return _StderrTail(stream)
