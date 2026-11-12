"""Which models each agent CLI offers right now (a host's model picker, its "New models" note)

The curated list (``specs.py``, or the ``models`` of ``agent_cli_bridge.json``) alone misses
any model released after it was edited. The CLIs that can say what they offer are asked — ``agy models``,
``grok models``, ``cursor-agent models``, ``opencode models`` — and their answer is merged into
that curated list:

- a model the CLI lists and the curated list lacks is added, and flagged **new** (the browser
  announces it once, and keeps it out of the picker until the owner ticks it in Settings);
- a curated model the CLI no longer lists is dropped (a retired stealth model, a pulled id).
  A curated ``openrouter/`` id stays when that listing contains no OpenRouter ids at all
  (OpenCode with no key prints only its Zen models);
- a CLI that cannot list (Claude Code, whose aliases already follow the newest release; Gemini
  CLI; Copilot) or that fails keeps the curated list unchanged.

Claude Code through a company gateway (``claude_account.claude_gateway``: ``ANTHROPIC_BASE_URL``
on a host that is not Anthropic's) offers what that gateway lists. Its ``/v1/models`` is read the
way Claude Code's own model discovery reads it (``?limit=1000``, no redirect), but with **no
credentials** — only a gateway that answers without a token is listed, and Anthropic's API never
is. The gateway's list is that company's curated list: its first read is offered as usual, with
each model's ``display_name`` (``labels``) and price; what it lists later is new; a model it says
cannot call tools is optional (an agent cannot run without them). Claude Code's aliases and
pinned ids stay — it resolves them itself (``ANTHROPIC_DEFAULT_OPUS_MODEL``…). Whether the
gateway can run a listed model under Claude Code is its own setup: one it cannot answers the turn
with its error. A gateway that does not answer (it may start after the host) is asked again a
minute later.

Two catalogs are markets rather than lists. OpenCode's (every OpenRouter model) is read with
``--verbose`` when that flag exists (OpenCode 1.x): it gives each model's price, so the free
ones (``:free``, a last-segment ``-free``, stealth, and OpenCode Zen's own at no cost) are
offered as usual and the paid ones are **optional** — listed with their price so Settings can
show them, but out of the picker until the owner ticks one, and never announced as new.
OpenCode 2 dropped the flag (``Unrecognized flag: --verbose``, exit 1); the same split is then
read from the plain id list, without prices. Any catalog too long to review (Cursor's ~220 ids across effort tiers) is taken as already known
the first time it is read — only what appears after that counts as new. That first read is
kept in ``models-known.json``; its models are optional too (tickable in Settings, never announced).

Results are cached per CLI (an hour; a failure five minutes), so a host can re-check on a
timer without spawning a process each time.
"""

import http.client
import json
import logging
import math
import os
import re
import subprocess
import time
import urllib.error
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple
from urllib.parse import urlsplit

from .cli_status import USER_AGENT, clear_macos_quarantine
from .http_get import get_bytes
from .model_ranking import fetch_leaderboard_metrics, model_metrics, sanitize_metrics_table, update_live_metrics
from .processes import background_process_options

log = logging.getLogger(__name__)

LIST_TIMEOUT = 45.0  # `opencode models` refreshes its catalog from the network first
LIST_TTL = 60 * 60.0
FAILURE_TTL = 5 * 60.0
# A first read longer than this is a catalog nobody reviews line by line: it becomes the baseline.
REVIEWABLE = 40
MAX_MODELS = 800  # OpenCode lists ~400 OpenRouter + Zen models

GATEWAY_TIMEOUT = 5.0
GATEWAY_RETRY = 60.0  # a gateway that did not answer: it may start after the host at login
GATEWAY_MAX_BYTES = 4 * 1024 * 1024
LABEL_MAX = 100
# A gateway entry of these types writes no text (Anthropic's own list says "model", LiteLLM "chat").
NON_CHAT_TYPES = frozenset({"embedding", "embeddings", "rerank", "moderation"})

# The CLIs that print their models, by flavor (the argument after the binary).
LIST_ARGS = {
    "antigravity": ["models"],
    "grok": ["models"],
    "cursor": ["models"],
    "opencode": ["models", "--verbose"],  # 1.x: id line, then JSON (price). 2.x: flag is gone.
}
# Ids that are not models but a "let the CLI pick" setting: never dropped.
KEEP_ALWAYS = frozenset({"auto", "default"})

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@\[\]=+-]*$")


def parse_models(text: str) -> list[str]:
    """Model ids in a ``<cli> models`` output, in the CLI's order, without duplicates.

    Each line's first word counts when it looks like an id: letters, digits and ``.-_:/``, with
    a digit or a slash in it (so "Fetching", "Available", "Error:" never do). Bullets (``*``,
    ``-``, ``•``) and colour codes are stripped — ``  * grok-4.7 (default)`` → ``grok-4.7``,
    ``gemini-3.8-flash-high\\tGemini 3.8 Flash (High)`` → ``gemini-3.8-flash-high``.
    """
    seen: dict[str, None] = {}
    for raw in _ANSI_RE.sub("", text or "").splitlines():
        line = raw.strip().lstrip("*-•→> \t")
        if not line:
            continue
        word = line.split()[0].rstrip(",")
        if word.endswith((":", ".")) or not _ID_RE.match(word):
            continue
        if not any(ch.isdigit() for ch in word) and "/" not in word:
            continue
        seen.setdefault(word, None)
    return list(seen)[:MAX_MODELS]


def parse_verbose_models(text: str) -> tuple[list[str], dict[str, list[float]]]:
    """Ids and prices in ``opencode models --verbose``: each id line is followed by its JSON.

    A price is ``[input, output]`` in USD per million tokens. Models that cannot write text (music,
    images) are left out; a block that is not JSON keeps its id without a price.
    """
    ids: dict[str, None] = {}
    prices: dict[str, list[float]] = {}
    decoder = json.JSONDecoder()
    lines = _ANSI_RE.sub("", text or "").splitlines(keepends=True)
    index = 0
    while index < len(lines) and len(ids) < MAX_MODELS:
        word = lines[index].strip()
        index += 1
        if not word or " " in word or not _ID_RE.match(word) or "/" not in word:
            continue
        rest = "".join(lines[index : index + 400]).lstrip()
        info: Any = None
        if rest.startswith("{"):
            try:
                info, _ = decoder.raw_decode(rest)
            except ValueError:
                info = None
        if isinstance(info, dict):
            capabilities = info.get("capabilities")
            output = capabilities.get("output") if isinstance(capabilities, dict) else None
            if isinstance(output, dict) and output.get("text") is False:
                continue
            cost = info.get("cost")
            if isinstance(cost, dict):
                pair: list[Any] = [cost.get("input"), cost.get("output")]
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 for v in pair):
                    prices[word] = [float(pair[0]), float(pair[1])]
        ids.setdefault(word, None)
    return list(ids), prices


def read_opencode_catalog(run: Callable[[list[str]], str], binary: str) -> tuple[list[str], dict[str, list[float]]]:
    """Ids and prices from OpenCode. 1.x prints JSON after ``--verbose``; 2.x lists ids only.

    A missing flag is an error, not an empty catalog: falling back keeps the free models
    (``:free``, ``-free``, stealth, Zen) instead of the two curated ids.
    """
    try:
        output = run([binary, "models", "--verbose"])
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
        log.info("opencode models --verbose failed (%s); listing ids only", exc)
        return parse_models(run([binary, "models"])), {}
    listed, prices = parse_verbose_models(output)
    if listed:
        return listed, prices
    return parse_models(run([binary, "models"])), {}


def is_openrouter_promo(model: str) -> bool:
    """Open Router ids that are free for a limited time (``:free``, ``-free``, stealth)."""
    text = (model or "").lower()
    if "/stealth/" in text or text.endswith(":free"):
        return True
    name = text.rsplit("/", 1)[-1]
    return name.endswith("-free")


def is_free(model: str, prices: dict[str, list[float]] | None = None) -> bool:
    """A free OpenCode model: an Open Router promo id, or an OpenCode Zen model at no cost.

    A price of zero alone is not enough: Open Router's routers (``openrouter/openrouter/auto``)
    report 0 because they bill whatever model they pick.
    """
    if is_openrouter_promo(model):
        return True
    if not model.startswith("opencode/"):
        return False
    price = (prices or {}).get(model)
    return price is None or not any(price)


def _lists_openrouter(listed: set[str]) -> bool:
    """True when this listing is OpenRouter's catalog, not OpenCode Zen alone."""
    return any(item.startswith("openrouter/") for item in listed)


def offered(flavor: str, listed: list[str], prices: dict[str, list[float]] | None = None) -> list[str]:
    """What of a CLI's full list is offered as usual: OpenCode keeps its free models only."""
    if flavor != "opencode":
        return listed
    return [m for m in listed if is_free(m, prices)]


def is_listed(flavor: str, model: str, listed: set[str]) -> bool:
    """Whether a curated id is still among the CLI's models (Grok's ``-high``/``-low`` are efforts).

    OpenCode with no OpenRouter key lists only Zen ids. A curated ``openrouter/`` model stays
    until a listing that actually contains OpenRouter ids leaves it out.
    """
    if model in listed or model in KEEP_ALWAYS:
        return True
    if flavor == "opencode" and model.startswith("openrouter/") and not _lists_openrouter(listed):
        return True
    if flavor == "grok":
        for suffix in ("-high", "-low"):
            if model.endswith(suffix) and model[: -len(suffix)] in listed:
                return True
    return False


def run_list(argv: list[str], timeout: float = LIST_TIMEOUT) -> str:
    """Run one ``<cli> models`` (no shell); raises when it cannot run or exits non-zero."""
    # Same dialog as a version probe: a cask upgrade quarantines the binary, and this
    # listing can be the first thing to exec it.
    if argv:
        clear_macos_quarantine(argv[0])
    completed = subprocess.run(  # noqa: S603 — argv is a discovered binary plus a fixed word
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        check=False,
        **background_process_options(),
    )
    if completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "").strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"exit {completed.returncode}: {tail[0][:200]}")
    return completed.stdout or ""


# ── a company gateway's list, for Claude Code ──


class GatewayModels(NamedTuple):
    """What a gateway's ``/v1/models`` offers, in its order."""

    ids: list[str]
    prices: dict[str, list[float]]  # model → [input, output] USD per million tokens
    labels: dict[str, str]  # model → its display name, when that is not the id itself
    toolless: list[str]  # the models it says cannot call tools


def gateway_models_url(base_url: str) -> str:
    """Where a gateway lists its models: the URL Claude Code's own model discovery reads."""
    return f"{base_url.strip().rstrip('/')}/v1/models?limit=1000"


def _per_million(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return round(value * 1_000_000, 4)


def _label(name: Any, model: str) -> str:
    if not isinstance(name, str):
        return ""
    label = " ".join("".join(ch if ch.isprintable() else " " for ch in name).split())[:LABEL_MAX]
    return label if label != model else ""


def parse_gateway_models(data: Any) -> GatewayModels:
    """The models of a ``/v1/models`` answer (Anthropic's shape, or OpenAI's and LiteLLM's ``data``).

    An entry counts when its ``id`` looks like a model id, and not when it writes no text (an
    ``embedding`` type, ``output_modalities`` without ``text``). ``display_name`` is its label,
    ``info.input_cost_per_token`` / ``output_cost_per_token`` its price (none when both are zero:
    a gateway that does not price a model says 0), and ``capabilities.tools: false`` makes it toolless.
    """
    entries = data.get("data") if isinstance(data, dict) else None
    ids: dict[str, None] = {}
    prices: dict[str, list[float]] = {}
    labels: dict[str, str] = {}
    toolless: list[str] = []
    for entry in entries if isinstance(entries, list) else []:
        if len(ids) >= MAX_MODELS:
            break
        if not isinstance(entry, dict):
            continue
        model = entry.get("id")
        if not isinstance(model, str) or len(model) > 200 or not _ID_RE.match(model) or model in ids:
            continue
        if str(entry.get("type") or "").lower() in NON_CHAT_TYPES:
            continue
        outputs = entry.get("output_modalities")
        if isinstance(outputs, list) and outputs and "text" not in outputs:
            continue
        ids[model] = None
        label = _label(entry.get("display_name"), model)
        if label:
            labels[model] = label
        info = entry.get("info")
        if isinstance(info, dict):
            cost_in = _per_million(info.get("input_cost_per_token"))
            cost_out = _per_million(info.get("output_cost_per_token"))
            if cost_in is not None and cost_out is not None and (cost_in or cost_out):
                prices[model] = [cost_in, cost_out]
        capabilities = entry.get("capabilities")
        if isinstance(capabilities, dict) and capabilities.get("tools") is False:
            toolless.append(model)
    return GatewayModels(list(ids), prices, labels, toolless)


def _host_port(url: str) -> str:
    """``host`` or ``host:port`` of a URL — what a log line or a saved key names a gateway by."""
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = None
    host = parts.hostname or "?"
    return f"{host}:{port}" if port else host


def fetch_json(url: str, timeout: float = GATEWAY_TIMEOUT) -> Any:
    """GET ``url`` as JSON, at most ``GATEWAY_MAX_BYTES``, via the shared size-limited GET."""
    body = get_bytes(
        url,
        GATEWAY_MAX_BYTES,
        timeout=timeout,
        headers={"Accept": "application/json", "User-Agent": USER_AGENT},
    )
    return json.loads(body.decode("utf-8"))


class ModelCatalog:
    """The models each CLI offers, merged into the curated list, cached per command."""

    def __init__(
        self,
        known_path: Path,
        *,
        run: Callable[[list[str]], str] = run_list,
        fetch: Callable[[str], Any] = fetch_json,
        fetch_rankings: Callable[[], dict[str, dict[str, list[int | None]]]] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._known_path = known_path
        self._metrics_path = known_path.with_name("models-metrics.json")
        self._run = run
        self._fetch = fetch
        self._fetch_rankings = (
            (None if "PYTEST_CURRENT_TEST" in os.environ else fetch_leaderboard_metrics)
            if fetch_rankings is None
            else fetch_rankings
        )
        self._clock = clock
        self._listed: dict[str, tuple[list[str] | None, float]] = {}  # command → (ids, expires_at)
        self._prices: dict[str, dict[str, list[float]]] = {}  # command → model → [in, out] $/M
        self._labels: dict[str, dict[str, str]] = {}  # command → model → display name (a gateway's)
        self._toolless: dict[str, set[str]] = {}  # command → what its gateway says cannot call tools
        self._gateways: dict[str, str] = {}  # command → the gateway base URL its list comes from
        self._known: dict[str, list[str]] | None = None
        self._metrics: dict[str, dict[str, list[int | None]]] | None = None
        self._metrics_expires_at: float = 0.0

    def forget(self, command: str) -> None:
        """Read that CLI's models again next time (it was just updated)."""
        for cache in (self._listed, self._prices, self._labels, self._toolless, self._gateways):
            cache.pop(command, None)
        self._metrics_expires_at = 0.0

    def _load_metrics(self) -> dict[str, dict[str, list[int | None]]]:
        if self._metrics is None:
            try:
                data = json.loads(self._metrics_path.read_text(encoding="utf-8"))
                self._metrics = sanitize_metrics_table(data)
            except (OSError, ValueError):
                self._metrics = {}
            if self._metrics:
                update_live_metrics(self._metrics)
        return self._metrics

    def _save_metrics(self, metrics: dict[str, dict[str, list[int | None]]]) -> None:
        clean = sanitize_metrics_table(metrics)
        self._metrics = clean
        update_live_metrics(clean)
        try:
            self._metrics_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._metrics_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(clean, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self._metrics_path)
        except OSError as exc:
            log.warning("Could not save %s: %s", self._metrics_path, exc)

    def _refresh_rankings(self, *, force: bool = False) -> None:
        """Fetch Artificial Analysis leaderboard ratings (Intelligence Index + median output t/s)."""
        self._load_metrics()
        if not self._fetch_rankings:
            return
        if not force and self._metrics_expires_at > self._clock():
            return
        try:
            fresh = sanitize_metrics_table(self._fetch_rankings())
            if not fresh:
                raise ValueError("no ranked models in the leaderboard response")
        except (OSError, ValueError, RuntimeError, http.client.HTTPException) as exc:
            log.info("Could not refresh Artificial Analysis model rankings: %s", exc)
            self._metrics_expires_at = self._clock() + FAILURE_TTL
            return
        merged = {family: dict(efforts) for family, efforts in (self._metrics or {}).items()}
        for family, efforts in fresh.items():
            merged.setdefault(family, {}).update(efforts)
        self._save_metrics(merged)
        self._metrics_expires_at = self._clock() + LIST_TTL

    def _with_metrics(self, merged: dict[str, Any]) -> dict[str, Any]:
        """Attach ``metrics`` (``{model: [intelligence, speed]}``) when live ratings are loaded."""
        extra = self._load_metrics()
        if not extra:
            return merged
        metrics: dict[str, list[int | None]] = {}
        for model in merged.get("models") or []:
            pair = model_metrics(model, extra_metrics=extra)
            if pair is not None:
                metrics[model] = list(pair)
        if metrics:
            merged["metrics"] = metrics
        return merged

    def _load_known(self) -> dict[str, list[str]]:
        if self._known is None:
            try:
                data = json.loads(self._known_path.read_text(encoding="utf-8"))
                self._known = (
                    {str(k): [str(m) for m in v] for k, v in data.items() if isinstance(v, list)}
                    if isinstance(data, dict)
                    else {}
                )
            except (OSError, ValueError):
                self._known = {}
        return self._known

    def _remember_baseline(self, key: str, models: list[str], *, is_curated: bool = False) -> None:
        known = self._load_known()
        if key in known:
            return
        # A list short enough to read is announced model by model; a market is the baseline. A
        # gateway's list is its company's curated list: all of it is.
        known[key] = models if is_curated or len(models) > REVIEWABLE else []
        try:
            self._known_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._known_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(known, indent=1, sort_keys=True), encoding="utf-8")
            tmp.replace(self._known_path)
        except OSError as exc:
            log.warning("Could not save %s: %s", self._known_path, exc)

    def refresh(
        self, agents: list[dict[str, Any]], *, force: bool = False, claude_gateway: str | None = None
    ) -> None:
        """Ask every CLI that can list its models and whose cached answer expired (blocking).

        ``claude_gateway`` is the company gateway Claude Code talks to
        (``claude_account.claude_gateway``): its list stands for Claude Code's.
        Also refreshes the Artificial Analysis leaderboard ratings when expired, forced, or when any
        CLI's model list changed.
        """
        models_changed = False
        for agent in agents:
            command = str(agent.get("command") or "")
            flavor = str(agent.get("flavor") or "")
            if flavor == "claude" and command and agent.get("binary_found"):
                if self._refresh_gateway(command, claude_gateway, force=force):
                    models_changed = True
                continue
            args = LIST_ARGS.get(flavor)
            if not command or not args or not agent.get("binary_found"):
                continue
            cached = self._listed.get(command)
            if cached and not force and cached[1] > self._clock():
                continue
            prev_ids = cached[0] if cached else None
            binary = str(agent.get("path") or command)
            prices: dict[str, list[float]] = {}
            try:
                if "--verbose" in args:
                    listed, prices = read_opencode_catalog(self._run, binary)
                else:
                    listed = parse_models(self._run([binary, *args]))
                if not listed:
                    raise RuntimeError("no model ids in the output")
            except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as exc:
                log.info("Could not list %s models: %s", command, exc)
                self._listed[command] = (prev_ids, self._clock() + FAILURE_TTL)
                continue
            if prev_ids != listed:
                models_changed = True
            self._listed[command] = (listed, self._clock() + LIST_TTL)
            self._prices[command] = prices
            self._remember_baseline(command, offered(flavor, listed, prices))
        self._refresh_rankings(force=force or models_changed)

    def _refresh_gateway(self, command: str, base_url: str | None, *, force: bool) -> bool:
        """Read the models of the gateway Claude Code talks to, unless the cached answer is fresh."""
        if self._gateways.get(command) != base_url:
            self.forget(command)  # another gateway, or none any more: the last one's list is not offered
        if not base_url:
            return False
        cached = self._listed.get(command)
        if cached and not force and cached[1] > self._clock():
            return False
        prev_ids = cached[0] if cached else None
        self._gateways[command] = base_url
        try:
            found = parse_gateway_models(self._fetch(gateway_models_url(base_url)))
            if not found.ids:
                raise ValueError("no model ids in the answer")
        except (OSError, ValueError, http.client.HTTPException) as exc:
            # Not up yet (it may start after the host at login): ask again soon. It said no: later.
            is_unreachable = isinstance(exc, OSError) and not isinstance(exc, urllib.error.HTTPError)
            log.info("Could not list the models of the gateway at %s: %s", _host_port(base_url), exc)
            retry = GATEWAY_RETRY if is_unreachable else FAILURE_TTL
            self._listed[command] = (prev_ids, self._clock() + retry)
            return False
        toolless = set(found.toolless)
        self._listed[command] = (found.ids, self._clock() + LIST_TTL)
        self._prices[command] = found.prices
        self._labels[command] = found.labels
        self._toolless[command] = toolless
        self._remember_baseline(self._baseline_key(command), [m for m in found.ids if m not in toolless], is_curated=True)
        return prev_ids != found.ids

    def _baseline_key(self, command: str) -> str:
        """Where ``models-known.json`` keeps a gateway's first read: per gateway, as two companies'
        lists have nothing in common."""
        return f"{command}@{_host_port(self._gateways.get(command, ''))}"

    def _merge_gateway(self, command: str, curated: list[str], listed: list[str]) -> dict[str, Any]:
        """Claude Code's own aliases and ids, then the gateway's models with their labels and prices.

        What the gateway lists since its first read is new; what cannot call tools is optional.
        """
        toolless = self._toolless.get(command, set())
        baseline = set(self._load_known().get(self._baseline_key(command), []))
        taken = set(curated)
        usable = [m for m in listed if m not in taken and m not in toolless]
        optional = [m for m in listed if m not in taken and m in toolless]
        merged: dict[str, Any] = {
            "models": curated + usable + optional,
            "new_models": [m for m in usable if m not in baseline],
        }
        if optional:
            merged["optional_models"] = optional
        prices = self._prices.get(command) or {}
        if prices:
            merged["prices"] = {m: prices[m] for m in merged["models"] if m in prices}
        labels = self._labels.get(command) or {}
        if labels:
            merged["labels"] = {m: labels[m] for m in merged["models"] if m in labels}
        return merged

    def merge(self, agent: dict[str, Any]) -> dict[str, Any]:
        """``{models, new_models}`` for one agent: curated ∪ listed, and which of them are new.

        ``optional_models`` are appended to ``models`` but out of the picker until ticked: a
        long catalog's baseline, and the paid ones of a CLI that prices its models (OpenCode,
        which also gets ``prices``). Claude Code through a company gateway also gets ``labels``
        (model → the gateway's name for it) and that gateway's ``prices``.
        """
        command = str(agent.get("command") or "")
        curated = [str(m) for m in agent.get("models") or []]
        cached = self._listed.get(command)
        listed = cached[0] if cached else None
        if not listed:
            return self._with_metrics({"models": curated, "new_models": []})
        if command in self._gateways:
            return self._with_metrics(self._merge_gateway(command, curated, listed))
        flavor = str(agent.get("flavor") or "")
        prices = self._prices.get(command) or {}
        everything = set(listed)
        kept = [m for m in curated if is_listed(flavor, m, everything)]
        baseline = set(self._load_known().get(command, []))
        free = offered(flavor, listed, prices)
        added = [m for m in free if m not in set(kept) and m not in baseline]
        merged: dict[str, Any] = {"models": (kept + added) or curated, "new_models": added}
        chosen = set(merged["models"])
        offered_now = set(free)
        # The baseline is not announced, but each of its models can still be ticked in Settings
        # (a first read taken late would otherwise hide what shipped in the meantime for good).
        optional = [m for m in listed if m not in chosen and (m in baseline or m not in offered_now)]
        if optional:
            merged["models"] = merged["models"] + optional
            merged["optional_models"] = optional
        if prices:
            merged.setdefault("optional_models", [])
            merged["prices"] = {m: prices[m] for m in merged["models"] if m in prices}
        return self._with_metrics(merged)
