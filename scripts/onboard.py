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
    """Search for a binary in PATH, ~/.local/bin, or Windows npm/app dirs."""
    found = shutil.which(name)
    if found:
        return found
    candidates = [
        Path.home() / ".local" / "bin" / name,
        Path.home() / ".local" / "bin" / f"{name}.exe",
        Path.home() / ".local" / "bin" / f"{name}.cmd",
        Path.home() / "AppData" / "Roaming" / "npm" / f"{name}.cmd",
        Path.home() / "AppData" / "Local" / "Programs" / name / f"{name}.exe",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return None


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


def find_common_vaults() -> list[tuple[Path, str]]:
    """Scan common paths for personal knowledge bases or Obsidian vaults."""
    candidates = [
        (Path("/mnt/hdd/notes/Dominion"), "Dominion"),
        (Path.home() / "notes", "Notes"),
        (Path.home() / "Obsidian", "Obsidian"),
        (Path.home() / "Documents" / "Obsidian", "Obsidian"),
        (Path.home() / "Documents" / "notes", "Notes"),
        (Path.home() / "vault", "Vault"),
        (Path.home() / "second_brain", "Second Brain"),
    ]
    found = []
    for p, name in candidates:
        if p.exists() and p.is_dir():
            md_files = list(p.glob("*.md")) + list(p.glob("*/*.md"))
            if md_files:
                found.append((p.resolve(), name))
    return found


def setup_knowledge_base(
    vault_path_str: Optional[str] = None,
    vault_name: Optional[str] = None,
    interactive: bool = True,
    init_template: bool = False,
) -> tuple[Path, str]:
    """Configure or initialize the knowledge base directory."""
    default_vault = str(Path.home() / "notes")

    # If not specified, look for existing configured vault or common vaults
    if not vault_path_str:
        if CONFIG_FILE.exists():
            try:
                cfg_data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                existing_vp = cfg_data.get("kb", {}).get("vault_path")
                if existing_vp and Path(existing_vp).exists():
                    default_vault = existing_vp
                    if not vault_name:
                        vault_name = cfg_data.get("kb", {}).get("vault_name")
            except Exception:
                pass
        if default_vault == str(Path.home() / "notes"):
            detected = find_common_vaults()
            if detected:
                default_vault = str(detected[0][0])
                if not vault_name:
                    vault_name = detected[0][1]

    if not vault_path_str and interactive:
        print("\n--- 1. Knowledge Base Configuration ---")
        print("Oracle can connect to any Markdown folder, Obsidian vault, Logseq directory, or Dominion.")
        print(f"Default path: {default_vault}")
        vault_path_str = prompt_user("Enter knowledge base path", default=default_vault)
    elif not vault_path_str:
        vault_path_str = default_vault

    vault_path = Path(os.path.expanduser(vault_path_str)).resolve()

    if not vault_path.exists():
        if init_template or not interactive or prompt_yes_no(f"Path '{vault_path}' does not exist. Create with starter template?"):
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

    cfg_backend = None
    cfg_model = None
    if CONFIG_FILE.exists():
        try:
            cfg_data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg_backend = cfg_data.get("ai", {}).get("backend")
            cfg_model = cfg_data.get("ai", {}).get("model")
        except Exception:
            pass

    if not chosen_backend and interactive:
        print("\n--- 2. AI Inference Backend ---")
        print(f" - [1] agy (Google Antigravity CLI / Gemini) - {'detected' if agy_found else 'not detected in PATH'}")
        print(f" - [2] claude_cli (Anthropic Claude Code CLI) - {'detected' if claude_found else 'not detected in PATH'}")
        if cfg_backend in ("agy", "claude_cli"):
            def_choice = "1" if cfg_backend == "agy" else "2"
        else:
            def_choice = "1" if agy_found else ("2" if claude_found else "1")
        sel = prompt_user("Select backend [1/2]", default=def_choice)
        chosen_backend = "agy" if sel == "1" else "claude_cli"
    elif not chosen_backend:
        chosen_backend = cfg_backend or ("agy" if agy_found else "claude_cli")

    if chosen_backend == "agy":
        default_model = "gemini-3.8-flash-high"
    else:
        default_model = "claude-sonnet-4-6"

    if not chosen_model:
        chosen_model = cfg_model or default_model

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
    try:
        os.chmod(ENV_FILE, 0o600)
    except Exception:
        pass
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


def generate_windows_scripts() -> tuple[Path, Path]:
    """Generate run_oracle.bat and start_oracle.ps1 in repository root."""
    bat_content = """@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Oracle Discord Bot

echo ======================================================
echo           🔮 Starting Oracle Discord Bot
echo ======================================================

if exist .venv\\Scripts\\python.exe (
    set "PYTHON_EXE=.venv\\Scripts\\python.exe"
) else if exist .venv\\bin\\python (
    set "PYTHON_EXE=.venv\\bin\\python"
) else (
    set "PYTHON_EXE=python"
)

echo Using Python: !PYTHON_EXE!
"!PYTHON_EXE!" scripts\\oracle_bot.py

if %ERRORLEVEL% neq 0 (
    echo.
    echo Oracle exited with error code %ERRORLEVEL%.
    pause
)
"""
    ps1_content = """# Oracle Discord Bot Startup Script (PowerShell)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "          🔮 Starting Oracle Discord Bot             " -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan

$PythonExe = if (Test-Path "$ScriptDir\\.venv\\Scripts\\python.exe") {
    "$ScriptDir\\.venv\\Scripts\\python.exe"
} elseif (Test-Path "$ScriptDir\\.venv\\bin\\python") {
    "$ScriptDir\\.venv\\bin\\python"
} else {
    "python"
}

Write-Host "Using Python: $PythonExe" -ForegroundColor Green
& $PythonExe "$ScriptDir\\scripts\\oracle_bot.py"

if ($LASTEXITCODE -ne 0) {
    Write-Host "`nOracle exited with error code $LASTEXITCODE." -ForegroundColor Red
}
"""
    bat_file = AI_DIR / "run_oracle.bat"
    ps1_file = AI_DIR / "start_oracle.ps1"
    bat_file.write_text(bat_content, encoding="utf-8")
    ps1_file.write_text(ps1_content, encoding="utf-8")
    print(f"✓ Created Windows startup scripts: {bat_file.name}, {ps1_file.name}")
    return bat_file, ps1_file


def generate_systemd_service(install: bool = False, interactive: bool = True) -> Optional[Path]:
    """Generate systemd user service file tailored to current environment."""
    if sys.platform == "win32":
        return None

    py_bin = f"{AI_DIR}/.venv/bin/python" if (AI_DIR / ".venv" / "bin" / "python").exists() else sys.executable
    service_content = f"""[Unit]
Description=Oracle Discord Bot (modular AI backend)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={AI_DIR}
EnvironmentFile=-{AI_DIR}/.env
Environment="PATH={Path.home()}/.local/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart={py_bin} {AI_DIR}/scripts/oracle_bot.py
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


def run_doctor(json_output: bool = False) -> int:
    """Check system health, dependencies, and configuration."""
    status: Dict[str, Any] = {
        "ok": True,
        "python": {
            "version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "ok": sys.version_info >= (3, 10),
            "venv": sys.prefix != sys.base_prefix,
        },
        "dependencies": {},
        "backends": {},
        "env": {},
        "kb": {},
        "service": {},
        "issues": [],
    }

    if not status["python"]["ok"]:
        status["ok"] = False
        status["issues"].append("Python 3.10+ required")

    for pkg in ["discord", "anthropic"]:
        try:
            m = __import__(pkg)
            ver = getattr(m, "__version__", "installed")
            status["dependencies"][pkg] = {"installed": True, "version": ver}
        except ImportError:
            status["dependencies"][pkg] = {"installed": False}
            status["ok"] = False
            status["issues"].append(f"Missing dependency: {pkg} (run: pip install -r scripts/requirements.txt)")

    agy_bin = find_binary("agy")
    claude_bin = find_binary("claude")
    status["backends"]["agy"] = {"found": bool(agy_bin), "path": agy_bin}
    status["backends"]["claude"] = {"found": bool(claude_bin), "path": claude_bin}

    env_exists = ENV_FILE.exists()
    has_token = False
    has_anthropic_key = False
    if env_exists:
        try:
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                if line.startswith("DISCORD_TOKEN="):
                    val = line.split("=", 1)[1].strip()
                    if val and "YOUR_DISCORD_BOT_TOKEN_HERE" not in val and val != "your_bot_token_here":
                        has_token = True
                if line.startswith("ANTHROPIC_API_KEY="):
                    val = line.split("=", 1)[1].strip()
                    if val and "sk-ant" in val:
                        has_anthropic_key = True
        except Exception:
            pass

    status["env"]["file_exists"] = env_exists
    status["env"]["discord_token_configured"] = has_token
    status["env"]["anthropic_key_configured"] = has_anthropic_key

    if not has_token:
        status["ok"] = False
        status["issues"].append("DISCORD_TOKEN not configured in .env")

    if not agy_bin and not claude_bin and not has_anthropic_key:
        status["ok"] = False
        status["issues"].append("No AI inference backend found (install 'agy' or 'claude', or set ANTHROPIC_API_KEY in .env)")

    cfg_exists = CONFIG_FILE.exists()
    status["kb"]["config_exists"] = cfg_exists
    if cfg_exists:
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            vpath_str = cfg.get("kb", {}).get("vault_path")
            vname = cfg.get("kb", {}).get("vault_name", "Unknown")
            status["kb"]["vault_name"] = vname
            status["kb"]["vault_path"] = vpath_str
            if vpath_str:
                vp = Path(vpath_str)
                exists = vp.exists()
                status["kb"]["exists"] = exists
                if exists:
                    md_count = len(list(vp.rglob("*.md")))
                    status["kb"]["markdown_count"] = md_count
                else:
                    status["ok"] = False
                    status["issues"].append(f"Configured vault path does not exist: {vpath_str}")
        except Exception as e:
            status["kb"]["error"] = str(e)
            status["ok"] = False
            status["issues"].append(f"Invalid config.json: {e}")
    else:
        status["ok"] = False
        status["issues"].append("config.json not found (run: python scripts/onboard.py)")

    if sys.platform == "win32":
        status["service"]["bat_script"] = (AI_DIR / "run_oracle.bat").exists()
        status["service"]["ps1_script"] = (AI_DIR / "start_oracle.ps1").exists()
    else:
        unit = Path.home() / ".config" / "systemd" / "user" / "oracle-discord.service"
        status["service"]["systemd_unit_installed"] = unit.exists()
        is_active = False
        if unit.exists():
            try:
                res = subprocess.run(["systemctl", "--user", "is-active", "oracle-discord"], capture_output=True, text=True)
                is_active = (res.stdout.strip() == "active")
            except Exception:
                pass
        status["service"]["systemd_unit_active"] = is_active

    if json_output:
        print(json.dumps(status, indent=2))
        return 0 if status["ok"] else 1

    print("=" * 60)
    print("           🩺 Oracle Doctor Health Diagnostics")
    print("=" * 60)

    py_ok = "✓" if status["python"]["ok"] else "✗"
    print(f"[{py_ok}] Python Version:    {status['python']['version']} (venv: {'active' if status['python']['venv'] else 'inactive'})")

    dep_ok = "✓" if all(d.get("installed") for d in status["dependencies"].values()) else "✗"
    dep_str = ", ".join(f"{k} ({v.get('version', 'missing')})" if v.get("installed") else f"{k} (MISSING)" for k, v in status["dependencies"].items())
    print(f"[{dep_ok}] Dependencies:      {dep_str}")

    backend_ok = "✓" if (agy_bin or claude_bin or has_anthropic_key) else "✗"
    b_found = []
    if agy_bin:
        b_found.append(f"agy ({agy_bin})")
    if claude_bin:
        b_found.append(f"claude ({claude_bin})")
    if has_anthropic_key:
        b_found.append("Anthropic API Key (.env)")
    print(f"[{backend_ok}] AI Backend:        {', '.join(b_found) if b_found else 'NONE DETECTED'}")

    tok_ok = "✓" if has_token else "✗"
    print(f"[{tok_ok}] Discord Token:     {'Configured in .env' if has_token else 'NOT CONFIGURED (.env)'}")

    kb_ok = "✓" if status["kb"].get("exists") else "✗"
    kb_info = f"{status['kb'].get('vault_name', 'None')} ({status['kb'].get('vault_path', 'Not configured')}"
    if status["kb"].get("markdown_count") is not None:
        kb_info += f" · {status['kb']['markdown_count']} notes)"
    else:
        kb_info += ")"
    print(f"[{kb_ok}] Knowledge Base:    {kb_info}")

    if sys.platform == "win32":
        s_ok = "✓" if (status["service"].get("bat_script") and status["service"].get("ps1_script")) else "✗"
        print(f"[{s_ok}] Launchers:         run_oracle.bat, start_oracle.ps1")
    else:
        s_ok = "✓" if status["service"].get("systemd_unit_installed") else "○"
        s_state = "active" if status["service"].get("systemd_unit_active") else ("installed" if status["service"].get("systemd_unit_installed") else "not installed")
        print(f"[{s_ok}] Systemd Service:   oracle-discord.service ({s_state})")

    print("-" * 60)
    if status["ok"]:
        print("Status: All systems configured and operational!")
    else:
        print("Issues found:")
        for issue in status["issues"]:
            print(f"  • {issue}")
    print("=" * 60)

    return 0 if status["ok"] else 1


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
    parser.add_argument("--doctor", action="store_true", help="Inspect environment and print health diagnostics")
    parser.add_argument("--json", action="store_true", help="Output doctor results in JSON format")
    parser.add_argument("--auto", action="store_true", help="Auto-detect all settings non-interactively")
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

    if args.doctor:
        sys.exit(run_doctor(json_output=args.json))

    if args.auto:
        args.non_interactive = True
        args.init_starter_kb = True
        if sys.platform != "win32":
            args.install_service = True

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

    # 7. Service / Startup Scripts
    service_path = None
    if sys.platform == "win32":
        bat_file, ps1_file = generate_windows_scripts()
    else:
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
    if sys.platform == "win32":
        print("1. Start Oracle from CMD or PowerShell:")
        print("   .\\run_oracle.bat")
        print("   or")
        print("   .\\start_oracle.ps1")
        print("\n2. To run automatically on login, place a shortcut to run_oracle.bat in your Startup folder:")
        print("   Press Win+R -> type 'shell:startup' -> paste shortcut to run_oracle.bat")
    else:
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
