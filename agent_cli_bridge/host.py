"""This machine's agent CLIs as a host app shows them: each one's models, version, update and sign-in.

``AgentHost`` puts together what the rest of the package does piece by piece — ``available_agents``
(which CLIs), ``ModelCatalog`` (what each one offers now), ``CliStatus`` (installed vs newest),
``update_plan`` / ``run_update`` (upgrade it), ``install_plan`` (add a missing one), ``uninstall_plan`` (remove it), ``CliLogins`` (browser sign-in) and
``claude_account`` / ``claude_gateway`` (personal or company Claude, and that company gateway's
models) — so every app built on AgentCliBridge lists,
ranks, updates and signs in the same CLIs the same way (a model picker, Settings › Agents and
Settings › Models).

Every method blocks (a CLI run, a registry fetch): an async host calls them in a worker thread.
A ``command`` from a request only ever selects a CLI that discovery found; the binary and every
argv come from here, never from the request.
"""

import logging
import os
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .claude_account import claude_account, claude_gateway
from .cli_login import CliLogins
from .cli_status import (
    CliStatus,
    catch_up_claude_cask,
    clear_macos_quarantine,
    install_plan,
    is_claude_latest_cask_binary,
    remove_native_install,
    run_update,
    uninstall_plan,
    update_plan,
)
from .model_catalog import ModelCatalog
from .specs import (
    CLI_AGENT_SPECS,
    disabled_agents,
    discover_agents,
    enable_agents,
    is_available,
    is_cursor_grok_collision,
    resolve_binary,
)

log = logging.getLogger(__name__)

KNOWN_MODELS_FILE = "models-known.json"


def default_known_models() -> Path:
    """Where a host keeps the first read of each long model catalog unless it picks its own file."""
    return Path.home() / ".agent-cli-bridge" / KNOWN_MODELS_FILE


def collision_refusal(agent: dict[str, Any]) -> str:
    """Why Cursor's ``agent`` name resolving to Grok CLI's binary is never run, updated or signed in."""
    name = str(agent.get("name") or "Cursor Agent")
    path = str(agent.get("path") or "(unknown path)")
    return (
        f"{name} on this machine resolves to {path} — that is Grok CLI's own binary, not Cursor's. "
        "Refusing to use it as Cursor. Install Cursor Agent separately and correct the PATH collision."
    )


class AgentHost:
    """The agent CLIs of this machine for one host process (one instance per process).

    ``is_busy(command)`` tells whether a reply of that CLI is running in the host: an update is
    refused meanwhile (npm swaps the files under a running CLI). ``home`` / ``env`` are where
    Claude Code's account is read from (default: the user's home and ``os.environ``).
    """

    def __init__(
        self,
        *,
        known_models: Path | None = None,
        agents_provider: Callable[[], list[dict[str, Any]]] = discover_agents,
        home: Path | None = None,
        env: Mapping[str, str] | None = None,
        model_catalog: ModelCatalog | None = None,
        cli_status: CliStatus | None = None,
        cli_logins: CliLogins | None = None,
        update_runner: Callable[[list[str]], tuple[int, str]] = run_update,
        is_busy: Callable[[str], bool] = lambda _command: False,
        disabled_provider: Callable[[], set[str]] = disabled_agents,
        enabler: Callable[[set[str]], None] = enable_agents,
        binary_resolver: Callable[[str], str | None] = resolve_binary,
    ) -> None:
        self._agents_provider = agents_provider
        self._home = home
        self._env = env
        self._models = model_catalog or ModelCatalog(known_models or default_known_models())
        self._status = cli_status or CliStatus()
        self._logins = cli_logins or CliLogins()
        self._run_update = update_runner
        self._is_busy = is_busy
        self._disabled_provider = disabled_provider
        self._enable = enabler
        self._resolve_binary = binary_resolver
        self._refresh_lock = threading.Lock()
        self._refresher_lock = threading.Lock()
        self._refresher: threading.Thread | None = None

    # -- the list ---------------------------------------------------------------------------

    def agents(self) -> list[dict[str, Any]]:
        """The agents this machine offers (``is_available``), each with the models its CLI offers now.

        ``{command, name, flavor, models, new_models, optional_models?, prices?, labels?, account?}``
        — the models are the last ``refresh_models`` merged into the curated list (see
        ``model_catalog``), the curated list alone before the first one. ``labels`` names the
        models of a company gateway; ``account`` tags Claude Code as ``personal`` or ``work``.
        """
        account = claude_account(*self._claude_setup())
        return [
            {
                "command": a["command"],
                "name": a["name"],
                "flavor": a["flavor"],
                **self._models.merge(a),
                **({"account": account} if account and a["flavor"] == "claude" else {}),
            }
            for a in self._agents_provider()
            if is_available(a)
        ]

    def installed_agents(self) -> list[dict[str, Any]]:
        """``{command, name, path}`` of each available agent — what the version check covers."""
        return [
            {"command": a["command"], "name": a["name"], "path": a.get("path") or ""}
            for a in self._agents_provider()
            if is_available(a)
        ]

    def missing_agents(self) -> list[dict[str, Any]]:
        """``{command, name, install_hint, is_disabled, is_installed}`` of each known CLI this
        machine does not offer — what Settings › Agents can install or turn on.

        ``is_disabled``: the settings file turns it off (``install`` turns it back on);
        ``is_installed``: its binary is already there, so ``install`` only turns it on.
        """
        present = {a["command"] for a in self._agents_provider() if is_available(a)}
        disabled = set(self._disabled_provider())
        rows = []
        for spec in CLI_AGENT_SPECS:
            if spec.command in present:
                continue
            is_disabled = spec.command in disabled or spec.flavor in disabled
            rows.append({
                "command": spec.command,
                "name": spec.name,
                "install_hint": spec.install_hint,
                "is_disabled": is_disabled,
                "is_installed": bool(is_disabled and self._resolve_binary(spec.command)),
            })
        return rows

    def refresh_models(self, *, force: bool = False) -> None:
        """Ask the CLIs that can list their models, those whose cached answer expired.

        One refresh at a time: a second caller waits for the running one, then finds the answers
        fresh. A failure is logged, never raised — the curated lists stand. Claude Code through
        a company gateway offers that gateway's list (``model_catalog``).
        """
        with self._refresh_lock:
            try:
                self._models.refresh(
                    [a for a in self._agents_provider() if is_available(a)],
                    force=force,
                    claude_gateway=claude_gateway(*self._claude_setup()),
                )
            except Exception:  # a bad CLI answer must never take the host down
                log.exception("Listing the agents' models failed")

    def _claude_setup(self) -> tuple[Path, Mapping[str, str]]:
        """The home and environment Claude Code's account and gateway are read from."""
        return self._home or Path.home(), os.environ if self._env is None else self._env

    def refresh_models_soon(self) -> None:
        """``refresh_models`` in a daemon thread, unless one is already running — for a route that
        answers from the cache at once and lets the next request see the fresh lists."""
        with self._refresher_lock:
            if self._refresher is not None and self._refresher.is_alive():
                return
            self._refresher = threading.Thread(target=self.refresh_models, name="agent-models", daemon=True)
            self._refresher.start()

    def warm(self) -> None:
        """The model lists and version checks once (a worker thread at start), so the first picker
        and the first Settings › Agents answer at once.

        Also drops a download quarantine a previous update left on a CLI: the dialog it causes
        appears at the next launch, which may be long before the next upgrade.
        """
        for agent in self.installed_agents():
            self.clear_quarantine(agent["command"])
        self.refresh_models()
        try:
            self.status()
        except Exception as exc:  # a warm-up failure only means the first check waits
            log.debug("CLI status warm-up failed: %s", exc)

    # -- versions and updates ---------------------------------------------------------------

    def status(self, *, force: bool = False) -> dict[str, Any]:
        """Installed vs newest version of each available CLI (cached, see ``cli_status``).

        ``{checked_at, agents: [{command, name, flavor, installed, latest, is_outdated, source,
        error, can_sign_in, needs_code, account?}], missing: [{command, name, install_hint}]}``;
        ``force`` asks every CLI, registry and model catalog again.
        """
        if force:
            self.refresh_models(force=True)
        status = self._status.status(self.installed_agents(), force=force)
        known = {a["command"]: a for a in self.agents()}
        for row in status["agents"]:
            agent = known.get(row["command"], {})
            row["flavor"] = agent.get("flavor", "")
            for key in ("account", "models", "new_models", "optional_models", "prices", "labels", "metrics"):
                if agent.get(key):
                    row[key] = agent[key]
        status["missing"] = self.missing_agents()
        return status

    def update(self, command: str) -> dict[str, Any]:
        """Upgrade one CLI the way it was installed (Homebrew, npm or its own updater), then read
        its version again: ``{ok, command, how, output, hint, status}``.

        ``hint`` without ``output`` means this host cannot update that install (the owner runs the
        hint). ``ValueError`` for a CLI discovery did not find, the Grok binary answering to
        Cursor's name, or a CLI that is answering a chat right now.
        """
        agent = self._found(command)
        if self._is_busy(command):
            raise ValueError(f"{agent['name']} is answering a chat on this machine — update it once that reply ends")
        binary = str(agent.get("path") or "")
        resolved = os.path.realpath(binary) if binary else ""
        plan = update_plan(command, binary, resolved, is_windows=os.name == "nt")
        if not plan["argv"]:
            return {"ok": False, "command": command, "how": "", "output": "", "hint": plan["hint"]}
        # A plan may be several commands (a cask channel switch): run them in order and stop at
        # the first failure, so a download that fails never uninstalls anything.
        code, outputs = self._run_plan_steps(command, [plan["argv"], *plan.get("then", [])], action="Updating")
        output = "\n\n".join(outputs)
        how = plan["how"]
        # Drop the quarantine before anything execs the new binary. The catch-up below reads
        # `claude --version`, and that launch is what makes Gatekeeper offer to trash it.
        self._clear_binary_quarantine(command, binary)
        # `brew upgrade --cask claude-code@latest` exits 0 with "already installed" while
        # Anthropic has already published a newer binary than the formula: install that one.
        if code == 0 and command == "claude":
            resolved_now = os.path.realpath(binary) if binary else ""
            if is_claude_latest_cask_binary(resolved_now):
                self._status.forget(command)
                installed_now = self._status.installed(command)["version"]
                npm_latest = self._status.latest(command, force=True)["version"]
                catch_code, note = catch_up_claude_cask(
                    resolved_now, installed_now, npm_latest, fetch=self._status.fetch
                )
                if note:
                    output = f"{output}\n{note}".strip()
                    log.info("Claude cask catch-up (%s): %s", catch_code, note)
                if catch_code != 0:
                    code = catch_code
                elif note:
                    how = f"{how} — then Anthropic's published build, because the cask formula was behind"
        # The direct download can land quarantined too. Clear again before the version re-read.
        self._clear_binary_quarantine(command, binary)
        self._status.forget(command)
        self._models.forget(command)  # a new CLI version may offer new models
        if code == 0:
            self.refresh_models()
        return {"ok": code == 0, "command": command, "how": how, "output": output, "hint": "", "status": self.status()}

    def uninstall(self, command: str) -> dict[str, Any]:
        """Remove one CLI the way it was installed (Homebrew, npm, WinGet, or a native install's
        own folder): ``{ok, command, how, output, hint, status}``.

        ``hint`` without ``output`` means this host cannot remove that install (the owner does it
        by hand). Same refusals as ``update``: a CLI discovery did not find, the Grok binary
        answering to Cursor's name, or a CLI that is answering a chat right now.
        """
        agent = self._found(command)
        if self._is_busy(command):
            raise ValueError(f"{agent['name']} is answering a chat on this machine — uninstall it once that reply ends")
        binary = str(agent.get("path") or "")
        resolved = os.path.realpath(binary) if binary else ""
        plan = uninstall_plan(command, binary, resolved, is_windows=os.name == "nt", home=self._home)
        if plan.get("remove"):
            log.info("Uninstalling %s: removing %s", command, plan["remove"].get("dir"))
            code, output = remove_native_install(plan["remove"])
        elif plan["argv"]:
            log.info("Uninstalling %s: %s", command, " ".join(plan["argv"]))
            code, output = self._run_update(plan["argv"])
        else:
            return {"ok": False, "command": command, "how": "", "output": "", "hint": plan["hint"]}
        self._status.forget(command)
        self._models.forget(command)
        return {"ok": code == 0, "command": command, "how": plan["how"], "output": output, "hint": "", "status": self.status()}

    def install(self, command: str) -> dict[str, Any]:
        """Install a known CLI this machine does not have, with its vendor's documented installer:
        ``{ok, command, how, output, hint, status}``.

        A CLI the settings file turns off is turned back on (dropped from ``disabled_agents``):
        right away when its binary is already there (nothing is installed), else once its
        installer succeeded. ``hint`` without ``output`` means this host cannot install it (no
        npm, no Homebrew…). ``ValueError`` for a command that is not one of ``missing_agents``
        (unknown, or already offered).
        """
        missing = next((a for a in self.missing_agents() if a["command"] == command), None)
        if missing is None:
            raise ValueError(f"{command!r} is not an agent CLI this machine can install")
        if missing["is_installed"]:
            self._turn_on(command)
            self.refresh_models()
            return {"ok": True, "command": command, "how": "turned on", "output": "", "hint": "", "status": self.status()}
        plan = install_plan(command, is_windows=os.name == "nt", home=self._home)
        if not plan["argv"]:
            return {"ok": False, "command": command, "how": "", "output": "", "hint": plan["hint"]}
        code, outputs = self._run_plan_steps(command, [plan["argv"], *plan.get("then", [])], action="Installing")
        if code != 0 and plan.get("manual"):
            outputs.append(f"Run it by hand in a PowerShell window: {plan['manual']}")
        if code == 0 and missing["is_disabled"]:
            self._turn_on(command)
        self._status.forget(command)
        self._models.forget(command)
        installed = next((a for a in self.installed_agents() if a["command"] == command), None)
        if installed:
            self._clear_binary_quarantine(command, installed["path"])
        if code == 0:
            self.refresh_models()
        return {
            "ok": code == 0, "command": command, "how": plan["how"], "output": "\n\n".join(outputs),
            "hint": "", "status": self.status(),
        }

    def _run_plan_steps(self, command: str, steps: list[list[str]], *, action: str) -> tuple[int, list[str]]:
        """Run each argv in order and stop at the first non-zero status.

        ``action`` is the log word (``Updating`` or ``Installing``). One step keeps that command's
        own output; several steps keep each as ``$ argv`` plus its output. The caller joins the
        pieces, so it can still append a line of its own (an install's manual hint).
        """
        outputs: list[str] = []
        code = 0
        for argv in steps:
            log.info("%s %s: %s", action, command, " ".join(argv))
            code, output = self._run_update(argv)
            outputs.append(f"$ {' '.join(argv)}\n{output}".strip() if len(steps) > 1 else output)
            if code != 0:
                break
        return code, outputs

    def _turn_on(self, command: str) -> None:
        """Drop that CLI (its command and flavor) from the settings file's ``disabled_agents``."""
        spec = next(spec for spec in CLI_AGENT_SPECS if spec.command == command)
        log.info("Turning %s back on (settings file)", command)
        self._enable({spec.command, spec.flavor})
        self._status.forget(command)
        self._models.forget(command)

    # -- sign-in ----------------------------------------------------------------------------

    def sign_in(self, command: str) -> dict[str, Any]:
        """Start that CLI's browser sign-in and return its link (see ``cli_login``):
        ``{url, running, output, needs_code, user_code}``."""
        binary = self._binary(command)
        self._clear_binary_quarantine(command, binary)
        result = self._logins.start(command, binary)
        self._models.forget(command)  # a signed-in CLI may list other models
        return result

    def sign_in_code(self, command: str, code: str) -> dict[str, Any]:
        """Hand the code (Claude) or API key (Open Router) the owner pasted to the waiting sign-in."""
        self._binary(command)
        return self._logins.submit(command, code)

    def sign_in_status(self, command: str) -> dict[str, Any]:
        """``{signed_in: true | false | null, running, url, output, error, needs_code, user_code}``."""
        binary = self._binary(command)
        self._clear_binary_quarantine(command, binary)
        result = self._logins.status(command, binary)
        if result["signed_in"]:
            self._models.forget(command)
        return result

    def sign_out(self, command: str) -> dict[str, Any]:
        """Run that CLI's own logout, then report its status."""
        binary = self._binary(command)
        self._clear_binary_quarantine(command, binary)
        result = self._logins.logout(command, binary)
        self._models.forget(command)
        return result

    # -- macOS Gatekeeper ---------------------------------------------------------------------

    def clear_quarantine(self, command: str) -> bool:
        """Drop Gatekeeper's download mark from ``command``'s binary before something execs it.

        A chat, a sign-in and a version probe can each be the first launch after Homebrew or npm
        stamped ``com.apple.quarantine`` — and that launch is the "Not Opened / Move to Trash"
        dialog. A host calls this before it runs a turn; ``True`` when a mark was removed. An
        unknown command, or anything off macOS, is a no-op.
        """
        agent = next((a for a in self.installed_agents() if a["command"] == command), None)
        return self._clear_binary_quarantine(command, str((agent or {}).get("path") or ""))

    def _clear_binary_quarantine(self, command: str, binary: str) -> bool:
        if binary and clear_macos_quarantine(binary):
            log.info("Removed the download quarantine on %s so macOS will open it", command)
            return True
        return False

    # -- which CLI a command names ----------------------------------------------------------

    def _found(self, command: str) -> dict[str, Any]:
        """The discovered agent ``command`` names, with its binary — else ``ValueError``."""
        agents = list(self._agents_provider())
        collision = next((a for a in agents if a.get("command") == command and is_cursor_grok_collision(a)), None)
        if collision is not None:
            # A real binary, just not the one it claims to be: never "update" Grok as Cursor.
            raise ValueError(collision_refusal(collision))
        agent = next((a for a in agents if a.get("binary_found") and a.get("command") == command), None)
        if agent is None:
            raise ValueError(f"No agent CLI named {command!r} on this machine")
        return agent

    def _binary(self, command: str) -> str:
        """The discovered binary of ``command`` — never a path from the request."""
        path = str(self._found(command).get("path") or "")
        if not path:
            raise ValueError(f"No agent CLI named {command!r} on this machine")
        return path
