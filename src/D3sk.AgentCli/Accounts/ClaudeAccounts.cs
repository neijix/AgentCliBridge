using System.Text.Json;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Accounts;

/// <summary>One account in <c>agent-accounts.json</c>: a folder id, a name and the agent commands added to it.</summary>
public sealed record AgentAccount(string Id, string Name, IReadOnlyList<string> Agents);

/// <summary>
/// The accounts of one node, read from its state folder: <c>agent-accounts.json</c> and
/// <c>accounts/&lt;id&gt;/.claude</c> (and the other CLIs' sub-folders). Same layout and same
/// cleaning as the Python app, because AI_token_status and the user's existing folders read it.
/// No account for a folder means the default account: the computer's own <c>~/.claude</c>.
/// </summary>
public sealed partial class ClaudeAccounts
{
    /// <summary>The rules file in the state folder.</summary>
    public const string FileName = "agent-accounts.json";
    /// <summary>The state sub-folder holding one folder per account.</summary>
    public const string HomesDir = "accounts";
    /// <summary>A rule value: the agent never runs in that folder.</summary>
    public const string Off = "off";
    /// <summary>Most accounts on one computer.</summary>
    public const int MaxAccounts = 16;
    /// <summary>Most folder rules kept.</summary>
    public const int MaxFolders = 64;
    /// <summary>Longest account name.</summary>
    public const int NameLimit = 40;

    /// <summary>This computer's route to Claude; an account's turn gets each one blank (read as unset).</summary>
    public static readonly IReadOnlyList<string> ClaudeRouteVariables =
    [
        "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN",
        "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_BETAS",
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
        "ANTHROPIC_BEDROCK_BASE_URL", "ANTHROPIC_VERTEX_BASE_URL", "ANTHROPIC_FOUNDRY_BASE_URL",
        "ANTHROPIC_FOUNDRY_RESOURCE", "ANTHROPIC_FOUNDRY_API_KEY", "ANTHROPIC_VERTEX_PROJECT_ID",
        "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
    ];

    /// <summary>The CLI flavors an account can hold, in the Python app's order.</summary>
    public static readonly IReadOnlyList<string> Flavors = ["claude", "copilot", "cursor", "gemini", "grok"];

    private static readonly Dictionary<string, string> FlavorOfAgent = new(StringComparer.Ordinal)
    {
        ["claude"] = "claude",
        ["copilot"] = "copilot",
        ["cursor-agent"] = "cursor",
        ["agent"] = "cursor",
        ["gemini"] = "gemini",
        ["grok"] = "grok",
    };

    private static readonly Dictionary<string, string[]> SignInByFlavor = new(StringComparer.Ordinal)
    {
        ["claude"] = ["auth", "login"],
        ["copilot"] = ["login"],
        ["cursor"] = ["login"],
        ["gemini"] = [],
        ["grok"] = ["login"],
    };

    [GeneratedRegex("^[a-z0-9][a-z0-9-]{0,31}$")]
    private static partial Regex IdPattern();

    [GeneratedRegex("^[a-z][a-z0-9-]{0,31}$")]
    private static partial Regex AgentPattern();

    private readonly string _stateDir;

    /// <summary>Reads the accounts under <paramref name="stateDir"/> (the node's state folder).</summary>
    public ClaudeAccounts(string stateDir) => _stateDir = stateDir;

    /// <summary>Every variable an account sets.</summary>
    public static IReadOnlyCollection<string> AccountVariables { get; } = BuildVariables();

    private static SortedSet<string> BuildVariables()
    {
        var names = new SortedSet<string>(StringComparer.Ordinal);
        foreach (var flavor in Flavors)
        {
            foreach (var name in EnvForFlavor(flavor, "/").Keys)
            {
                names.Add(name);
            }
        }
        return names;
    }

    /// <summary>The flavor whose sign-in an account can hold for the agent command, or <c>""</c>.</summary>
    public static string Flavor(string agent) => FlavorOfAgent.GetValueOrDefault(agent, "");

    /// <summary>The variables that move one CLI into an account's folder.</summary>
    public static IReadOnlyDictionary<string, string> EnvForFlavor(string flavor, string home)
    {
        var env = new Dictionary<string, string>(StringComparer.Ordinal);
        switch (flavor)
        {
            case "claude":
                foreach (var name in ClaudeRouteVariables)
                {
                    env[name] = "";
                }
                env["CLAUDE_CONFIG_DIR"] = Path.Combine(home, ".claude");
                break;
            case "copilot":
                env["COPILOT_HOME"] = Path.Combine(home, ".copilot");
                break;
            case "cursor":
                env["CURSOR_CONFIG_DIR"] = Path.Combine(home, ".cursor");
                env["CURSOR_DATA_DIR"] = Path.Combine(home, ".cursor");
                break;
            case "gemini":
                env["GEMINI_CLI_HOME"] = home;
                break;
            case "grok":
                env["GROK_HOME"] = Path.Combine(home, ".grok");
                break;
            default:
                throw new ArgumentException($"unknown flavor {flavor}", nameof(flavor));
        }
        return env;
    }

    /// <summary>The account's own folder, <c>accounts/&lt;id&gt;</c> under the state folder.</summary>
    public string Home(string account) => Path.Combine(_stateDir, HomesDir, account);

    /// <summary>The default account's Claude folder: this computer's own sign-in (<paramref name="userHome"/>/.claude).</summary>
    public static string DefaultClaudeDir(string userHome) => Path.Combine(userHome, ".claude");

    /// <summary>Creates the account's folder, private to the user on POSIX (0700), and returns it.</summary>
    public string EnsureHome(string account)
    {
        var home = Home(account);
        if (OperatingSystem.IsWindows())
        {
            Directory.CreateDirectory(home);
        }
        else
        {
            Directory.CreateDirectory(home, UnixFileMode.UserRead | UnixFileMode.UserWrite | UnixFileMode.UserExecute);
        }
        return home;
    }

    /// <summary>Every listed account whose folder exists (history readers look in each).</summary>
    public IReadOnlyList<string> Homes() =>
        [.. Load().Accounts.Select(a => Home(a.Id)).Where(Directory.Exists)];

    /// <summary>The account's <c>.claude</c> folders, one per existing account home.</summary>
    public IReadOnlyList<string> ClaudeDirs() =>
        [.. Homes().Select(h => Path.Combine(h, ".claude"))];

    /// <summary>The variables a turn of <paramref name="agent"/> in <paramref name="cwd"/> runs with.</summary>
    /// <exception cref="UnauthorizedAccessException">The agent is off in that folder.</exception>
    public IReadOnlyDictionary<string, string> TurnEnv(string agent, string cwd)
    {
        var value = Rule(agent, cwd);
        if (value == Off)
        {
            throw new UnauthorizedAccessException($"This agent is turned off for {cwd}.");
        }
        var flavor = Flavor(agent);
        if (value.Length == 0 || flavor.Length == 0)
        {
            return new Dictionary<string, string>();
        }
        return EnvForFlavor(flavor, EnsureHome(value));
    }

    /// <summary>The terminal command, environment and folder that sign an account in to an agent's CLI.</summary>
    public (IReadOnlyList<string> Args, IReadOnlyDictionary<string, string> Env, string Home) SignIn(string account, string agent)
    {
        if (!Load().Accounts.Any(a => a.Id == account && a.Agents.Contains(agent)))
        {
            throw new ArgumentException("No such account on this computer.");
        }
        var flavor = Flavor(agent);
        if (flavor.Length == 0)
        {
            throw new ArgumentException("This agent cannot use a second account.");
        }
        var home = EnsureHome(account);
        return (SignInByFlavor[flavor], EnvForFlavor(flavor, home), home);
    }

    /// <summary>The deepest folder rule that holds <paramref name="cwd"/>: <c>""</c> (default account), <c>off</c> or an id.</summary>
    public string Rule(string agent, string cwd)
    {
        var data = Load();
        var place = Comparable(cwd);
        var best = "";
        var value = "";
        foreach (var (folder, rules) in data.Folders)
        {
            if (rules.TryGetValue(agent, out var v) && Holds(Comparable(folder), place) && folder.Length > best.Length)
            {
                best = folder;
                value = v;
            }
        }
        return value;
    }

    /// <summary>The file as this node trusts it: known shapes only, anything else dropped; unreadable = empty.</summary>
    public AccountsFile Load()
    {
        try
        {
            using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(_stateDir, FileName)));
            return Clean(doc.RootElement);
        }
        catch (Exception e) when (e is IOException or JsonException or UnauthorizedAccessException)
        {
            return new AccountsFile([], new Dictionary<string, IReadOnlyDictionary<string, string>>());
        }
    }

    private static AccountsFile Clean(JsonElement root)
    {
        var accounts = new List<(string Id, string Name, List<string>? Agents)>();
        if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("accounts", out var list) && list.ValueKind == JsonValueKind.Array)
        {
            foreach (var item in list.EnumerateArray())
            {
                var id = Str(item, "id");
                if (item.ValueKind != JsonValueKind.Object || !IdPattern().IsMatch(id) || accounts.Any(a => a.Id == id))
                {
                    continue;
                }
                var name = Str(item, "name").Trim();
                name = name.Length == 0 ? id : name[..Math.Min(name.Length, NameLimit)];
                List<string>? agents = null;
                if (item.TryGetProperty("agents", out var raw) && raw.ValueKind == JsonValueKind.Array)
                {
                    agents = [.. raw.EnumerateArray()
                        .Where(a => a.ValueKind == JsonValueKind.String)
                        .Select(a => a.GetString()!)
                        .Where(a => AgentPattern().IsMatch(a) && Flavor(a).Length > 0)
                        .Distinct()];
                }
                accounts.Add((id, name, agents));
            }
        }
        accounts = accounts.Take(MaxAccounts).ToList();
        var ids = accounts.Select(a => a.Id).ToHashSet();
        var folders = new Dictionary<string, IReadOnlyDictionary<string, string>>();
        if (root.ValueKind == JsonValueKind.Object && root.TryGetProperty("folders", out var raws) && raws.ValueKind == JsonValueKind.Object)
        {
            foreach (var entry in raws.EnumerateObject())
            {
                var kept = CleanRules(entry.Value, ids);
                if (kept.Count > 0 && Path.IsPathRooted(entry.Name) && folders.Count < MaxFolders)
                {
                    folders[entry.Name] = kept;
                }
            }
        }
        // Saved before accounts named their agents: the ones its folders use.
        var result = accounts.Select(a => new AgentAccount(a.Id, a.Name,
            a.Agents ?? [.. folders.Values.SelectMany(r => r).Where(p => p.Value == a.Id).Select(p => p.Key).Distinct().Order(StringComparer.Ordinal)])).ToList();
        return new AccountsFile(result, folders);
    }

    private static Dictionary<string, string> CleanRules(JsonElement rules, HashSet<string> ids)
    {
        var kept = new Dictionary<string, string>();
        if (rules.ValueKind != JsonValueKind.Object)
        {
            return kept;
        }
        foreach (var rule in rules.EnumerateObject())
        {
            var value = rule.Value.ValueKind == JsonValueKind.String ? rule.Value.GetString()! : "";
            if (AgentPattern().IsMatch(rule.Name) && (value == Off || (ids.Contains(value) && Flavor(rule.Name).Length > 0)))
            {
                kept[rule.Name] = value;
            }
        }
        return kept;
    }

    private static string Str(JsonElement item, string name) =>
        item.ValueKind == JsonValueKind.Object && item.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() ?? "" : "";

    private static string Comparable(string path)
    {
        var text = path.Replace('\\', '/').TrimEnd('/');
        return OperatingSystem.IsWindows() ? text.ToLowerInvariant() : text;
    }

    private static bool Holds(string folder, string path) =>
        path == folder || path.StartsWith(folder + "/", StringComparison.Ordinal);
}

/// <summary>The cleaned <c>agent-accounts.json</c>: accounts and the per-folder rules (agent to account id or <c>off</c>).</summary>
public sealed record AccountsFile(
    IReadOnlyList<AgentAccount> Accounts,
    IReadOnlyDictionary<string, IReadOnlyDictionary<string, string>> Folders);
