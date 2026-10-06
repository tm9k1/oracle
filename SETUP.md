# Oracle AI Setup & Runbook

Step-by-step setup guide for Oracle on Linux / homelab environments.

---

## 1. Prerequisites & Dependencies

- Python 3.11+
- Virtual environment (`.venv`)
- [Antigravity CLI](https://github.com/google-deepmind/antigravity) (`agy`) installed and authenticated, or Anthropic CLI (`claude`) / API key.
- Discord Application & Bot Token

Install Python dependencies:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt
```

> **Tip:** You can ask any AI assistant (Claude Code, Antigravity, Cursor, Devin) to **"Set up Oracle for me"** — the repository includes [`AGENTS.md`](file:///home/tm9k1/.ai/AGENTS.md) and [`CLAUDE.md`](file:///home/tm9k1/.ai/CLAUDE.md) designed for autonomous agents. Or run `python3 scripts/onboard.py --auto` directly. See [ONBOARDING.md](file:///home/tm9k1/.ai/ONBOARDING.md) for details.

---

## 2. Credentials & Configuration

Copy the sample environment file to `.env`:
```bash
cp .env.example .env
```

Edit `.env`:
```ini
DISCORD_TOKEN=your_bot_token_here
ANTHROPIC_API_KEY=sk-ant-... # Optional: required only if using Claude API direct
```

Configure AI models, behavior, and thresholds in `config.json`:
```json
{
  "ai": {
    "backend": "agy",
    "model": "gemini-3.8-flash-high",
    "effort": "high",
    "timeout_seconds": 1500,
    "compact_threshold": 0.65,
    "compact_idle_seconds": 180,
    "auto_upgrade": {
      "enabled": true,
      "series": "flash",
      "effort": "high",
      "check_interval_seconds": 86400
    }
  },
  "discord": {
    "token": "YOUR_DISCORD_BOT_TOKEN_HERE",
    "allowed_user_ids": [],
    "allowed_guild_ids": [],
    "allowed_channel_ids": [],
    "allow_dms": true,
    "bot_name": "Oracle",
    "edit_interval": 5,
    "max_message_chunks": 4
  },
  "kb": {
    "base_dir": "/home/tm9k1/.ai",
    "max_context_chars": 20000,
    "max_retrieval_results": 8,
    "history_turns": 20,
    "stale_threshold_days": 7,
    "resume_max_age_minutes": 30
  }
}
```

---

## 3. Discord Bot Application Setup

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create a **New Application** → select **Bot**.
3. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
4. Under **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`, `View Channels`, `Attach Files`, `Add Reactions`
5. Generate the invite URL and authorize the bot into your private server.
6. Copy the Bot Token into `.env`.

---

## 4. Systemd Service Deployment

To run Oracle continuously in the background under systemd user management:

```bash
# Link or install service file to user systemd directory
mkdir -p ~/.config/systemd/user
cp scripts/oracle-bot.service ~/.config/systemd/user/oracle-discord.service

# Reload and enable
systemctl --user daemon-reload
systemctl --user enable oracle-discord
systemctl --user restart oracle-discord

# Check service status
systemctl --user status oracle-discord
```

---

## 5. Interacting with Oracle

- **Direct Messages**: Message the bot directly in Discord DMs or in authorized channels.
- **Start Fresh Session**: Send `/new`, `new session`, or `fresh` to start a new context.
- **Manual Compaction**: Send `/compact` to immediately trigger transcript summarization.
- **Routines**:
  - `/routine list` — view configured recurring schedules and daily completion status.
  - `/routine run <id>` — manually trigger a specific scheduled routine dispatch.
- **Safe-word Emergency Restart**: Send `reset` or `restart bot` to cleanly flush state and restart the bot process.

---

## 6. Logs & Diagnostics

Monitor live operational logs:
```bash
journalctl --user -u oracle-discord -f
# or directly from file
tail -f /home/tm9k1/.ai/logs/oracle_bot.log
```

Run test suite:
```bash
PYTHONPATH=/home/tm9k1/.ai/scripts python3 -m unittest discover -s /home/tm9k1/.ai/scripts/tests
```
