# AGENTS.md — AI Agent Operating Guide & Setup Playbook

This document is for AI coding assistants and autonomous agents (e.g., Claude Code, Antigravity CLI, Cursor, Devin, Codex, Windsurf, Aider) working in or setting up this repository.

---

## 🎯 Purpose of Oracle

Oracle is an always-on, intelligent interface and operational bridge connecting an operator to their personal knowledge base (Obsidian vault, Logseq folder, Markdown notes, or Dominion). It provides:
1. **Interactive Discord Bot**: Natural-language Q&A and task execution powered by `agy` (Google Gemini) or `claude` (Anthropic Claude Code).
2. **Context Retrieval**: BM25, grep, and frontmatter-aware knowledge graph querying (`scripts/retrieve.py`).
3. **Autonomous Subsystems**: Proactive curiosity surveys (`scripts/curiosity_engine.py`), scheduled briefings (`scripts/routine_manager.py`), and cross-machine notifications (`scripts/dispatch_manager.py`).

---

## 🤖 How an AI Agent Sets Up Oracle For a User

When an operator asks you: **"Set up Oracle for me"**, follow this automated protocol:

### Step 1: Run System Diagnostics
Run the built-in diagnostic tool to assess what's already installed and what's missing:
```bash
python3 scripts/onboard.py --doctor
# Or machine-readable JSON:
python3 scripts/onboard.py --doctor --json
```

### Step 2: Ensure Virtual Environment & Dependencies
If dependencies are missing:
- **Linux / macOS**:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r scripts/requirements.txt
  ```
- **Windows**:
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  pip install -r scripts\requirements.txt
  ```
Or run the all-in-one bootstrap:
- `./scripts/setup.sh` (Linux/macOS)
- `scripts\setup.bat` (Windows)

### Step 3: Run Automated Onboarding
You can run automated onboarding headlessly:
```bash
# Standard automated setup (auto-detects vaults, backends, user name):
python3 scripts/onboard.py --auto

# Or specify custom vault path and Discord token explicitly:
python3 scripts/onboard.py --auto --vault-path "/path/to/notes" --discord-token "YOUR_DISCORD_TOKEN"
```

If the operator has not provided their Discord Bot Token:
- Check if `.env` already has `DISCORD_TOKEN`.
- If not, prompt the operator to supply their token (from https://discord.com/developers/applications) or leave the placeholder in `.env` for them to fill in later.

### Step 4: Verify Installation
Run the test suite to guarantee everything works:
```bash
PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests
```

### Step 5: Start or Enable the Service
- **Linux (Background daemon via systemd)**:
  ```bash
  systemctl --user daemon-reload
  systemctl --user enable --now oracle-discord
  # Check status:
  systemctl --user status oracle-discord
  ```
- **Windows**:
  - Run `run_oracle.bat` or `.\start_oracle.ps1`
  - For startup on login: advise creating a shortcut to `run_oracle.bat` in `shell:startup`.

---

## 🏗️ Repository Architecture

- `scripts/oracle_bot.py`: Discord bot client, session manager, and event router.
- `scripts/onboard.py`: Setup wizard, `--doctor` health check, and configuration manager.
- `scripts/setup.sh` / `scripts/setup.bat`: One-shot bootstrap scripts.
- `scripts/backends/`: AI engine adapters (`agy.py` and `claude_cli.py`).
- `scripts/curiosity_engine.py`: Proactive knowledge base exploration & gap finding.
- `scripts/routine_manager.py`: Scheduled daily routines and briefings.
- `scripts/dispatch_manager.py`: Outbound notification dispatcher.
- `scripts/retrieve.py`: Local context retrieval and search.
- `scripts/update_kb.py`: Staging transcript insights into KB inbox notes.
- `templates/starter_kb/`: Modular markdown template used when initializing new vaults.

---

## 🔒 Security & Safety Invariants

1. **Constitution Article VIII.1 (Zero Plaintext Secrets)**: Never commit tokens, API keys, or passwords to git. Secrets belong exclusively in `.env`, which is in `.gitignore`.
2. **Never Fabricate Facts**: Oracle is an authoritative mirror of the user's knowledge base. If information is not found in the vault, state so honestly.
3. **Safe Storage & Inbox Staging**: AI sessions must never overwrite core knowledge files directly without operator review. Transcribed insights are staged into `mind/inbox/` or `inbox/`.
4. **Non-Destructive Operations**: Prefer recoverable moves (`trash`) over permanent deletion (`rm`).
