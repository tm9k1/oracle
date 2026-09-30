# Oracle Bot — Operational Knowledge

## Service & Process

- **Systemd unit**: `/home/tm9k1/.config/systemd/user/oracle-discord.service` (user service)
- **Launch command**: `/home/tm9k1/.ai/.venv/bin/python /home/tm9k1/.ai/scripts/oracle_bot.py`
- **Log file**: `/home/tm9k1/.ai/logs/oracle_bot.log`
- **Sessions file**: `/home/tm9k1/.ai/sessions.json`
- **Modular backends**: `/home/tm9k1/.ai/scripts/backends/` (`agy`, `claude_cli`, etc.)

## Restart Procedure

Kill the process directly; systemd's `Restart=always` handles the rest.

```bash
kill $(pgrep -f oracle_bot.py)
# Wait ~4s — systemd restarts it automatically
ps aux | grep oracle_bot   # confirm new PID
```

## Backend Architecture

Oracle uses a modular backend system defined in `backends/base.py`:
- **Default backend**: `AgyBackend` (Antigravity CLI `agy`)
- **Alternative backends**: `ClaudeCliBackend` (Claude Code CLI `claude`)
- Switch backends at any time in `~/.ai/config.json` (`ai.backend`) or via environment variable `ORACLE_BACKEND=agy` / `ORACLE_BACKEND=claude`.
- Configure models via `ai.model` or `ORACLE_MODEL` (e.g. `gemini-3.7-flash-high`, `gemini-3.1-pro-high`, `claude-sonnet-4-6`).

### Streaming Architecture

- Uses `agy -p --output-format stream-json --dangerously-skip-permissions --add-dir /`
- Events consumed:
  - `init`: extracts conversation_id
  - `step_update`:
    - `agent_response`: streams text deltas and tracks token usage
    - `tool`: sets activity to `tool:<name>` when active, `thinking` when done
    - `system_message`: sets activity to `thinking`
  - `result`: terminal result, session ID, usage stats

## Startup Sequence

`on_ready` flow:
1. Fetch owner, create DM channel
2. Run blocking startup backend test (`ai_backend.startup_test()`)
3. **Send "I'm back" DM** (with `CHANGES` constant listing what's new if `CHANGES != last_changes.txt`)
4. `_resume_interrupted()` — resumes any pending prompts from before restart

## Reaction System

`_dispatch_with_reactions(message, channel, user_text, session_id, channel_id)` wraps `_dispatch`:
- Adds 👀 to user's message at start
- Removes 👀 and adds ✅ when done (via `_react_done`)
- All reaction ops wrapped in `try/except discord.HTTPException` to be non-fatal

## Status Message (_LazyStatus)

- `_LazyStatus` sends nothing until there's real content to show (no placeholder hourglass/timer).
- First `status.set()` sends the message; subsequent periodic updates edit in place every `EDIT_INTERVAL` seconds.

## Concurrency & Channel Locks

- `_lock_for(channel_id)` returns a per-channel `asyncio.Lock`.
- Serializes `_dispatch`, background task resumption, and session compaction per channel.

## `CHANGES` Constant

Lives at the top of `oracle_bot.py`. Update this string whenever deploying a new version so the startup DM describes what's new to the user.
