"""AgentCliBridge's setup wizard and release tooling.

Not part of the library: the wheel ships only ``agent_cli_bridge`` (pyproject ``packages.find``),
so the apps that pin the bridge in their ``uv.lock`` never see this package. Stdlib only: the
wizard runs before the gateway's venv exists.
"""

APP = "agentclibridge"  # file and package names: agentclibridge-<version>-<os>-<arch><suffix>
DISPLAY_NAME = "AgentCliBridge"
MANIFEST_NAME = "agentclibridge-snapshot.json"
PYTHON_VERSION = "3.12"  # what packaging/setup.sh and setup.ps1 install with uv
DEFAULT_PORT = 4747
INSTALL_DIR_ENV = "AGENT_CLI_BRIDGE_INSTALL_DIR"  # start.sh / start.ps1 read it
SETUP_UV_ENV = "AGENT_CLI_BRIDGE_SETUP_UV"  # the uv setup.sh / setup.ps1 found or fetched
