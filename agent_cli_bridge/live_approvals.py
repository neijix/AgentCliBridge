"""Live-turn approvals, and the non-live kill after a high-severity injection.

On a live Claude turn the default tool list does not pre-approve Bash. While that turn
is still clean, the runner answers the same way ``TurnInput.answer`` does — allow, and do
not yield ``ApprovalRequest`` — for generic Bash, one plain ``d3skwebscout search``
(``is_plain_search``), one plain ``d3skwebscout status`` (``is_plain_status``), and a
plain fetch ``WebScout.is_scout_fetch_approval`` accepts. A Bash call with no command is
not auto-allowed. A command whose text contains ``d3skwebscout`` and is not exactly one
plain search, status or fetch — ``--allow-risky`` or an unambiguous prefix of it, a chain,
a path, or the name inside a substitution — is yielded, and so is every other tool. Once
the turn is tainted,
``InjectionGuard.review`` decides: a tool it does not treat as read-only is denied.

On a non-live turn nothing can answer an approval, so the first HIGH finding kills the
CLI's process group before the error event is yielded, then ``Completed(-1)`` ends the turn. Two LOW findings do not, even
when they are different rules that would taint a live turn.
"""
import asyncio
import contextvars
import logging
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Protocol

from .control import TurnInput
from .events import ActionBlocked, ApprovalRequest, Completed, InjectionDetected, StreamError, StreamEvent
from .injection_guard import HIGH, PAGE_WITHHELD_RULE, RULES, InjectionGuard, Rule
from .web_scout import (
    WebScout,
    invokes_scout,
    is_plain_search,
    is_plain_status,
    plain_scout_verb,
    shell_command,
)

log = logging.getLogger(__name__)

# None when this task is not recording a child; otherwise the children spawned so far.
_turn_process: contextvars.ContextVar[list[asyncio.subprocess.Process] | None] = contextvars.ContextVar(
    "acb_turn_process", default=None
)

_NON_LIVE_HIGH = (
    "Stopped this turn: a tool result matched a high-severity prompt-injection rule."
)


@dataclass(frozen=True)
class SettledApproval:
    """An approval the runner answered itself. Both flags clear: the host still decides."""

    blocked: ActionBlocked | None = None
    allowed: bool = False


def settle_approval(
    event: ApprovalRequest,
    *,
    turn_input: TurnInput,
    guard: InjectionGuard | None,
    scout: WebScout | None,
) -> SettledApproval:
    """Deny a tainted non-safe tool, or allow a clean-turn Bash form.

    The control response is the one ``TurnInput.answer`` writes. A denial the turn could
    not accept, and anything this does not allow, is left for the host.
    """
    blocked = guard.review(event) if guard is not None else None
    if blocked is not None and turn_input.answer(event.request_id, False, blocked.reason):
        return SettledApproval(blocked=blocked)
    if (
        _turn_is_clean(guard)
        and is_auto_allowed_while_clean(event, scout)
        and turn_input.answer(event.request_id, True)
    ):
        return SettledApproval(allowed=True)
    return SettledApproval()


def is_auto_allowed_while_clean(event: ApprovalRequest, scout: WebScout | None) -> bool:
    """Generic Bash, one plain search, one plain status, or a plain fetch the scout accepts.

    A missing or non-string command is not generic Bash. Search and status are plain only
    when they carry no ``--allow-risky`` (``is_plain_search``, ``is_plain_status``). When
    the command text names the scout or ``allow-risky`` (``invokes_scout``) and it is not
    exactly one of those plain forms, it stays with the host.
    """
    command = shell_command(event.name, event.arguments)
    if command is None:
        return False
    if is_plain_search(command) or is_plain_status(command):
        return True
    if scout is not None and scout.is_scout_fetch_approval(event):
        return True
    return plain_scout_verb(command) is None and not invokes_scout(command)


def non_live_kill_error(
    detection: InjectionDetected,
    *,
    is_live: bool,
    guard: InjectionGuard | None = None,
    stop: Callable[[], None] | None = None,
) -> StreamError | None:
    """The error for a non-live turn's first HIGH finding; None when the turn continues.

    ``stop`` kills the CLI's process group before this returns, so the child is already
    dead when the caller receives the error. Two LOW rules taint a live turn and do not
    take this path.
    """
    if is_live or not _is_high(detection, guard.rules if guard is not None else RULES):
        return None
    if stop is not None:
        stop()
    log.warning("stopping a non-live turn after a high-severity injection: %s", ", ".join(detection.rules))
    return StreamError(_NON_LIVE_HIGH, code="injection")


def _turn_is_clean(guard: InjectionGuard | None) -> bool:
    return guard is None or not guard.is_tainted


def _is_high(detection: InjectionDetected, rules: tuple[Rule, ...]) -> bool:
    high = {rule.name for rule in rules if rule.severity == HIGH}
    return any(name in high for name in detection.rules)


class _TurnLog(Protocol):
    def observe(self, event: StreamEvent) -> None: ...

    def detected(self, detection: InjectionDetected) -> InjectionDetected: ...

    def blocked(self, blocked: ActionBlocked) -> ActionBlocked: ...


def remember_spawned(proc: asyncio.subprocess.Process) -> asyncio.subprocess.Process:
    """Record the first child of a captured turn and return it."""
    procs = _turn_process.get()
    if procs is not None and not procs:
        procs.append(proc)
    return proc


@contextmanager
def turn_process_capture() -> Iterator[None]:
    """Record the child spawned on this task until the block ends."""
    token = _turn_process.set([])
    try:
        yield
    finally:
        _turn_process.reset(token)


def _captured_stop(kill: Callable[[asyncio.subprocess.Process], None]) -> Callable[[], None] | None:
    procs = _turn_process.get()
    if not procs:
        return None
    proc = procs[0]
    return lambda: kill(proc)


async def guard_turn_events(
    source: AsyncIterator[StreamEvent],
    *,
    turn_input: TurnInput | None,
    guard: InjectionGuard | None,
    scout: WebScout | None,
    recorder: _TurnLog | None,
    activity: bool,
    is_live: bool,
    kill: Callable[[asyncio.subprocess.Process], None],
    activity_events: tuple[type[Any], ...],
) -> AsyncIterator[StreamEvent]:
    """Yield the turn, answering approvals here and killing before a non-live high error."""
    async for event in source:
        if isinstance(event, ApprovalRequest) and turn_input is not None:
            settled = settle_approval(event, turn_input=turn_input, guard=guard, scout=scout)
            if settled.blocked is not None:
                blocked = recorder.blocked(settled.blocked) if recorder is not None else settled.blocked
                yield blocked
                continue
            if settled.allowed:
                continue
        if recorder is not None:
            recorder.observe(event)
        detection = guard.observe(event) if guard is not None else None
        if activity or not isinstance(event, activity_events):
            yield event
        if detection is None:
            continue
        if recorder is not None and detection.rules != (PAGE_WITHHELD_RULE,):  # logged as page_withheld
            detection = recorder.detected(detection)
        if activity:
            yield detection
        error = non_live_kill_error(detection, is_live=is_live, guard=guard, stop=_captured_stop(kill))
        if error is not None:
            yield error
            yield Completed(-1)  # the turn still ends the way every non-interrupted turn does
            break
