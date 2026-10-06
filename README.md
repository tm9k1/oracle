# Oracle 🔮

> Autonomous personal executive assistant, homelab secretary, and proactive AI companion running on local Linux infrastructure, interfacing seamlessly over Discord.

Oracle is an always-on, intelligent interface and operational bridge to [Dominion](file:///mnt/hdd/notes/Dominion) (the authoritative personal knowledge graph and deputy brain). Built to run self-hosted on homelab nodes (`REQUIEM`), Oracle provides persistent conversational assistance, real-time message streaming, background routine scheduling, proactive inquiries, and automated knowledge graph ingestion.

---

## 🌟 Key Architecture & Capabilities

### 1. Pluggable AI Backends
- **Modular Engine Abstraction** (`scripts/backends/base.py`): Clean backend protocol decoupling bot logic from AI inference providers.
- **Antigravity CLI Backend** (`scripts/backends/agy.py`): Powers real-time streaming, persistent multi-turn reasoning, and high-effort problem solving using Google's Antigravity CLI and Gemini models (`gemini-3.8-flash-high`).
- **Claude Code CLI Backend** (`scripts/backends/claude_cli.py`): Pluggable integration with Anthropic Claude models.
- **Dynamic Model Auto-Upgrade** (`scripts/check_model_upgrade.py`): Autonomous daily monitor that surveys available models and upgrades active configurations seamlessly.

### 2. Autonomous Dominion Subsystems
- **Routine Scheduler** (`scripts/routine_manager.py` & `routines.json`): Manages recurring daily schedules (e.g. puppy feeding intervals, habit check-ins, medication timings) with sliding-window due checks, daily completion state tracking, and slash commands.
- **Dispatch Engine** (`scripts/dispatch_manager.py`): Surveys cross-machine tasks in Dominion (`DISPATCH.md`), evaluates due dates and machine targeting, and delivers synthesized conversational alerts to Discord.
- **Curiosity Engine** (`scripts/curiosity_engine.py`): Proactive background inquiry system that identifies open life or infrastructure questions in Dominion, presents thoughtful decision forks at appropriate conversational intervals, and autonomously stages captured insights to `mind/inbox/`.
- **Knowledge Base Extraction** (`scripts/update_kb.py` & `scripts/retrieve.py`): Asynchronous post-turn analysis that extracts facts, preferences, and lessons, staging them directly into Dominion for sovereign review.

### 3. Session Lifecycle & Compaction
- **Live Discord Streaming**: Progressive message streaming with status reactions, typing indicators, and message chunking (up to 2,000 characters per Discord chunk).
- **Intelligent Compaction**: Token-aware context compaction with dynamic idle debouncing (`compact_idle_seconds`) to prevent mid-conversation latency.
- **Rolling Transcript Fallback**: Automatically creates rolled summary checkpoints from on-disk session logs if standard compaction encounters backend stream disconnects.
- **Duplicate Suppression & Crash Recovery**: Checkpoints pending prompts to disk with `_is_prompt_already_answered` transcript verification upon reboot, preventing duplicate dispatches across restarts.
- **Safe-word Emergency Restarts**: Graceful self-reboot triggered by conversational emergency keywords (`reset`, `restart bot`).

### 4. Privacy, Security & Governance
- **Zero-Secret Baseline (Constitution Article VIII.1)**: Strictly zero API tokens, bot credentials, or private keys in tracked files. Sensitive credentials are isolated to `.env` (git-ignored).
- **Knowledge Separation (Constitution Article XII)**: The Oracle codebase is completely sanitized of personal data and sovereign history. All long-term memory, personal entities, and life context live exclusively in Dominion (`/mnt/hdd/notes/Dominion/`).

---

## 📂 Repository Layout

```
.ai/
├── config.json                 # AI backend parameters, thresholds, and limits
├── .env.example                # Template for environment variables and secrets
├── routines.json               # Configured recurring daily schedules
├── .gitignore                  # Git exclusions (runtime state, sessions, .env)
│
├── IDENTITY.md                 # Executive assistant persona definition
├── SOUL.md                     # Knowledge base discipline & privacy rules
├── USER.md                     # Context pointer stub to Dominion
├── TOOLS.md                    # Environment and homelab tool notes
├── SETUP.md                    # Setup, systemd deployment, and runbook
│
├── scripts/
│   ├── oracle_bot.py           # Core Discord bot engine & event loop
│   ├── routine_manager.py      # Scheduled routine manager & CLI
│   ├── dispatch_manager.py     # Cross-machine dispatch parser & alerter
│   ├── curiosity_engine.py     # Autonomous inquiry & insight loop
│   ├── check_model_upgrade.py  # Model version scanner & auto-upgrader
│   ├── retrieve.py             # Context retrieval engine
│   ├── update_kb.py            # Post-turn insight extraction engine
│   ├── oracle-bot.service      # Systemd user service definition
│   ├── requirements.txt        # Python package dependencies
│   │
│   ├── backends/               # Pluggable AI backend implementations
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract BaseAIBackend & data structures
│   │   ├── agy.py              # Antigravity CLI (Gemini) implementation
│   │   └── claude_cli.py       # Anthropic Claude CLI implementation
│   │
│   └── tests/                  # Automated test suite
│       ├── test_backends.py
│       ├── test_curiosity_conversation.py
│       ├── test_curiosity_engine.py
│       ├── test_dispatch_conversation.py
│       ├── test_dispatch_manager.py
│       ├── test_oracle_bot.py
│       └── test_routine_manager.py
```

---

## 🚀 Quickstart & Setup

### Prerequisites
- Python 3.11+
- [Antigravity CLI (`agy`)](https://github.com/google-deepmind/antigravity) or [Anthropic Claude CLI (`claude`)](https://github.com/anthropics/claude-code)
- Discord Application & Bot Token

### Installation

1. **Clone and create virtual environment**:
   ```bash
   git clone git@github.com:tm9k1/oracle.git ~/.ai
   cd ~/.ai
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r scripts/requirements.txt
   ```

2. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Set your DISCORD_TOKEN in .env
   ```

3. **Tune AI configuration** (`config.json`):
   ```json
   {
     "ai": {
       "backend": "agy",
       "model": "gemini-3.8-flash-high",
       "effort": "high",
       "timeout_seconds": 1500,
       "compact_threshold": 0.65,
       "compact_idle_seconds": 180
     }
   }
   ```

4. **Run the bot**:
   ```bash
   python3 scripts/oracle_bot.py
   ```

---

## ⚙️ Systemd Service Deployment

To run Oracle continuously under systemd user control on Linux:

```bash
mkdir -p ~/.config/systemd/user
cp scripts/oracle-bot.service ~/.config/systemd/user/oracle-discord.service

systemctl --user daemon-reload
systemctl --user enable oracle-discord
systemctl --user start oracle-discord
```

Inspect operational logs:
```bash
journalctl --user -u oracle-discord -f
```

---

## 💬 Discord Commands & Triggers

| Command / Trigger | Action |
|---|---|
| Direct Message / Mention | Standard conversational turn with progressive streaming |
| `/new`, `new session`, `fresh` | Flushes active session context and starts a fresh conversation |
| `/compact` | Immediately summarizes and compacts the active session transcript |
| `/routine list` | Displays all configured routines and their completion status for today |
| `/routine run <id>` | Manually triggers execution of a specific routine notification |
| `reset`, `restart bot` | Triggers a clean process restart and verifies service recovery |

---

## 🧪 Testing

The test suite covers backend adapters, conversation loops, curiosity engines, dispatch handlers, and routine managers.

Run all tests:
```bash
PYTHONPATH=/home/tm9k1/.ai/scripts python3 -m unittest discover -s /home/tm9k1/.ai/scripts/tests
```

---

## 🛡️ License

Private homelab repository. Built and maintained for Piyush Aggarwal.
