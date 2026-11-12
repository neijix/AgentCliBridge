"""Ship AgentCliBridge's pushed ``main`` to every app built on it.

Each app pins one AgentCliBridge commit in its own ``uv.lock`` (KNOWLEDGE.md, "One copy only"), so
a fix pushed here reaches nobody until that app relocks — and an app nobody relocks keeps running
an old bridge. This finds the sibling checkouts whose ``pyproject.toml`` declares the AgentCliBridge
git source and, for each one behind ``origin/main``: pull, relock, run its tests in a throwaway
environment (the app's own ``.venv`` may be serving), commit and push. The app's own updater then
installs the new pin on every machine.

    python scripts/bump_consumers.py [--dry-run] [--no-test] [--no-push] [--root DIR]

Stdlib only. An app with local changes, on another branch than its default, or whose pull or
tests fail is left exactly as it was and reported; the others still ship. Exit 1 when any failed.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

PACKAGE = "AgentCliBridge"
BRIDGE_REPO = Path(__file__).resolve().parents[1]
# uv.lock: source = { git = "https://github.com/neijix/AgentCliBridge.git?branch=main#<sha>" }
_PIN = re.compile(r"AgentCliBridge(?:\.git)?\?[^#\"]*#([0-9a-f]{40})")
# pyproject.toml, [tool.uv.sources]: AgentCliBridge = { git = "…" }
_SOURCE = re.compile(r"^\s*AgentCliBridge\s*=\s*\{[^}\n]*\bgit\s*=", re.MULTILINE)
GIT_TIMEOUT = 120.0
TEST_TIMEOUT = 1800.0
# git must never wait on a credential prompt nobody sees.
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "never"}


@dataclass
class Outcome:
    app: str
    status: str  # bumped | up-to-date | would-bump | skipped | failed
    detail: str = ""


def locked_commit(lock_text: str) -> str | None:
    """The AgentCliBridge commit a ``uv.lock`` pins, or None when it pins none."""
    match = _PIN.search(lock_text)
    return match.group(1) if match else None


def declares_bridge(pyproject_text: str) -> bool:
    """Does this ``pyproject.toml`` take AgentCliBridge from git (a uv source)?"""
    return bool(_SOURCE.search(pyproject_text))


def find_consumers(root: Path, bridge: Path = BRIDGE_REPO) -> list[Path]:
    """The checkouts under ``root`` that pin AgentCliBridge in a ``uv.lock``, by name."""
    found: list[Path] = []
    for folder in sorted(root.iterdir(), key=lambda p: p.name.lower()):
        if not folder.is_dir() or folder.resolve() == bridge.resolve():
            continue
        pyproject, lock = folder / "pyproject.toml", folder / "uv.lock"
        if not (pyproject.is_file() and lock.is_file() and (folder / ".git").exists()):
            continue
        try:
            if declares_bridge(pyproject.read_text(encoding="utf-8")):
                found.append(folder)
        except OSError:
            continue
    return found


def commit_message(old: str | None, new: str, changes: list[str]) -> str:
    """The consumer's commit: which bridge commit it now runs, and what that brings."""
    subject = f"chore(deps): run AgentCliBridge {new[:7]}, its latest main"
    since = f"since {old[:7]}" if old else "since the previous pin"
    body = "\n".join(f"- {line}" for line in changes) or "- (no commit list: the old pin is unknown here)"
    return f"{subject}\n\nAgentCliBridge changes {since}:\n{body}\n\nShipped by AgentCliBridge scripts/bump_consumers.py.\n"


def _run(argv: list[str], cwd: Path, *, env: dict[str, str] | None = None, timeout: float = GIT_TIMEOUT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=str(cwd),
        env=env or _GIT_ENV,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return _run([shutil.which("git") or "git", *args], repo)  # the full path, as for uv


def _out(repo: Path, *args: str) -> str:
    result = _git(repo, *args)
    return result.stdout.strip() if result.returncode == 0 else ""


def _tail(result: subprocess.CompletedProcess[str], lines: int = 1) -> str:
    text = (result.stderr.strip() or result.stdout.strip()).splitlines()
    return " | ".join(text[-lines:]) if text else f"exit {result.returncode}"


def bridge_target(bridge: Path = BRIDGE_REPO) -> tuple[str, str]:
    """``(commit, warning)``: what ``origin/main`` holds after a fetch — only pushed work ships."""
    fetch = _git(bridge, "fetch", "--quiet", "origin")
    if fetch.returncode != 0:
        raise SystemExit(f"cannot fetch AgentCliBridge's origin: {_tail(fetch)}")
    target = _out(bridge, "rev-parse", "origin/main")
    if not target:
        raise SystemExit("AgentCliBridge has no origin/main")
    unpushed = _out(bridge, "rev-list", "--count", "origin/main..HEAD")
    warning = f"{unpushed} local AgentCliBridge commit(s) are not pushed and do not ship" if unpushed not in ("", "0") else ""
    return target, warning


def bridge_changes(old: str | None, new: str, bridge: Path = BRIDGE_REPO) -> list[str]:
    """``<sha> <subject>`` of each AgentCliBridge commit from ``old`` to ``new``, newest first."""
    if not old:
        return []
    return _out(bridge, "log", "--no-merges", "--format=%h %s", f"{old}..{new}").splitlines()


def _default_branch(repo: Path) -> str:
    head = _out(repo, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")  # origin/main
    return head.split("/", 1)[1] if "/" in head else _out(repo, "rev-parse", "--abbrev-ref", "HEAD")


def run_tests(repo: Path, uv: str) -> str | None:
    """The app's pytest suite on the new lock, in a throwaway venv; why it failed, or None."""
    if not (repo / "tests").is_dir():
        return None
    venv = Path(tempfile.mkdtemp(prefix=f"bump-{repo.name.lower()}-"))
    env = {**_GIT_ENV, "UV_PROJECT_ENVIRONMENT": str(venv)}
    env.pop("VIRTUAL_ENV", None)
    try:
        sync = _run([uv, "sync", "--locked", "--all-extras", "--all-groups", "--quiet"], repo, env=env, timeout=TEST_TIMEOUT)
        if sync.returncode != 0:
            return f"uv sync failed: {_tail(sync)}"
        test = _run([uv, "run", "--no-sync", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider"], repo, env=env, timeout=TEST_TIMEOUT)
        return None if test.returncode == 0 else f"tests failed: {_tail(test, 3)}"
    except subprocess.TimeoutExpired:
        return "tests timed out"
    finally:
        shutil.rmtree(venv, ignore_errors=True)


def bump(repo: Path, target: str, uv: str, *, test: bool = True, push: bool = True, dry_run: bool = False) -> Outcome:
    """Bring one app to ``target``; anything unexpected leaves it as it was."""
    name = repo.name
    if _out(repo, "status", "--porcelain", "--untracked-files=no"):
        return Outcome(name, "skipped", "local changes — commit or stash them, then run this again")
    branch, default = _out(repo, "rev-parse", "--abbrev-ref", "HEAD"), _default_branch(repo)
    if branch != default:
        return Outcome(name, "skipped", f"on {branch}, not {default}")
    if not dry_run:
        pull = _git(repo, "pull", "--ff-only", "--quiet")
        if pull.returncode != 0:
            return Outcome(name, "skipped", f"git pull --ff-only failed: {_tail(pull)}")
    lock = repo / "uv.lock"
    old = locked_commit(lock.read_text(encoding="utf-8"))
    if old == target:
        return Outcome(name, "up-to-date", target[:7])
    if dry_run:
        return Outcome(name, "would-bump", f"{(old or '?')[:7]} → {target[:7]}")

    relock = _run([uv, "lock", "--upgrade-package", PACKAGE], repo, timeout=TEST_TIMEOUT)
    new = locked_commit(lock.read_text(encoding="utf-8"))
    if relock.returncode != 0 or new != target:
        _git(repo, "checkout", "--", "uv.lock")
        why = _tail(relock) if relock.returncode != 0 else f"uv locked {(new or '?')[:7]}, origin/main is {target[:7]}"
        return Outcome(name, "failed", f"relock: {why}")
    if test and (failure := run_tests(repo, uv)):
        _git(repo, "checkout", "--", "uv.lock")
        return Outcome(name, "failed", failure)

    _git(repo, "add", "uv.lock")
    committed = _git(repo, "commit", "--quiet", "-m", commit_message(old, target, bridge_changes(old, target)))
    if committed.returncode != 0:
        return Outcome(name, "failed", f"commit: {_tail(committed)}")
    if not push:
        return Outcome(name, "bumped", f"{(old or '?')[:7]} → {target[:7]}, committed, not pushed")
    pushed = _git(repo, "pull", "--rebase", "--quiet")
    if pushed.returncode == 0:
        pushed = _git(repo, "push", "--quiet")
    else:
        _abort_rebase(repo)  # a conflicted rebase must not be left half-done in the app
    if pushed.returncode != 0:
        return Outcome(name, "failed", f"committed, push failed: {_tail(pushed)}")
    return Outcome(name, "bumped", f"{(old or '?')[:7]} → {target[:7]}, pushed")


def _abort_rebase(repo: Path) -> None:
    """Leave no rebase in progress in ``repo``; harmless (and silent) when there is none."""
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        _git(repo, "rebase", "--abort")


def bump_safely(repo: Path, target: str, uv: str, **options: bool) -> Outcome:
    """``bump``, but whatever it raises (a git timeout, an unreadable lock) is that app's failure.

    The rebase of a ``pull --rebase`` that died mid-way is aborted, so the app is left as it was.
    """
    try:
        return bump(repo, target, uv, **options)
    except Exception as exc:  # noqa: BLE001 — one app's crash must not stop the others
        _abort_rebase(repo)
        return Outcome(repo.name, "failed", f"{type(exc).__name__}: {exc}"[:300])


def summary(outcomes: list[Outcome]) -> str:
    """One line: how many apps ended in each status, then each failure or skip with its reason."""
    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    line = ", ".join(f"{count} {status}" for status, count in counts.items())
    problems = [f"{o.app}: {o.detail}" for o in outcomes if o.status in ("failed", "skipped")]
    return line + (" — " + "; ".join(problems) if problems else "")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Relock every app built on AgentCliBridge to its pushed main.")
    parser.add_argument("--root", type=Path, default=BRIDGE_REPO.parent, help="folder holding the app checkouts (default: AgentCliBridge's parent)")
    parser.add_argument("--dry-run", action="store_true", help="only say which apps are behind")
    parser.add_argument("--no-test", action="store_true", help="skip each app's pytest run")
    parser.add_argument("--no-push", action="store_true", help="commit, but leave the push to you")
    args = parser.parse_args(argv)

    uv = shutil.which("uv")
    if not uv:
        print("uv is not on PATH", file=sys.stderr)
        return 1
    target, warning = bridge_target()
    if warning:
        print(f"warning: {warning}")
    consumers = find_consumers(args.root)
    if not consumers:
        print(f"no app under {args.root} pins {PACKAGE}")
        return 0
    print(f"{PACKAGE} origin/main = {target[:7]}; apps: {', '.join(p.name for p in consumers)}")
    outcomes = []
    for repo in consumers:
        outcome = bump_safely(repo, target, uv, test=not args.no_test, push=not args.no_push, dry_run=args.dry_run)
        print(f"  {outcome.app}: {outcome.status}" + (f" — {outcome.detail}" if outcome.detail else ""), flush=True)
        outcomes.append(outcome)
    print(f"summary: {summary(outcomes)}")
    return 1 if any(o.status in ("failed", "skipped") for o in outcomes) else 0


if __name__ == "__main__":
    sys.exit(main())
