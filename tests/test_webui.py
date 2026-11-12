"""The status and security pages share one HTML escaper, and the token stays in the browser."""

import importlib.util
import json
import re
import subprocess
from pathlib import Path

WEBUI = Path(__file__).resolve().parent.parent / "agent_cli_bridge" / "webui.py"
_DEFINITION = re.compile(r"^  function esc\(s\) \{.*?^  \}", re.M | re.S)


def _pages() -> tuple[str, str]:
    # webui.py has no imports. Loading it by path keeps this test off the package init.
    spec = importlib.util.spec_from_file_location("webui_page", WEBUI)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PAGE, module.SECURITY_PAGE


def _esc_source() -> str:
    text = WEBUI.read_text(encoding="utf-8")
    assert text.count("function esc(") == 1
    found = _DEFINITION.findall(text)
    assert len(found) == 1
    return found[0]


def _call_esc(source: str, value: str) -> str:
    program = source + "\nprocess.stdout.write(esc(" + json.dumps(value) + "));\n"
    result = subprocess.run(
        ["node", "-e", program],
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_esc_escapes_markup_and_does_not_return_its_input_unchanged():
    page, security = _pages()
    source = _esc_source()
    assert page.count("function esc(") == 1
    assert security.count("function esc(") == 1
    assert source in page
    assert source in security
    raw = """<a href="x" title='&'>"""
    escaped = _call_esc(source, raw)
    assert escaped != raw
    assert escaped == "&lt;a href=&quot;x&quot; title=&#39;&amp;&#39;&gt;"


_LINK = re.compile(r"^  function link\(url, label\) \{.*?^  \}", re.M | re.S)


def _link_html(url: str) -> str:
    text = WEBUI.read_text(encoding="utf-8")
    found = _LINK.findall(text)
    assert len(found) == 1
    program = _esc_source() + "\n" + found[0] + "\nprocess.stdout.write(link(" + json.dumps(url) + ", 'page'));\n"
    result = subprocess.run(["node", "-e", program], check=False, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_the_security_page_links_only_http_and_https_urls():
    for url in ("https://example.com/a?b=1", "http://127.0.0.1:4747/x", "HTTP://EXAMPLE.COM"):
        html = _link_html(url)
        assert '<a class="link mono" href="' in html and 'rel="noopener noreferrer"' in html
    for url in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", " javascript:alert(1)", "data:text/html,x",
                "vbscript:x", "//evil.example/x", "file:///etc/passwd", 'x" onmouseover="alert(1)'):
        html = _link_html(url)
        assert "<a " not in html and "href" not in html, url
        assert html.startswith('<code class="link">') and html.endswith("</code>"), url


def test_status_page_keeps_token_in_local_storage():
    page, _security = _pages()
    assert 'TOKEN_KEY = "acb-gateway-token"' in page
    assert "localStorage.setItem(TOKEN_KEY," in page
    assert "localStorage.getItem(TOKEN_KEY)" in page


def test_the_status_page_shows_the_brave_leo_settings_and_a_missing_token():
    page, _ = _pages()
    assert "http://127.0.0.1:4747/browser/v1/chat/completions" in page
    assert "~/.agent-cli-bridge/gateway-token" in page
    assert '"token needed"' in page  # a 401 is not an offline gateway
