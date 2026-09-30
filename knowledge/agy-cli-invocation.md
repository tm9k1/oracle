# Driving `agy -p` Programmatically

How Oracle (and any script) invokes Antigravity CLI headless. Source of truth: `backends/agy.py`.

## Binary Discovery

`_find_agy()` checks, in order:
1. Custom path in config
2. `/home/tm9k1/.local/bin/agy`
3. `/usr/local/bin/agy`, `/usr/bin/agy`
4. `shutil.which("agy")`

## Flag Set

Common to both blocking and streaming calls:
```bash
agy -p "<prompt>" \
  --model gemini-3.7-flash-high \
  --effort high \
  --dangerously-skip-permissions \
  --add-dir /
```
- **New session**: includes system instructions in the turn 1 prompt (no `--conversation`).
- **Resume**: add `--conversation <session_id>`.
- Blocking: `--output-format json` (used for startup test, `/compact`).
- Streaming: `--output-format stream-json`.
- Working directory: `cwd="/home/tm9k1"`.

## Parsing `stream-json`

Newline-delimited JSON objects on stdout. Events:
- `init` → carries `conversation_id`.
- `step_update` →
  - `step_type == "agent_response"`: `text_delta` (streaming text), `usage`
  - `step_type == "tool"`: `state == "ACTIVE"` (`tool_name`), `state == "DONE"` (tool finished)
  - `step_type == "system_message"`
- `result` → terminal: carries `conversation_id`, final `response`, `usage`, `status`.

## Session Transcripts

Antigravity transcripts are stored at:
`~/.gemini/antigravity-cli/brain/<conversation_id>/.system_generated/logs/transcript.jsonl`
