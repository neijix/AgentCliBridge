using D3sk.AgentCli.Control;
using D3sk.AgentCli.Security;
using D3sk.AgentCli.WebScout;

namespace D3sk.AgentCli.Host;

/// <summary>A request with the web policy and the guard applied, and the pieces that watch the turn.</summary>
/// <param name="Request">The request to launch.</param>
/// <param name="Watch">The wrapper of the host stream; null when nothing watches the turn.</param>
/// <param name="Live">The live plumbing, or null.</param>
internal sealed record ArmedTurn(AgentTurnRequest Request, TurnGuard? Watch, LiveTurn? Live);

/// <summary>Applies a turn's defaults: web scout policy, injection guard, security log and live input.</summary>
internal static class TurnArming
{
    /// <summary>
    /// The request for <paramref name="flavor"/> with the scout's arguments, briefing and PATH, the guard's policy and
    /// the tool events the guard and the log need. The scout's settings merge into one <c>--settings</c>.
    /// </summary>
    internal static ArmedTurn Arm(AgentTurnRequest r, string flavor)
    {
        var guard = r.NoGuard ? null : r.Guard ?? new InjectionGuard();
        var scout = r.NoWebScout ? null : r.WebScout ?? new ScoutPolicy();
        var log = r.NoSecurityLog ? null : r.SecurityLog ?? new SecurityLog();
        var recorder = log?.Turn(r.Command, r.Model, r.Cwd);
        var live = LiveTurn.For(r.Input, flavor);
        var isLive = live is not null;

        var armed = r;
        if (scout is not null && ScoutPolicy.IsEnforced(flavor))
        {
            var args = scout.CliArgs(flavor, isLive, !isLive || r.AllowedTools is not null);
            armed = armed with
            {
                CliArgs = SettingsArgs.Merge([.. r.CliArgs, .. args]),
                SystemText = scout.SystemText(flavor, r.SystemText),
                ExtraEnv = scout.MergeEnv(flavor, r.Env, r.ExtraEnv),
            };
        }
        else
        {
            scout = null;
        }
        if (guard is not null)
        {
            armed = armed with { SystemText = guard.SystemText(armed.SystemText) };
        }
        var watch = guard is null && recorder is null && live is null
            ? null
            : new TurnGuard(guard, scout, recorder, live?.Input, isLive, r.Activity);
        return new ArmedTurn(armed with { Activity = r.Activity || guard is not null || recorder is not null }, watch, live);
    }
}
