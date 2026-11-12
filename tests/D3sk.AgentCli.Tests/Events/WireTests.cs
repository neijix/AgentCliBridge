using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;

namespace D3sk.AgentCli.Tests.Events;

/// <summary>The wire fold against the frozen tests/wire cases, and ToWire on every event class.</summary>
public class WireTests
{
    private static string WireDir()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "global.json")))
        {
            dir = dir.Parent;
        }
        return Path.Combine(dir?.FullName ?? throw new InvalidOperationException("repo root not found"), "tests", "wire");
    }

    public static TheoryData<string> Cases()
    {
        var data = new TheoryData<string>();
        foreach (var file in Directory.GetFiles(WireDir(), "*.json").Order(StringComparer.Ordinal))
        {
            data.Add(Path.GetFileName(file));
        }
        return data;
    }

    [Fact]
    [Trait("Preserve", "wire")]
    public void The_fixture_folder_has_cases() => Assert.NotEmpty(Cases());

    [Theory]
    [MemberData(nameof(Cases))]
    [Trait("Preserve", "wire")]
    public void Fold_equals_the_python_case(string file)
    {
        var doc = JsonNode.Parse(File.ReadAllText(Path.Combine(WireDir(), file)))!.AsObject();
        var parts = new JsonArray();
        foreach (var frame in doc["frames"]!.AsArray())
        {
            Wire.Fold(parts, frame![0]!.GetValue<string>(), frame[1]!.AsObject());
        }
        Assert.True(JsonNode.DeepEquals(doc["parts"], parts), $"{file}: expected {doc["parts"]!.ToJsonString()} got {parts.ToJsonString()}");
    }

    public static TheoryData<StreamEvent, string, string> Samples() => new()
    {
        { new TextDelta("hi"), "text", """{"v":1,"text":"hi"}""" },
        { new ThinkingDelta("hm"), "thinking", """{"v":1,"text":"hm"}""" },
        { new ToolCall("c1", "Read", JsonNode.Parse("""{"file_path":"a"}""")), "tool_call", """{"v":1,"call_id":"c1","name":"Read","arguments":{"file_path":"a"}}""" },
        { new ToolResult("c1", "ok", true), "tool_result", """{"v":1,"call_id":"c1","output":"ok","is_error":true}""" },
        { new ApprovalRequest("r1", "c1", "Bash", JsonNode.Parse("""{"command":"ls"}"""), "run ls"), "approval_request", """{"v":1,"approval_id":"r1","call_id":"c1","name":"Bash","arguments":{"command":"ls"},"description":"run ls"}""" },
        { new InjectionDetected("c1", "Read", ["role-override", "exfil"], "ignore previous", "/log/1"), "injection_detected", """{"v":1,"call_id":"c1","tool_name":"Read","rules":["role-override","exfil"],"excerpt":"ignore previous","details_url":"/log/1"}""" },
        { new ActionBlocked("r1", "c1", "Bash", JsonNode.Parse("""{"command":"rm"}"""), "tainted turn", "/log/2"), "action_blocked", """{"v":1,"call_id":"c1","name":"Bash","reason":"tainted turn","details_url":"/log/2"}""" },
        { new InputAccepted("more"), "input_accepted", """{"v":1}""" },
        { new ModeChanged("plan"), "permission_mode", """{"v":1,"mode":"plan"}""" },
        { new Notice("Loading Qwen…", "loading"), "notice", """{"v":1,"message":"Loading Qwen…","notice_kind":"loading"}""" },
        { new Notice("Waiting."), "notice", """{"v":1,"message":"Waiting."}""" },
        { new SessionUpdate("s1"), "session", """{"v":1,"session_id":"s1"}""" },
        { new StreamError("boom"), "error", """{"v":1,"message":"boom","code":"cli_agent_failed"}""" },
        { new Completed(3), "done", """{"v":1,"returncode":3}""" },
    };

    [Theory]
    [MemberData(nameof(Samples))]
    [Trait("Preserve", "wire")]
    public void ToWire_maps_every_event(StreamEvent e, string name, string json)
    {
        var frame = Wire.ToWire(e);
        Assert.Equal(name, frame.Name);
        Assert.True(JsonNode.DeepEquals(JsonNode.Parse(json), frame.Data), frame.Data.ToJsonString());
    }

    [Fact]
    public void Every_concrete_event_class_has_a_sample()
    {
        var sampled = Samples().Select(row => row.Data.Item1.GetType()).ToHashSet();
        var all = typeof(StreamEvent).Assembly.GetTypes().Where(t => t.IsSubclassOf(typeof(StreamEvent)) && !t.IsAbstract);
        Assert.Empty(all.Where(t => !sampled.Contains(t)).Select(t => t.Name));
    }

    [Fact]
    public void Long_output_and_arguments_are_cut_and_flagged()
    {
        var frame = Wire.ToWire(new ToolResult("c", new string('x', 30), false), 10);
        Assert.Equal(10, frame.Data["output"]!.GetValue<string>().Length);
        Assert.True(frame.Data["truncated"]!.GetValue<bool>());

        var args = new JsonObject { ["k"] = new string('y', Wire.ArgumentsLimit + 5) };
        var call = Wire.ToWire(new ToolCall("c", "Bash", args));
        Assert.Equal(Wire.ArgumentsLimit, call.Data["arguments"]!.GetValue<string>().Length);
        Assert.True(call.Data["truncated"]!.GetValue<bool>());
        Assert.False(Wire.ToWire(new TextDelta("a")).Data.ContainsKey("truncated"));
    }

    [Fact]
    public void ToolResult_equality_ignores_raw() =>
        Assert.Equal(new ToolResult("c", "o", false, "raw"), new ToolResult("c", "o"));

    [Fact]
    public void SseFrame_writes_one_frame_and_refuses_a_line_break_in_the_name()
    {
        Assert.Equal("event: text\ndata: {\"v\":1}\n\n", Wire.SseFrame("text", new JsonObject { ["v"] = 1 }));
        Assert.Throws<ArgumentException>(() => Wire.SseFrame("a\nb", new JsonObject()));
    }
}
