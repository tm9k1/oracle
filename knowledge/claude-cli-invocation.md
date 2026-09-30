# Driving `claude -p` Programmatically

How Oracle (and any script) invokes Claude Code headless. Source of truth: `oracle_bot.py`.

## Binary discovery

`_find_claude()` checks, in order:
1. `/home/tm9k1/.local/bin/claude`
2. `/usr/local/bin/claude`, `/usr/bin/claude`
3. Newest VS Code extension binary: `~/.vscode-server/extensions/anthropic.claude-code-*/resources/native-binary/claude`

## Flag set

Common to both blocking and streaming calls:
```
claude -p "<prompt>"
  --model opus                       # else inherits settings.json ("sonnet")
  --dangerously-skip-permissions     # MUST be baked in — see below
  --add-dir /                        # grant filesystem access beyond cwd
```
- **New session**: add `--append-system-prompt "<kb prompt>"` (no `--resume`).
- **Resume**: add `--resume <session_id>` (do NOT re-send the system prompt).
- Blocking: `--output-format json` (used for startup test, `/compact`).
- Streaming: `--output-format stream-json --verbose`.
- Always run with `cwd="/home/tm9k1"`.

## Why `--dangerously-skip-permissions` is mandatory

Without it, `claude -p` blocks waiting for interactive permission approval that can never
arrive in a subprocess — a bootstrap deadlock. It must be part of the command from the
first invocation. (scars/2026-06-20-001.)

## Parsing `stream-json`

Newline-delimited JSON objects on stdout. Event `type`s:
- `assistant` → iterate `message.content` blocks: `text` (append to output), `tool_use`
  (note tool name), `thinking` (skip entirely).
- `user` → tool results came back; reset activity to "thinking".
- `result` → terminal: carries `session_id`, final `result`, `usage`, `modelUsage`.

## Session resume error handling

If stderr/stdout contains `"No conversation found"` on a `--resume`, the session id is dead —
retry once with no session (fresh). Both `call_claude` and `_stream_claude` implement this.

## Context accounting

`_context_fraction` uses `usage.input_tokens + output_tokens` against `modelUsage[*].contextWindow`
(cache tokens excluded — they don't count toward the live window). Triggers `/compact` at ≥65%.

## Timeouts
- Blocking `call_claude`: 600s.
- Streaming `event_reader`: 1500s (25 min) wall clock; on timeout the process is killed but
  the session is preserved so the user can reply to check status.

## Related
- [[oracle-bot]] — the consumer of all this
