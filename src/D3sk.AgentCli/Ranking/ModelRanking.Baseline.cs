namespace D3sk.AgentCli.Ranking;

public sealed partial class ModelRanking
{
    // Snapshot of artificialanalysis.ai/leaderboards/models carried over from AgentCliBridge v0.3.0: family, effort, [intelligence, speed].
    private static MetricsTable BuildBaseline()
    {
        var table = BuildClaudeAndGptBaseline();
        AddOtherFamiliesBaseline(table);
        return table;
    }

    private static MetricsTable BuildClaudeAndGptBaseline() => new()
    {
        ["claude-opus-5-5"] = new() { ["max"] = new(58, null), ["xhigh"] = new(56, 89), ["high"] = new(54, 82), ["medium"] = new(51, 81), ["low"] = new(42, 80) },
        ["claude-sonnet-5-5"] = new() { ["max"] = new(56, 133), ["xhigh"] = new(52, 109), ["high"] = new(47, 106), ["medium"] = new(41, 106), ["low"] = new(36, 105) },
        ["claude-fable-5-1"] = new() {
            ["max"] = new(53, 69),
            ["xhigh"] = new(53, 66),
            ["high"] = new(51, 57),
            ["medium"] = new(49, 58),
            ["low"] = new(47, 58),
        },
        ["claude-opus-5"] = new() { ["max"] = new(51, 60) },
        ["claude-haiku-5-5"] = new() {
            ["max"] = new(43, 235),
            ["xhigh"] = new(41, 190),
            ["high"] = new(38, 182),
            ["medium"] = new(34, 178),
            ["low"] = new(29, 176),
        },
        ["claude-opus-4-8"] = new() { ["max"] = new(42, 53) },
        ["claude-opus-4-6"] = new() { ["high"] = new(39, 37) },
        ["claude-sonnet-5"] = new() {
            ["max"] = new(38, 84),
            ["xhigh"] = new(34, 70),
            ["high"] = new(32, 66),
            ["medium"] = new(28, 66),
            ["low"] = new(24, 60),
        },
        ["claude-sonnet-4-6"] = new() { ["high"] = new(25, 44) },
        ["claude-haiku-4-5"] = new() { ["high"] = new(17, 82) },
        ["gpt-6-astra"] = new() {
            ["max"] = new(53, 57),
            ["xhigh"] = new(52, 54),
            ["high"] = new(51, 53),
            ["medium"] = new(50, 50),
            ["low"] = new(46, 53),
        },
        ["gpt-6.1-sol"] = new() {
            ["max"] = new(52, 55),
            ["xhigh"] = new(51, 50),
            ["high"] = new(50, 49),
            ["medium"] = new(48, 48),
            ["low"] = new(42, 48),
        },
        ["gpt-6-sol"] = new() {
            ["max"] = new(48, 86),
            ["xhigh"] = new(44, 83),
            ["high"] = new(43, 84),
            ["medium"] = new(40, null),
            ["low"] = new(34, 82),
        },
        ["gpt-5.6-sol"] = new() { ["max"] = new(47, 96), ["high"] = new(47, 96) },
        ["gpt-5.6-terra"] = new() {
            ["max"] = new(42, 125),
            ["xhigh"] = new(38, 107),
            ["high"] = new(34, 103),
            ["medium"] = new(30, 106),
            ["low"] = new(27, 108),
        },
        ["gpt-6-luna"] = new() {
            ["max"] = new(38, 136),
            ["xhigh"] = new(35, 126),
            ["high"] = new(33, 123),
            ["medium"] = new(30, 92),
            ["low"] = new(22, 111),
        },
        ["gpt-5.3-codex"] = new() { ["xhigh"] = new(33, 118), ["high"] = new(33, 118) },
        ["gpt-oss-120b"] = new() { ["high"] = new(12, 206), ["low"] = new(10, 216) },
    };

    private static void AddOtherFamiliesBaseline(MetricsTable table)
    {
        table["grok-4.7"] = new() { ["xhigh"] = new(46, 82), ["high"] = new(46, 83), ["low"] = new(42, 78) };
        table["grok-4.6"] = new() { ["xhigh"] = new(44, 78), ["high"] = new(44, 66), ["medium"] = new(43, 69), ["low"] = new(35, 62) };
        table["grok-4.5"] = new() { ["high"] = new(39, 63) };
        table["gemini-4-argon"] = new() { ["high"] = new(53, 82) };
        table["gemini-3.8-flash"] = new() { ["high"] = new(41, 306), ["medium"] = new(40, null), ["low"] = new(33, null) };
        table["gemini-3.7-flash"] = new() { ["medium"] = new(40, 291), ["high"] = new(39, 283), ["low"] = new(37, 306) };
        table["gemini-3.6-flash"] = new() { ["high"] = new(34, 212) };
        table["gemini-3.5-flash"] = new() { ["high"] = new(33, 204) };
        table["gemini-3.5-flash-lite"] = new() { ["high"] = new(22, 349) };
        table["gemini-3.1-pro"] = new() { ["high"] = new(30, 119) };
        table["gemini-2.5-pro"] = new() { ["high"] = new(16, 139) };
        table["muse-spark-1.3"] = new() { ["max"] = new(48, 221), ["xhigh"] = new(45, 196) };
        table["mimo-v2.6-pro"] = new() { ["high"] = new(45, 55) };
        table["muse-wonder"] = new() { ["high"] = new(42, 234) };
        table["mimo-v2.6-flash"] = new() { ["high"] = new(38, 59) };
        table["inkling-small"] = new() { ["high"] = new(28, 210) };
        table["inkling"] = new() { ["high"] = new(25, 194) };
        table["ling-3.0-flash"] = new() { ["high"] = new(25, 373) };
        table["ling-3.0-flash-fin"] = new() { ["high"] = new(23, 161) };
        table["nemotron-3-ultra"] = new() { ["high"] = new(23, 214) };
        table["qwen3.8-27b"] = new() { ["xhigh"] = new(34, 47), ["high"] = new(20, 55), ["medium"] = new(28, 54), ["low"] = new(26, 56) };
        table["gemma-4-31b"] = new() { ["high"] = new(19, 35) };
        table["gemma-4-26b-a4b"] = new() { ["high"] = new(17, null) };
        table["nemotron-3.5-lightning"] = new() { ["high"] = new(13, 292) };
        table["nemotron-3-super"] = new() { ["high"] = new(13, 166) };
        table["nemotron-3-nano-omni"] = new() { ["high"] = new(10, 263) };
        table["north-mini-code"] = new() { ["high"] = new(10, 83) };
        table["lfm-2.5-2.6b"] = new() { ["high"] = new(8, null) };
    }
}
