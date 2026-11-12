"""A composer's Effort and Ultracode choices, turned into the CLI's own flags.

Only the CLIs that take them (verified live with `--help` and a run): Claude Code's ``--effort``
and its ``ultracode`` session setting (``--settings '{"ultracode": true}'``), and Copilot CLI's
``--reasoning-effort``. Every other CLI gets nothing and runs at its own default, so a stale or
foreign value can never break a turn — and only a known level ever reaches argv.

Claude models differ: the level runs as the composer shows it (``effortProfile`` /
``clampEffort`` / ``canUltracode`` in ``ui/models.js``, whose table this one mirrors — a test
keeps the two equal). A model older than effort gets neither flag; a level it lacks runs as the
strongest one below it.
"""

import json
import re

# Every level a page may send; "auto" (or anything unknown) passes no flag.
EFFORTS = ("auto", "low", "medium", "high", "xhigh", "max")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
# The levels every Copilot model takes; the higher ones exist only on some of them.
COPILOT_EFFORTS = ("low", "medium", "high")
ULTRACODE_SETTINGS = json.dumps({"ultracode": True}, separators=(",", ":"))

# Claude Code's own model table (claude 2.1.296). The only map for these four names.
# model_ranking imports it. ui/models.js keeps the same four pairs; a test fails if they differ.
CLAUDE_EFFORT_ALIASES = {
    "opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5", "haiku": "claude-haiku-5-5", "fable": "claude-fable-5-1",
}
CLAUDE_NO_EFFORT = re.compile(r"^claude-(3-|haiku-4|sonnet-4(-[05])?$|opus-4(-[01])?$|mythos-5$)")
CLAUDE_EFFORT_CAPS = {
    "claude-opus-4-5": ("low", "medium", "high"),
    "claude-opus-4-6": ("low", "medium", "high", "max"),
    "claude-sonnet-4-6": ("low", "medium", "high", "max"),
}


def claude_model_key(model: object) -> str:
    """The table's id for a Claude model: lower case, without 1M tag, provider prefix, version or date."""
    text = str(model or "").strip().lower().removesuffix("[1m]")
    text = text.rsplit("/", 1)[-1]
    text = re.sub(r"^(?:[a-z]+\.)?anthropic\.", "", text)
    text = re.sub(r"-v\d+(?::\d+)?$", "", text)
    text = re.sub(r"[-@]\d{8}$", "", text)
    return CLAUDE_EFFORT_ALIASES.get(text, text)


def claude_effort_levels(model: object) -> tuple[str, ...] | None:
    """The levels this Claude model takes, or None when it takes no effort at all."""
    key = claude_model_key(model)
    if CLAUDE_NO_EFFORT.match(key):
        return None
    return CLAUDE_EFFORT_CAPS.get(key, CLAUDE_EFFORTS)


def clamp_effort(levels: tuple[str, ...], effort: str) -> str:
    """``effort`` when the model takes it, else the strongest level it takes below it."""
    if effort in levels:
        return effort
    rank = CLAUDE_EFFORTS.index(effort)
    below = [level for level in levels if CLAUDE_EFFORTS.index(level) <= rank]
    return below[-1] if below else levels[0]


def effort_args(flavor: str, effort: object = None, ultracode: object = False, model: object = None) -> list[str]:
    """The extra argv for this turn's effort and Ultracode on a CLI of ``flavor``, for ``model``."""
    args: list[str] = []
    if flavor == "claude":
        levels = claude_effort_levels(model)
        if levels is None:
            return args
        if effort in CLAUDE_EFFORTS:
            args += ["--effort", clamp_effort(levels, str(effort))]
        if ultracode is True and "haiku" not in claude_model_key(model):
            args += ["--settings", ULTRACODE_SETTINGS]
    elif flavor == "copilot" and effort in COPILOT_EFFORTS:
        args += ["--reasoning-effort", str(effort)]
    return args
