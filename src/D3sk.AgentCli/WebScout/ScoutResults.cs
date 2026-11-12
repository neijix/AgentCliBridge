namespace D3sk.AgentCli.WebScout;

/// <summary>Where the scout's key comes from. The caller reads it from the OS keychain; nothing here stores or logs it.</summary>
public interface IScoutKeySource
{
    /// <summary>The keychain entry the scout's key is stored under.</summary>
    public const string EntryName = "d3sk/webscout";

    /// <summary>The key, or null when there is none.</summary>
    public string? ReadKey();
}

/// <summary>The outcome of one scout call; a caller matches on the type.</summary>
public abstract record ScoutResult;

/// <summary>The scout answered; <paramref name="Json"/> is its JSON body, untrusted web content inside.</summary>
public sealed record ScoutOk(string Json) : ScoutResult;

/// <summary>
/// The scout offers no keyed endpoint (plain http only, or no key check) and was not called with a
/// key. The views show it as a "service needs update" banner naming <paramref name="Service"/>.
/// </summary>
public sealed record ScoutNeedsUpdate(string Service, string Reason) : ScoutResult
{
    /// <summary>The service name the banner shows.</summary>
    public const string ServiceName = "web scout";
}

/// <summary>Nothing answers: the scout is not running or not installed (the shell client's <c>service_down</c>).</summary>
public sealed record ScoutDown(string Reason) : ScoutResult;

/// <summary>The keychain holds no key for the scout; nothing was sent.</summary>
public sealed record ScoutKeyMissing : ScoutResult;

/// <summary>The scout refused the key (401 or 403).</summary>
public sealed record ScoutKeyRejected : ScoutResult;

/// <summary>The client refused the transport: a socket others can reach, or an address that is not user-only.</summary>
public sealed record ScoutRefused(string Reason) : ScoutResult;

/// <summary>The scout answered with an error status other than a key refusal; <paramref name="Json"/> is its body.</summary>
public sealed record ScoutFailed(int Status, string Json) : ScoutResult;
