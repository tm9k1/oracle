# CLAUDE.md — Claude Code Agent Guidelines for Oracle

This repository contains **Oracle**, a knowledge-base agnostic Discord bot and operational bridge connecting users to their personal notes (Obsidian, Logseq, Markdown, or Dominion) using modular AI backends (`agy` or `claude`).

## Essential Commands

- **Run Diagnostics**: `python3 scripts/onboard.py --doctor` (or `python3 scripts/onboard.py --doctor --json`)
- **Run Automated Onboarding**: `python3 scripts/onboard.py --auto`
- **Run Tests**: `PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests`
- **Run Oracle (Interactive)**: `python3 scripts/oracle_bot.py`
- **One-Command Bootstrap**: `./scripts/setup.sh` (Linux/macOS) or `scripts\setup.bat` (Windows)

## Playbook: When Asked to "Set Up Oracle"

Follow these automated steps:
1. **Assess System**: Run `python3 scripts/onboard.py --doctor --json` to inspect installed dependencies, detected backends, and current config.
2. **Setup Environment**:
   - Linux/macOS: Run `./scripts/setup.sh --doctor` or create `.venv` and install `pip install -r scripts/requirements.txt`.
   - Windows: Run `scripts\setup.bat --doctor` or activate `.venv\Scripts\Activate.ps1`.
3. **Configure & Link Knowledge Base**:
   - Run `python3 scripts/onboard.py --auto` (auto-detects vaults and backends).
   - If the user specifies a vault path: pass `--vault-path "/path/to/notes"`.
   - If the user specifies a Discord token: pass `--discord-token "TOKEN"`.
4. **Verify**:
   - Run tests: `PYTHONPATH=scripts python3 -m unittest discover -s scripts/tests`.
5. **Start Oracle**:
   - Linux: Enable background service with `systemctl --user daemon-reload && systemctl --user enable --now oracle-discord`.
   - Windows: Start with `run_oracle.bat` or `.\start_oracle.ps1`.

## Architecture & Conventions

- **Path Handling**: Use `pathlib.Path` everywhere. On Windows, handle drive letters and avoid raw Unix slash replacements.
- **File Encoding**: Always specify `encoding="utf-8"` when reading or writing files.
- **Process Spawning**: On Windows (`sys.platform == "win32"`), wrap `.cmd` and `.bat` subprocess invocations with `["cmd.exe", "/c"]` to avoid WinError 193.
- **Privacy & Safety**: Never commit tokens or secrets to git. Credentials remain strictly in `.env`.
