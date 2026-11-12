using System.Text.Json;
using D3sk.AgentCli.ChildEnv;

namespace D3sk.AgentCli.Login;

/// <summary>
/// Copilot CLI has no status command. It is signed in by its own login (<c>logged_in_users</c> in
/// <c>~/.copilot/config.json</c>), a token in the environment, or the GitHub CLI's login.
/// </summary>
public static class CopilotSignIn
{
    private static readonly string[] TokenVariables = ["COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"];

    /// <summary>True / false, or null when Copilot's config cannot be read and nothing else says yes.</summary>
    public static async Task<bool?> IsSignedInAsync(ILoginHost host, string home, TimeSpan statusTimeout, CancellationToken ct)
    {
        var env = host.Environment;
        if (TokenVariables.Any(name => env.TryGetValue(name, out var value) && value.Length > 0))
        {
            return true;
        }
        var folder = env.TryGetValue("COPILOT_HOME", out var set) && set.Length > 0 ? set : Path.Combine(home, ".copilot");
        var fromConfig = ConfigUsers(folder);
        if (fromConfig == true)
        {
            return true;
        }
        return await GhIsSignedInAsync(host, statusTimeout, ct).ConfigureAwait(false) ? true : fromConfig;
    }

    /// <summary><c>logged_in_users</c> in Copilot's config (JSON under <c>//</c> comment lines); null if unreadable.</summary>
    internal static bool? ConfigUsers(string folder)
    {
        string text;
        try
        {
            text = string.Concat(File.ReadLines(Path.Combine(folder, "config.json")).Where(l => !l.TrimStart().StartsWith("//", StringComparison.Ordinal)).Select(l => l + "\n"));
        }
        catch (Exception e) when (e is FileNotFoundException or DirectoryNotFoundException)
        {
            return false; // never launched
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return null;
        }
        try
        {
            if (string.IsNullOrWhiteSpace(text))
            {
                return false;
            }
            using var doc = JsonDocument.Parse(text);
            return doc.RootElement.ValueKind == JsonValueKind.Object
                && doc.RootElement.TryGetProperty("logged_in_users", out var users)
                && users.ValueKind == JsonValueKind.Array
                && users.GetArrayLength() > 0;
        }
        catch (JsonException)
        {
            return null;
        }
    }

    // `gh auth token` would print the token, so it is never asked: only the exit code of `status`.
    private static async Task<bool> GhIsSignedInAsync(ILoginHost host, TimeSpan timeout, CancellationToken ct)
    {
        host.Environment.TryGetValue("PATH", out var path);
        var gh = CliTools.Which("gh", path);
        if (gh is null)
        {
            return false;
        }
        try
        {
            var done = await host.RunAsync([gh, "auth", "status", "--hostname", "github.com"], timeout, ct).ConfigureAwait(false);
            return done.ExitCode == 0;
        }
        catch (Exception e) when (e is IOException or System.ComponentModel.Win32Exception or TimeoutException)
        {
            return false;
        }
    }
}
