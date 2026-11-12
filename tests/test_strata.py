"""Strata: a server the owner already started, read from /health, never started here."""
import json
from pathlib import Path

import pytest

from agent_cli_bridge import strata

MODEL = "qwen3.8-flash-next-iq3_s"


def _health(**extra: object) -> bytes:
    body = {
        "status": "ok",
        "service": "strata",
        "model": MODEL,
        "max_context": 32768,
        "loaded": False,
    }
    body.update(extra)
    return json.dumps(body).encode()


def _stub(monkeypatch, answers: dict[str, bytes | None]) -> list[str]:
    seen: list[str] = []

    def fake(url, max_bytes, *, timeout, headers=None):
        del max_bytes, headers
        assert timeout == strata._PROBE_TIMEOUT_SECONDS
        seen.append(url)
        body = answers.get(url)
        if body is None:
            raise OSError("down")
        return body

    monkeypatch.setattr(strata, "get_bytes", fake)
    return seen


def test_state_dir_matches_stratas_folders(tmp_path):
    assert strata.state_dir(environ={}, windows=False, home=tmp_path) == tmp_path / ".local" / "state" / "strata"
    assert strata.state_dir(
        environ={"XDG_STATE_HOME": str(tmp_path / "state")}, windows=False, home=tmp_path,
    ) == tmp_path / "state" / "strata"
    assert strata.state_dir(
        environ={"LOCALAPPDATA": str(tmp_path / "local")}, windows=True, home=tmp_path,
    ) == tmp_path / "local" / "Strata"


def test_an_unloaded_server_is_still_listed(tmp_path, monkeypatch):
    """/v1/models is empty until the engine loads. /health already names the model."""
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "launch.ready.json").write_text(json.dumps({
        "api_url": "http://127.0.0.1:8080",
        "bound_port": 8080,
        "model_id": MODEL,
        "model_state": "unloaded",
    }), encoding="utf-8")
    seen = _stub(monkeypatch, {"http://127.0.0.1:8080/health": _health()})
    found = strata.discover(tmp_path)
    assert found == [strata.Serving(MODEL, "http://127.0.0.1:8080", 32768, False)]
    assert seen == ["http://127.0.0.1:8080/health"]  # /v1/models is not asked


def test_a_server_that_is_not_strata_is_ignored(tmp_path, monkeypatch):
    _stub(monkeypatch, {"http://127.0.0.1:8080/health": json.dumps({"status": "ok", "service": "other"}).encode()})
    assert strata.discover(tmp_path) == []


def test_a_lan_address_is_never_probed(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "a.ready.json").write_text(
        json.dumps({"api_url": "http://192.168.1.20:8080", "bound_port": 8080}), encoding="utf-8",
    )
    launch = tmp_path / "launch"
    launch.mkdir()
    (launch / "run.json").write_text(json.dumps({"host": "10.0.0.8", "port": 9090}), encoding="utf-8")
    (launch / "run.choices.json").write_text(json.dumps({"port": 1}), encoding="utf-8")
    seen = _stub(monkeypatch, {})
    assert strata.discover(tmp_path) == []
    assert seen == ["http://127.0.0.1:8080/health"]


def test_a_custom_port_in_the_launch_config_is_used(tmp_path, monkeypatch):
    launch = tmp_path / "launch"
    launch.mkdir()
    (launch / "wide.json").write_text(
        json.dumps({"host": "0.0.0.0", "port": 9090, "model_name": MODEL}), encoding="utf-8",
    )
    _stub(monkeypatch, {
        "http://127.0.0.1:9090/health": _health(max_context=0, loaded=True),
        "http://127.0.0.1:8080/health": None,
    })
    found = strata.discover(tmp_path)
    assert found == [strata.Serving(MODEL, "http://127.0.0.1:9090", strata.DEFAULT_CONTEXT, True)]


def test_a_down_server_is_absent(tmp_path, monkeypatch):
    _stub(monkeypatch, {})
    assert strata.discover(tmp_path) == []
    assert strata.serving_for(MODEL, tmp_path) is None


def test_serving_for_picks_the_named_model(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "a.ready.json").write_text(json.dumps({"api_url": "http://127.0.0.1:8080"}), encoding="utf-8")
    (runtime / "b.ready.json").write_text(json.dumps({"api_url": "http://[::1]:8081"}), encoding="utf-8")
    other = _health(model="other-model")
    _stub(monkeypatch, {
        "http://127.0.0.1:8080/health": _health(),
        "http://[::1]:8081/health": other,
    })
    named = strata.serving_for(MODEL, tmp_path)
    assert named is not None and named.base_url == "http://127.0.0.1:8080"
    assert strata.serving_for("missing", tmp_path) is None
    only = strata.serving_for("", tmp_path)
    assert only is not None and only.model == MODEL


def test_a_blank_model_name_is_not_a_server(monkeypatch):
    monkeypatch.setattr(strata, "get_bytes", lambda *args, **kwargs: _health(model="  "))
    assert strata.probe("http://127.0.0.1:8080") is None


def test_probe_rejects_a_non_object(monkeypatch):
    monkeypatch.setattr(strata, "get_bytes", lambda *args, **kwargs: b"[]")
    assert strata.probe("http://127.0.0.1:8080") is None


def test_loopback_helpers():
    assert strata._loopback_base("192.168.1.20", 8080) is None
    assert strata._loopback_base("127.0.0.1", "nope") is None
    assert strata._base_from_url("http://127.0.0.1:8080/v1") == "http://127.0.0.1:8080"
    assert strata._base_from_url("http://127.0.0.1:8080/other") is None
    assert strata._read_json(Path("/no/such/strata.json")) is None


def test_discover_skips_a_duplicate_model(tmp_path, monkeypatch):
    launch = tmp_path / "launch"
    launch.mkdir()
    (launch / "a.json").write_text(json.dumps({"port": 8080}), encoding="utf-8")
    seen = _stub(monkeypatch, {"http://127.0.0.1:8080/health": _health(loaded=True)})
    assert len(strata.discover(tmp_path)) == 1
    assert seen == ["http://127.0.0.1:8080/health"]


def test_a_broken_ready_file_falls_through_to_the_default_port(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "bad.ready.json").write_text("{", encoding="utf-8")
    seen = _stub(monkeypatch, {"http://127.0.0.1:8080/health": _health()})
    assert strata.discover(tmp_path)[0].model == MODEL
    assert seen == ["http://127.0.0.1:8080/health"]


def test_get_json_failure_is_absence(monkeypatch):
    def boom(*args, **kwargs):
        raise strata.http.client.IncompleteRead(b"")

    monkeypatch.setattr(strata, "get_bytes", boom)
    assert strata.probe("http://127.0.0.1:9") is None


@pytest.mark.parametrize("port", [0, 65536])
def test_a_port_outside_range_is_dropped(port):
    assert strata._loopback_base("localhost", port) is None
