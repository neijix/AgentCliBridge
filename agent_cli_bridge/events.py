"""Structured stream events yielded by the runner.

The runner never formats transport frames: it yields these events and nothing else, which
keeps it reusable across apps. A host that streams to a web page can turn them into the shared
chat wire format with ``wire.py`` (``to_wire`` / ``sse_frame``; ``ui/stream.js`` is the page
half); a host with another transport translates the events itself.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TextDelta:
    """A chunk of assistant text, in arrival order."""

    text: str


@dataclass(frozen=True)
class SessionUpdate:
    """The CLI's own session id, captured for --resume on later turns.

    Emitted as soon as the id is known (init event or final result). Consumers
    persist it however they like (DB row, file, memory) and pass it back via
    ``resume_id`` next turn.
    """

    session_id: str


@dataclass(frozen=True)
class StreamError:
    """Terminal failure with a human-readable message.

    Emitted when the CLI produced no usable output, or when a stream-json
    ``result`` is marked ``is_error`` / ``subtype: error`` (Claude OAuth expiry
    is that, with the reason in ``result``). JSON error payloads on stderr
    (e.g. Gemini's ``{error:{message}}``) are already unwrapped.
    """

    message: str
    code: str = "cli_agent_failed"


@dataclass(frozen=True)
class Completed:
    """The subprocess exited; last event of a non-interrupted run."""

    returncode: int


# ── activity events: only yielded by run_agent(..., activity=True) ──


@dataclass(frozen=True)
class ThinkingDelta:
    """A chunk of the model's visible reasoning, in arrival order."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    """The agent started a tool (read a file, run a command, …).

    ``call_id`` pairs it with its ToolResult; ``arguments`` is the tool input
    as the CLI reported it (usually a dict).
    """

    call_id: str
    name: str
    arguments: Any


@dataclass(frozen=True)
class ToolResult:
    """A tool finished; ``output`` is its text as the CLI reported it.

    ``raw`` is the CLI's text before the parser unwrapped it (a JSON envelope whose ``output``
    became ``output``), "" when nothing was unwrapped. The guard scans both: a field the
    unwrapping dropped is still something the model read.
    """

    call_id: str
    output: str
    is_error: bool = False
    raw: str = field(default="", compare=False, repr=False)


# ── live input: only yielded by run_agent(..., turn_input=TurnInput()) (control.py) ──


@dataclass(frozen=True)
class ApprovalRequest:
    """The CLI waits until the host allows or denies one tool call (``TurnInput.answer``).

    ``request_id`` is what to answer; ``call_id`` pairs it with the ToolCall it gates.
    """

    request_id: str
    call_id: str
    name: str
    arguments: Any
    description: str = ""


@dataclass(frozen=True)
class InputAccepted:
    """The CLI took a message added with ``TurnInput.say``; what follows answers it too.

    Messages are taken in the order they were said.
    """

    text: str


@dataclass(frozen=True)
class ModeChanged:
    """The CLI answered ``TurnInput.set_permission_mode``: ``mode`` now applies to the rest
    of the turn, or ``error`` says why the CLI refused it (the previous mode stays)."""

    mode: str
    error: str = ""


# ── injection guard: yielded by run_agent unless guard=False (injection_guard.py) ──


@dataclass(frozen=True)
class InjectionDetected:
    """A tool's output looks like a prompt injection; the turn is now tainted.

    Yielded right after that ToolResult when ``activity`` is on. ``rules`` names the
    heuristics that matched; ``excerpt`` is a short slice of the flagged text.
    ``details_url`` opens this stop in the gateway's security log ("" when not logged).
    """

    call_id: str
    tool_name: str
    rules: tuple[str, ...]
    excerpt: str
    details_url: str = ""


@dataclass(frozen=True)
class ActionBlocked:
    """The guard denied a tool approval on a tainted turn; the host never has to answer it.

    Yielded in place of the ApprovalRequest. ``reason`` is what the model was told.
    ``details_url`` opens this stop in the gateway's security log ("" when not logged).
    """

    request_id: str
    call_id: str
    name: str
    arguments: Any
    reason: str
    details_url: str = ""


StreamEvent = (
    TextDelta | SessionUpdate | StreamError | Completed | ThinkingDelta | ToolCall | ToolResult
    | ApprovalRequest | InputAccepted | ModeChanged | InjectionDetected | ActionBlocked
)
