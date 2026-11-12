"""The shared page files (agent_cli_bridge/ui/) ship with the package and keep their rules."""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from agent_cli_bridge.ui_assets import UI_DIR, UI_FILES

ROOT = Path(__file__).resolve().parent.parent

MODEL_SCRIPTS = (
    "model_names.js",
    "model_ranking.js",
    "model_tags.js",
    "model_picker.js",
    "model_catalog.js",
    "model_effort.js",
    "model_agents.js",
    "models.js",
)
COMPOSER_SCRIPTS = (
    "composer_menu.js",
    "composer.js",
)
UI_SCRIPTS = (
    "icons.js",
    "permission_modes.js",
    "settings_models.js",
    "settings_agents.js",
    "components.js",
)


def test_model_scripts_load_before_components_and_stay_classic():
    files = list(UI_FILES)
    start = files.index("model_names.js")
    assert tuple(files[start:start + len(MODEL_SCRIPTS)]) == MODEL_SCRIPTS
    assert files.index("models.js") < files.index("components.js")
    models = (UI_DIR / "models.js").read_text(encoding="utf-8")
    assert "globalThis.AgentModels" in models
    assert "pickModelEffortFromVariants" in models
    for name in MODEL_SCRIPTS:
        text = (UI_DIR / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 800, name
        assert not re.search(r"^\s*(import|export)\b", text, re.M), name


def test_composer_scripts_load_before_components_and_stay_classic():
    files = list(UI_FILES)
    start = files.index("composer_menu.js")
    assert tuple(files[start:start + len(COMPOSER_SCRIPTS)]) == COMPOSER_SCRIPTS
    assert files.index("models.js") < start < files.index("components.js")
    components = (UI_DIR / "components.js").read_text(encoding="utf-8")
    assert "root.AgentUI = AgentUI" in components
    assert "mountComposer" in components
    for name in COMPOSER_SCRIPTS:
        text = (UI_DIR / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 800, name
        assert not re.search(r"^\s*(import|export)\b", text, re.M), name
        assert "globalThis.__acbComposer" in text


def test_ui_scripts_load_after_the_composer_and_stay_classic():
    files = list(UI_FILES)
    assert files[files.index("composer.js") + 1:files.index("stream.js")] == list(UI_SCRIPTS)
    components = (UI_DIR / "components.js").read_text(encoding="utf-8")
    assert "root.AgentUI = AgentUI" in components
    assert "mountComposer" in components
    for name in UI_SCRIPTS:
        text = (UI_DIR / name).read_text(encoding="utf-8")
        assert len(text.splitlines()) <= 800, name
        assert not re.search(r"^\s*(import|export)\b", text, re.M), name
    for name in UI_SCRIPTS[:-1]:
        assert "globalThis.__acbUi" in (UI_DIR / name).read_text(encoding="utf-8"), name


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_script_tags_publish_agent_ui_without_a_build():
    # Each classic script has its own scope. Node's vm shares one, so wrap the way a tag does.
    names = ",".join(repr(name) for name in (*MODEL_SCRIPTS, *COMPOSER_SCRIPTS, *UI_SCRIPTS))
    script = (
        "const fs=require('fs');const vm=require('vm');const path=require('path');"
        f"const dir={str(UI_DIR)!r};const ctx=vm.createContext({{console}});"
        "ctx.globalThis=ctx;ctx.window=ctx;"
        f"for (const name of [{names}]) {{"
        "const code=fs.readFileSync(path.join(dir,name),'utf8');"
        "vm.runInContext('(function(){\\n'+code+'\\n})()', ctx, {filename:name});}"
        "if (typeof ctx.AgentUI.mountComposer!=='function') process.exit(1);"
        "if (ctx.AgentUI.PERMISSION_MODES[0][0]!=='plan') process.exit(1);"
        "if (typeof ctx.AgentUI.mountModelsSettings!=='function') process.exit(1);"
        "if (typeof ctx.AgentUI.mountAgentsSettings!=='function') process.exit(1);"
        "if (ctx.AgentUI.slashQuery('/rev')!=='rev') process.exit(1);"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_script_tags_publish_agent_models_without_a_build():
    # Each classic script has its own scope. Node's vm shares one, so wrap the way a tag does.
    names = ",".join(repr(name) for name in MODEL_SCRIPTS)
    script = (
        "const fs=require('fs');const vm=require('vm');const path=require('path');"
        f"const dir={str(UI_DIR)!r};const ctx=vm.createContext({{console}});"
        "ctx.globalThis=ctx;ctx.window=ctx;"
        f"for (const name of [{names}]) {{"
        "const code=fs.readFileSync(path.join(dir,name),'utf8');"
        "vm.runInContext('(function(){\\n'+code+'\\n})()', ctx, {filename:name});}"
        "if (ctx.AgentModels.agentDisplayName({command:'opencode',name:'OpenCode'})!=='Open Router') process.exit(1);"
        "if (typeof ctx.AgentModels.modelMetrics!=='function') process.exit(1);"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_shared_page_file_is_in_the_package():
    for name in UI_FILES:
        path = UI_DIR / name
        assert path.is_file(), name
        assert path.stat().st_size > 0, name


def test_the_package_data_covers_the_shared_page_files():
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = config["tool"]["setuptools"]["package-data"]["agent_cli_bridge"]
    for name in UI_FILES:
        assert any(Path("ui", name).match(pattern) for pattern in patterns), name


# Layout knobs a host may set; every other custom property the shared CSS reads is a colour.
LAYOUT_PROPERTIES = {"--settings-nav-width", "--settings-pad"}


def test_the_palette_sets_every_colour_the_components_read():
    palette = (UI_DIR / "palette.css").read_text(encoding="utf-8")
    rule = re.search(r"^\.acb-ui \{(.*?)^\}", palette, re.S | re.M).group(1)
    defined = dict(re.findall(r"(--[a-z0-9-]+):\s*var\((--acb-[a-z0-9-]+),", rule))
    read = set()
    for name in ("chatbox.css", "settings.css"):
        read |= set(re.findall(r"var\((--[a-z0-9-]+)", (UI_DIR / name).read_text(encoding="utf-8")))
    missing = read - LAYOUT_PROPERTIES - set(defined)
    assert not missing, f"palette.css does not set {sorted(missing)}"
    # Each colour reads its own --acb-* override, with a default.
    assert all(override == "--acb-" + name[2:] for name, override in defined.items())


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("name", sorted(path.name for path in (ROOT / "tests" / "ui").glob("*.test.cjs")))
def test_the_shared_page_files_pass_their_node_tests(name):
    result = subprocess.run(
        ["node", "--test", str(ROOT / "tests" / "ui" / name)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
