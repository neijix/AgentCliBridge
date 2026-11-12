"""The front-end files every host page shares, shipped as package data in ``agent_cli_bridge/ui/``.

- Model scripts, in the order a host loads them: ``model_names.js``, ``model_ranking.js``,
  ``model_tags.js``, ``model_picker.js``, ``model_catalog.js``, ``model_effort.js``,
  ``model_agents.js``, then ``models.js``. ``models.js`` defines ``window.AgentModels`` (no build
  step) from the scripts before it: names, ranking, tags, the picker, the Settings catalog,
  effort, and which CLIs a page can sign in.
- Composer scripts, loaded after the model scripts: ``composer_menu.js`` then ``composer.js``.
  Classic scripts (no build step). They register the chat box on ``globalThis.__acbComposer``.
- UI scripts, loaded after the composer and before ``stream.js``: ``icons.js``,
  ``permission_modes.js``, ``settings_models.js``, ``settings_agents.js``, then ``components.js``.
  Classic scripts (no build step). The first four register on ``globalThis.__acbUi``;
  ``components.js`` publishes ``window.AgentUI`` — the chat box (``mountComposer``), Settings ›
  Models (``mountModelsSettings``) and Settings › Agents (``mountAgentsSettings``). Needs
  ``models.js`` and the composer scripts first.
- ``stream.js``: the chat event stream — the SSE parser, the fetch reader and the fold into message
  parts, matching ``agent_cli_bridge/wire.py`` (``window.AgentStream``; no dependency).
- ``chatbox.css``: the chat box — the message, its controls inside along the bottom — and its
  Web search dialog.
- ``settings.css``: the Settings page (nav, categories, cards), Settings › Agents and › Models.
- ``palette.css``: the components' own colours and type (on ``.acb-ui``), so a page's theme
  cannot make them look different from one app to the next.

A host serves ``UI_DIR`` as static files (mounted at ``/acb``) and loads them before its own
script and stylesheet; it gives the components their data and actions, never their look.
"""

from pathlib import Path

UI_DIR = Path(__file__).resolve().parent / "ui"
UI_FILES = (
    "model_names.js",
    "model_ranking.js",
    "model_tags.js",
    "model_picker.js",
    "model_catalog.js",
    "model_effort.js",
    "model_agents.js",
    "models.js",
    "composer_menu.js",
    "composer.js",
    "icons.js",
    "permission_modes.js",
    "settings_models.js",
    "settings_agents.js",
    "components.js",
    "stream.js",
    "chatbox.css",
    "settings.css",
    "palette.css",
)
