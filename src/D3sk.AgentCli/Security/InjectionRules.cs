using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace D3sk.AgentCli.Security;

/// <summary>How much one rule hit weighs.</summary>
public enum Severity
{
    /// <summary>Taints a turn alone.</summary>
    High,

    /// <summary>Taints only together with a different rule's hit.</summary>
    Low,
}

/// <summary>One text heuristic of the injection guard.</summary>
public sealed record Rule(string Name, Severity Severity, Regex Pattern);

/// <summary>One rule that matched, with a short excerpt around its first match.</summary>
public sealed record Finding(string Rule, Severity Severity, string Excerpt);

/// <summary>
/// The detection layer of the injection guard: heuristic rules over tool output. A tripwire, not a proof:
/// a clean scan never means the content is safe.
/// </summary>
public static partial class InjectionScanner
{
    private const RegexOptions Flags = RegexOptions.IgnoreCase | RegexOptions.Singleline | RegexOptions.CultureInvariant;

    /// <summary>The rule set, in the order findings are reported.</summary>
    public static IReadOnlyList<Rule> Rules { get; } =
    [
        new("instruction_override", Severity.High, new(
            @"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}?\b(previous|prior|above|earlier|"
            + @"preceding|all|any|your|existing|system)\b[^.\n]{0,30}?\b(instructions?|prompts?|rules|"
            + @"directions|directives|restrictions|guidelines|guardrails|constraints)\b", Flags)),
        new("fake_role_tag", Severity.High, new(
            @"<\|?\s*(im_start|im_end|system|endoftext)\s*\|?>|</?\s*(system|instructions?|"
            + @"system[_-]prompt)\s*>|\[/?\s*(INST|SYSTEM)\s*\]|(^|\n)\s*#{1,3}\s*(system|assistant)\s*:?\s*$",
            Flags | RegexOptions.Multiline)),
        new("system_notice", Severity.Low, new(
            @"\b(system|admin(istrator)?|security|developer)\s+(notice|override|message|instruction|"
            + @"directive|alert)s?\b\s*[:\-—]", Flags)),
        new("addressed_to_ai", Severity.High, new(
            @"\b(if|when)\s+you\s+are\s+an?\s+(ai|llm|language model|assistant|agent|bot)\b|"
            + @"\b(note|message|instructions?)\s+(to|for)\s+(the\s+)?(ai|llm|assistant|agent|model|bot)\b|"
            + @"\b(ai|llm)\s+(assistant|agent)s?\s+(reading|processing|summari[sz]ing)\b", Flags)),
        new("covert_action", Severity.High, new(
            @"\bwithout\s+(asking|telling|informing|notifying|alerting|confirming\s+with|consulting)\b"
            + @"[^.\n]{0,20}?\b(the\s+)?(user|owner|human|recipient|them)\b|"
            + @"\b(do\s+not|don'?t|never)\s+(mention|tell|inform|reveal|disclose|report|show)\b[^.\n]{0,40}?"
            + @"\b(user|owner|human|summary|anyone)\b|"
            + @"\bwithout\s+(asking|requesting)\s+(for\s+)?(confirmation|permission|approval)\b", Flags)),
        // Tag characters (U+E0000-E007F, a surrogate pair), bidi controls, runs of zero-width characters.
        new("hidden_unicode", Severity.High, new(
            @"\uDB40[\uDC00-\uDC7F]|[\u202a-\u202e\u2066-\u2069]|[\u200b-\u200d\u2060\ufeff]{3,}",
            RegexOptions.CultureInvariant)),
        new("role_hijack", Severity.Low, new(
            @"\b(you\s+are\s+now|from\s+now\s+on,?\s+you|new\s+(system\s+)?instructions?\s*:|"
            + @"act\s+as\s+(an?\s+)?(unrestricted|different|new)|pretend\s+(to\s+be|you\s+are))\b", Flags)),
        new("outbound_request", Severity.Low, new(
            @"\b(send|forward|email|e-mail|post|upload|transmit|exfiltrate)\b[^.\n]{0,80}?"
            + @"([\w.+-]+@[\w-]+\.[\w.-]+|https?://\S+)", Flags)),
        new("hidden_styling", Severity.Low, new(
            @"(color\s*:\s*(#fff(fff)?|white)\b[^>]{0,80}?background(-color)?\s*:\s*(#fff(fff)?|white)\b|"
            + @"font-size\s*:\s*0(px|pt|em)?\b|display\s*:\s*none|white[- ]on[- ]white)", Flags)),
    ];

    /// <summary>Every rule that matches <paramref name="text"/>, with a short excerpt around the first match.</summary>
    public static List<Finding> ScanText(string? text, IEnumerable<Rule>? rules = null)
    {
        var findings = new List<Finding>();
        if (string.IsNullOrEmpty(text))
        {
            return findings;
        }
        foreach (var rule in rules ?? Rules)
        {
            var match = rule.Pattern.Match(text);
            if (match.Success)
            {
                findings.Add(new Finding(rule.Name, rule.Severity, Excerpt(text, match.Index, match.Index + match.Length)));
            }
        }
        return findings;
    }

    /// <summary>One high-severity hit, or two distinct low-severity ones.</summary>
    public static bool IsInjection(IEnumerable<Finding> findings)
    {
        var all = findings.ToList();
        return all.Any(f => f.Severity == Severity.High)
            || all.Where(f => f.Severity == Severity.Low).Select(f => f.Rule).Distinct().Count() >= 2;
    }

    private static string Excerpt(string text, int start, int end, int margin = 60)
    {
        var from = Math.Max(0, start - margin);
        var to = Math.Min(text.Length, end + margin);
        if (from > 0 && char.IsLowSurrogate(text[from]))
        {
            from--;
        }
        if (to < text.Length && char.IsLowSurrogate(text[to]))
        {
            to++;
        }
        var snippet = Whitespace().Replace(text[from..to], " ").Trim();
        return IsPrintable(snippet) ? snippet : UnicodeEscape(snippet);
    }

    [GeneratedRegex(@"\s+")]
    private static partial Regex Whitespace();

    private static bool IsPrintable(string text)
    {
        foreach (var rune in text.EnumerateRunes())
        {
            if (!IsPrintable(rune))
            {
                return false;
            }
        }
        return true;
    }

    private static bool IsPrintable(Rune rune) => rune.Value == ' ' || Rune.GetUnicodeCategory(rune) is not (
        UnicodeCategory.Control or UnicodeCategory.Format or UnicodeCategory.Surrogate or UnicodeCategory.PrivateUse
        or UnicodeCategory.OtherNotAssigned or UnicodeCategory.LineSeparator or UnicodeCategory.ParagraphSeparator
        or UnicodeCategory.SpaceSeparator);

    /// <summary>Python's <c>unicode_escape</c> spelling, so the excerpt of hidden characters stays plain ASCII.</summary>
    private static string UnicodeEscape(string text)
    {
        var sb = new StringBuilder();
        foreach (var rune in text.EnumerateRunes())
        {
            var v = rune.Value;
            sb.Append(v switch
            {
                '\\' => "\\\\",
                '\t' => "\\t",
                '\n' => "\\n",
                '\r' => "\\r",
                >= 0x20 and < 0x7f => ((char)v).ToString(),
                < 0x100 => $"\\x{v:x2}",
                < 0x10000 => $"\\u{v:x4}",
                _ => $"\\U{v:x8}",
            });
        }
        return sb.ToString();
    }
}
