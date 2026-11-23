# Claude Code stream: a background task (CLI 2.1.330)

Five real `claude` 2.1.330 (Windows) stdout recordings, one JSON object per line, in the order the CLI
wrote them. They show what the CLI says on stdout while a background task runs, for the .NET line
(`D3sk.AgentCli`): when the task is listed open, what the CLI does with stdin during the wait, and
when it exits. Run 3 is about a race: a task that ends during a reply. Runs 4 and 5 show what the CLI does with a notice that
is not followed by a follow-up turn: a task that ends during a foreground command (4), a task the model stops itself (5).

They sit in `tests/fixtures/claude/2.1.330/` and not in `tests/streams`: that folder is frozen at the
Python line's `v0.3.0` (`tests/frozen-manifest.txt`), and `FrozenFixturesTests` fails on any file the
manifest does not list.

## How they were recorded

A script in a scratch folder outside this repo started `claude`, with `TEMP` / `TMP` / `TMPDIR` and
the working directory in scratch folders, wrote the prompt to stdin as one stream-json user message
and read stdout line by line. The prompt is neutral: start a 60 s shell loop (12 ticks, 5 s apart) in
the background, reply in one sentence, and say one more sentence (run 1) or run `git init` (run 2)
when the completion notice arrives.

| File | Run | Argv (after `claude`) | stdin |
|---|---|---|---|
| `background-task.stdout.jsonl` | 1 | `-p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --replay-user-messages --permission-prompt-tool stdio --permission-mode bypassPermissions --dangerously-skip-permissions` | prompt, closed at the first `result`; the CLI left alone until it exited (exit 0, 0.5 s after its last `result`) |
| `background-task-input.stdout.jsonl` | 2 | `-p --input-format stream-json --output-format stream-json --verbose --include-partial-messages --replay-user-messages --permission-prompt-tool stdio --permission-mode acceptEdits` | prompt, then open: one more user message 12 s after the first `result`, every `can_use_tool` request answered `allow`, closed at the last `result` (exit 0, 0.1 s later) |
| `background-task-race.stdout.jsonl` | 3 | run 1's argv plus `--model haiku` | prompt, then open; closed 20 s after the last `result` with nothing more on stdout (exit 0, 0.3 s later) |
| `background-task-echo.stdout.jsonl` | 4 | run 3's | prompt, then open; closed 20 s after the last `result` with nothing more on stdout (exit 0, 0.2 s later) |
| `background-task-stopped.stdout.jsonl` | 5 | run 3's | as run 4 (exit 0, 0.2 s later) |

Run 1 is the argv of a hub-started live turn plus
the bypass flags; run 2 is the hub's default mode (no bypass); run 3 is run 1's, on a small model to keep it cheap.
Its prompt: start `sleep 3` in the background, then write a story of about 500 words without a tool, and reply
with one sentence when the completion notice arrives. Run 4's prompt: start `sleep 3` in the background, then run `sleep 10`
in the foreground, and reply with one short sentence when both are done. Run 5's: start `sleep 120` in the background, stop that
task with the task-stopping tool, and reply with one short sentence.

## Lines kept

Line numbers are those of the files; `stream_event` lines (partial messages: `message_start`,
`content_block_*`, `message_delta`, `message_stop`) sit between the ones listed.

Run 1, `background-task.stdout.jsonl` (56 lines):

| Lines | Shows |
|---|---|
| 1-4 | `system` `hook_started`, `hook_response` (a `SessionStart` hook, empty output), `init` (cut), `status` |
| 5 | the prompt, replayed (`--replay-user-messages`) |
| 21 | the reply's `assistant` line: `Bash` with `run_in_background: true` |
| 25 | `system` `background_tasks_changed`: lists task `bunc7z7ge` (`task_type: local_bash`), **before the first `result`** |
| 26 | `system` `task_started` for `bunc7z7ge` |
| 27 | the tool result "Command running in background with ID: ..." |
| 37 | the reply text `assistant` line |
| 41 | the **first `result`** (`success`, no `origin`): the task is still open, stdin is closed here |
| 42-44 | about 60 s later: `task_updated` (`patch.status: completed`), `task_notification` (`status: completed`, `output_file`), `background_tasks_changed` with `[]` |
| 45-52 | the CLI's own follow-up turn on the notification: `init`, `status`, the reply |
| 56 | the **second `result`** (`origin.kind: task-notification`); the process exits 0 about 0.5 s later |

Run 2, `background-task-input.stdout.jsonl` (99 lines):

| Lines | Shows |
|---|---|
| 1-5 | as run 1 |
| 21-24 | the `Bash` `tool_use`, then a `control_request` (`can_use_tool`, `Bash`: the loop's command) and the `control_response` `allow` the script wrote (echoed on stdout) |
| 27-28 | `background_tasks_changed` listing `bo2i5sseh` and `task_started`, before the first `result` |
| 29-45 | the tool result, then the reply |
| 49 | the **first `result`**: the task is open, stdin stays open |
| 50-60 | the user message written 12 s later (line 52, replayed) is taken at once: `init`, `status`, the reply `pong` (56) and its own `result` (60, no `origin`) while the task still runs |
| 61-63 | `task_updated`, `task_notification`, `background_tasks_changed []` |
| 64-85 | the follow-up turn: `init`, `status`, `Bash` `git init` (78), a `control_request` for it (82), the script's `allow` (83), its result (84) |
| 95-99 | the closing reply and the last `result` (`origin.kind: task-notification`); stdin closed there, the process exits 0 within 0.1 s |

Run 3, `background-task-race.stdout.jsonl` (63 lines):

| Lines | Shows |
|---|---|
| 1-5 | as run 1 |
| 23 | the `Bash` `tool_use` with `run_in_background: true` (`sleep 3`) |
| 27-28 | `background_tasks_changed` listing the task, and `task_started`, before the first `result` |
| 41-43 | the first reply's text (the three kept of its streamed deltas) |
| 44-46 | **while the first reply is still streaming**, 3 s after the task started: `task_updated` (`completed`), `task_notification`, `background_tasks_changed` with `[]` |
| 47-51 | the first reply ends: its `assistant` line and the **first `result`** (no `origin`, `queued_turn_count` 0): the list is already `[]` |
| 52-63 | **after** that `result`: `init`, `status`, the follow-up's text and the **second `result`** (`origin.kind: task-notification`, `queued_turn_count` 0) |

Run 4, `background-task-echo.stdout.jsonl` (62 lines):

| Lines | Shows |
|---|---|
| 15, 22-23 | the `Bash` call with `run_in_background: true` (`sleep 3`), `background_tasks_changed` listing `bscjs476d` (with its `run_id`), `task_started` |
| 28 | the foreground `Bash` call (`sleep 10`) |
| 32-34 | 3 s later, during that command: `task_updated` (`completed`), `task_notification` for `bscjs476d` (it carries `run_id`), `background_tasks_changed` with `[]` |
| 35-36 | `task_started` and a `completed` `task_notification` for `b3bbpxf0k`, the foreground command itself: **no `background_tasks_changed` ever lists it** |
| 37 | the foreground command's tool result |
| 38 | **the notice echoed as a `user` line**: `isReplay: true`, `origin.kind: task-notification` with `origin.runId` = the task's `run_id`, the XML notice (`<task-id>`, ...) as content; it comes before the reply, inside the same turn |
| 62 | the only `result` (no `origin`): no follow-up turn followed, the CLI exited 0 once stdin closed |

Run 5, `background-task-stopped.stdout.jsonl` (68 lines):

| Lines | Shows |
|---|---|
| 22, 26-27 | the `Bash` call (`sleep 120`, background), `background_tasks_changed` listing `bdnbz3ndi`, `task_started` |
| 31-43 | the model looks the stopping tool up (`ToolSearch`) |
| 49 | the `TaskStop` call |
| 51-53 | `task_updated` (`killed`), `task_notification` with **`status: stopped`**, `background_tasks_changed` with `[]` |
| 54 | the `TaskStop` result |
| 68 | the only `result` (no `origin`): the CLI ran no follow-up turn on the notice |

Not recorded: a task ending in `failed`, a `deny` answer, POSIX.

## Event order

Run 1 (time from the prompt): `background_tasks_changed [bunc7z7ge]` (3.0 s), `task_started` (3.0 s),
`result` #1 (3.9 s), `task_updated` completed, `task_notification` completed,
`background_tasks_changed []` (all 63.6 s), `result` #2 (64.7 s), exit 0 (65.2 s).

Run 2: `control_request` for the loop (3.0 s, answered at once), `background_tasks_changed [bo2i5sseh]`
and `task_started` (3.2 s), `result` #1 (4.1 s), user message (16.1 s), `result` #2 for it (16.9 s,
task still open), `task_updated`, `task_notification`, `background_tasks_changed []` (63.7 s),
`control_request` for `git init` (65.1 s, answered at once), `result` #3 (66.1 s), stdin closed,
exit 0 (66.2 s).

Run 3 (time from the prompt): `background_tasks_changed [task]` and `task_started` (2.8 s), `task_updated` completed,
`task_notification` and `background_tasks_changed []` (5.9 s, mid-reply), `result` #1 (9.6 s), `init` of the follow-up
(9.7 s), `result` #2 (10.8 s), stdin closed (31.0 s), exit 0 (31.3 s).

## Findings (CLI 2.1.330, Windows)

1. **The task is listed open before the first `result`.** The `background_tasks_changed` that lists it
   and its `task_started` come about 0.9 s before the first `result` in both runs; the next
   `background_tasks_changed` is `[]`, after `task_notification`. A reader that judges each `result`
   from what came before it sees the task open at the first one and none open at the later ones. The
   `result` that follows the notification carries `origin.kind: task-notification`.
2. **With stdin open, the CLI takes a user message mid-wait and the follow-up's tool approval, and
   exits once stdin closes.** In run 2 the message written while the task ran was run at once and
   answered with its own `result` (the task kept running); the follow-up the CLI started on the
   notification sent a `can_use_tool` `control_request`, it ran the tool after the `allow` and
   finished; stdin closed after that last `result` and the process exited 0 within 0.1 s. In
   `acceptEdits` mode the background `Bash` call itself also asked for approval.
3. In run 1 the CLI stayed alive until the task ended, then ran the follow-up on its own and exited 0,
   although stdin was closed at the first `result`.
4. **Run 3, the race: the list can be `[]` at a `result` that the CLI still answers.** The task ended while the first reply
   streamed, so its `result` came after `background_tasks_changed []` (a reader judging by the list alone sees nothing open),
   yet the CLI ran a follow-up turn on the task's notice right after it. **`queued_turn_count` is 0 on both `result`s**
   (in all five recordings), so it is no signal. What tells the two apart is the `task_notification` `system` line:
   it came before `result` #1 and no reply had taken it up; the follow-up's `init` followed the `result`. In runs 1-3 the
   follow-up's `result` carries `origin.kind: task-notification` and `origin.runId`, the `run_id` the task has in
   `background_tasks_changed` (the `task_notification` line carries `run_id` too).
5. **Run 4: a notice taken inside a reply is echoed, and no follow-up comes.** The task ended during a foreground command; the CLI
   echoed the notice as a `user` line (`isReplay: true`, `origin.kind: task-notification`, `origin.runId`) before the reply's
   `result`, and ran no follow-up turn after it. That echo looks like the user's replayed message (`isReplay`), so it must not
   reach the live input. The foreground command's own `task_notification` (a task no list ever shows) is answered by nobody.
6. **Run 5: a task the model stops itself gives a `task_notification` with `status: stopped`, and no follow-up turn.**
7. Rules used by the library, from these five recordings: a `task_notification` waits for a reply only when its task was
   listed in a `background_tasks_changed` and its `status` is not `stopped`; it is taken by the `user` echo or by the `result`
   with `origin.kind: task-notification` that names its `run_id` (without a run, the oldest one); never by an `init`, nor by a
   `result` with no `origin`; a `result` judged with a task listed open or a notice waiting keeps the wait going. Not recorded,
   so not a rule: a `failed` task's notice (counted like a completed one), two tasks ending together, and a message turn
   during a pending notice (those tests are hand-built from the recorded line shapes).

## Scrub (the repo is public)

The recording script applied these rules (they are the trim of `tests/streams/capture.py`, which is a
frozen file that cannot be run here, plus one stricter rule and the scrub of an earlier transcript fixture):

- An `init` line (`subtype` or `event` `init`) cut to `type`, `subtype`, `event`, `session_id`,
  `conversation_id`, `model`, `claude_code_version`, `permissionMode`: 2 lines in run 1, 3 in run 2.
- `uuid`, `usage`, `modelUsage`, `rate_limit_info`, `total_cost_usd`, `permission_denials`,
  `subagent_stats`, `signature`, `request_id`, `api_message_id` dropped at any depth. Keys dropped,
  run 1 / run 2: `uuid` 54 / 92, `usage` 11 / 20, `api_message_id` 37 / 66, `request_id` 3 / 11,
  `total_cost_usd` 2 / 3, `modelUsage` 2 / 3, `permission_denials` 2 / 3, `subagent_stats` 2 / 3,
  `signature` 0 / 6, `rate_limit_info` 0 (those lines are dropped whole, below).
- Also dropped at any depth, beyond `capture.py`: `thinking` (0 / 6, empty text anyway),
  `credential_expires_at` (2 / 3, an account detail) and `model_usage_since_last_result` (2 / 3, usage).
- `rate_limit_event` lines dropped whole: 2 in each run (`capture.py` drops only their
  `rate_limit_info` key).
- The home folder, the user name and the machine's scratch paths replaced: working folder
  `C:\work\project`, temp root `C:\agent-temp`, the per-project hash folder `0909090909090909` (run 1) and
  `0a0a0a0a0a0a0a0a` (run 2), session ids `00000000-0000-4000-8000-000000000101` / `...102`. A path
  the model streamed in pieces across text deltas is put whole into the block's first delta (1 block in
  run 2; the final `assistant` line is unchanged by this).
- The prompt, the commands, descriptions, tool output and reply text are as recorded: the prompt was
  neutral, so nothing needed replacing. Task ids, run ids, tool-use ids, message ids and timestamps are
  kept as recorded.

Runs 4 and 5 were scrubbed by the same rules, with no text cut and no prompt replaced (both prompts are neutral): `init` lines cut (1
each), `rate_limit_event` lines dropped (1 each), keys dropped, run 4 / run 5: `uuid` 61 / 67, `usage` 9 / 14,
`api_message_id` 39 / 44, `request_id` 4 / 5, `thinking` 4 / 4, `signature` 3 / 3, `total_cost_usd` 1 / 1, `modelUsage` 1 / 1,
`permission_denials` 1 / 1, `subagent_stats` 1 / 1, `model_usage_since_last_result` 1 / 1, `credential_expires_at` 1 / 1; working folder
`C:\work\project`, temp roots `C:\agent-temp\claude\0c0c0c0c0c0c0c0c` / `...0d0d0d0d0d0d0d0d`, session ids
`00000000-0000-4000-8000-000000000104` / `...105`.

Run 3 was scrubbed by the same rules: `init` lines cut (2), `rate_limit_event` lines dropped (1), keys dropped (`uuid` 61,
`usage` 13, `api_message_id` 38, `request_id` 5, `total_cost_usd` 2, `modelUsage` 2, `permission_denials` 2,
`subagent_stats` 2, `signature` 6, `thinking` 8, `credential_expires_at` 2, `model_usage_since_last_result` 2), the working
folder `C:\work\project`, the temp root `C:\agent-temp` with the hash folder `0b0b0b0b0b0b0b0b`, session id
`00000000-0000-4000-8000-000000000103`. The first reply's 265 streamed text deltas (a story) were cut to three short ones
and its `assistant` and `result` text set to the same neutral sentence (262 lines dropped); the follow-up's text is as
recorded.
