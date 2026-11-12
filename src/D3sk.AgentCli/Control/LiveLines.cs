using System.Text.Json.Nodes;
using D3sk.AgentCli.Events;
using D3sk.AgentCli.Output.Common;

namespace D3sk.AgentCli.Control;

/// <summary>
/// The control lines of one live Claude turn: permission prompts become <c>ApprovalRequest</c>,
/// replayed user messages become <c>InputAccepted</c>, answers to a mode switch become
/// <c>ModeChanged</c>. One instance per turn; the Claude parser feeds it every line and falls back
/// to its own handling when <see cref="TryHandle"/> returns false.
/// </summary>
/// <param name="Input">The turn's input channel.</param>
/// <param name="Write">Writes one JSON line to the CLI's stdin; false when it cannot.</param>
public sealed class LiveLines(TurnInput Input, Func<JsonObject, bool> Write)
{
    private int _replays;

    /// <summary>How many user messages the CLI echoed back so far (the first is the prompt itself).</summary>
    public int Replays => _replays;

    /// <summary>Handles <paramref name="line"/> when it is a control line or a replayed user message.</summary>
    public bool TryHandle(JsonObject line, out List<StreamEvent> events)
    {
        events = [];
        switch (Json.AsString(line["type"]))
        {
            case "control_request":
                events = ControlRequest(line);
                return true;
            case "control_response":
                events = ControlResponse(line);
                return true;
            case "control_cancel_request":
                Input.Withdrawn(Json.AsString(line["request_id"]) ?? "");
                return true;
            case "user" when Json.IsTruthy(line["isReplay"]):
                _replays++;
                if (_replays > 1)
                {
                    Input.TookMessage();
                    events = [new InputAccepted(ReplayText(line))];
                }
                return true;
            default:
                return false;
        }
    }

    /// <summary>
    /// A resumed session's leftover task, not this turn's result: it first reports a background
    /// task its last run left behind, then an empty result with <c>num_turns</c> 0, and only then
    /// takes the prompt. Ending the turn on it stopped Claude mid-answer. Only that exact shape counts.
    /// </summary>
    public bool IsEmptyResume(JsonObject result, bool isFailure) =>
        _replays == 0
        && !isFailure
        && result["num_turns"] is JsonValue turns && turns.TryGetValue<double>(out var n) && n == 0
        && !Json.IsTruthy(result["result"]);

    /// <summary>A <c>result</c> arrived: true when nothing is left on the way, so stdin may close and the result grace may start.</summary>
    public bool TurnEnded() => Input.TurnEnded();

    private List<StreamEvent> ControlRequest(JsonObject line)
    {
        var requestId = Json.AsString(line["request_id"]) ?? "";
        var request = Json.AsObject(line["request"]);
        if (Json.AsString(request["subtype"]) == "can_use_tool")
        {
            var toolInput = Json.AsObject(request["input"]);
            Input.Asked(requestId, toolInput);
            return
            [
                new ApprovalRequest(
                    requestId,
                    Json.AsString(request["tool_use_id"]) ?? "",
                    Json.IsTruthy(request["tool_name"]) ? Json.AsString(request["tool_name"]) ?? "tool" : "tool",
                    toolInput.DeepClone(),
                    Json.AsString(request["description"]) ?? ""),
            ];
        }

        // Nothing else is enabled (no hooks, no SDK MCP servers): refuse rather than leave the CLI waiting.
        Write(new JsonObject
        {
            ["type"] = "control_response",
            ["response"] = new JsonObject
            {
                ["subtype"] = "error",
                ["request_id"] = requestId,
                ["error"] = $"Unsupported control request: {Json.AsString(request["subtype"]) ?? "None"}",
            },
        });
        return [];
    }

    private List<StreamEvent> ControlResponse(JsonObject line)
    {
        var response = Json.AsObject(line["response"]);
        if (Input.ModeAnswered(Json.AsString(response["request_id"]) ?? "") is not { } asked)
        {
            return [];
        }
        if (Json.AsString(response["subtype"]) == "success")
        {
            var granted = Json.AsString(Json.AsObject(response["response"])["mode"]);
            return [new ModeChanged(string.IsNullOrEmpty(granted) ? asked : granted)];
        }
        var error = Json.AsString(response["error"]);
        return [new ModeChanged(asked, string.IsNullOrEmpty(error) ? "The CLI refused the mode change." : error)];
    }

    private static string ReplayText(JsonObject line)
    {
        var content = Json.AsObject(line["message"])["content"];
        if (Json.AsString(content) is { } text)
        {
            return text;
        }
        return content is JsonArray blocks
            ? string.Concat(blocks.OfType<JsonObject>()
                .Where(block => Json.AsString(block["type"]) == "text")
                .Select(block => Json.AsString(block["text"]) ?? ""))
            : "";
    }
}
