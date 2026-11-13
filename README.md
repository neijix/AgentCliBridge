# AgentCliBridge

> **Python frozen at `v0.3.0`: fixes only.** Python gateway fixes stay on the `python` branch
> (`v0.3.x` tags) for the apps that pin that tag. `main` is now C#: the `D3sk.AgentCli.Usage`
> library and the AgentCli Usage app, plus the C# CLI runner `D3sk.AgentCli`, moved there from
> AgentCliBridge.Net (archived).

Use the AI coding CLIs you already pay for — Claude Code, Cursor Agent, Gemini CLI, Antigravity,
Grok, Copilot and OpenCode — from your own apps, as if they were APIs. The Python gateway and its
installer are on the [`python`](https://github.com/neijix/AgentCliBridge/tree/python) branch.

## D3sk.AgentCli

`D3sk.AgentCli` runs the AI coding
CLIs (Claude Code, Cursor, Gemini, Copilot, Grok, OpenCode) and folds their output streams into
typed events. Package `D3sk.AgentCli`.

### Frozen fixtures

`tests/streams` and `tests/wire` are byte-for-byte copies of this repo's Python line at tag `v0.3.0`
(commit `e493c737baee2e11621ea80199ef332f48c3b7f0`). `tests/frozen-manifest.txt` records the tag
and each file's SHA-256; `FrozenFixturesTests` fails when a file differs, is missing or is extra.
Never edit those files: a new capture goes in a new folder with its own manifest entry.

### Build and test

Needs the .NET 10 SDK (`global.json`).

```bash
dotnet test D3sk.AgentCli.slnx
dotnet pack src/D3sk.AgentCli -c Release
```

Restoring this repo needs no credential: it has no `D3sk.*` dependency yet.

### Install the package

The package is published to GitHub Packages, which needs a token even for a public package: a
classic personal access token with `read:packages`. Copy this repo's `nuget.config` into the
consuming repo, then set the credential in the environment, never in a file:

```bash
export NuGetPackageSourceCredentials_github="Username=<github-login>;Password=<token>"
```

In GitHub Actions use the job's `GITHUB_TOKEN` with `permissions: packages: read`.

### Release

Tag `dotnet-vX.Y.Z` (never `vX.Y.Z`: those are the Python line's, and its updater reads the
Latest release, so a C# release is never marked Latest), or run `publish.yml` by hand on an
existing tag (`gh workflow run publish.yml -f tag=dotnet-vX.Y.Z`). `.github/workflows/publish.yml`
tests, packs `D3sk.AgentCli` with that version and pushes it to
`https://nuget.pkg.github.com/neijix/index.json` with the job's `GITHUB_TOKEN`, and to nuget.org by
[Trusted Publishing](https://learn.microsoft.com/nuget/nuget-org/trusted-publishing). No API key is
stored: the account that owns the package adds a policy (nuget.org → user name → Trusted Publishing)
with this repository's owner, the repository name and the workflow file `publish.yml`. The job logs
in as the repository owner, or as the repository variable `NUGET_USER` when set.

## Licence

MIT, see `LICENSE`.
