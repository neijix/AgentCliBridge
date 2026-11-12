"""Record one live CLI turn as a stream fixture for tests/test_stream_contracts.py.

    python tests/streams/capture.py <command> <scenario> "<prompt>" [--model M] [--mode plan]

Runs the installed CLI with the bridge's own headless argv (plan mode by default, so a capture
never edits anything) in a scratch folder, and writes its raw stdout to
``tests/streams/<command>__<scenario>.jsonl``: init events cut to their ids and versions, account
and usage fields dropped, the home folder and user name redacted.

Before committing, read the file and remove anything private the trimming missed. Then write its expected events
with ``ACB_UPDATE_STREAMS=1 python -m pytest tests/test_stream_contracts.py`` and review them.
"""
import argparse
import getpass
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from agent_cli_bridge.argv import build_argv
from agent_cli_bridge.processes import background_process_options
from agent_cli_bridge.specs import flavor_for, resolve_binary

STREAMS = Path(__file__).parent


# An init event lists the machine's tools, skills, plugins, MCP servers and paths: only these stay.
INIT_KEYS = {"type", "subtype", "event", "session_id", "conversation_id", "model", "claude_code_version",
             "permissionMode"}
# Account, billing and bulky fields no parser reads, dropped at any depth.
DROPPED_KEYS = {"uuid", "usage", "modelUsage", "rate_limit_info", "total_cost_usd", "permission_denials",
                "subagent_stats", "signature", "request_id", "api_message_id"}


def trim(value):
    if isinstance(value, list):
        return [trim(item) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("subtype") == "init" or value.get("event") == "init":
        value = {key: item for key, item in value.items() if key in INIT_KEYS}
    return {key: trim(item) for key, item in value.items() if key not in DROPPED_KEYS}


def trim_lines(text: str) -> str:
    """Each JSON line through ``trim``; any other line (a CLI's plain-text notice) unchanged."""
    lines = []
    for line in text.splitlines():
        try:
            lines.append(json.dumps(trim(json.loads(line)), ensure_ascii=False))
        except ValueError:
            lines.append(line)
    return "".join(line + "\n" for line in lines)


def redact(text: str) -> str:
    home = str(Path.home())
    for private, placeholder in ((home, "~"), (home.replace("\\", "\\\\"), "~"), (getpass.getuser(), "user")):
        text = text.replace(private, placeholder)
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", help='spec command or alias: "claude", "agent", "agy", …')
    parser.add_argument("scenario", help="short snake_case name: what the turn shows")
    parser.add_argument("prompt")
    parser.add_argument("--model")
    parser.add_argument("--mode", default="plan", help="permission mode (default: plan)")
    args = parser.parse_args()

    binary = resolve_binary(args.command)
    if binary is None:
        print(f"{args.command} is not installed", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="acb-capture-") as cwd:
        argv = build_argv(binary=binary, flavor=flavor_for(args.command), prompt=args.prompt,
                          model=args.model, permission_mode=args.mode, cwd=cwd)
        done = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=600, **background_process_options())
    target = STREAMS / f"{args.command}__{args.scenario}.jsonl"
    target.write_text(redact(trim_lines(done.stdout.decode("utf-8", "replace"))), encoding="utf-8")
    print(f"wrote {target} (exit {done.returncode}, {len(done.stdout)} bytes)")
    if done.stderr:
        print(redact(done.stderr.decode("utf-8", "replace"))[-2000:], file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
