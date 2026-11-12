# Changelog

The C# line on `main`, tagged `dotnet-v<semver>`. The Python line lives on the `python` branch
with its own `v*` tags; this file does not cover it.

## [dotnet-v0.2.0] — 2026-11-07

### Added
- `Notice(Text, Kind)` stream event: a display-only note for the person watching, never part of the
  reply and never saved. Wire frame `notice` (`message`, optional `notice_kind`).
- `MlxChat` yields a `Notice` ("Loading {model}…", kind `loading`) when the server has not begun
  answering within `MlxOptions.LoadNoticeDelay` (default 2 s). Additive: no existing event changes.

## [dotnet-v0.1.0] — 2026-11-04

First release of `D3sk.AgentCli`, the C# port of AgentCliBridge's CLI runner, for D3SKHAND.

### Added
- Child turn runner: spawn with a given environment only, line streaming, result grace, timeout,
  process-tree kill, stderr tail; host-built child environment with prefix drops and shims.
- Agent specs, argv and stdout parsers for Claude Code, Cursor Agent, Gemini CLI, Antigravity,
  Copilot, Grok and OpenCode, equal to the Python line's frozen `v0.3.0` stream captures.
- Agent registry, availability rules and one run-a-turn entry returning the event stream.
- Live control: approvals, AskUserQuestion answers, mode switches and input while running.
- Injection guard with a stop event and a private security log.
- Claude accounts, per-CLI sign-in flows and the auth-expired signal.
- CLI status (installed and newest versions), install, update and uninstall through saved
  vendor installers.
- Model catalog (lists, merge, cache, TTLs, effort flags) and ranking with display names and prices.
- Web scout and local MLX clients over keyed user-only channels, never plain HTTP; Strata counts
  as a local model.
