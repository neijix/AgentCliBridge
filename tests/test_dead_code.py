"""Names with no reader outside their definition are gone (AC25)."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from agent_cli_bridge import effort, model_ranking
from agent_cli_bridge.web_scout import WebScout

ROOT = Path(__file__).resolve().parents[1]
_STREAM_HANDLERS = frozenset({"chat_completions", "_stream_cli_events"})


def _defined_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _handlers_with_pass_only_finally(path: Path, handlers: frozenset[str]) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    hits: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in handlers:
            continue
        for inner in ast.walk(node):
            if not isinstance(inner, ast.Try):
                continue
            body = inner.finalbody
            if body and all(isinstance(stmt, ast.Pass) for stmt in body):
                hits.append(node.name)
    return hits


def test_default_effort_is_gone() -> None:
    assert "DEFAULT_EFFORT" not in _defined_names(ROOT / "agent_cli_bridge" / "effort.py")
    assert not hasattr(effort, "DEFAULT_EFFORT")


def test_live_metrics_getter_is_gone_and_writers_stay() -> None:
    defined = _defined_names(ROOT / "agent_cli_bridge" / "model_ranking.py")
    assert "live_metrics" not in defined
    assert "update_live_metrics" in defined
    assert "clear_live_metrics" in defined
    assert not hasattr(model_ranking, "live_metrics")
    assert callable(model_ranking.update_live_metrics)
    assert callable(model_ranking.clear_live_metrics)


def test_is_scout_tool_is_gone() -> None:
    assert "is_scout_tool" not in _defined_names(ROOT / "agent_cli_bridge" / "web_scout.py")
    assert not hasattr(WebScout, "is_scout_tool")


def test_pick_model_effort_wrapper_is_gone() -> None:
    text = (ROOT / "agent_cli_bridge" / "ui" / "models.js").read_text(encoding="utf-8")
    assert re.search(r"\bpickModelEffort\b", text) is None
    assert re.search(r"\bpickModelEffortFromVariants\b", text)


def test_cli_row_detail_is_gone() -> None:
    text = (ROOT / "agent_cli_bridge" / "ui" / "models.js").read_text(encoding="utf-8")
    assert re.search(r"\bcliRowDetail\b", text) is None


def test_streaming_chat_handler_has_no_pass_only_finally() -> None:
    hits = _handlers_with_pass_only_finally(ROOT / "agent_cli_bridge" / "gateway.py", _STREAM_HANDLERS)
    assert hits == []
