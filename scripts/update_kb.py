#!/usr/bin/env python3
"""
Knowledge base updater — extracts learnings from Oracle sessions and stages them into Dominion.
Uses Oracle's modular AI backend (BaseAIBackend) to perform extraction.
Stages output into /mnt/hdd/notes/Dominion/mind/inbox/ as pending-review notes (Article XII).
"""
import asyncio
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, Optional

KB_DIR = Path(os.environ.get("ORACLE_DIR") or Path(__file__).resolve().parent.parent)
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from backends.base import BaseAIBackend


def _get_inbox_dir() -> Path:
    env_inbox = os.environ.get("KB_INBOX_DIR")
    if env_inbox:
        return Path(env_inbox)
    cfg_path = KB_DIR / "config.json"
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            vpath = cfg.get("kb", {}).get("vault_path")
            if vpath:
                vp = Path(vpath)
                if (vp / "mind" / "inbox").exists():
                    return vp / "mind" / "inbox"
                if (vp / "inbox").exists():
                    return vp / "inbox"
                return vp / "inbox"
        except Exception:
            pass
    if Path("/mnt/hdd/notes/Dominion/mind/inbox").exists():
        return Path("/mnt/hdd/notes/Dominion/mind/inbox")
    return KB_DIR / "knowledge/inbox"


DOMINION_INBOX = _get_inbox_dir()

log_dir = KB_DIR / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_path = log_dir / "update_kb.log"


def log(msg: str) -> None:
    today = date.today().isoformat()
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{today}] {msg}\n")


def load_config() -> dict:
    cfg_path = KB_DIR / "config.json"
    if cfg_path.exists():
        try:
            return json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def read_transcript(transcript_path: str) -> str:
    """Read and summarise the last 80 turns from a JSONL transcript."""
    path = Path(transcript_path)
    if not path.exists():
        return ""
    lines = []
    try:
        for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                continue

            # Antigravity stream-json format
            if "event" in obj:
                etype = obj.get("event")
                if etype == "step_update":
                    su = obj.get("step_update", {})
                    stype = su.get("step_type", "")
                    delta = su.get("text_delta", "")
                    if delta:
                        lines.append(f"AGENT: {delta[:300]}")
                    elif stype == "tool":
                        tname = su.get("tool_name") or su.get("tool_info", {}).get("name", "")
                        lines.append(f"[TOOL: {tname}]")
                elif etype == "result":
                    res = obj.get("result", {}).get("response", "")
                    if res:
                        lines.append(f"RESULT: {res[:500]}")
                continue

            # Step / Transcript line format (Claude or AGY brain logs)
            stype = obj.get("type") or obj.get("step_type") or obj.get("role", "")
            content = obj.get("content") or obj.get("text_delta") or ""
            if isinstance(content, list):
                parts = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            parts.append(f"[tool: {block.get('name','')}]")
                content = " ".join(parts)
            if stype and content:
                lines.append(f"{str(stype).upper()}: {str(content)[:500]}")
    except Exception as e:
        return f"[transcript parse error: {e}]"
    return "\n".join(lines[-80:])


EXTRACTION_PROMPT = """Analyze this session transcript and extract learnings.
Output ONLY valid JSON with these keys (omit a key if nothing found):

{{
  "stars": [
    {{"title": "short title", "body": "what worked, why it's a guiding star", "tags": ["tag1"]}}
  ],
  "scars": [
    {{"title": "short title", "body": "what went wrong, what to avoid next time", "tags": ["tag1"]}}
  ],
  "profile_updates": [
    "new fact about the user or their preferences"
  ],
  "context_updates": [
    "new project or infrastructure context"
  ]
}}

STARS = approaches the user explicitly liked, validated, or confirmed worked well.
SCARS = mistakes made, corrections from the user, failed approaches, wrong assumptions.
PROFILE_UPDATES = new facts about the user's role, preferences, expertise, workflow.
CONTEXT_UPDATES = new information about active projects or infrastructure.

Only extract things that are genuinely new and non-obvious. If nothing notable happened, return {{}}.

TRANSCRIPT:
{transcript}"""


def _fmt_items(items: Any) -> str:
    out = []
    for it in items or []:
        if isinstance(it, dict):
            title = it.get("title", "").strip()
            body = it.get("body", "").strip()
            tags = ", ".join(it.get("tags", []) or [])
            head = f"- **{title}**" + (f"  _({tags})_" if tags else "")
            out.append(head + (f"\n  {body}" if body else ""))
        else:
            out.append(f"- {it}")
    return "\n".join(out) if out else "_none_"


def stage_insights(insights: dict) -> Path:
    today = date.today().isoformat()
    target = DOMINION_INBOX if DOMINION_INBOX.parent.parent.exists() else (KB_DIR / "inbox")
    target.mkdir(parents=True, exist_ok=True)
    n = len(list(target.glob(f"{today}-*.md"))) + 1
    path = target / f"{today}-{n:03d}.md"

    path.write_text(f"""---
status: pending-review
source: oracle-session
date: {today}
---

# Oracle staged insights — {today} (#{n:03d})

Auto-extracted by session post-hook. **Unvetted — not fact.**
A steward reviews each item and promotes the true/useful ones into `mind/`
(feedback/user), `entities/` (sourced facts), or `CORRECTIONS.md` (mistakes),
discards the rest, then deletes this file. See `mind/inbox/README.md`.

## Stars — patterns that worked
{_fmt_items(insights.get("stars"))}

## Scars — mistakes / corrections
{_fmt_items(insights.get("scars"))}

## Profile updates — about the user
{_fmt_items(insights.get("profile_updates"))}

## Context updates — projects / infra
{_fmt_items(insights.get("context_updates"))}
""", encoding="utf-8")
    log(f"staged insights → {path}")
    return path


async def extract_and_stage_async(
    transcript_path: str,
    backend: BaseAIBackend,
) -> Optional[Path]:
    """
    Idiomatic extractor: runs through the active modular backend asynchronously.
    """
    transcript = read_transcript(transcript_path)
    if not transcript or len(transcript.strip().splitlines()) < 2:
        log("transcript too short for extraction — skipping")
        return None

    prompt = EXTRACTION_PROMPT.format(transcript=transcript)
    result = await backend.run_turn(prompt, session_id=None)

    if not result or not result.success:
        err = result.error if result else "no result"
        log(f"extraction backend error: {err}")
        return None

    raw = result.result.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]

    try:
        insights = json.loads(raw.strip())
    except Exception as e:
        log(f"failed to parse extraction output as JSON: {e} (raw: {raw[:150]})")
        return None

    if not isinstance(insights, dict) or not any(insights.values()):
        log("no new insights extracted from session")
        return None

    log(f"Extracted insights: {list(insights.keys())}")
    return stage_insights(insights)


def main():
    """Standalone CLI invocation: python update_kb.py <transcript_path>"""
    if len(sys.argv) < 2:
        print("Usage: python update_kb.py <transcript_path>")
        sys.exit(1)

    tp = sys.argv[1]
    from backends import get_backend
    cfg = load_config()
    ai_cfg = cfg.get("ai", {})
    backend = get_backend(
        backend_type=os.environ.get("ORACLE_BACKEND") or ai_cfg.get("backend", "agy"),
        model=os.environ.get("ORACLE_MODEL") or ai_cfg.get("model", "gemini-3.7-flash-high"),
    )
    staged = asyncio.run(extract_and_stage_async(tp, backend))
    if staged:
        print(f"Staged to: {staged}")
    else:
        print("No insights staged.")


if __name__ == "__main__":
    main()
