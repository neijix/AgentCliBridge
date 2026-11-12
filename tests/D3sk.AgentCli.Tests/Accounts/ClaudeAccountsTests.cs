using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;
using D3sk.AgentCli.Accounts;

namespace D3sk.AgentCli.Tests.Accounts;

/// <summary>Equal to row 7's layout fixture (d3skhand tests/fixtures/contracts/accounts_layout.json).</summary>
public sealed class ClaudeAccountsTests : IDisposable
{
    private readonly string _tmp = Path.Combine(Path.GetTempPath(), "acct-" + Guid.NewGuid().ToString("N"));

    public ClaudeAccountsTests() => Directory.CreateDirectory(_tmp);

    public void Dispose() => Directory.Delete(_tmp, true);

    private static string Root()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "global.json")))
        {
            dir = dir.Parent;
        }
        return dir?.FullName ?? throw new InvalidOperationException("repo root not found");
    }

    private JsonNode Golden() =>
        JsonNode.Parse(File.ReadAllText(Path.Combine(Root(), "tests", "fixtures", "contracts", "accounts_layout.json")).Replace("<TMP>", _tmp.Replace('\\', '/')))!;

    private static JsonNode Dict(IEnumerable<KeyValuePair<string, string>> pairs) =>
        new JsonObject(pairs.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)JsonValue.Create(p.Value))));

    private static JsonArray Strings(IEnumerable<string> items) => new(items.Select(s => (JsonNode?)JsonValue.Create(s)).ToArray());

    /// <summary>The state folder as the Python app leaves it after its steps: file written, homes created.</summary>
    private (ClaudeAccounts Accounts, string Work, string State) Layout()
    {
        var state = Path.Combine(_tmp, "state");
        var work = Path.Combine(_tmp, "Code", "Work").Replace('\\', '/');
        Directory.CreateDirectory(work);
        Directory.CreateDirectory(state);
        File.WriteAllText(Path.Combine(state, "agent-accounts.json"), Golden()["agent_accounts_json"]!.ToJsonString());
        var accounts = new ClaudeAccounts(state);
        foreach (var id in new[] { "work", "perso-two" })
        {
            accounts.EnsureHome(id);
        }
        return (accounts, work, state);
    }

    [Fact]
    [Trait("Preserve", "P37")]
    public void Layout_equals_the_golden()
    {
        var (accounts, work, state) = Layout();
        var golden = Golden();

        Assert.Equal(golden["account_homes"]!.ToJsonString(),
            Strings(Directory.GetDirectories(Path.Combine(state, "accounts")).Select(Path.GetFileName).Order(StringComparer.Ordinal)!).ToJsonString());
        Assert.Equal(golden["state_files"]!.ToJsonString(),
            Strings(Directory.GetFileSystemEntries(state).Select(Path.GetFileName).Order(StringComparer.Ordinal)!).ToJsonString());
        Assert.Equal(golden["flavors"]!.ToJsonString(), Strings(ClaudeAccounts.Flavors).ToJsonString());
        Assert.Equal(golden["account_variables"]!.ToJsonString(), Strings(ClaudeAccounts.AccountVariables).ToJsonString());

        var loaded = accounts.Load();
        var file = new JsonObject
        {
            ["accounts"] = new JsonArray(loaded.Accounts.Select(a => (JsonNode?)new JsonObject
            {
                ["id"] = a.Id,
                ["name"] = a.Name,
                ["agents"] = Strings(a.Agents),
            }).ToArray()),
            ["folders"] = new JsonObject(loaded.Folders.Select(f => KeyValuePair.Create(f.Key, (JsonNode?)Dict(f.Value)))),
        };
        Assert.True(JsonNode.DeepEquals(golden["agent_accounts_json"], file), file.ToJsonString());

        var env = Dict(accounts.TurnEnv("claude", work));
        Assert.True(JsonNode.DeepEquals(golden["claude_env"], env), env.ToJsonString());
        Assert.Empty(accounts.TurnEnv("cursor-agent", work));
        Assert.Equal("{}", golden["cursor_env_default"]!.ToJsonString());

        var signIn = accounts.SignIn("work", "claude");
        Assert.Equal(golden["sign_in_claude"]![0]!.ToJsonString(), Strings(signIn.Args).ToJsonString());
        Assert.True(JsonNode.DeepEquals(golden["sign_in_claude"]![1], Dict(signIn.Env)));
    }

    [Fact]
    [Trait("Preserve", "P37")]
    public void Homes_lists_each_existing_account_folder_and_claude_sits_inside()
    {
        var (accounts, _, state) = Layout();
        Assert.Equal(
            [Path.Combine(state, "accounts", "perso-two"), Path.Combine(state, "accounts", "work")],
            accounts.Homes().Order(StringComparer.Ordinal));
        Assert.Equal(Path.Combine(state, "accounts", "work", ".claude"), accounts.ClaudeDirs().Single(d => d.Contains("work")));
        Assert.Equal(Path.Combine("/h", ".claude"), ClaudeAccounts.DefaultClaudeDir("/h"));
    }

    [Fact]
    [Trait("Security", "off-rule")]
    public void A_turn_of_an_agent_turned_off_in_the_folder_is_refused()
    {
        var (accounts, work, _) = Layout();
        Assert.Throws<UnauthorizedAccessException>(() => accounts.TurnEnv("copilot", work));
        Assert.Throws<UnauthorizedAccessException>(() => accounts.TurnEnv("copilot", work + "/sub"));
    }

    [Fact]
    public void Home_is_private_on_posix()
    {
        if (OperatingSystem.IsWindows())
        {
            return;
        }
        var (accounts, _, _) = Layout();
        Assert.Equal("0o700", "0o" + Convert.ToString((int)File.GetUnixFileMode(accounts.Home("work")) & 0x1FF, 8));
    }

    [Fact]
    public void Unreadable_or_missing_file_means_the_default_account_and_bad_entries_are_dropped()
    {
        var state = Path.Combine(_tmp, "s2");
        Directory.CreateDirectory(state);
        var accounts = new ClaudeAccounts(state);
        Assert.Empty(accounts.Load().Accounts);
        File.WriteAllText(Path.Combine(state, "agent-accounts.json"), "{nope");
        Assert.Empty(accounts.Load().Accounts);
        Assert.Equal("", accounts.Rule("claude", _tmp));
        File.WriteAllText(Path.Combine(state, "agent-accounts.json"), JsonSerializer.Serialize(new
        {
            accounts = new object[] { new { id = "../evil", name = "x" }, new { id = "ok", name = "Ok", agents = new[] { "claude", "mlx" } } },
            folders = new Dictionary<string, object> { ["relative"] = new { claude = "ok" }, ["/abs"] = new { claude = "ghost", mlx = "off" } },
        }));
        var data = accounts.Load();
        Assert.Equal("ok", data.Accounts.Single().Id);
        Assert.Equal(["claude"], data.Accounts.Single().Agents);
        Assert.Equal("off", data.Folders["/abs"]["mlx"]);
        Assert.False(data.Folders["/abs"].ContainsKey("claude"));
        Assert.False(data.Folders.ContainsKey("relative"));
    }

    [Fact]
    public void Copied_contract_fixtures_match_their_manifest()
    {
        var dir = Path.Combine(Root(), "tests", "fixtures", "contracts");
        var listed = new HashSet<string>();
        foreach (var line in File.ReadAllLines(Path.Combine(dir, "manifest.txt")).Where(l => l.Length > 66 && l[0] != '#'))
        {
            var name = line[66..];
            listed.Add(name);
            Assert.Equal(line[..64], Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(Path.Combine(dir, name)))));
        }
        Assert.Equal(
            Directory.GetFiles(dir).Select(Path.GetFileName).Where(n => n != "manifest.txt").Order(StringComparer.Ordinal),
            listed.Order(StringComparer.Ordinal));
    }
}
