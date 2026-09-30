#!/usr/bin/env python3
"""
Oracle Discord bot — personal AI assistant backed by a modular AI backend (agy / claude-cli).
Streams output via stream-json / NDJSON; the status message is sent once real text
exists, then edited every EDIT_INTERVAL seconds.
"""
import asyncio
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord

# Add scripts directory to sys.path for local imports
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from backends import BackendResult, BaseAIBackend, get_backend
from dispatch_manager import Dispatch, DispatchManager
from curiosity_engine import CuriosityEngine, ActiveQuestion

AI_DIR = Path("/home/tm9k1/.ai")
CONFIG_FILE = AI_DIR / "config.json"
SESSIONS_FILE = AI_DIR / "sessions.json"
LAST_CHANGES_FILE = AI_DIR / "last_changes.txt"
DOWNLOADS_DIR = AI_DIR / "downloads"
ATTACHMENTS_DIR = DOWNLOADS_DIR / "attachments"
DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)

# ── Config Loader ─────────────────────────────────────────────────────────────

def load_config() -> dict:
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            return {}
    return {}

def load_env() -> dict:
    env_file = AI_DIR / ".env"
    env = {}
    if env_file.exists():
        try:
            for line in env_file.read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    env[k.strip()] = v.strip()
        except Exception:
            pass
    return env

ENV = load_env()
CFG = load_config()

# Discord & bot settings
DISCORD_CFG = CFG.get("discord", {})

def get_allowed_ids() -> set[int]:
    ids = set()
    for uid in DISCORD_CFG.get("allowed_user_ids", []):
        try:
            ids.add(int(uid))
        except (ValueError, TypeError):
            pass
    env_val = os.environ.get("ALLOWED_USER_IDS") or ENV.get("ALLOWED_USER_IDS", "")
    if env_val:
        for uid in env_val.split(","):
            uid = uid.strip()
            if uid.isdigit():
                ids.add(int(uid))
    return ids

ALLOWED_IDS = get_allowed_ids()
EDIT_INTERVAL = float(DISCORD_CFG.get("edit_interval", 5.0))
MAX_MSG_CHUNKS = int(DISCORD_CFG.get("max_message_chunks", 4))

# KB and session settings
KB_CFG = CFG.get("kb", {})
STALE_THRESHOLD = float(KB_CFG.get("stale_threshold_days", 7)) * 24 * 60 * 60
RESUME_MAX_AGE = float(KB_CFG.get("resume_max_age_minutes", 30)) * 60

# AI backend settings
AI_CFG = CFG.get("ai", {})
BACKEND_NAME = os.environ.get("ORACLE_BACKEND") or AI_CFG.get("backend", "agy")
BACKEND_MODEL = os.environ.get("ORACLE_MODEL") or AI_CFG.get("model", "gemini-3.7-flash-high")
BACKEND_EFFORT = os.environ.get("ORACLE_EFFORT") or AI_CFG.get("effort", "high")
COMPACT_THRESHOLD = float(AI_CFG.get("compact_threshold", 0.65))
COMPACT_IDLE_SECS = float(AI_CFG.get("compact_idle_seconds", 600))
TIMEOUT_SECONDS = int(AI_CFG.get("timeout_seconds", 1500))

NEW_SESSION_TRIGGERS = {
    "new session", "fresh session", "new", "fresh", "reset",
    "/new", "/reset", "/fresh",
}

CHANGES = (
    "**What's new since last run:**\n"
    "• Upgraded AI backend from Claude CLI to **Antigravity CLI (agy)**\n"
    "• Default model: **Gemini 3.8 Flash (High reasoning)** — ultra fast and capable\n"
    "• Added daily automated checks & self-upgrades for newer Gemini Flash releases\n"
    "• Modular AI backend architecture: easily swap between agy, claude-cli, and other backends via config\n"
    "• Preserved all session routing, live streaming, Discord reactions, and recovery features"
)

# ── Logging & Diagnostics ─────────────────────────────────────────────────────

LOG_DIR = AI_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],  # systemd redirects stdout/stderr to oracle_bot.log
)
log = logging.getLogger("oracle")

# Global crash & unhandled exception handlers
def _handle_unhandled_exception(loop, context):
    msg = context.get("message", "Unhandled exception in event loop")
    exc = context.get("exception")
    log.critical("UNHANDLED ASYNC EXCEPTION: %s", msg, exc_info=exc)

def _handle_sys_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    log.critical("UNCAUGHT EXCEPTION: %s", exc_value, exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = _handle_sys_exception

# Graceful signal handling for systemd restarts / SIGTERM / SIGINT
def _handle_signal(sig, frame):
    sig_name = signal.Signals(sig).name if hasattr(signal, "Signals") else str(sig)
    log.info("Received signal %s — initiating graceful teardown...", sig_name)
    try:
        if "sessions" in globals() and callable(globals().get("save_sessions")):
            save_sessions(sessions)
    except Exception as e:
        log.error("Failed to save sessions during signal teardown: %s", e)
    sys.exit(0)

try:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
except Exception:
    pass

# ── Initialize AI Backend ─────────────────────────────────────────────────────

ai_backend: BaseAIBackend = get_backend(
    backend_type=BACKEND_NAME,
    model=BACKEND_MODEL,
    effort=BACKEND_EFFORT,
    timeout_seconds=TIMEOUT_SECONDS,
    edit_interval=EDIT_INTERVAL,
)
log.info("Initialized AI backend: %s", ai_backend.name)

curiosity_engine = CuriosityEngine()

# ── Session store ─────────────────────────────────────────────────────────────
# {channel_id: {session_id, last_active, started_at, pending_prompt, msg_ids}}

def load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text())
        except Exception:
            return {}
    return {}

def save_sessions(sessions_dict: dict):
    try:
        SESSIONS_FILE.write_text(json.dumps(sessions_dict, indent=2))
    except Exception as e:
        log.error("Failed to save sessions: %s", e)

# ── System prompt ─────────────────────────────────────────────────────────────

def _kb_system_prompt() -> str:
    return (
        "You are Oracle, a personal executive assistant and secretary running on the homelab host. "
        "Your working directory is /home/tm9k1. "
        "Read /home/tm9k1/.ai/IDENTITY.md and /home/tm9k1/.ai/SOUL.md for your persona and operating instructions. "
        "COMMUNICATION & PERSONA: Act as a personal assistant/secretary. Keep your replies natural, conversational, terse, and direct. "
        "SILENT FILE MANAGEMENT: When managing files, ledgers, notes, or code, handle everything quietly in the background. "
        "NEVER list, enumerate, or cite the files you updated, modified, or touched (no file paths, no lists of 'Updated file1, file2...'). "
        "Answer the core question/status conversationally without meta-documentation or file inventories. "
        "Your AUTHORITATIVE knowledge base is Dominion — the synced vault at /mnt/hdd/notes/Dominion/. "
        "Use it for anything about your operator, devices, finances, people, systems, preferences, or plans. "
        "Boot order: read CONSTITUTION.md, then CORRECTIONS.md, PLANNING-CHAMBER.md, CENSUS.md; "
        "personal preferences and feedback are in mind/, facts about the world are in entities/. "
        "For deeper Dominion work invoke the `dominion` skill. "
        "For homelab how-to (service fixes, upgrades) use the operational annex at "
        "/home/tm9k1/.ai/knowledge/ and .ai/stars|scars — treat it as a source, not ground truth (see Dominion CORRECTIONS.md). "
        "If /mnt/hdd is not mounted the vault is unavailable — fall back to .ai/USER.md and say so. "
        "Do NOT hand-edit Dominion entities/ or mind/ unless explicitly acting as its steward; "
        "your session insights are captured automatically into Dominion's review inbox. "
        "IMPORTANT: Always write a short text reply first before using any tools. "
        "Even if you need to check something, acknowledge the message in one line first, then do the tool work. "
        "ATTACHMENTS & IMAGES: Files/images sent on Discord are saved to /home/tm9k1/.ai/downloads/attachments/ and can be viewed with tools. "
        "When you generate or reference an image path (or use `![alt](path)`), Oracle will automatically attach the image to your Discord message."
    )

# ── Streaming Status Helper ───────────────────────────────────────────────────

def _status_text(text: str) -> str:
    """Compose the Discord message text for the current streaming state, truncated to fit."""
    if len(text) <= 1990:
        return text
    cut = text[-1990:]
    nl = cut.find('\n')
    return cut[nl + 1:] if nl != -1 else cut

class _LazyStatus:
    """A status message that isn't sent until there's real content to show.
    First `set()` sends; subsequent calls edit."""

    def __init__(self, channel):
        self.channel = channel
        self.msg: Optional[discord.Message] = None

    async def set(self, content: str, files: Optional[list[discord.File]] = None):
        if not content and not files:
            return self.msg
        if self.msg is None:
            if files:
                self.msg = await self.channel.send(content or None, files=files)
            else:
                self.msg = await self.channel.send(content)
        else:
            if files:
                try:
                    await self.msg.edit(content=content or None, attachments=files)
                except Exception as e:
                    log.warning("Failed to edit with attachments (%s); sending as separate message", e)
                    self.msg = await self.channel.send(content or None, files=files)
            else:
                await self.msg.edit(content=content)
        return self.msg


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}

def _extract_image_attachments(text: str) -> tuple[str, list[Path]]:
    """
    Extract local image file paths from text, clean the text for Discord,
    and return (cleaned_text, list_of_existing_image_paths).
    """
    found_paths: list[Path] = []
    seen: set[str] = set()

    def _add_path(p_str: str) -> bool:
        p_str = p_str.strip().strip("'\"`<>()")
        if p_str.startswith("file://"):
            p_str = p_str[7:]
        path = Path(p_str)
        if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file():
            canon = str(path.resolve())
            if canon not in seen:
                seen.add(canon)
                found_paths.append(path)
            return True
        return False

    def _md_repl(m):
        alt = m.group(1)
        p_str = m.group(2)
        if _add_path(p_str):
            return f"**{alt}**" if alt else ""
        return m.group(0)

    # 1. Matches ![alt](path) or [alt](path)
    cleaned = re.sub(r'!\[(.*?)\]\(((?:file://)?[^)\s]+?\.(?:png|jpe?g|webp|gif))\)', _md_repl, text, flags=re.IGNORECASE)
    cleaned = re.sub(r'(?<!!)\[(.*?)\]\(((?:file://)?[^)\s]+?\.(?:png|jpe?g|webp|gif))\)', _md_repl, cleaned, flags=re.IGNORECASE)

    # 2. Matches <attachment>path</attachment> or <image>path</image>
    def _tag_repl(m):
        p_str = m.group(1)
        if _add_path(p_str):
            return ""
        return m.group(0)

    cleaned = re.sub(r'<(?:attachment|image)>(.*?)</(?:attachment|image)>', _tag_repl, cleaned, flags=re.IGNORECASE)

    # 3. Matches [attachment: path]
    def _attach_note_repl(m):
        p_str = m.group(1)
        if _add_path(p_str):
            return ""
        return m.group(0)

    cleaned = re.sub(r'\[attachment:\s*([^\s\]]+)\]', _attach_note_repl, cleaned, flags=re.IGNORECASE)

    # 4. Matches [ARTIFACT: ...] \n Path: ...
    def _artifact_repl(m):
        p_str = m.group(1)
        if _add_path(p_str):
            return ""
        return m.group(0)

    cleaned = re.sub(r'\[ARTIFACT:[^\]]+\]\s*Path:\s*((?:file://)?\S+?\.(?:png|jpe?g|webp|gif))', _artifact_repl, cleaned, flags=re.IGNORECASE)

    # 5. Standalone file lines or Path: ... lines
    lines = []
    for line in cleaned.splitlines():
        trimmed = line.strip()
        if trimmed.lower().startswith("path:"):
            cand = trimmed[5:].strip()
            if _add_path(cand):
                continue
        if (trimmed.startswith("/") or trimmed.startswith("file://")) and any(trimmed.lower().endswith(ext) for ext in IMAGE_EXTENSIONS):
            if _add_path(trimmed):
                continue
        lines.append(line)
    cleaned = "\n".join(lines)

    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
    return cleaned, found_paths


# ── Quota / availability state ────────────────────────────────────────────────

_quota_reset_at: float = 0.0   # epoch seconds; 0 = no quota problem
_quota_watcher_task: "asyncio.Task | None" = None


def _parse_quota_reset(error_str: str) -> float:
    """Parse 'Resets in 71h49m55s' from error string → absolute epoch seconds. Returns 0 if not found."""
    m = re.search(r"Resets in (\d+)h(\d+)m(\d+)s", error_str or "")
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return time.time() + h * 3600 + mn * 60 + s
    # Fallback: unknown reset time — assume 24 h
    if "quota" in (error_str or "").lower():
        return time.time() + 86400
    return 0.0


def _quota_remaining_str(reset_at: float) -> str:
    secs = max(0, reset_at - time.time())
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


async def _set_quota_mode(reset_at: float):
    global _quota_reset_at, _quota_watcher_task
    _quota_reset_at = reset_at
    remaining = _quota_remaining_str(reset_at)
    log.warning("Quota exceeded — setting Busy presence. Resets in %s", remaining)
    try:
        await bot.change_presence(
            status=discord.Status.dnd,
            activity=discord.CustomActivity(name=f"Quota exceeded — resets in {remaining}"),
        )
    except Exception as e:
        log.warning("Could not set DND presence: %s", e)
    # Cancel any existing watcher and start a fresh one
    if _quota_watcher_task and not _quota_watcher_task.done():
        _quota_watcher_task.cancel()
    _quota_watcher_task = asyncio.create_task(_quota_watcher(reset_at))


def _format_status_activity() -> str:
    """Format status string: backend and active session count."""
    n = len(sessions)
    sess_label = f"{n} session" if n == 1 else f"{n} sessions"
    return f"{ai_backend.name} · {sess_label}"


async def _update_presence(status: discord.Status = discord.Status.online):
    """Set Discord presence showing backend and active session count.
    Ignored if currently in quota-exceeded mode."""
    if _quota_reset_at and time.time() < _quota_reset_at:
        return
    text = _format_status_activity()
    try:
        await bot.change_presence(
            status=status,
            activity=discord.CustomActivity(name=text),
        )
        log.info("Updated Discord presence: %s (%s)", status, text)
    except Exception as e:
        log.warning("Could not update presence: %s", e)


async def _clear_quota_mode():
    global _quota_reset_at
    _quota_reset_at = 0.0
    log.info("Quota cleared — restoring Online presence")
    await _update_presence(discord.Status.online)


async def _quota_watcher(reset_at: float):
    """Sleep until quota reset time, then verify backend and restore presence."""
    sleep_secs = max(0, reset_at - time.time()) + 60  # +60 s buffer
    log.info("Quota watcher sleeping %.0f s (until ~%s)", sleep_secs,
             datetime.fromtimestamp(reset_at).strftime("%H:%M"))
    await asyncio.sleep(sleep_secs)
    # Try a startup test — if it passes, go online; if not, re-arm
    try:
        res = await ai_backend.startup_test()
        if res.success:
            await _clear_quota_mode()
            return
        new_reset = _parse_quota_reset(res.error or "")
        if new_reset:
            log.warning("Quota still exceeded after wakeup — rearming watcher")
            await _set_quota_mode(new_reset)
        else:
            # Some other error — still clear quota mode, let normal dispatch surface it
            await _clear_quota_mode()
    except Exception as e:
        log.error("Quota watcher test failed: %s", e)
        await _clear_quota_mode()

# ── Concurrency & Background Tasks ───────────────────────────────────────────

_channel_locks: dict[str, asyncio.Lock] = {}
_bg_pollers: dict[str, asyncio.Task] = {}

def _lock_for(channel_id: str) -> asyncio.Lock:
    """One lock per channel — serializes invocations to prevent racing against the same session."""
    return _channel_locks.setdefault(channel_id, asyncio.Lock())

def _transcript_path(session_id: str) -> Optional[str]:
    """Find transcript path for a session across known locations."""
    if not session_id:
        return None
    # agy brain path
    agy_path = Path(f"/home/tm9k1/.gemini/antigravity-cli/brain/{session_id}/.system_generated/logs/transcript.jsonl")
    if agy_path.exists():
        return str(agy_path)
    # claude path
    claude_path = Path(f"/home/tm9k1/.claude/projects/-home-tm9k1/{session_id}.jsonl")
    if claude_path.exists():
        return str(claude_path)
    return None

def _task_mtimes(session_id: str) -> dict:
    if not session_id:
        return {}
    mtimes = {}
    # agy tasks
    agy_task_dir = Path(f"/home/tm9k1/.gemini/antigravity-cli/brain/{session_id}/.system_generated/tasks")
    if agy_task_dir.exists():
        for f in agy_task_dir.glob("*.log"):
            if f.exists():
                mtimes[str(f)] = f.stat().st_mtime
    # claude tasks
    claude_task_dir = Path(f"/tmp/claude-1000/-home-tm9k1/{session_id}/tasks")
    if claude_task_dir.exists():
        for f in claude_task_dir.glob("*.output"):
            if f.exists():
                mtimes[str(f)] = f.stat().st_mtime
    return mtimes

async def _poll_background_tasks(channel, channel_id: str, session_id: str):
    """Watch for background task files to change and notify via Discord."""
    initial = _task_mtimes(session_id)
    if not initial:
        return

    log.info("bg task poller started for session %s (%d task(s))", session_id[:8], len(initial))
    for _ in range(25):  # max ~25 minutes
        await asyncio.sleep(60)

        current = sessions.get(channel_id, {})
        if current.get("session_id") != session_id:
            log.info("bg task poller: session changed, stopping")
            return

        current_mtimes = _task_mtimes(session_id)
        if current_mtimes == initial:
            continue

        log.info("bg task poller: tasks changed for session %s, resuming", session_id[:8])
        status = _LazyStatus(channel)
        try:
            async with _lock_for(channel_id):
                async def on_periodic(t, a):
                    await status.set(_status_text(t))

                data = await ai_backend.stream_turn(
                    prompt="task-notification: one or more background tasks just completed. Report their results now.",
                    session_id=session_id,
                    system_prompt=_kb_system_prompt(),
                    periodic_status_callback=on_periodic,
                )

            text = data.result or "_(background tasks completed)_"
            if len(text) > 1990:
                split_at = text.rfind('\n', 0, 1990)
                split_at = (split_at + 1) if split_at != -1 else 1990
                first_chunk, rest = text[:split_at], text[split_at:]
            else:
                first_chunk, rest = text, ""
            await status.set(first_chunk)
            if rest:
                await _send_chunks(channel, rest)

            new_sid = data.session_id
            sessions[channel_id]["session_id"] = new_sid
            sessions[channel_id]["last_active"] = time.time()
            sessions[channel_id]["pending_prompt"] = None
            save_sessions(sessions)
            ai_backend.mirror_session(new_sid)
            log.info("bg task poller: delivered update for session %s", session_id[:8])
        except Exception as e:
            log.error("bg task poller error: %s", e)
            await status.set(f"_(background tasks done — error fetching results: {e})_")
        return

    log.warning("bg task poller timed out for session %s with no task changes", session_id[:8])

async def _maybe_compact(channel, channel_id: str, session_id: str, fraction: float):
    """Wait for idle, then /compact if context is still over threshold and session unchanged."""
    pct = int(fraction * 100)
    log.info("context at %d%%, scheduling compact for session %s after %ds idle",
             pct, session_id[:8], int(COMPACT_IDLE_SECS))
    await asyncio.sleep(COMPACT_IDLE_SECS)

    current = sessions.get(channel_id, {})
    if current.get("session_id") != session_id:
        log.info("compact skipped: session changed while waiting")
        return
    if time.time() - current.get("last_active", 0) < COMPACT_IDLE_SECS:
        log.info("compact skipped: session still active")
        return

    log.info("compacting session %s (was %d%% full)", session_id[:8], pct)
    try:
        async with _lock_for(channel_id):
            data = await ai_backend.compact(session_id)
        if data and data.session_id:
            new_sid = data.session_id
            sessions[channel_id]["session_id"] = new_sid
            sessions[channel_id]["pending_prompt"] = None
            save_sessions(sessions)
            ai_backend.mirror_session(new_sid)
            log.info("compacted %s → %s", session_id[:8], new_sid[:8])
            await channel.send(f"_(context was {pct}% full — compacted)_")
    except Exception as e:
        log.error("compaction failed: %s", e)

# ── Daily Model Upgrade Checker ──────────────────────────────────────────────

_model_checker_task: "asyncio.Task | None" = None


async def _daily_model_upgrade_checker(dm=None):
    """Periodically check once a day for newer Gemini Flash models and auto-upgrade."""
    await asyncio.sleep(60)
    while True:
        try:
            log.info("Running daily model upgrade check...")
            from check_model_upgrade import check_and_upgrade_model, restart_service

            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(
                None,
                lambda: check_and_upgrade_model(force=False, check_only=False, do_restart=False),
            )
            if res.get("upgraded"):
                old_m = res.get("old_model")
                new_m = res.get("new_model")
                log.info("Auto-upgraded model from %s to %s!", old_m, new_m)
                if dm:
                    try:
                        await dm.send(
                            f"🚀 **Oracle Auto-Upgraded Model**:\n`{old_m}` ➔ `{new_m}`\nRestarting service now..."
                        )
                    except Exception as de:
                        log.warning("Could not send upgrade notification DM: %s", de)
                await asyncio.sleep(2)
                await loop.run_in_executor(None, restart_service)
                return
            else:
                log.info("Daily model check complete: %s", res.get("status", "ok"))
        except Exception as e:
            log.error("Error in daily model upgrade checker: %s", e)

        await asyncio.sleep(86400)

# ── Dominion Dispatch Service ─────────────────────────────────────────────────

_dispatch_checker_task: Optional[asyncio.Task] = None
DISPATCH_CHECK_INTERVAL = float(CFG.get("dominion", {}).get("dispatch_check_interval_seconds", 3600))


async def _periodic_dispatch_checker(dm=None):
    """Periodically check DISPATCH.md for due dispatches targeting Oracle and notify owner via DM."""
    await asyncio.sleep(45)
    while True:
        try:
            if dm:
                manager = DispatchManager()
                due = manager.get_due_for("oracle", ignore_already_sent=True)
                for d in due:
                    log.info("Dispatch due for Oracle: [%s] %s — sending to owner DM", d.id, d.title)
                    msg = manager.format_discord_message(d)
                    sent_msg = await dm.send(msg)
                    manager.mark_dispatched(d, channel_id=str(dm.id), message_id=sent_msg.id)
                    await asyncio.sleep(2)
        except Exception as e:
            log.error("Error in periodic dispatch checker: %s", e)

        await asyncio.sleep(DISPATCH_CHECK_INTERVAL)


async def _handle_dispatch_command(channel, user_text: str):
    """Handle /dispatch commands in Discord."""
    parts = user_text.strip().split()
    subcmd = parts[1].lower() if len(parts) > 1 else "list"
    manager = DispatchManager()

    if subcmd in ("list", "all"):
        target_filter = parts[2].lower() if len(parts) > 2 else "all"
        if target_filter == "all":
            dispatches = manager.parse_dispatches()
        else:
            dispatches = manager.get_pending_for(target_filter)

        if not dispatches:
            await channel.send(f"No pending dispatches found matching target `{target_filter}`.")
            return

        lines = [f"📋 **Dominion Pending Dispatches** (`{len(dispatches)}`):"]
        for idx, d in enumerate(dispatches, 1):
            sent_tag = "✅ *sent*" if manager.is_dispatched(d.id) else ("⏰ *due*" if d.is_due else "⏳ *waiting*")
            due_str = f"due `{d.due_date}`" if d.due_date else (f"`{d.trigger}`" if d.trigger else "no trigger")
            lines.append(f"{idx}. `[{d.id}]` **{d.target}**: {d.title}\n   └ {due_str} · {sent_tag}")
        await channel.send("\n".join(lines))

    elif subcmd == "check":
        due = manager.get_due_for("oracle", ignore_already_sent=True)
        if not due:
            await channel.send("No dispatches are currently due for Oracle.")
            return
        sent_count = 0
        for d in due:
            msg = manager.format_discord_message(d)
            sent_msg = await channel.send(msg)
            manager.mark_dispatched(d, channel_id=str(channel.id), message_id=sent_msg.id)
            sent_count += 1
            await asyncio.sleep(1)
        await channel.send(f"Dispatched {sent_count} pending request(s).")

    elif subcmd in ("send", "trigger", "run"):
        if len(parts) < 3:
            await channel.send("Usage: `/dispatch send <id or keyword>` (e.g. `/dispatch send contrite` or `/dispatch send 89a4ca8085e1`)")
            return
        query = parts[2].lower()
        dispatches = manager.parse_dispatches()
        matched = [d for d in dispatches if query == d.id.lower() or query in d.title.lower() or query in d.target.lower()]
        if not matched:
            await channel.send(f"No dispatch found matching `{query}`.")
            return
        d = matched[0]
        msg = manager.format_discord_message(d)
        sent_msg = await channel.send(msg)
        manager.mark_dispatched(d, channel_id=str(channel.id), message_id=sent_msg.id)

    else:
        help_text = (
            "**Dominion Dispatch Commands:**\n"
            "• `/dispatch list [target]` — list pending dispatches (e.g. `/dispatch list oracle` or `/dispatch list all`)\n"
            "• `/dispatch check` — check and deliver any pending dispatches due for Oracle\n"
            "• `/dispatch send <id/keyword>` — deliver a specific dispatch right now (e.g. `/dispatch send contrite`)"
        )
        await channel.send(help_text)

# ── Dominion Curiosity & Inquirer Service ─────────────────────────────────────

_curiosity_checker_task: Optional[asyncio.Task] = None
CURIOUSITY_CHECK_INTERVAL = float(CFG.get("curiosity", {}).get("check_interval_seconds", 1800))


async def _periodic_curiosity_checker(dm=None):
    """Periodically survey Dominion and ask/nudge curiosity questions via DM."""
    await asyncio.sleep(60)
    while True:
        try:
            if dm:
                should_act, action = curiosity_engine.should_ask_now()
                if should_act and action == "ask":
                    q = curiosity_engine.pop_next_question()
                    if q:
                        log.info("Curiosity engine: asking question [%s] (%s) to owner DM", q.id, q.topic)
                        msg = curiosity_engine.format_discord_question(q)
                        sent_msg = await dm.send(msg)
                        curiosity_engine.register_message_sent(sent_msg.id, str(dm.id))
                elif should_act and action == "nudge":
                    aq = curiosity_engine.get_active_question()
                    if aq:
                        log.info("Curiosity engine: gentle nudge for [%s] to owner DM", aq.id)
                        msg = curiosity_engine.format_discord_nudge(aq)
                        await dm.send(msg)
                        curiosity_engine.register_nudge_sent()
        except Exception as e:
            log.error("Error in periodic curiosity checker: %s", e)

        await asyncio.sleep(CURIOUSITY_CHECK_INTERVAL)


async def _handle_curiosity_command(channel, user_text: str):
    """Handle /curiosity commands in Discord."""
    parts = user_text.strip().split()
    subcmd = parts[1].lower() if len(parts) > 1 else "status"

    if subcmd in ("status", "info"):
        summary = curiosity_engine.get_status_summary()
        status_lines = [
            "🧭 **Dominion Curiosity Status**:",
            f"• **Enabled**: `{summary['enabled']}`",
            f"• **Queued Questions**: `{summary['queue_length']}`",
            f"• **Answered Questions**: `{summary['answered_count']}`",
            f"• **Skipped Questions**: `{summary['skipped_count']}`",
        ]
        daily = summary.get("daily_stats", {})
        if daily.get("date"):
            status_lines.append(f"• **Today ({daily['date']})**: `{daily.get('count', 0)}` asked")

        aq = summary.get("active_question")
        if aq:
            asked_at_str = datetime.fromtimestamp(aq["asked_at"]).strftime("%Y-%m-%d %H:%M")
            status_lines.append(
                f"• **Active Question**: `[{aq['id']}]` ({aq['topic']}) - asked `{asked_at_str}`, nudges: `{aq.get('nudge_count', 0)}`\n"
                f"  └ *\"{aq['question']}\"*"
            )
        else:
            status_lines.append("• **Active Question**: none (ready for next prompt)")

        await channel.send("\n".join(status_lines))

    elif subcmd in ("ask", "next"):
        q = curiosity_engine.pop_next_question()
        if not q:
            await channel.send("No curiosity questions available in queue. Run `/curiosity survey` to discover new questions.")
            return
        msg = curiosity_engine.format_discord_question(q)
        sent_msg = await channel.send(msg)
        curiosity_engine.register_message_sent(sent_msg.id, str(channel.id))

    elif subcmd in ("survey", "scan", "refresh"):
        questions = curiosity_engine.run_survey(force=True)
        await channel.send(f"Dominion survey complete. Queued `{len(questions)}` candidate question(s).")

    elif subcmd in ("skip", "pass"):
        skipped = curiosity_engine.skip_active_question("manual_command")
        if skipped:
            await channel.send(f"Skipped active question on `{skipped.topic}`.")
        else:
            await channel.send("No active curiosity question to skip.")

    elif subcmd in ("queue", "list"):
        st = curiosity_engine.load_state()
        queue = st.get("queued_questions", [])
        if not queue:
            await channel.send("Curiosity queue is empty. Run `/curiosity survey` to refresh.")
            return
        lines = [f"📋 **Upcoming Curiosity Queue** (`{len(queue)}` queued):"]
        for idx, q_dict in enumerate(queue[:5], 1):
            lines.append(f"{idx}. `[{q_dict.get('category', 'general')}]` **{q_dict.get('topic', '')}**: {q_dict.get('question', '')[:90]}...")
        await channel.send("\n".join(lines))

    else:
        help_text = (
            "**Dominion Curiosity Commands:**\n"
            "• `/curiosity status` — view current state and active question\n"
            "• `/curiosity ask` — ask the next queued question right now\n"
            "• `/curiosity survey` — force weekly survey of Dominion vault to find new gaps\n"
            "• `/curiosity skip` — pass on the current active question\n"
            "• `/curiosity queue` — view upcoming questions in queue"
        )
        await channel.send(help_text)


# ── Dominion KB Extraction ───────────────────────────────────────────────────

_extracted_sessions: set[str] = set()
_kb_extract_tasks: dict[str, asyncio.Task] = {}
EXTRACTION_IDLE_SECS = float(KB_CFG.get("extraction_idle_seconds", 300))


def _get_transcript_path(session_id: str) -> Optional[Path]:
    if not session_id:
        return None
    agy_path = Path(f"/home/tm9k1/.gemini/antigravity-cli/brain/{session_id}/.system_generated/logs/transcript.jsonl")
    if agy_path.exists():
        return agy_path
    claude_path = Path(f"/tmp/claude-1000/-home-tm9k1/{session_id}.jsonl")
    if claude_path.exists():
        return claude_path
    claude_path2 = Path(f"/home/tm9k1/.claude/projects/-home-tm9k1/{session_id}.jsonl")
    if claude_path2.exists():
        return claude_path2
    return None


async def _maybe_extract_kb(channel_id: str, session_id: str, delay: float = EXTRACTION_IDLE_SECS):
    """Wait for conversation to go idle, then extract learnings into Dominion inbox."""
    if not session_id or session_id in _extracted_sessions:
        return
    if delay > 0:
        await asyncio.sleep(delay)

    current = sessions.get(channel_id, {})
    if delay > 0 and current.get("session_id") != session_id:
        return
    if session_id in _extracted_sessions:
        return

    tp = _get_transcript_path(session_id)
    if not tp:
        log.debug("no transcript found for session %s, skipping KB extraction", session_id[:8])
        return

    _extracted_sessions.add(session_id)
    log.info("extracting KB insights for session %s", session_id[:8])
    try:
        import update_kb
        await update_kb.extract_and_stage_async(str(tp), ai_backend)
    except Exception as e:
        log.error("KB extraction failed for session %s: %s", session_id[:8], e)
        _extracted_sessions.discard(session_id)

# ── Discord bot ───────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Client(intents=intents)

sessions: dict = {}
pending: dict = {}

def _fmt_elapsed(seconds: float) -> str:
    if seconds < 60: return f"{int(seconds)}s"
    if seconds < 3600: return f"{int(seconds / 60)}m"
    if seconds < 86400: return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"

def _strip_mention(text: str) -> str:
    if bot.user:
        text = text.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "")
    return text.strip()

async def _send_chunks(channel, text: str) -> list[discord.Message]:
    """Send text split at newline boundaries near 1990 chars. Returns all sent messages."""
    if not text:
        return []
    msgs = []
    while text:
        if len(text) <= 1990:
            chunk, text = text, ""
        else:
            split_at = text.rfind('\n', 0, 1990)
            split_at = (split_at + 1) if split_at != -1 else 1990
            chunk, text = text[:split_at], text[split_at:]
        msgs.append(await channel.send(chunk))
    return msgs

async def _resolve_reply_context(message: discord.Message) -> Optional[str]:
    if not message.reference:
        return None
    try:
        ref = await message.channel.fetch_message(message.reference.message_id)
    except Exception:
        return None

    ref_text = ref.content or "(no text)"
    author = "Oracle" if ref.author == bot.user else "User"

    # Check if reply points to a different session
    channel_id = str(message.channel.id)
    current_sid = (sessions.get(channel_id) or {}).get("session_id", "")
    cross_hint = ""
    for s in sessions.values():
        if str(ref.id) in [str(m) for m in (s.get("msg_ids") or [])]:
            ref_sid = s.get("session_id", "")
            if ref_sid and ref_sid != current_sid:
                tpath = _transcript_path(ref_sid)
                cross_hint = f"\n(from session {ref_sid}" + (f"; transcript at {tpath})" if tpath else ")")
            break

    return f"[Replying to {author}: {ref_text[:600]}{cross_hint}]"

async def _react(message: discord.Message, emoji: str):
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        pass

async def _react_done(message: discord.Message):
    try:
        await message.remove_reaction("👀", bot.user)
    except discord.HTTPException:
        pass
    await _react(message, "✅")

async def _dispatch_with_reactions(message: discord.Message, channel, user_text: str, session_id: Optional[str], channel_id: str):
    await _react(message, "👀")
    try:
        await _dispatch(channel, user_text, session_id, channel_id)
    finally:
        await _react_done(message)

async def _dispatch(channel, user_text: str, session_id: Optional[str], channel_id: str):
    now = time.time()
    existing = sessions.get(channel_id, {})

    sessions[channel_id] = {
        "session_id": session_id or existing.get("session_id", ""),
        "last_active": now,
        "started_at": existing.get("started_at", now),
        "pending_prompt": user_text,
        "msg_ids": existing.get("msg_ids", []),
    }
    save_sessions(sessions)

    status = _LazyStatus(channel)

    async def on_periodic_update(accumulated_text: str, current_activity: str):
        await status.set(_status_text(accumulated_text))

    try:
        async with _lock_for(channel_id):
            data = await ai_backend.stream_turn(
                prompt=user_text,
                session_id=session_id,
                system_prompt=_kb_system_prompt(),
                periodic_status_callback=on_periodic_update,
            )
    except Exception as e:
        log.error("AI backend error: %s", e)
        is_timeout = "timed out" in str(e).lower()
        if is_timeout:
            await status.set("timed out after 25 min — session preserved, reply to check status or say `new session` to start fresh")
        else:
            await status.set(f"Error: {e}")
        sessions[channel_id]["pending_prompt"] = None
        save_sessions(sessions)
        return

    final_text = data.result or "_(no response)_"

    # Extract image attachments from text and/or session brain directory
    cleaned_text, image_paths = _extract_image_attachments(final_text)

    # Detect newly generated images in artifact dir during this turn
    existing_canon = {str(p.resolve()) for p in image_paths}
    if data.session_id:
        brain_dir = Path(f"/home/tm9k1/.gemini/antigravity-cli/brain/{data.session_id}")
        if brain_dir.is_dir():
            for img_file in brain_dir.glob("*"):
                if img_file.suffix.lower() in IMAGE_EXTENSIONS and img_file.is_file():
                    try:
                        if img_file.stat().st_mtime >= now - 5:
                            canon = str(img_file.resolve())
                            if canon not in existing_canon:
                                existing_canon.add(canon)
                                image_paths.append(img_file)
                    except Exception:
                        pass

    discord_files = []
    total_size = 0
    MAX_UPLOAD_BYTES = 24 * 1024 * 1024  # Discord upload limit safety buffer
    for p in image_paths[:10]:
        try:
            sz = p.stat().st_size
            if sz > MAX_UPLOAD_BYTES:
                log.warning("Image %s exceeds Discord max size (%d bytes); skipping", p, sz)
                continue
            if total_size + sz > MAX_UPLOAD_BYTES:
                log.warning("Total upload size limit reached; skipping remaining images (%s)", p)
                break
            discord_files.append(discord.File(str(p), filename=p.name))
            total_size += sz
        except Exception as e:
            log.warning("Failed to load image %s for discord: %s", p, e)

    final_text = cleaned_text or "_(no response)_"

    # Cap total output to MAX_MSG_CHUNKS messages to avoid spam on long responses
    cap = MAX_MSG_CHUNKS * 1990
    if len(final_text) > cap:
        final_text = final_text[-cap:]

    if len(final_text) > 1990:
        split_at = final_text.rfind('\n', 0, 1990)
        split_at = (split_at + 1) if split_at != -1 else 1990
        first_chunk, rest = final_text[:split_at], final_text[split_at:]
    else:
        first_chunk, rest = final_text, ""

    await status.set(first_chunk, files=discord_files if discord_files else None)
    overflow = await _send_chunks(channel, rest) if rest else []

    if len(image_paths) > 10:
        extra_files = []
        for p in image_paths[10:20]:
            try:
                extra_files.append(discord.File(str(p), filename=p.name))
            except Exception:
                pass
        if extra_files:
            try:
                extra_msg = await channel.send(files=extra_files)
                overflow.append(extra_msg)
            except Exception as e:
                log.warning("Failed to send extra images: %s", e)

    sent_ids = ([str(status.msg.id)] if status.msg else []) + [str(m.id) for m in overflow]

    sessions[channel_id] = {
        "session_id": data.session_id,
        "last_active": time.time(),
        "started_at": existing.get("started_at", now),
        "pending_prompt": None,
        "msg_ids": (existing.get("msg_ids", []) + sent_ids)[-20:],
    }
    save_sessions(sessions)
    await _update_presence()
    log.info("session %s active for channel %s", data.session_id[:8] if data.session_id else "-", channel_id)

    # Background task poller
    old_poller = _bg_pollers.pop(channel_id, None)
    if old_poller:
        old_poller.cancel()
    if data.session_id:
        _bg_pollers[channel_id] = asyncio.create_task(
            _poll_background_tasks(channel, channel_id, data.session_id)
        )

    # Compaction check
    fraction = ai_backend.get_context_fraction(data)
    if fraction >= COMPACT_THRESHOLD and data.session_id:
        asyncio.create_task(_maybe_compact(channel, channel_id, data.session_id, fraction))

    # Post-turn idle KB extraction (debounced: resets idle timer on each message)
    if data.session_id:
        old_kb = _kb_extract_tasks.pop(channel_id, None)
        if old_kb:
            old_kb.cancel()
        _kb_extract_tasks[channel_id] = asyncio.create_task(
            _maybe_extract_kb(channel_id, data.session_id)
        )

async def _resume_interrupted():
    for channel_id, session in list(sessions.items()):
        prompt = session.get("pending_prompt")
        if not prompt:
            continue
        age = time.time() - session.get("last_active", 0)
        if age > RESUME_MAX_AGE:
            log.info("dropping stale pending_prompt for channel %s (age %.0fs)", channel_id, age)
            sessions[channel_id]["pending_prompt"] = None
            save_sessions(sessions)
            continue
        sid = session.get("session_id") or None
        log.info("resuming interrupted prompt for channel %s", channel_id)
        try:
            channel = await bot.fetch_channel(int(channel_id))
            await channel.send("_(picking up where I left off...)_")
            await _dispatch(channel, prompt, sid, channel_id)
        except Exception as e:
            log.error("failed to resume channel %s: %s", channel_id, e)

@bot.event
async def on_ready():
    log.info("Oracle online as %s (id=%s) with backend: %s", bot.user, bot.user.id if bot.user else "-", ai_backend.name)
    try:
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(_handle_unhandled_exception)
    except Exception:
        pass
    try:
        app = await bot.application_info()
        owner = app.owner
        log.info("Bot owner: %s (id=%s)", owner, owner.id)
        dm = await owner.create_dm()

        try:
            res = await ai_backend.startup_test()
            if not res.success and res.error:
                raise RuntimeError(res.error)
            log.info("startup AI backend test passed, session %s", res.session_id[:8] if res.session_id else "-")
        except Exception as ce:
            err_str = str(ce)
            reset_at = _parse_quota_reset(err_str)
            if reset_at:
                await _set_quota_mode(reset_at)
                remaining = _quota_remaining_str(reset_at)
                await dm.send(f"⚠️ Oracle is up but **{ai_backend.name} quota is exceeded** — set to Busy. Resets in **{remaining}**.")
            else:
                await dm.send(f"Oracle is up but {ai_backend.name} test failed: {ce}")
            log.error("startup AI backend test failed: %s", ce)
            return

        last_changes = LAST_CHANGES_FILE.read_text() if LAST_CHANGES_FILE.exists() else ""
        if CHANGES != last_changes:
            LAST_CHANGES_FILE.write_text(CHANGES)

        await _update_presence(discord.Status.online)
        await _resume_interrupted()

        global _model_checker_task
        if _model_checker_task is None or _model_checker_task.done():
            _model_checker_task = asyncio.create_task(_daily_model_upgrade_checker(dm))

        global _dispatch_checker_task
        if _dispatch_checker_task is None or _dispatch_checker_task.done():
            _dispatch_checker_task = asyncio.create_task(_periodic_dispatch_checker(dm))

        global _curiosity_checker_task
        if _curiosity_checker_task is None or _curiosity_checker_task.done():
            _curiosity_checker_task = asyncio.create_task(_periodic_curiosity_checker(dm))
    except Exception as e:
        log.warning("on_ready error: %s", e)

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user or message.author.bot:
        return
    if not isinstance(message.channel, discord.DMChannel):
        return
    if message.author.id not in ALLOWED_IDS:
        return

    channel_id = str(message.channel.id)
    user_text = _strip_mention(message.content)

    # ── Inbound attachments (images, docs, files) ───────────────────────────
    downloaded_attachments: list[Path] = []
    if message.attachments:
        ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)
        date_prefix = datetime.now().strftime("%Y%m%d")
        for att in message.attachments:
            safe_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', att.filename)
            dest_file = ATTACHMENTS_DIR / f"{date_prefix}_{message.id}_{safe_name}"
            try:
                await att.save(dest_file)
                downloaded_attachments.append(dest_file)
                log.info("Downloaded inbound attachment: %s (%d bytes) -> %s", att.filename, att.size, dest_file)
            except Exception as e:
                log.error("Failed to save inbound attachment %s: %s", att.filename, e)

    if not user_text and not downloaded_attachments:
        await message.channel.send("?")
        return

    if downloaded_attachments:
        att_lines = []
        for p in downloaded_attachments:
            if p.suffix.lower() in IMAGE_EXTENSIONS:
                att_lines.append(f"- [Image attachment: {p}] (type: {p.suffix.lower()})")
            else:
                att_lines.append(f"- [File attachment: {p}]")
        att_section = "User uploaded the following attachment(s):\n" + "\n".join(att_lines)
        if not user_text:
            user_text = f"User sent the following attachment(s) with no additional text:\n{att_section}\n\nPlease inspect the attachment(s) and assist."
        else:
            user_text = f"{user_text}\n\n[Inbound Attachments]\n{att_section}"

    # ── Quota guard ───────────────────────────────────────────────────────────
    if _quota_reset_at and time.time() < _quota_reset_at:
        remaining = _quota_remaining_str(_quota_reset_at)
        await message.channel.send(
            f"⚠️ AI backend quota exceeded — I'm offline until quota resets (~{remaining} left). No AI calls are being made."
        )
        return

    # ── Explicit new session ──────────────────────────────────────────────────
    if user_text.lower() in NEW_SESSION_TRIGGERS:
        old_s = sessions.pop(channel_id, None)
        pending.pop(channel_id, None)
        save_sessions(sessions)
        await _update_presence()
        old_poller = _bg_pollers.pop(channel_id, None)
        if old_poller:
            old_poller.cancel()
        old_kb = _kb_extract_tasks.pop(channel_id, None)
        if old_kb:
            old_kb.cancel()
        if old_s and old_s.get("session_id"):
            asyncio.create_task(_maybe_extract_kb(channel_id, old_s["session_id"], delay=0))
        await message.channel.send("Starting fresh session.")
        return

    # ── Dominion Dispatch commands ────────────────────────────────────────────
    if user_text.lower().startswith(("/dispatch", "/dispatches")):
        await _handle_dispatch_command(message.channel, user_text)
        return

    # ── Dominion Curiosity commands ───────────────────────────────────────────
    if user_text.lower().startswith(("/curiosity", "/inquirer")):
        await _handle_curiosity_command(message.channel, user_text)
        return

    # ── Reply context injection ───────────────────────────────────────────────
    reply_ctx = await _resolve_reply_context(message)
    if reply_ctx:
        user_text = f"{reply_ctx}\n\n{user_text}"

    # ── Dominion Curiosity Conversation Tracking ──────────────────────────────
    active_q = curiosity_engine.get_active_question()
    if active_q and active_q.status == "pending":
        reply_to_msg_id = message.reference.message_id if message.reference else None
        curiosity_intent = curiosity_engine.classify_intent(user_text, reply_to_message_id=reply_to_msg_id)

        if curiosity_intent == "skip":
            curiosity_engine.skip_active_question("user_skipped")
            await message.channel.send("Understood — skipped that question for now. I'll ask about another area next time.")
            return
        elif curiosity_intent == "answer":
            aq, staged_path = curiosity_engine.record_answer(user_text, auto_stage=True)
            staged_name = staged_path.name if staged_path else "inbox"
            curiosity_context = (
                f"\n\n[Dominion Curiosity: User answered our question about {aq.topic}: '{aq.question}'. "
                f"Insight staged into Dominion inbox ({staged_name}). "
                f"Acknowledge what they shared conversationally and concisely (1-2 lines), matching their terse tone, and reflect on it naturally.]"
            )
            user_text = user_text + curiosity_context
        elif curiosity_intent == "unrelated":
            curiosity_context = (
                f"\n\n[Dominion Curiosity: Note that question about {active_q.topic} is currently pending: '{active_q.question}'. "
                f"User's message here is unrelated. Keep an open ear: answer their immediate request fully and directly without getting distracted, and do not nag them about the pending question.]"
            )
            user_text = user_text + curiosity_context

    # ── Pending stale confirmation ────────────────────────────────────────────
    if channel_id in pending:
        choice = message.content.strip().lower()
        p = pending.pop(channel_id)
        if choice in ("n", "new", "fresh", "reset"):
            old_s = sessions.pop(channel_id, None)
            save_sessions(sessions)
            await _update_presence()
            old_kb = _kb_extract_tasks.pop(channel_id, None)
            if old_kb:
                old_kb.cancel()
            if old_s and old_s.get("session_id"):
                asyncio.create_task(_maybe_extract_kb(channel_id, old_s["session_id"], delay=0))
            await _dispatch_with_reactions(message, message.channel, p["prompt"], None, channel_id)
        else:
            await _dispatch_with_reactions(message, message.channel, p["prompt"], p["session"]["session_id"], channel_id)
        return

    # ── Normal routing ────────────────────────────────────────────────────────
    session = sessions.get(channel_id)
    if session:
        elapsed = time.time() - session["last_active"]
        if elapsed > STALE_THRESHOLD:
            elapsed_s = _fmt_elapsed(elapsed)
            started = datetime.fromtimestamp(session["started_at"]).strftime("%H:%M")
            pending[channel_id] = {"session": session, "prompt": user_text}
            await message.channel.send(
                f"Session from {elapsed_s} ago (started {started}). `c` continue · `n` new"
            )
            return
        await _dispatch_with_reactions(message, message.channel, user_text, session["session_id"], channel_id)
    else:
        await _dispatch_with_reactions(message, message.channel, user_text, None, channel_id)

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    sessions.update(load_sessions())
    log.info("Loaded %d persisted sessions", len(sessions))

    env: dict[str, str] = {}
    env_file = AI_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()

    token = os.environ.get("DISCORD_TOKEN") or env.get("DISCORD_TOKEN", "") or DISCORD_CFG.get("token", "")
    if not token or "your_" in token:
        log.error("Set DISCORD_TOKEN in %s or environment", env_file)
        raise SystemExit(1)

    bot.run(token, log_handler=None)
