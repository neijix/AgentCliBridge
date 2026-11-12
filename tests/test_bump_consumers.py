"""scripts/bump_consumers.py: which apps pin the bridge, and what each run does to them."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "bump_consumers.py"
_spec = importlib.util.spec_from_file_location("bump_consumers", SCRIPT)
assert _spec and _spec.loader
bump_consumers = importlib.util.module_from_spec(_spec)
sys.modules["bump_consumers"] = bump_consumers
_spec.loader.exec_module(bump_consumers)

OLD = "43cf0988e23fc4f81dcc2ce469e0793b74ff794c"
NEW = "669ec6f1037529342dd11a8f841e780aad049ce9"
SOURCE = '[tool.uv.sources]\nAgentCliBridge = { git = "https://github.com/neijix/AgentCliBridge.git", branch = "main" }\n'


def lock(commit: str) -> str:
    return (
        '[[package]]\nname = "agentclibridge"\nversion = "0.3.0"\n'
        f'source = {{ git = "https://github.com/neijix/AgentCliBridge.git?branch=main#{commit}" }}\n'
    )


def make_app(root: Path, name: str, pyproject: str = SOURCE, commit: str = OLD) -> Path:
    app = root / name
    app.mkdir()
    (app / ".git").mkdir()
    (app / "pyproject.toml").write_text(pyproject, encoding="utf-8")
    (app / "uv.lock").write_text(lock(commit), encoding="utf-8")
    return app


def test_locked_commit_reads_the_pin() -> None:
    assert bump_consumers.locked_commit(lock(NEW)) == NEW
    assert bump_consumers.locked_commit('[[package]]\nname = "httpx"\n') is None


def test_declares_bridge_needs_the_git_source() -> None:
    assert bump_consumers.declares_bridge(SOURCE)
    assert not bump_consumers.declares_bridge('dependencies = ["AgentCliBridge"]\n')


def test_find_consumers_lists_the_pinning_checkouts_but_not_the_bridge(tmp_path: Path) -> None:
    bridge = make_app(tmp_path, "AgentCliBridge")
    mate = make_app(tmp_path, "D3SKMATE")
    hand = make_app(tmp_path, "d3skhand")
    make_app(tmp_path, "Other", pyproject='[project]\nname = "other"\n')
    (tmp_path / "loose-file.txt").write_text("", encoding="utf-8")

    assert bump_consumers.find_consumers(tmp_path, bridge) == [hand, mate]


def test_commit_message_names_the_pin_and_the_changes() -> None:
    message = bump_consumers.commit_message(OLD, NEW, ["669ec6f refactor(colibri): x", "ec23f46 fix(runner): y"])
    subject, _, body = message.partition("\n\n")
    assert subject == "chore(deps): run AgentCliBridge 669ec6f, its latest main"
    assert "since 43cf098" in body
    assert "- ec23f46 fix(runner): y" in body


def git_app(tmp_path: Path, commit: str) -> Path:
    app = tmp_path / "App"
    app.mkdir()
    (app / "pyproject.toml").write_text(SOURCE, encoding="utf-8")
    (app / "uv.lock").write_text(lock(commit), encoding="utf-8")
    for argv in (["init", "--quiet"], ["add", "."], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "--quiet", "-m", "init"]):
        subprocess.run(["git", *argv], cwd=app, check=True, capture_output=True)
    return app


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


@needs_git
def test_bump_leaves_an_app_with_local_changes_alone(tmp_path: Path) -> None:
    app = git_app(tmp_path, OLD)
    (app / "pyproject.toml").write_text(SOURCE + "# edited\n", encoding="utf-8")

    outcome = bump_consumers.bump(app, NEW, "uv-is-never-run")

    assert outcome.status == "skipped"
    assert "local changes" in outcome.detail
    assert bump_consumers.locked_commit((app / "uv.lock").read_text(encoding="utf-8")) == OLD


@needs_git
@pytest.mark.parametrize(("pinned", "status"), [(NEW, "up-to-date"), (OLD, "would-bump")])
def test_dry_run_says_which_apps_are_behind(tmp_path: Path, pinned: str, status: str) -> None:
    app = git_app(tmp_path, pinned)

    outcome = bump_consumers.bump(app, NEW, "uv-is-never-run", dry_run=True)

    assert outcome.status == status
    assert bump_consumers.locked_commit((app / "uv.lock").read_text(encoding="utf-8")) == pinned


def test_one_app_that_raises_does_not_stop_the_others(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    for name in ("Alpha", "Bravo", "Charlie"):
        make_app(tmp_path, name)
    seen: list[str] = []

    def fake_bump(repo: Path, target: str, uv: str, **options: bool) -> object:
        seen.append(repo.name)
        if repo.name == "Bravo":
            raise subprocess.TimeoutExpired(["git", "pull"], 120)
        return bump_consumers.Outcome(repo.name, "bumped", "ok")

    monkeypatch.setattr(bump_consumers, "bump", fake_bump)
    monkeypatch.setattr(bump_consumers, "bridge_target", lambda: (NEW, ""))
    monkeypatch.setattr(bump_consumers.shutil, "which", lambda name: "/usr/bin/uv")
    monkeypatch.setattr(bump_consumers, "_abort_rebase", lambda repo: seen.append(f"abort:{repo.name}"))

    assert bump_consumers.main(["--root", str(tmp_path), "--no-test"]) == 1
    assert seen == ["Alpha", "Bravo", "abort:Bravo", "Charlie"]
    out = capsys.readouterr().out
    assert "Bravo: failed — TimeoutExpired" in out
    assert "Charlie: bumped" in out
    assert "summary: 2 bumped, 1 failed — Bravo: TimeoutExpired" in out


def test_summary_counts_each_status_and_names_the_problems() -> None:
    outcomes = [
        bump_consumers.Outcome("A", "bumped", "x"),
        bump_consumers.Outcome("B", "skipped", "local changes"),
        bump_consumers.Outcome("C", "up-to-date"),
    ]
    assert bump_consumers.summary(outcomes) == "1 bumped, 1 skipped, 1 up-to-date — B: local changes"
    assert bump_consumers.summary([]) == ""


@pytest.fixture(autouse=True)
def _git_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # bump() commits as the user; a fresh CI runner has no git identity.
    for key in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(key, "t")
    for key in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(key, "t@t")


def _git_in(cwd: Path, *argv: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *argv], cwd=cwd, check=True, capture_output=True, text=True
    )
    return done.stdout


@needs_git
def test_a_conflicting_rebase_is_aborted_and_the_app_left_as_it_was(tmp_path: Path) -> None:
    origin = tmp_path / "origin.git"
    _git_in(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(origin))
    app = tmp_path / "App"
    _git_in(tmp_path, "clone", "--quiet", str(origin), str(app))
    (app / "pyproject.toml").write_text(SOURCE, encoding="utf-8")
    (app / "uv.lock").write_text(lock(OLD), encoding="utf-8")
    _git_in(app, "add", ".")
    _git_in(app, "commit", "--quiet", "-m", "init")
    _git_in(app, "push", "--quiet", "-u", "origin", "HEAD:main")
    rival = tmp_path / "Rival"
    _git_in(tmp_path, "clone", "--quiet", str(origin), str(rival))
    # A fake `uv lock`: while the app is relocking, someone else pushes another change to uv.lock.
    uv = tmp_path / "uv"
    uv.write_text(
        "#!/bin/sh\n"
        f'cd "{rival}" && echo "# someone else" >> uv.lock && git -c user.name=t -c user.email=t@t commit -qam rival '
        "&& git push -q origin HEAD:main\n"
        f'cd "{app}" && printf \'%s\\n\' \'[[package]]\' \'source = {{ git = "https://github.com/neijix/AgentCliBridge.git?branch=main#{NEW}" }}\' > uv.lock\n'
    )
    uv.chmod(0o755)

    outcome = bump_consumers.bump(app, NEW, str(uv), test=False)

    assert outcome.status == "failed" and "push failed" in outcome.detail
    assert not (app / ".git" / "rebase-merge").exists() and not (app / ".git" / "rebase-apply").exists()
    assert _git_in(app, "status", "--porcelain", "--untracked-files=no") == ""
    assert _git_in(app, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
