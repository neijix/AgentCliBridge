using System.Text.Json.Nodes;
using D3sk.AgentCli.Control;

namespace D3sk.AgentCli.Tests.Control;

/// <summary>The answers a host writes back to a running Claude turn, against a recording writer.</summary>
public class TurnInputTests
{
    private sealed class Recorder
    {
        public List<JsonObject> Written { get; } = [];
        public bool Ok { get; set; } = true;

        public bool Write(JsonObject payload)
        {
            Written.Add((JsonObject)payload.DeepClone());
            return Ok;
        }
    }

    private static (TurnInput Input, Recorder Log) Bound(string prompt = "hi")
    {
        var log = new Recorder();
        var input = new TurnInput();
        input.Bind(log.Write, prompt);
        return (input, log);
    }

    private static JsonNode Decision(Recorder log) => log.Written[^1]["response"]!["response"]!;

    [Fact]
    [Trait("Preserve", "P14")]
    public void The_prompt_is_the_first_line_and_a_message_said_before_start_follows_it()
    {
        var input = new TurnInput();
        Assert.True(input.Say("queued early"));
        var log = new Recorder();
        input.Bind(log.Write, "hi");

        Assert.Equal(
            ["hi", "queued early"],
            log.Written.Select(w => (string)w["message"]!["content"]!));
        Assert.Equal("user", (string)log.Written[0]["type"]!);
        Assert.Equal("", (string)log.Written[0]["session_id"]!);
        Assert.Null(log.Written[0]["parent_tool_use_id"]);
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void An_approval_allows_exactly_the_call_the_cli_asked_about()
    {
        var (input, log) = Bound();
        input.Asked("r1", new JsonObject { ["file_path"] = "a" });

        Assert.True(input.Answer("r1", true));
        Assert.False(input.Answer("r1", true)); // already answered
        Assert.False(input.Answer("r-unknown", true));

        var response = log.Written[1]["response"]!;
        Assert.Equal("r1", (string)response["request_id"]!);
        Assert.Equal("success", (string)response["subtype"]!);
        // Guard: only allow plus the CLI's own input; no edited input, no permission rule or mode.
        Assert.Equal("""{"behavior":"allow","updatedInput":{"file_path":"a"}}""", response["response"]!.ToJsonString());
        Assert.Equal(2, log.Written.Count);
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void A_denial_carries_the_users_reason_or_the_default()
    {
        var (input, log) = Bound();
        input.Asked("r1", new JsonObject());
        input.Asked("r2", new JsonObject());

        Assert.True(input.Answer("r1", false, "  use git status instead "));
        Assert.Equal("""{"behavior":"deny","message":"use git status instead"}""", Decision(log).ToJsonString());
        Assert.True(input.Answer("r2", false, "   "));
        Assert.Equal(TurnInput.DeniedMessage, (string)Decision(log)["message"]!);
    }

    [Fact]
    public void Nothing_is_answered_before_the_cli_started_or_when_the_write_fails()
    {
        var early = new TurnInput();
        early.Asked("r1", new JsonObject());
        Assert.False(early.Answer("r1", true));

        var (input, log) = Bound();
        log.Ok = false;
        Assert.False(input.Say("lost"));
        Assert.False(input.SetPermissionMode("plan"));
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void Answering_a_question_allows_it_with_the_chosen_answers()
    {
        var (input, log) = Bound();
        input.Asked("r1", JsonNode.Parse("""{"questions":[{"question":"OS?"},{"question":"Key?"}],"metadata":{"m":1}}""")!);

        var answers = new Dictionary<string, JsonNode?>
        {
            ["OS?"] = "macOS",
            ["Key?"] = JsonNode.Parse("""["env","file"]"""),
            ["Empty text"] = "",
            ["Empty list"] = new JsonArray(),
            ["Nothing"] = null,
        };
        Assert.True(input.AnswerQuestion("r1", answers, "  "));
        Assert.Equal(
            """{"behavior":"allow","updatedInput":{"questions":[{"question":"OS?"},{"question":"Key?"}],"metadata":{"m":1},"answers":{"OS?":"macOS","Key?":["env","file"]}}}""",
            Decision(log).ToJsonString());
        Assert.False(input.AnswerQuestion("r1", answers)); // already answered
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void A_skipped_question_is_allowed_with_no_answers_and_a_global_response_is_kept()
    {
        var (input, log) = Bound();
        input.Asked("r1", JsonNode.Parse("""{"questions":[{"question":"OS?"}]}""")!);
        Assert.True(input.AnswerQuestion("r1", new Dictionary<string, JsonNode?>()));
        Assert.Equal("""{"behavior":"allow","updatedInput":{"questions":[{"question":"OS?"}]}}""", Decision(log).ToJsonString());

        input.Asked("r2", JsonNode.Parse("""{"questions":[]}""")!);
        Assert.True(input.AnswerQuestion("r2", null, " go with the default "));
        Assert.Equal("""{"behavior":"allow","updatedInput":{"questions":[],"response":"go with the default"}}""", Decision(log).ToJsonString());
    }

    [Fact]
    [Trait("Security", "ask-question-input")]
    public void Answer_question_refuses_to_edit_a_gated_tools_input()
    {
        var (input, log) = Bound();
        input.Asked("r1", new JsonObject { ["command"] = "rm -rf build" });

        Assert.False(input.AnswerQuestion("r1", new Dictionary<string, JsonNode?> { ["anything"] = "yes" }));
        Assert.Single(log.Written); // only the prompt: the call is left pending
        Assert.True(input.Answer("r1", true));
        Assert.Equal("""{"behavior":"allow","updatedInput":{"command":"rm -rf build"}}""", Decision(log).ToJsonString());
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void A_permission_mode_switch_is_numbered_and_an_unknown_mode_is_refused()
    {
        var input = new TurnInput();
        Assert.True(input.SetPermissionMode("auto")); // before the CLI starts: sent right after the prompt
        Assert.False(input.SetPermissionMode("yolo"));
        Assert.False(input.SetPermissionMode(""));
        var log = new Recorder();
        input.Bind(log.Write, "hi");

        Assert.Equal(
            """{"type":"control_request","request_id":"d3sk-mode-1","request":{"subtype":"set_permission_mode","mode":"auto"}}""",
            log.Written[1].ToJsonString());
        Assert.True(input.SetPermissionMode("plan"));
        Assert.Equal("d3sk-mode-2", (string)log.Written[2]["request_id"]!);
        Assert.Equal("auto", input.ModeAnswered("d3sk-mode-1"));
        Assert.Null(input.ModeAnswered("d3sk-mode-1"));
    }

    [Fact]
    [Trait("Preserve", "P14")]
    public void A_message_still_on_its_way_keeps_the_turn_open_until_it_is_taken()
    {
        var (input, _) = Bound();
        Assert.True(input.Say("one more thing"));

        Assert.False(input.TurnEnded());
        Assert.True(input.IsOpen);
        input.TookMessage();
        Assert.True(input.TurnEnded());
        Assert.False(input.IsOpen);
        Assert.False(input.Say("too late"));
        Assert.False(input.SetPermissionMode("plan"));
    }

    [Fact]
    public void An_empty_message_is_refused_and_a_closed_turn_forgets_its_approvals()
    {
        var (input, _) = Bound();
        Assert.False(input.Say(""));
        input.Asked("r1", new JsonObject());
        Assert.True(input.TurnEnded());
        Assert.False(input.Answer("r1", true));
    }

    [Fact]
    public void A_withdrawn_approval_can_no_longer_be_answered()
    {
        var (input, _) = Bound();
        input.Asked("r1", new JsonObject());
        input.Withdrawn("r1");
        Assert.False(input.Answer("r1", true));
    }

    [Fact]
    public void Close_ends_the_turn_at_once_even_with_a_message_still_on_its_way()
    {
        var (input, _) = Bound();
        Assert.True(input.Say("one more thing"));
        input.Asked("r1", new JsonObject());

        input.Close();
        input.Close(); // safe to call again

        Assert.False(input.IsOpen);
        Assert.False(input.Say("too late"));
        Assert.False(input.Answer("r1", true));
    }
}
