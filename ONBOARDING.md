# Onboarding Your Knowledge Base to Oracle 🔮

Oracle is designed to be completely knowledge-base agnostic. You can connect it to:
- **An existing Obsidian vault**
- **A Logseq directory**
- **A plain folder of Markdown notes**
- **An AI-maintained knowledge graph** (like [Dominion](file:///mnt/hdd/notes/Dominion))
- **A fresh knowledge base** initialized in 5 seconds from the built-in starter template

---

## ⚡ 3-Minute Quickstart (Automated Wizard)

Oracle includes an interactive onboarding wizard that detects your environment, configures credentials, links your notes directory, and sets up background systemd services.

### Linux / macOS
```bash
# 1. Clone the repository
git clone git@github.com:tm9k1/oracle.git ~/.ai
cd ~/.ai

# 2. Set up virtual environment and dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r scripts/requirements.txt

# 3. Run the onboarding wizard
python3 scripts/onboard.py
```

### Windows (PowerShell or CMD)
```powershell
# 1. Clone the repository
git clone git@github.com:tm9k1/oracle.git oracle
cd oracle

# 2. Set up virtual environment and dependencies
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r scripts\requirements.txt

# 3. Run the onboarding wizard
python scripts\onboard.py
```

The wizard will interactively:
1. Ask for your name / operator handle.
2. Ask for the path to your notes (e.g. `C:\Users\Alice\Obsidian\Vault` or `~/notes`, or offer to create a new starter knowledge base).
3. Detect available AI backends (`agy` / Antigravity CLI or `claude` / Anthropic Claude Code CLI).
4. Prompt for your Discord Bot Token (saving safely to `.env`).
5. Update `config.json` with your paths and preferences.
6. Generate systemd user services (Linux) or Windows batch/PowerShell launchers (`run_oracle.bat`, `start_oracle.ps1`).
7. Run the verification test suite to confirm everything works.

---

## 🤖 Non-Interactive / Scripted Onboarding

For headless servers, Docker containers, or automated scripts:

```bash
# Example: Link an existing Obsidian vault
python3 scripts/onboard.py \
  --non-interactive \
  --user-name "Alice" \
  --vault-path "~/Obsidian/SecondBrain" \
  --vault-name "SecondBrain" \
  --backend agy \
  --model "gemini-3.8-flash-high" \
  --discord-token "YOUR_DISCORD_BOT_TOKEN" \
  --install-service

# Example: Initialize a brand new knowledge base from the starter template
python3 scripts/onboard.py \
  --non-interactive \
  --user-name "Bob" \
  --vault-path "~/notes" \
  --init-starter-kb \
  --backend agy \
  --discord-token "YOUR_DISCORD_BOT_TOKEN" \
  --install-service
```

---

## 📁 Knowledge Base Structure & Integration

### Connecting an Existing Notes Vault
If you already have a folder of Markdown files (Obsidian, Logseq, or notes):
1. Point `vault_path` to that folder in `config.json` (or via `scripts/onboard.py`).
2. Oracle automatically indexes all `.md` files in that directory for context retrieval.
3. Oracle creates an `inbox/` subfolder where newly learned facts, preferences, and feedback from your Discord conversations will be staged as dated `pending-review` notes.

### Using the Starter Knowledge Base Template
If you are starting from scratch, `scripts/onboard.py --init-starter-kb` copies `templates/starter_kb/` into your target directory:

```
your-vault/
├── README.md              # Overview of your personal knowledge base
├── DISPATCH.md            # Scheduled tasks, reminders, and proactive inquiries
├── inbox/                 # Review inbox where Oracle stages newly learned insights
├── entities/              # Structured facts about people, systems, and entities
│   ├── me.md              # Your profile, ongoing goals, habits, and background
│   └── infrastructure.md  # Devices, homelab hosts, and network setup
└── mind/                  # Principles and communication preferences
    └── preferences.md     # Communication style and rules
```

---

## 🧠 How Oracle Interacts with Your Knowledge Base

| Feature | How It Works |
|---|---|
| **Context Retrieval** | When you chat on Discord, Oracle searches your vault for relevant documents and injects them into the prompt turn. |
| **Silent Insight Staging** | After conversations go idle, Oracle synthesizes new user preferences, project updates, or facts, staging them into `inbox/` as dated `pending-review` notes for you to review. |
| **Scheduled Dispatches** | Add future tasks or check-ins to `DISPATCH.md`. Oracle monitors due dates and sends proactive Discord DMs when tasks are due. |
| **Curiosity Inquiries** | Add "Open Questions" to your entity notes. At comfortable conversational cadences, Oracle asks thoughtful check-ins and records your answers. |
| **Daily Routines** | Configure recurring daily schedules (habits, check-ins, reminders) in `routines.json`. |

---

## 🔑 Discord Bot Setup Checklist

1. Open the [Discord Developer Portal](https://discord.com/developers/applications).
2. Create **New Application** → go to **Bot**.
3. Under **Privileged Gateway Intents**, enable:
   - ✅ **Message Content Intent**
4. Under **OAuth2 → URL Generator**:
   - Scopes: `bot`
   - Permissions: `Send Messages`, `Read Message History`, `View Channels`, `Attach Files`, `Add Reactions`
5. Open the generated URL in your browser to invite the bot to your personal server.
6. Copy the Bot Token into `.env` (or supply during `scripts/onboard.py`).

---

## 🚀 Running Oracle

### Linux / macOS
```bash
# Interactive
source .venv/bin/activate
python3 scripts/oracle_bot.py

# Or background daemon via systemd
systemctl --user daemon-reload
systemctl --user enable --now oracle-discord

# Check live logs
journalctl --user -u oracle-discord -f
tail -f logs/oracle_bot.log
```

### Windows (CMD or PowerShell)
```cmd
:: Quick launch (batch script)
run_oracle.bat

:: Or PowerShell
.\start_oracle.ps1
```

**Run on Windows Startup automatically:**
1. Press `Win + R`, type `shell:startup`, and press Enter.
2. Create a shortcut to `run_oracle.bat` and paste it into the Startup folder.
3. Oracle will now automatically start in the background upon login!

---

## 🛡️ Privacy & Knowledge Separation

- **Constitution Article VIII.1 Standard**: No plaintext secrets (tokens, passwords, private keys) are ever committed to git. Sensitive values are stored exclusively in `.env` (which is git-ignored).
- **Knowledge Separation**: Your personal thoughts, identity facts, and life notes live in your external knowledge base (`vault_path`), keeping the Oracle repository generic, shareable, and clean.
