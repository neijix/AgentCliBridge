"""How strong a model is, for a host's own Python: the Artificial Analysis Intelligence Index and
median output speed the Settings › Models tables show (https://artificialanalysis.ai/leaderboards/models).

``MODEL_METRICS`` / ``MODEL_FAMILY_ALIASES`` in ``ui/models.js`` and here start from the same
baseline snapshot, kept equal by ``tests/test_model_ranking.py``, and ``ModelCatalog.refresh``
updates the table live from Artificial Analysis (cached in ``models-metrics.json`` and sent to
the browser on each agent as ``metrics``), so both Python (D3SKHAND's account failover) and the
page always rank models with fresh ratings.
"""

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, TypeGuard

from .cli_status import USER_AGENT
from .effort import CLAUDE_EFFORT_ALIASES
from .http_get import get_bytes

LEADERBOARD_URL = "https://artificialanalysis.ai/leaderboards/models"
LEADERBOARD_TIMEOUT = 10.0
LEADERBOARD_MAX_BYTES = 8 * 1024 * 1024

# Baseline snapshot matching ui/models.js MODEL_METRICS: family → effort → [intelligence, speed].
MODEL_METRICS: dict[str, dict[str, list[int | None]]] = {
    "claude-opus-5-5": {"max": [58, None], "xhigh": [56, 89], "high": [54, 82], "medium": [51, 81], "low": [42, 80]},
    "claude-sonnet-5-5": {"max": [56, 133], "xhigh": [52, 109], "high": [47, 106], "medium": [41, 106], "low": [36, 105]},
    "claude-fable-5-1": {"max": [53, 69], "xhigh": [53, 66], "high": [51, 57], "medium": [49, 58], "low": [47, 58]},
    "claude-opus-5": {"max": [51, 60]},
    "claude-haiku-5-5": {"max": [43, 235], "xhigh": [41, 190], "high": [38, 182], "medium": [34, 178], "low": [29, 176]},
    "claude-opus-4-8": {"max": [42, 53]},
    "claude-opus-4-6": {"high": [39, 37]},
    "claude-sonnet-5": {"max": [38, 84], "xhigh": [34, 70], "high": [32, 66], "medium": [28, 66], "low": [24, 60]},
    "claude-sonnet-4-6": {"high": [25, 44]},
    "claude-haiku-4-5": {"high": [17, 82]},
    "gpt-6-astra": {"max": [53, 57], "xhigh": [52, 54], "high": [51, 53], "medium": [50, 50], "low": [46, 53]},
    "gpt-6.1-sol": {"max": [52, 55], "xhigh": [51, 50], "high": [50, 49], "medium": [48, 48], "low": [42, 48]},
    "gpt-6-sol": {"max": [48, 86], "xhigh": [44, 83], "high": [43, 84], "medium": [40, None], "low": [34, 82]},
    "gpt-5.6-sol": {"max": [47, 96], "high": [47, 96]},
    "gpt-5.6-terra": {"max": [42, 125], "xhigh": [38, 107], "high": [34, 103], "medium": [30, 106], "low": [27, 108]},
    "gpt-6-luna": {"max": [38, 136], "xhigh": [35, 126], "high": [33, 123], "medium": [30, 92], "low": [22, 111]},
    "gpt-5.3-codex": {"xhigh": [33, 118], "high": [33, 118]},
    "gpt-oss-120b": {"high": [12, 206], "low": [10, 216]},
    "grok-4.7": {"xhigh": [46, 82], "high": [46, 83], "low": [42, 78]},
    "grok-4.6": {"xhigh": [44, 78], "high": [44, 66], "medium": [43, 69], "low": [35, 62]},
    "grok-4.5": {"high": [39, 63]},
    "gemini-4-argon": {"high": [53, 82]},
    "gemini-3.8-flash": {"high": [41, 306], "medium": [40, None], "low": [33, None]},
    "gemini-3.7-flash": {"medium": [40, 291], "high": [39, 283], "low": [37, 306]},
    "gemini-3.6-flash": {"high": [34, 212]},
    "gemini-3.5-flash": {"high": [33, 204]},
    "gemini-3.5-flash-lite": {"high": [22, 349]},
    "gemini-3.1-pro": {"high": [30, 119]},
    "gemini-2.5-pro": {"high": [16, 139]},
    "muse-spark-1.3": {"max": [48, 221], "xhigh": [45, 196]},
    "mimo-v2.6-pro": {"high": [45, 55]},
    "muse-wonder": {"high": [42, 234]},
    "mimo-v2.6-flash": {"high": [38, 59]},
    "inkling-small": {"high": [28, 210]},
    "inkling": {"high": [25, 194]},
    "ling-3.0-flash": {"high": [25, 373]},
    "ling-3.0-flash-fin": {"high": [23, 161]},
    "nemotron-3-ultra": {"high": [23, 214]},
    "qwen3.8-27b": {"xhigh": [34, 47], "high": [20, 55], "medium": [28, 54], "low": [26, 56]},
    "gemma-4-31b": {"high": [19, 35]},
    "gemma-4-26b-a4b": {"high": [17, None]},
    "nemotron-3.5-lightning": {"high": [13, 292]},
    "nemotron-3-super": {"high": [13, 166]},
    "nemotron-3-nano-omni": {"high": [10, 263]},
    "north-mini-code": {"high": [10, 83]},
    "lfm-2.5-2.6b": {"high": [8, None]},
}

# Intelligence half of MODEL_METRICS: family → effort → index.
MODEL_INTELLIGENCE: dict[str, dict[str, int]] = {
    family: {effort: int(pair[0]) for effort, pair in variants.items() if pair[0] is not None}
    for family, variants in MODEL_METRICS.items()
}

# opus / sonnet / haiku / fable are not here. CLAUDE_EFFORT_ALIASES is their only map.
MODEL_FAMILY_ALIASES = {
    "claude-haiku": "claude-haiku-4-5",
    "claude-sonnet": "claude-sonnet-5",
    "gemini-3.1-pro-preview": "gemini-3.1-pro",
}
_PICKERS = ("auto", "default")
_EFFORT = re.compile(r"(?:-thinking)?-(max|xhigh|high|medium|low)$")
_DIGIT_DOT_RE = re.compile(r"(?<=\d)\.(?=\d)")
_SLUG_EFFORT_RE = re.compile(r"-(max|xhigh|high|medium|low)$")
_LABEL_EFFORT_RE = re.compile(r"\((max|xhigh|high|medium|low)\b[^)]*\)$", re.IGNORECASE)
_RSC_CHUNK_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)')
_MODELS_ARRAY_RE = re.compile(r'"(?:initialModels|models)"\s*:\s*\[')

# Live ratings fetched from Artificial Analysis (or loaded from models-metrics.json).
_LIVE_METRICS: dict[str, dict[str, list[int | None]]] = {}


def _canonical_stem(text: str) -> str:
    return _DIGIT_DOT_RE.sub("-", text)


def _normalize(model_id: str) -> str:
    text = model_id.strip().lower().removesuffix("[1m]")
    text = text[text.rfind("/") + 1:]
    text = text.removeprefix("cursor-")
    return text.removesuffix(":free").removesuffix("-free")


def _is_positive_number(value: Any) -> TypeGuard[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _valid_pair(pair: Any) -> list[int | None] | None:
    if not isinstance(pair, (list, tuple)) or not pair or not _is_positive_number(pair[0]):
        return None
    intelligence = round(float(pair[0]))
    speed = round(float(pair[1])) if len(pair) > 1 and _is_positive_number(pair[1]) else None
    return [intelligence, speed]


def parse_leaderboard_models(raw: str | bytes | list[Any]) -> dict[str, dict[str, list[int | None]]]:
    """Extract ``{family: {effort: [intelligence, speed]}}`` from Artificial Analysis's leaderboard.

    Accepts either the ``initialModels`` array directly or the Next.js HTML / RSC payload served by
    ``https://artificialanalysis.ai/leaderboards/models``. Non-reasoning duplicates and unranked
    rows are skipped.
    """
    entries: Any = None
    if isinstance(raw, list):
        entries = raw
    else:
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw or "")
        chunks: list[str] = []
        for match in _RSC_CHUNK_RE.finditer(text):
            try:
                chunk = json.loads(match.group(1))
            except ValueError:
                continue
            if isinstance(chunk, str):
                chunks.append(chunk)
        joined = "".join(chunks)
        for candidate in (joined, text):
            for match in _MODELS_ARRAY_RE.finditer(candidate):
                start = match.end() - 1
                try:
                    entries, _ = json.JSONDecoder().raw_decode(candidate, start)
                    break
                except ValueError:
                    entries = None
            if isinstance(entries, list):
                break
    if not isinstance(entries, list):
        return {}
    families: dict[str, dict[str, list[int | None]]] = {}
    for item in entries:
        if not isinstance(item, dict):
            continue
        slug = str(item.get("slug") or "").strip().lower()
        idx = item.get("intelligenceIndex")
        if idx is None:
            idx = item.get("intelligence_index")
        if not slug or not _is_positive_number(idx):
            continue
        label = str(item.get("shortName") or item.get("short_name") or item.get("name") or "").strip()
        if slug.endswith("-non-reasoning") or "(non-reasoning)" in label.lower():
            continue
        if slug_match := _SLUG_EFFORT_RE.search(slug):
            family = slug[: slug_match.start()]
            effort = slug_match.group(1)
        else:
            family = slug
            label_match = _LABEL_EFFORT_RE.search(label)
            effort = label_match.group(1).lower() if label_match else "high"
        spd = item.get("medianOutputTokensPerSecond")
        if spd is None:
            timescale = item.get("timescaleData")
            if isinstance(timescale, Mapping):
                spd = timescale.get("median_output_speed")
        pair: list[int | None] = [round(float(idx)), round(float(spd)) if _is_positive_number(spd) else None]
        families.setdefault(family, {}).setdefault(effort, pair)
    return families


def fetch_leaderboard_metrics(
    url: str = LEADERBOARD_URL, *, timeout: float = LEADERBOARD_TIMEOUT
) -> dict[str, dict[str, list[int | None]]]:
    """Fetch and parse live model metrics from Artificial Analysis's leaderboard page."""
    body = get_bytes(
        url,
        LEADERBOARD_MAX_BYTES,
        timeout=timeout,
        headers={"Accept": "text/html,application/xhtml+xml,application/json", "User-Agent": USER_AGENT},
    )
    parsed = parse_leaderboard_models(body)
    if not parsed:
        raise ValueError("no model metrics in the leaderboard response")
    return parsed


def sanitize_metrics_table(raw: Any) -> dict[str, dict[str, list[int | None]]]:
    """Validate a ``{family: {effort: [intelligence, speed]}}`` table from disk or network."""
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, dict[str, list[int | None]]] = {}
    for family, variants in raw.items():
        if not isinstance(family, str) or not family or not isinstance(variants, Mapping):
            continue
        valid_variants: dict[str, list[int | None]] = {}
        for effort, pair in variants.items():
            if not isinstance(effort, str) or not effort:
                continue
            valid = _valid_pair(pair)
            if valid is not None:
                valid_variants[effort] = valid
        if valid_variants:
            cleaned[family] = valid_variants
    return cleaned


def update_live_metrics(metrics: Mapping[str, Mapping[str, Sequence[int | None]]]) -> None:
    """Overlay live Artificial Analysis metrics onto the baseline table."""
    cleaned = sanitize_metrics_table(metrics)
    if cleaned:
        _LIVE_METRICS.clear()
        _LIVE_METRICS.update(cleaned)


def clear_live_metrics() -> None:
    """Drop any live overlay (restores the baseline snapshot)."""
    _LIVE_METRICS.clear()


def _merged_table(
    extra_metrics: Mapping[str, Mapping[str, Sequence[int | None]]] | None = None,
) -> dict[str, dict[str, list[int | None]]]:
    table: dict[str, dict[str, list[int | None]]] = {}
    for source in (MODEL_METRICS, _LIVE_METRICS, sanitize_metrics_table(extra_metrics) if extra_metrics else {}):
        for family, variants in source.items():
            bucket = table.setdefault(_canonical_stem(family), {})
            for effort, pair in variants.items():
                bucket[effort] = list(pair)
    return table


def _claude_effort_target(stem: str) -> str | None:
    """The canonical id for a Claude short name, or ``stem`` when it already is one.

    ``None`` for every other id. A canonical id with no metrics row stays unknown: it must not
    fall through to a shorter family such as ``claude-sonnet-5`` or ``claude-haiku-4-5``.
    """
    target = CLAUDE_EFFORT_ALIASES.get(stem)
    if target is not None:
        return target
    canonical = _canonical_stem(stem)
    if stem in CLAUDE_EFFORT_ALIASES.values() or canonical in CLAUDE_EFFORT_ALIASES.values():
        return stem
    return None


def _family(stem: str, table: Mapping[str, Any] = MODEL_INTELLIGENCE) -> str:
    if stem in table:
        return stem
    pinned = _claude_effort_target(stem)
    if pinned is not None:
        if pinned in table:
            return pinned
        canonical = _canonical_stem(pinned)
        if canonical in table:
            return canonical
        return ""
    if stem in MODEL_FAMILY_ALIASES and MODEL_FAMILY_ALIASES[stem] in table:
        return MODEL_FAMILY_ALIASES[stem]
    c_stem = _canonical_stem(stem)
    if c_stem in table:
        return c_stem
    for alias, target in MODEL_FAMILY_ALIASES.items():
        if _canonical_stem(alias) == c_stem:
            c_target = _canonical_stem(target)
            if target in table:
                return target
            if c_target in table:
                return c_target
    best = ""
    for key in table:
        c_key = _canonical_stem(key)
        if c_stem == c_key or c_stem.startswith(f"{c_key}-") or c_key.startswith(f"{c_stem}-") or c_key.endswith(f"-{c_stem}"):
            best = key if len(key) > len(best) else best
    return best


def model_metrics(
    model_id: str | None,
    *,
    extra_metrics: Mapping[str, Mapping[str, Sequence[int | None]]] | None = None,
) -> tuple[int, int | None] | None:
    """``(intelligence, speed)`` for ``model_id``, or ``None`` when unranked / picker."""
    raw = _normalize(model_id or "")
    if not raw or (raw in _PICKERS and "/" not in (model_id or "")):
        return None
    stem = raw.removesuffix("-thinking")
    effort = ""
    if match := _EFFORT.search(stem):
        effort = match.group(1)
        stem = stem[: match.start()]
    table = _merged_table(extra_metrics)
    variants = table.get(_family(stem, table))
    if not variants:
        return None
    chosen: list[int | None] | None = None
    if effort in variants:
        chosen = variants[effort]
    else:
        for key in ("high", "medium", "max", "xhigh", "low"):
            if key in variants:
                chosen = variants[key]
                break
        if chosen is None and variants:
            chosen = next(iter(variants.values()))
    if not chosen or chosen[0] is None:
        return None
    return int(chosen[0]), (int(chosen[1]) if chosen[1] is not None else None)


def model_power(model_id: str | None) -> int | None:
    """The model's intelligence index, as ui/models.js's modelMetrics reads it; None = not ranked
    (unknown, or a CLI's own auto/default picker)."""
    pair = model_metrics(model_id)
    return pair[0] if pair is not None else None
