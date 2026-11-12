"""Talking to a running turn: tool approvals and messages added while it works.

Claude Code only (``supports_live_input``). Given a ``TurnInput``, the runner starts
Claude Code with ``--input-format stream-json --permission-prompt-tool stdio
--replay-user-messages`` and writes the prompt to stdin instead of argv. The CLI then
(verified live against Claude Code 2.1.212, 2026-09-14):

- asks before a gated tool with ``{"type": "control_request", "request_id", "request":
  {"subtype": "can_use_tool", "tool_name", "input", "tool_use_id", "description", …}}``
  and waits for ``{"type": "control_response", "response": {"subtype": "success",
  "request_id", "response": {"behavior": "allow", "updatedInput": <input>}}}`` or
  ``{"behavior": "deny", "message": …}`` (the message is what the model reads);
- takes a user message written to stdin at its next step — after the running tools,
  before the next model call — and echoes it with ``"isReplay": true`` at that point
  (the prompt itself is echoed first);
- switches its permission mode mid-turn on ``{"type": "control_request", "request_id",
  "request": {"subtype": "set_permission_mode", "mode"}}`` and answers with a
  ``control_response`` (``success``, or ``error`` — e.g. ``bypassPermissions`` in a
  session not launched with ``--allow-dangerously-skip-permissions``); verified live
  against Claude Code 2.1.293, 2026-10-07;
- ends each turn with one ``result`` and exits once stdin is closed.
"""
from collections.abc import Callable
from typing import Any

from .argv import PERMISSION_MODES

LIVE_INPUT_FLAVORS = frozenset({"claude"})
DENIED_MESSAGE = "The user denied this tool call."

Write = Callable[[dict[str, Any]], bool]


def supports_live_input(flavor: str) -> bool:
    """Whether a flavor's CLI can take approvals and extra messages mid-turn."""
    return flavor in LIVE_INPUT_FLAVORS


def user_message(text: str) -> dict[str, Any]:
    return {
        "type": "user",
        "session_id": "",
        "parent_tool_use_id": None,
        "message": {"role": "user", "content": text},
    }


class TurnInput:
    """Answer a running turn's tool approvals and add messages to it.

    Create one per turn, pass it as ``run_agent(..., turn_input=…)``, and call ``say`` /
    ``answer`` from any task on the same event loop. ``say`` only hands a message over:
    the runner yields ``InputAccepted`` once the CLI actually took it. Both return False
    when the turn cannot take the input (another flavor, the turn ended, an approval that
    is unknown or already answered).
    """

    def __init__(self) -> None:
        self._write: Write | None = None
        self._backlog: list[str] = []  # said before the CLI was started
        self._is_closed = False
        self._untaken = 0  # written to the CLI, not echoed back yet
        self._approvals: dict[str, Any] = {}  # request id → the tool input it asks about
        self._early_mode: str | None = None  # asked for before the CLI was started
        self._mode_requests: dict[str, str] = {}  # our control request id → the mode asked for
        self._mode_count = 0

    @property
    def is_open(self) -> bool:
        return not self._is_closed

    def say(self, text: str) -> bool:
        if self._is_closed or not text:
            return False
        if self._write is None:
            self._backlog.append(text)
            return True
        if not self._write(user_message(text)):
            return False
        self._untaken += 1
        return True

    def answer(self, request_id: str, allow: bool, message: str = "") -> bool:
        """Allow or deny one pending tool call.

        An allowed call runs with the input the CLI asked about, never an edited one, and
        no permission rule or mode change is ever sent: an approval covers this call only.
        """
        if self._write is None or request_id not in self._approvals:
            return False
        tool_input = self._approvals.pop(request_id)
        if allow:
            decision: dict[str, Any] = {"behavior": "allow", "updatedInput": tool_input}
        else:
            decision = {"behavior": "deny", "message": message.strip() or DENIED_MESSAGE}
        return self._write({
            "type": "control_response",
            "response": {"subtype": "success", "request_id": request_id, "response": decision},
        })

    def answer_question(
        self, request_id: str, answers: dict[str, Any], response: str = ""
    ) -> bool:
        """Answer one pending AskUserQuestion call with the user's choices.

        Unlike ``answer``, this allows the call with an ``updatedInput`` carrying the chosen
        ``answers`` (each keyed by the question text; a value is one option label, a list of
        labels for a multi-select, or free text) and an optional global ``response``. It only
        substitutes input for AskUserQuestion — a call whose asked input is a ``{"questions":
        [...]}`` object — so a gated file or shell tool can never be run with an edited input
        through this path (its input has no ``questions`` key, and the call is left pending).
        """
        if self._write is None:
            return False
        tool_input = self._approvals.get(request_id)
        if not isinstance(tool_input, dict) or "questions" not in tool_input:
            return False
        self._approvals.pop(request_id, None)
        updated: dict[str, Any] = {"questions": tool_input["questions"]}
        if isinstance(tool_input.get("metadata"), dict):
            updated["metadata"] = tool_input["metadata"]
        chosen = {str(k): v for k, v in (answers or {}).items() if v not in (None, "", [])}
        if chosen:
            updated["answers"] = chosen
        text = (response or "").strip()
        if text:
            updated["response"] = text
        return self._write({
            "type": "control_response",
            "response": {
                "subtype": "success",
                "request_id": request_id,
                "response": {"behavior": "allow", "updatedInput": updated},
            },
        })

    def set_permission_mode(self, mode: str) -> bool:
        """Switch the running turn to another permission mode from its next tool call on.

        Only hands the request over: the runner yields ``ModeChanged`` once the CLI took it
        (or refused it). The host clamps ``mode`` to what it allows before calling this;
        ``bypassPermissions`` also needs the CLI started with
        ``--allow-dangerously-skip-permissions``. False for an unknown mode or a closed turn.
        """
        if self._is_closed or mode not in PERMISSION_MODES:
            return False
        if self._write is None:
            self._early_mode = mode
            return True
        return self._request_mode(self._write, mode)

    # ── runner side ──

    def _request_mode(self, write: Write, mode: str) -> bool:
        self._mode_count += 1
        request_id = f"d3sk-mode-{self._mode_count}"
        if not write({
            "type": "control_request",
            "request_id": request_id,
            "request": {"subtype": "set_permission_mode", "mode": mode},
        }):
            return False
        self._mode_requests[request_id] = mode
        return True

    def _mode_answered(self, request_id: str) -> str | None:
        """The mode one of our set_permission_mode requests asked for (None: not ours)."""
        return self._mode_requests.pop(request_id, None)

    def _bind(self, write: Write) -> None:
        self._write = write
        backlog, self._backlog = self._backlog, []
        for text in backlog:
            if write(user_message(text)):
                self._untaken += 1
        if self._early_mode is not None:
            self._request_mode(write, self._early_mode)
            self._early_mode = None

    def _asked(self, request_id: str, tool_input: Any) -> None:
        self._approvals[request_id] = tool_input

    def _withdrawn(self, request_id: str) -> None:
        self._approvals.pop(request_id, None)

    def _took_message(self) -> None:
        self._untaken = max(0, self._untaken - 1)

    def _turn_ended(self) -> bool:
        """A ``result`` arrived: True (and no more input) unless a message is still on its way."""
        if self._untaken:
            return False
        self._close()
        return True

    def _close(self) -> None:
        self._is_closed = True
        self._approvals.clear()
        self._backlog.clear()
        self._early_mode = None
        self._mode_requests.clear()
