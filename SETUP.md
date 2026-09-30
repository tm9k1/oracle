# Oracle AI Setup

## 1. Credentials & Configuration

Edit `/home/tm9k1/.ai/.env`:
```
DISCORD_TOKEN=your_bot_token
ANTHROPIC_API_KEY=sk-ant-... (optional, if using direct api)
```

Tune backend and model in `/home/tm9k1/.ai/config.json`:
```json
{
  "ai": {
    "backend": "agy",
    "model": "gemini-3.7-flash-high",
    "effort": "high"
  }
}
```

## 2. Discord bot setup

1. Go to https://discord.com/developers/applications
2. New Application → Bot → Reset Token → copy the token into `.env`
3. Under **OAuth2 → URL Generator**: check `bot`, then check `Send Messages`, `Read Message History`, `Read Messages/View Channels`
4. Open the generated URL in your browser to invite the bot to your server
5. Enable **Message Content Intent** under Bot → Privileged Gateway Intents

## 3. Install the systemd service

```bash
systemctl --user daemon-reload
systemctl --user enable oracle-discord
systemctl --user restart oracle-discord
```

## 4. Talk to Oracle

- **DMs**: DM the bot directly
- **New session**: send `new session` or `/new` or `reset`

## Files

```
.ai/
├── .env                    ← secrets (DISCORD_TOKEN)
├── config.json             ← AI backend, model, discord restrictions
├── USER.md                   ← user context (thin pointer stub to Dominion)
├── stars/                  ← guiding stars (positive patterns)
├── scars/                  ← lessons learned
├── context/                ← active project context
├── sessions.json           ← session logs & state
├── logs/                   ← bot logs
└── scripts/
    ├── oracle_bot.py       ← the bot entrypoint
    ├── backends/           ← modular AI backend implementations
    │   ├── base.py         ← BaseAIBackend & BackendResult
    │   ├── agy.py          ← Antigravity CLI backend
    │   └── claude_cli.py   ← Claude Code CLI backend
    ├── update_kb.py        ← KB extractor
    └── retrieve.py         ← RAG engine
```

## Logs

```bash
tail -f /home/tm9k1/.ai/logs/oracle_bot.log   # live bot activity
```
