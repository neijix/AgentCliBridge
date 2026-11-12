"""The terminal setup wizard: ``python -m bridge_installer`` (setup.sh / setup.ps1 run it).

Questions, each with a flag for a run without prompts (``--yes``, or no terminal):
the install folder (``--dir``, no default), the settings folder (``--settings-dir``, default
``<install>/config``), the gateway port (``--port``, default 4747), and the start at login
(``--autostart`` / ``--no-autostart``, default off). AgentCliBridge needs no sibling repo.
``--uninstall`` removes an install, ``--update`` installs the latest GitHub Release over it.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from bridge_installer import DEFAULT_PORT, DISPLAY_NAME
from bridge_installer.apply import install
from bridge_installer.layout import (
    Answers,
    Layout,
    SetupError,
    answers_from_record,
    check_path,
    check_port,
    read_record,
)
from bridge_installer.system import autostart_target
from bridge_installer.uninstall import uninstall, verified_answers
from bridge_installer.update import update

Ask = Callable[[str], str]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="setup", description=f"Install, update or remove {DISPLAY_NAME} (the gateway and its shims).",
    )
    parser.add_argument("--dir", type=Path, help="install folder (asked when missing; no default)")
    parser.add_argument("--settings-dir", type=Path, help="settings folder (default: <install folder>/config)")
    parser.add_argument("--port", help=f"gateway port on 127.0.0.1 (default: {DEFAULT_PORT})")
    start_login = parser.add_mutually_exclusive_group()
    start_login.add_argument("--autostart", dest="autostart", action="store_true", default=None,
                             help="start the gateway at login (writes one entry outside the install folder)")
    start_login.add_argument("--no-autostart", dest="autostart", action="store_false")
    start_now = parser.add_mutually_exclusive_group()
    start_now.add_argument("--start", dest="should_start", action="store_true", default=True,
                           help="start the gateway when the setup ends (default)")
    start_now.add_argument("--no-start", dest="should_start", action="store_false")
    parser.add_argument("-y", "--yes", action="store_true", help="take every default; ask nothing")
    parser.add_argument("--uv", type=Path, help="the uv to build the venv with (default: the setup's)")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--uninstall", action="store_true", help="remove the install in --dir")
    action.add_argument("--update", action="store_true", help="install the latest GitHub Release over --dir")
    parser.add_argument("--remove-settings", action="store_true", help="with --uninstall: delete the settings folder too")
    parser.add_argument("--check", action="store_true", help="with --update: only say whether a release is newer")
    return parser


def _ask_text(ask: Ask, question: str, default: str | None) -> str:
    suffix = f" [{default}]" if default else " (no default)"
    answer = ask(f"{question}{suffix}: ").strip()
    if not answer and default is None:
        raise SetupError(f"no answer to: {question}")
    return answer or (default or "")


def _ask_yes_no(ask: Ask, question: str, default: bool) -> bool:
    answer = ask(f"{question} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not answer else answer in ("y", "yes", "o", "oui")


def resolve_answers(args: argparse.Namespace, *, ask: Ask | None) -> Answers:
    """The four answers: flags first, then the previous install's, then a prompt or the default."""
    if args.dir is None:
        if ask is None:
            raise SetupError("the install folder is required: --dir <folder>")
        args.dir = Path(_ask_text(ask, "Install folder", None))
    root = check_path(args.dir, "install folder")
    record = read_record(Layout(root))
    previous = answers_from_record(Layout(root), record) if record else None
    settings_default = previous.settings_dir if previous else Layout(root).default_settings
    port_default = previous.port if previous else DEFAULT_PORT
    autostart_default = previous.autostart if previous else False

    settings = args.settings_dir
    if settings is None:
        settings = Path(_ask_text(ask, "Settings folder", str(settings_default))) if ask else settings_default
    port = args.port
    if port is None:
        port = _ask_text(ask, "Gateway port on 127.0.0.1", str(port_default)) if ask else port_default
    autostart = args.autostart
    if autostart is None:
        if ask:
            print(f"Start at login writes {autostart_target(Layout(root))}; nothing else leaves the install folder.")
            autostart = _ask_yes_no(ask, "Start the gateway at login?", autostart_default)
        else:
            autostart = autostart_default
    return Answers(root=root, settings_dir=check_path(settings, "settings folder"), port=check_port(port), autostart=autostart)


def _confirm_uninstall(args: argparse.Namespace, layout: Layout, ask: Ask | None) -> bool:
    answers = verified_answers(layout)
    if args.yes:
        return True
    if ask is None:
        raise SetupError("--uninstall without a terminal needs --yes")
    if not _ask_yes_no(ask, f"Remove {DISPLAY_NAME} from {layout.root}?", False):
        return False
    if not args.remove_settings:
        args.remove_settings = _ask_yes_no(ask, f"Also delete the settings folder {answers.settings_dir}?", False)
    return True


def run(args: argparse.Namespace, *, ask: Ask | None) -> int:
    if args.uninstall or args.update:
        if args.dir is None:
            raise SetupError("--uninstall and --update need --dir <install folder>")
        layout = Layout(check_path(args.dir, "install folder"))
        if args.uninstall:
            if not _confirm_uninstall(args, layout, ask):
                print("Nothing removed.")
                return 0
            return uninstall(layout, remove_settings=args.remove_settings)
        return update(layout, check_only=args.check, uv=args.uv)
    answers = resolve_answers(args, ask=ask)
    return install(answers, uv=args.uv, should_start=args.should_start)


def main(argv: list[str] | None = None, *, ask: Ask | None = None, is_tty: bool | None = None) -> int:
    args = build_parser().parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)  # our lines stay in order with uv's and the scripts'
    interactive = (sys.stdin.isatty() if is_tty is None else is_tty) and not args.yes
    prompt = (ask or input) if interactive else None
    try:
        return run(args, ask=prompt)
    except SetupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (KeyboardInterrupt, EOFError):
        print("\nStopped; run the setup again to finish.", file=sys.stderr)
        return 130
