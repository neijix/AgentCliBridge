# config.local/ (example)

AgentCliBridge reads its optional settings from a `config.local/` folder beside this one, in the
bridge's own checkout. Every app built on the bridge (run from a sibling checkout) reads that same
file. The folder is gitignored, and nothing creates it on its own: without it you get every
installed CLI with the built-in model lists.

```
config.local/
└── agent_cli_bridge.json   # {"disabled_agents": [...], "models": {"<command or flavor>": [...]}}
```

- `disabled_agents`: commands or flavors never listed or offered (e.g. `["gemini"]`).
- `models`: per command or flavor, replaces the built-in model list.

Signing in to a disabled CLI from an app drops it from `disabled_agents` in this same file. No
secrets go there.

- To use another folder, set `AGENT_CLI_BRIDGE_CONFIG_LOCAL=/path/to/folder`.
- `AGENT_CLI_BRIDGE_CONFIG_LOCAL=none` ignores `config.local/`: only `~/.agent_cli_bridge.json`
  (this computer only) is read, else the defaults.
