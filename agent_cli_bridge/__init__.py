"""AgentCliBridge — local AI coding CLIs as streaming chat backends.

Official binaries, documented headless flags, your own logins. See README.md
for the compliance stance and the event-stream contract.
"""

from .argv import (
    DEFAULT_PERMISSION_MODE,
    PERMISSION_MODES,
    build_argv,
    compose_prompt,
    model_args,
    normalize_permission_mode,
    permission_args,
)
from .control import TurnInput, supports_live_input
from .events import (
    ActionBlocked,
    ApprovalRequest,
    Completed,
    InjectionDetected,
    InputAccepted,
    ModeChanged,
    SessionUpdate,
    StreamError,
    StreamEvent,
    TextDelta,
    ThinkingDelta,
    ToolCall,
    ToolResult,
)
from .host import AgentHost
from .injection_guard import POLICY_TEXT, Finding, InjectionGuard, is_injection, scan_text
from .runner import run_agent
from .security_log import SecurityLog
from .specs import (
    CLI_AGENT_SPECS,
    CliAgentSpec,
    app_installed,
    apps_config_dir,
    available_agents,
    bridge_checkout,
    cli_agent_spec,
    config_local_dir,
    config_path,
    discover_agents,
    flavor_for,
    is_available,
    is_cursor_grok_collision,
    resolve_binary,
)
from .web_scout import WebScout

__version__ = "0.3.0"

__all__ = [
    "ActionBlocked",
    "AgentHost",
    "ApprovalRequest",
    "CLI_AGENT_SPECS",
    "CliAgentSpec",
    "Completed",
    "DEFAULT_PERMISSION_MODE",
    "Finding",
    "InjectionDetected",
    "InjectionGuard",
    "InputAccepted",
    "ModeChanged",
    "PERMISSION_MODES",
    "POLICY_TEXT",
    "TurnInput",
    "WebScout",
    "SecurityLog",
    "SessionUpdate",
    "StreamError",
    "StreamEvent",
    "TextDelta",
    "ThinkingDelta",
    "ToolCall",
    "ToolResult",
    "app_installed",
    "apps_config_dir",
    "available_agents",
    "bridge_checkout",
    "build_argv",
    "cli_agent_spec",
    "compose_prompt",
    "config_local_dir",
    "config_path",
    "discover_agents",
    "flavor_for",
    "is_available",
    "is_cursor_grok_collision",
    "is_injection",
    "model_args",
    "normalize_permission_mode",
    "permission_args",
    "resolve_binary",
    "run_agent",
    "scan_text",
    "supports_live_input",
]
