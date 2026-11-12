using System.Globalization;
using D3sk.AgentCli.Catalog;

namespace D3sk.AgentCli.Ranking;

/// <summary>The Price cell: text, hover title and whether the model costs nothing.</summary>
public readonly record struct PriceNote(string Text, string Title, bool IsFree);

/// <summary>A badge next to a model: text and hover title.</summary>
public readonly record struct TagNote(string Text, string Title);

/// <summary>Tags on a model: limited-time free, preview, graduated, and the price.</summary>
public static class ModelTags
{
    /// <summary>Open Router's <c>:free</c>, <c>-free</c> and stealth ids are promotional, the lab may pull them. OpenCode Zen is not.</summary>
    public static bool IsLimitedFree(string? id)
    {
        var text = (id ?? "").ToLowerInvariant();
        return text.Contains("/stealth/", StringComparison.Ordinal)
            || text.EndsWith(":free", StringComparison.Ordinal)
            || LastSegment(text).EndsWith("-free", StringComparison.Ordinal);
    }

    /// <summary>Local models run by the host itself (<c>mlx</c> is the only local flavor): MLX weights already downloaded.</summary>
    public static bool IsLocalAgent(CatalogAgent? agent) => agent?.Flavor == "mlx" || agent?.Command == "mlx";

    /// <summary>OpenCode prices its models, and so does a company gateway Claude Code goes through; the other CLIs run on a subscription.</summary>
    public static bool IsPricedAgent(CatalogAgent? agent) =>
        agent is not null && !IsLocalAgent(agent) && (agent.Flavor == "opencode" || agent.HasPrices);

    /// <summary>Free = an Open Router promo id, or an OpenCode Zen model at no cost. A price of zero alone is not: routers bill the model they pick.</summary>
    public static bool IsFree(string? id, IReadOnlyList<double>? price)
    {
        if (IsLimitedFree(id))
        {
            return true;
        }

        return (id ?? "").StartsWith("opencode/", StringComparison.Ordinal) && IsZero(price);
    }

    /// <summary>"$3", "$1.50", "$0.15": three styles by size.</summary>
    public static string FormatUsd(double value)
    {
        if (value >= 100)
        {
            return string.Create(CultureInfo.InvariantCulture, $"${Math.Round(value, MidpointRounding.AwayFromZero)}");
        }

        if (value >= 1)
        {
            return string.Create(CultureInfo.InvariantCulture, $"${value:F2}");
        }

        if (value <= 0)
        {
            return "$0";
        }

        // Two significant digits, no exponent, no trailing zeros.
        var digits = Math.Min(28, 1 - (int)Math.Floor(Math.Log10(value)));
        var rounded = Math.Round((decimal)value, digits, MidpointRounding.AwayFromZero);
        return "$" + rounded.ToString("0.############################", CultureInfo.InvariantCulture);
    }

    /// <summary>The Price cell of a model; <paramref name="price"/> is the catalog's [input, output] pair. <paramref name="isPriced"/> false = a subscription CLI.</summary>
    public static PriceNote PriceNote(string? id, IReadOnlyList<double>? price, bool isPriced = true, bool isLocal = false)
    {
        if (isLocal)
        {
            return new PriceNote("Local", "Runs on this computer, no token charge", true);
        }

        if (!isPriced)
        {
            return new PriceNote("Plan", "Included in your subscription", false);
        }

        if (IsFree(id, price))
        {
            return new PriceNote("Free", "No cost per token", true);
        }

        if (IsZero(price))
        {
            return new PriceNote("—", "No fixed price (a router bills the model it picks)", false);
        }

        var input = FormatUsd(price![0]);
        var output = FormatUsd(price[1]);
        return new PriceNote($"{input} / {output}", $"USD per million tokens — input {input}, output {output}", false);
    }

    /// <summary>The "limited" badge of a promotional free id, or null.</summary>
    public static TagNote? LimitedNote(string? id) => IsLimitedFree(id)
        ? new TagNote("limited", "Open Router is offering this free for a limited time; that endpoint may disappear.")
        : null;

    /// <summary>A lab preview, stealth or alpha id: not yet graduated.</summary>
    public static bool IsPreview(string? id)
    {
        var text = (id ?? "").ToLowerInvariant();
        if (text.Contains("/stealth/", StringComparison.Ordinal))
        {
            return true;
        }

        var name = LastSegment(text);
        if (name.Contains("preview", StringComparison.Ordinal) || name.Contains("-alpha", StringComparison.Ordinal)
            || name.StartsWith("alpha-", StringComparison.Ordinal))
        {
            return true;
        }

        return (name.EndsWith("-free", StringComparison.Ordinal) ? name[..^"-free".Length] : name) == "space-bunny";
    }

    /// <summary>The "preview" badge, or null.</summary>
    public static TagNote? PreviewNote(string? id) => IsPreview(id)
        ? new TagNote("preview", "This id has not graduated yet (a lab preview, stealth, or alpha). It may change or disappear.")
        : null;

    /// <summary>The "graduated" badge: an Open Router id the Index ranks, so not a lab preview.</summary>
    public static TagNote? IndexNote(string? id, ModelRanking ranking)
    {
        var text = (id ?? "").ToLowerInvariant();
        if (ranking.Metrics(id).Kind != MetricKind.Ranked
            || !(text.StartsWith("openrouter/", StringComparison.Ordinal) || text.StartsWith("opencode/", StringComparison.Ordinal)))
        {
            return null;
        }

        return new TagNote("graduated", "Graduated — this model has been on the Artificial Analysis Intelligence Index for a while, not a lab preview.");
    }

    private static bool IsZero(IReadOnlyList<double>? price) => price is not { Count: >= 2 } p || (p[0] == 0 && p[1] == 0);

    private static string LastSegment(string text) => text[(text.LastIndexOf('/') + 1)..];
}
