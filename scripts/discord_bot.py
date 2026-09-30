#!/usr/bin/env python3
"""
Oracle — personal AI assistant Discord bot backed by the .ai knowledge base.
Talks to Claude with your KB context injected every turn.
"""
import json
import os
import sys
import asyncio
import logging
from pathlib import Path

import discord
import anthropic

KB_DIR = Path("/home/tm9k1/.ai")
sys.path.insert(0, str(KB_DIR / "scripts"))
from retrieve import get_core_context, retrieve_context, format_retrieved

# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    path = KB_DIR / "config.json"
    return json.loads(path.read_text()) if path.exists() else {}

CFG = load_config()
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN") or CFG.get("discord", {}).get("token", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY") or CFG.get("anthropic", {}).get("api_key", "")
MODEL = CFG.get("anthropic", {}).get("model", "claude-sonnet-4-6")
MAX_TOKENS = CFG.get("anthropic", {}).get("max_tokens", 4096)
ALLOW_DMS = CFG.get("discord", {}).get("allow_dms", True)
ALLOWED_GUILDS = set(CFG.get("discord", {}).get("allowed_guild_ids", []))
ALLOWED_CHANNELS = set(CFG.get("discord", {}).get("allowed_channel_ids", []))
MAX_HISTORY = CFG.get("kb", {}).get("history_turns", 20)
BOT_NAME = CFG.get("discord", {}).get("bot_name", "Oracle")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(KB_DIR / "logs" / "discord_bot.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ── State ─────────────────────────────────────────────────────────────────────

# channel_id -> list of {"role": ..., "content": ...}
histories: dict[str, list[dict]] = {}

ac = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ── Discord setup ─────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

# ── Helpers ───────────────────────────────────────────────────────────────────

def build_system_prompt(query: str) -> str:
    core = get_core_context(max_chars=12000)
    retrieved = format_retrieved(retrieve_context(query, top_k=5), max_chars=4000)

    parts = [
        f"You are {BOT_NAME}, a personal AI assistant with deep context about the user.",
        "Answer concisely and directly. You have memory of the user's profile, past learnings, and current projects.",
        "",
        "# Knowledge Base",
        core,
    ]
    if retrieved:
        parts += ["", "# Relevant Context (retrieved)", retrieved]

    return "\n".join(parts)


async def send_chunked(channel, text: str):
    """Send a message, splitting at 2000-char Discord limit on newlines."""
    if len(text) <= 2000:
        await channel.send(text)
        return
    chunks = []
    buf = ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > 1950:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    for chunk in chunks:
        await channel.send(chunk)


def is_allowed(message: discord.Message) -> bool:
    if isinstance(message.channel, discord.DMChannel):
        return ALLOW_DMS
    if ALLOWED_GUILDS and message.guild and message.guild.id not in ALLOWED_GUILDS:
        return False
    if ALLOWED_CHANNELS and message.channel.id not in ALLOWED_CHANNELS:
        return False
    return True


def strip_mention(text: str, bot_id: int) -> str:
    return text.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "").strip()

# ── Event handlers ────────────────────────────────────────────────────────────

@client.event
async def on_ready():
    log.info(f"{BOT_NAME} connected as {client.user} (id={client.user.id})")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return
    if message.author.bot:
        return

    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = client.user in (message.mentions or [])

    if not (is_dm or is_mentioned):
        return

    if not is_allowed(message):
        return

    user_text = strip_mention(message.content, client.user.id)
    if not user_text:
        await message.channel.send("Yes?")
        return

    channel_id = str(message.channel.id)
    history = histories.setdefault(channel_id, [])

    async with message.channel.typing():
        try:
            system = build_system_prompt(user_text)
            messages = history + [{"role": "user", "content": user_text}]

            resp = ac.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=system,
                messages=messages,
            )
            reply = resp.content[0].text

        except anthropic.APIError as e:
            log.error(f"Anthropic error: {e}")
            await message.channel.send(f"API error: {e}")
            return
        except Exception as e:
            log.error(f"Unexpected error: {e}", exc_info=True)
            await message.channel.send("Something went wrong on my end.")
            return

    # Update history
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": reply})
    # Keep only last N turns (each turn = 2 messages)
    if len(history) > MAX_HISTORY * 2:
        histories[channel_id] = history[-(MAX_HISTORY * 2):]

    await send_chunked(message.channel, reply)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not DISCORD_TOKEN or DISCORD_TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        log.error("Set DISCORD_TOKEN in env or config.json before running")
        sys.exit(1)
    if not ANTHROPIC_API_KEY:
        log.error("Set ANTHROPIC_API_KEY in env or config.json")
        sys.exit(1)
    client.run(DISCORD_TOKEN, log_handler=None)
