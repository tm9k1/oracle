#!/usr/bin/env python3
"""
Oracle Onboarding Setup Wizard
Initializes and links any personal knowledge base (Obsidian, Logseq, Markdown, Dominion)
with Oracle's Discord bot and autonomous subsystems.
"""
import argparse
import getpass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, Dict, Optional

SCRIPT_DIR = Path(__file__).resolve().parent
AI_DIR = SCRIPT_DIR.parent
TEMPLATES_DIR = AI_DIR / "templates" / "starter_kb"
CONFIG_FILE = AI_DIR / "config.json"
ENV_FILE = AI_DIR / ".env"
ENV_EXAMPLE_FILE = AI_DIR / ".env.example"


def prompt_user(prompt: str, default: Optional[str] = None) -> str:
    """Prompt the user for input with an optional default value."""
    if default is not None:
        p = f"{prompt} [{default}]: "
    else:
        p = f"{prompt}: "
    val = input(p).strip()
    return val if val else (default or "")


def prompt_yes_no(prompt: str, default_yes: bool = True) -> bool:
    """Prompt user for a yes/no response."""
    choice_str = "[Y/n]" if default_yes else "[y/N]"
    val = input(f"{prompt} {choice_str}: ").strip().lower()
    if not val:
        return default_yes
    return val in ("y", "yes")


def find_binary(name: str) -> Optional[str]:
    """Search for a binary in PATH or ~/.local/bin."""
    home_bin = Path.home() / ".local/bin" / name
    if home_bin.exists():
        return str(home_bin)
    return shutil.which(name)


def init_starter_kb(target_dir: Path) -> None:
    """Copy template starter knowledge base to target directory."""
    target_dir.mkdir(parents=True, exist_ok=True)
    if not TEMPLATES_DIR.exists():
        print(f"Template directory {TEMPLATES_DIR} not found; skipping template copy.")
        return

    for item in TEMPLATES_DIR.rglob("*"):
        rel = item.relative_to(TEMPLATES_DIR)
        dest = target_dir / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            if not dest.exists():
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, dest)
    print(f"✓ Initialized starter knowledge base in: {target_dir}")


def setup_knowledge_base(
    vault_path_str: Optional[str] = None,
    vault_name: Optional[str] = None,
    interactive: bool = True,
    init_template: bool = False,
) -> tuple[Path, str]:
    """Configure or initialize the knowledge base directory."""
    default_vault = str(Path.home() / "notes")
    if not vault_path_str and interactive:
        print("\n--- 1. Knowledge Base Configuration ---")
        print("Oracle can connect to any Markdown folder, Obsidian vault, Logseq directory, or Dominion.")
        print(f"Default path: {default_vault}")
        vault_path_str = prompt_user("Enter knowledge base path", default=default_vault)
    elif not vault_path_str:
        vault_path_str = default_vault

    vault_path = Path(os.path.expanduser(vault_path_str)).resolve()

    if not vault_path.exists():
        if init_template or (interactive and prompt_yes_no(f"Path '{vault_path}' does not exist. Create with starter template?")):
            init_starter_kb(vault_path)
        else:
            vault_path.mkdir(parents=True, exist_ok=True)
            print(f"Created directory: {vault_path}")

    # Ensure staging inbox exists
    inbox = vault_path / "inbox"
    mind_inbox = vault_path / "mind" / "inbox"
    if not inbox.exists() and not mind_inbox.exists():
        inbox.mkdir(parents=True, exist_ok=True)

    if not vault_name:
        if "dominion" in str(vault_path).lower():
            vault_name = "Dominion"
        elif interactive:
            def_name = vault_path.name.replace("-", " ").title() or "Knowledge Base"
            vault_name = prompt_user("Enter knowledge base name", default=def_name)
        else:
            vault_name = vault_path.name.replace("-", " ").title() or "Knowledge Base"

    return vault_path, vault_name


def setup_backend(
    chosen_backend: Optional[str] = None,
    chosen_model: Optional[str] = None,
    interactive: bool = True,
) -> tuple[str, str]:
    """Detect available CLI backends and configure chosen engine."""
    agy_found = bool(find_binary("agy"))
    claude_found = bool(find_binary("claude"))

    if not chosen_backend and interactive:
        print("\n--- 2. AI Inference Backend ---")
        print(f" - [1] agy (Google Antigravity CLI / Gemini) - {'detected' if agy_found else 'not detected in PATH'}")
        print(f" - [2] claude_cli (Anthropic Claude Code CLI) - {'detected' if claude_found else 'not detected in PATH'}")
        def_choice = "1" if agy_found else ("2" if claude_found else "1")
        sel = prompt_user("Select backend [1/2]", default=def_choice)
        chosen_backend = "agy" if sel == "1" else "claude_cli"
    elif not chosen_backend:
        chosen_backend = "agy" if agy_found else "claude_cli"

    if chosen_backend == "agy":
        default_model = "gemini-3.8-flash-high"
    else:
        default_model = "claude-sonnet-4-6"

    if not chosen_model:
        chosen_model = default_model

    return chosen_backend, chosen_model


def setup_env_credentials(token: Optional[str] = None, interactive: bool = True) -> None:
    """Ensure .env exists and configure Discord bot credentials."""
    existing_token = ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("DISCORD_TOKEN="):
                existing_token = line.split("=", 1)[1].strip()

    if not token and interactive:
        print("\n--- 3. Discord Bot Credentials ---")
        if existing_token and existing_token != "your_bot_token_here":
            masked = existing_token[:6] + "..." + existing_token[-4:] if len(existing_token) > 10 else "configured"
            if prompt_yes_no(f"Discord token is already configured ({masked}). Keep it?"):
                token = existing_token

        if not token:
            print("Create a bot application at https://discord.com/developers/applications and copy the token.")
            token = prompt_user("Enter Discord Bot Token (leave empty to configure later)")

    if not token:
        token = existing_token or "YOUR_DISCORD_BOT_TOKEN_HERE"

    content = f"# Oracle Discord Bot Environment Configuration\nDISCORD_TOKEN={token}\nANTHROPIC_API_KEY=\n"
    ENV_FILE.write_text(content, encoding="utf-8")
    os.chmod(ENV_FILE, 0o600)
    print("✓ Environment file saved: .env")


def update_config_file(
    vault_path: Path,
    vault_name: str,
    backend: str,
    model: str,
    user_name: str,
    bot_name: str = "Oracle",
) -> None:
    """Update config.json with customized settings."""
    cfg: Dict[str, Any] = {}
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}

    if "ai" not in cfg:
        cfg["ai"] = {}
    cfg["ai"]["backend"] = backend
    cfg["ai"]["model"] = model
    cfg["ai"]["effort"] = "high"
    cfg["ai"]["timeout_seconds"] = 1500
    cfg["ai"]["compact_threshold"] = 0.65
    cfg["ai"]["compact_idle_seconds"] = 180

    if "discord" not in cfg:
        cfg["discord"] = {}
    cfg["discord"]["bot_name"] = bot_name

    if "kb" not in cfg:
        cfg["kb"] = {}
    cfg["kb"]["base_dir"] = str(AI_DIR)
    cfg["kb"]["vault_path"] = str(vault_path)
    cfg["kb"]["vault_name"] = vault_name
    cfg["kb"]["inbox_rel_path"] = "mind/inbox" if (vault_path / "mind").exists() else "inbox"

    if "user" not in cfg:
        cfg["user"] = {}
    cfg["user"]["name"] = user_name

    CONFIG_FILE.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    print(f"✓ Configuration saved: config.json (KB: '{vault_name}' at {vault_path})")


def generate_systemd_service(install: bool = False, interactive: bool = True) -> Optional[Path]:
    """Generate systemd user service file tailored to current environment."""
    service_content = f"""[Unit]
Description=Oracle Discord Bot (modular AI backend)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={AI_DIR}
EnvironmentFile=-{AI_DIR}/.env
Environment="PATH={Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart={AI_DIR}/.venv/bin/python {AI_DIR}/scripts/oracle_bot.py
Restart=always
RestartSec=10
StandardOutput=append:{AI_DIR}/logs/oracle_bot.log
StandardError=append:{AI_DIR}/logs/oracle_bot.log

[Install]
WantedBy=default.target
"""
    # Write to scripts/oracle-bot.service
    service_file = AI_DIR / "scripts" / "oracle-bot.service"
    service_file.write_text(service_content, encoding="utf-8")

    user_unit_dir = Path.home() / ".config" / "systemd" / "user"
    user_unit_file = user_unit_dir / "oracle-discord.service"

    if not install and interactive:
        print("\n--- 4. Systemd Background Service ---")
        install = prompt_yes_no(f"Install systemd user service to {user_unit_file}?", default_yes=True)

    if install:
        user_unit_dir.mkdir(parents=True, exist_ok=True)
        user_unit_file.write_text(service_content, encoding="utf-8")
        print(f"✓ Systemd service installed: {user_unit_file}")
        return user_unit_file
    return None


def run_tests() -> bool:
    """Run test suite to verify installation integrity."""
    print("\n--- Running Test Suite ---")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SCRIPT_DIR)
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", str(SCRIPT_DIR / "tests")],
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        print("✓ All automated tests passed successfully!")
        return True
    else:
        print("⚠️ Some tests reported errors or warnings:")
        print(proc.stdout)
        print(proc.stderr)
        return False


def main():
    parser = argparse.ArgumentParser(description="Oracle Knowledge Base Onboarding Wizard")
    parser.add_argument("--non-interactive", action="store_true", help="Run without prompts using defaults/flags")
    parser.add_argument("--user-name", help="Operator name (e.g. Piyush, Alice)")
    parser.add_argument("--bot-name", default="Oracle", help="Discord bot name (default: Oracle)")
    parser.add_argument("--vault-path", help="Path to knowledge base / notes directory")
    parser.add_argument("--vault-name", help="Display name of knowledge base")
    parser.add_argument("--init-starter-kb", action="store_true", help="Initialize starter knowledge base template")
    parser.add_argument("--backend", choices=["agy", "claude_cli"], help="AI backend")
    parser.add_argument("--model", help="AI model name")
    parser.add_argument("--discord-token", help="Discord bot token")
    parser.add_argument("--install-service", action="store_true", help="Install systemd user service")
    parser.add_argument("--skip-tests", action="store_true", help="Skip running unit tests at the end")
    args = parser.parse_args()

    interactive = not args.non_interactive

    print("=" * 60)
    print("           🔮 Oracle Setup & Onboarding Wizard")
    print("=" * 60)

    # 1. User Name
    user_name = args.user_name
    if not user_name and interactive:
        def_user = getpass.getuser()
        user_name = prompt_user("Enter your name / operator handle", default=def_user)
    elif not user_name:
        user_name = getpass.getuser()

    # 2. Knowledge Base
    vault_path, vault_name = setup_knowledge_base(
        vault_path_str=args.vault_path,
        vault_name=args.vault_name,
        interactive=interactive,
        init_template=args.init_starter_kb,
    )

    # 3. AI Backend
    backend, model = setup_backend(
        chosen_backend=args.backend,
        chosen_model=args.model,
        interactive=interactive,
    )

    # 4. Discord Bot Token
    setup_env_credentials(token=args.discord_token, interactive=interactive)

    # 5. Config update
    update_config_file(
        vault_path=vault_path,
        vault_name=vault_name,
        backend=backend,
        model=model,
        user_name=user_name,
        bot_name=args.bot_name,
    )

    # 6. Ensure runtime dirs
    (AI_DIR / "logs").mkdir(parents=True, exist_ok=True)
    (AI_DIR / "downloads" / "attachments").mkdir(parents=True, exist_ok=True)

    # 7. Systemd Service
    service_path = generate_systemd_service(install=args.install_service, interactive=interactive)

    # 8. Run verification tests
    if not args.skip_tests:
        run_tests()

    # 9. Next Steps
    print("\n" + "=" * 60)
    print("🎉 Oracle Onboarding Complete!")
    print("=" * 60)
    print(f"• Knowledge Base: {vault_name} ({vault_path})")
    print(f"• AI Backend:     {backend} ({model})")
    print(f"• Operator:       {user_name}")
    print("\nNext Steps:")
    print("1. Start Oracle interactively:")
    print(f"   {sys.executable} scripts/oracle_bot.py")
    if service_path:
        print("\n2. Or enable and start via systemd:")
        print("   systemctl --user daemon-reload")
        print("   systemctl --user enable --now oracle-discord")
        print("   journalctl --user -u oracle-discord -f")
    print("\n3. Send a message to your bot on Discord!")
    print("=" * 60)


if __name__ == "__main__":
    main()
