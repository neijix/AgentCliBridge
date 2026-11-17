# Changelog

The C# line on `main`, tagged `dotnet-v<semver>`. The Python line lives on the `python` branch
with its own `v*` tags; this file does not cover it.

## [dotnet-v0.7.0] — 2026-11-17

### Added
- `ArtificialAnalysisApi`: the Artificial Analysis data API v2 model list (`/api/v2/language/models/free`,
  any key tier). `PageRequest(apiKey, page)` builds an authenticated GET; `ReadAll(fetchPage)` reads every
  page (at most `MaxPages`) into one `MetricsTable`. The host owns the transport and the key, and credits
  Artificial Analysis where it shows the figures. It rates models the leaderboard page leaves out
  (Beam 1.0, GLM-5.3-Flash, Nemotron 3.5 Super VL, DeepSeek V4.1 Flash 1017, ...).
- `ModelRanking.ParseLeaderboard` also reads one API v2 page (`{"data": [...]}`, the index under
  `evaluations`, the speed under `performance`).

### Changed
- The page files follow the Python line's `agent_cli_bridge/ui/` at rev `a379df29`: the components'
  buttons (`.acb-btn`) are styled once, in `palette.css`, instead of in both `chatbox.css` and
  `settings.css`; `stream.js` keeps its names private in a block instead of a wrapper function.
  A host that shows the chat box or Settings › Models / Agents already loads `palette.css`.

## [dotnet-v0.5.0] — 2026-11-15

### Added
- The package carries the 19 web page files (`chatbox.css`, `components.js`, `composer.js`, ... `stream.js`),
  byte-identical to the Python line's `agent_cli_bridge/ui/` at rev `8ed5e7c`. A project referencing
  the package finds them as files under `acb/` in its build and publish output
  (`buildTransitive/D3sk.AgentCli.targets`; `<CopyAgentCliPageFiles>false</CopyAgentCliPageFiles>` opts out).
- The UI tests (`tests/ui/*.test.cjs`, run against `src/D3sk.AgentCli/ui`) and a `node --test` step in `check.sh` / `check.ps1`.

### Changed
- Claude Code's curated list includes `claude-fable-5-2` (Fable 5.2); the `fable` alias maps to that family for ranking and effort. Cursor's shortlist includes `claude-fable-5-2-high`.

## [dotnet-v0.4.0] — 2026-11-14

### Added
- `ClaudeGateway.Url(home, env)` and `ClaudeGateway.Headers(home, env)`: the company gateway a Claude
  home talks to and the headers Claude Code sends it (`GatewayHeaders`, an ordered, case-insensitive
  map; the token or API key replaces a custom header of the same name).
- `ClaudeAccountKind.Of(home, env)`: which account a Claude home runs on — `personal` or `work`
  (gateway, cloud provider, Team/Enterprise) — with a short detail.
- `CatalogIo.FetchJson(url, headers)` and a `ModelCatalog` constructor whose fetch takes the headers.

### Changed
- `ModelCatalog.Refresh` takes an optional `claudeGatewayHeaders`. They are sent only over https;
  a plain-http gateway, loopback included, is read without credentials as before. Source-compatible;
  a consumer built against 0.3.0 must recompile.

### Fixed
- A Claude gateway that never answers no longer throws out of `ModelCatalog.Refresh`: it counts as
  unreachable and is asked again a minute later.
- A gateway header value that is not ASCII is refused before the request (a catalog failure, retried
  later) instead of failing as an unreachable network.
- A leading `~` in `CLAUDE_CONFIG_DIR` is the given home, as Python `expanduser` reads it.

## [dotnet-v0.3.0] — 2026-11-13

### Changed
- The local model client names D3SKMODEL: keychain entry `d3sk/d3skmodel` (account `d3skmodel`),
  socket `~/.d3skmodel/api.sock`, and messages that say `d3skmodel setup`.
- Antigravity: the auto and don't-ask modes run `--mode auto` (accept-edits still asked before a
  terminal command, which print mode soft-denied).
- The publish workflow also targets nuget.org, by Trusted Publishing (no stored key).

## [dotnet-v0.2.0] — 2026-11-07

### Added
- `Notice(Text, Kind)` stream event: a display-only note for the person watching, never part of the
  reply and never saved. Wire frame `notice` (`message`, optional `notice_kind`).
- `MlxChat` yields a `Notice` ("Loading {model}…", kind `loading`) when the server has not begun
  answering within `MlxOptions.LoadNoticeDelay` (default 2 s). Additive: no existing event changes.

## [dotnet-v0.1.0] — 2026-11-04

First release of `D3sk.AgentCli`, the C# port of AgentCliBridge's CLI runner.

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
