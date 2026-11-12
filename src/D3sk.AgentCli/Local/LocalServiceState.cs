namespace D3sk.AgentCli.Local;

/// <summary>Whether a local service can be called now, and if not, why.</summary>
public enum LocalServiceStatus
{
    /// <summary>A keyed, user-only endpoint answered and refused a request without the key.</summary>
    Ready,

    /// <summary>The service offers no keyed endpoint (plain HTTP only, no key check, or an unsafe socket): it must be upgraded. Never retried over plain HTTP.</summary>
    NeedsUpdate,

    /// <summary>Nothing answers on this computer.</summary>
    NotRunning,

    /// <summary>The keychain holds no key for the service yet.</summary>
    NoKey,
}

/// <summary>The typed result of reaching a local service; the views show <see cref="LocalServiceStatus.NeedsUpdate"/> as a banner naming <see cref="Service"/>.</summary>
/// <param name="Status">What was found.</param>
/// <param name="Service">The service's display name, for example <c>MLX</c>.</param>
/// <param name="Detail">One sentence for the owner; never contains the key.</param>
public sealed record LocalServiceState(LocalServiceStatus Status, string Service, string Detail)
{
    /// <summary>The <c>StreamError</c> code of a turn that stopped because the service needs an update.</summary>
    public const string NeedsUpdateCode = "service_needs_update";

    /// <summary>The <c>StreamError</c> code of a turn that stopped because no key is stored.</summary>
    public const string NoKeyCode = "service_key_missing";

    /// <summary>True when the service can be called.</summary>
    public bool IsReady => Status == LocalServiceStatus.Ready;

    /// <summary>The state of a service that can be called.</summary>
    public static LocalServiceState Ready(string service) => new(LocalServiceStatus.Ready, service, "");

    /// <summary>The state of a service that offers no keyed endpoint.</summary>
    public static LocalServiceState NeedsUpdate(string service, string reason) =>
        new(LocalServiceStatus.NeedsUpdate, service, $"{service} needs an update: {reason}");

    /// <summary>The state of a service nothing answers for.</summary>
    public static LocalServiceState NotRunning(string service, string detail) =>
        new(LocalServiceStatus.NotRunning, service, detail);

    /// <summary>The state of a service whose key is not in the keychain.</summary>
    public static LocalServiceState NoKey(string service, string detail) =>
        new(LocalServiceStatus.NoKey, service, detail);
}
