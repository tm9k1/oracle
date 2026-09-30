#!/usr/bin/env python3
"""
Oracle Model Auto-Upgrader
Checks for newer models in the Gemini Flash series via the Antigravity CLI (`agy`),
validates the candidate, updates config.json, and restarts oracle-discord.service.
"""
import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

AI_DIR = Path("/home/tm9k1/.ai")
CONFIG_PATH = AI_DIR / "config.json"
LOG_PATH = AI_DIR / "logs" / "model_upgrade.log"
CHANGES_PATH = AI_DIR / "last_changes.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("model_upgrader")


def setup_file_logger():
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        log.addHandler(fh)
    except Exception as e:
        print(f"Warning: could not attach file handler to {LOG_PATH}: {e}", file=sys.stderr)


def find_agy(custom_path: Optional[str] = None) -> str:
    if custom_path and Path(custom_path).exists():
        return custom_path
    candidates = [
        "/home/tm9k1/.local/bin/agy",
        "/usr/local/bin/agy",
        "/usr/bin/agy",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    found = shutil.which("agy")
    if found:
        return found
    raise RuntimeError("agy binary not found in PATH or standard locations")


def parse_version(ver_str: str) -> Tuple[int, ...]:
    """Parse '3.8' or '3.8.1' into tuple of integers."""
    parts = []
    for p in ver_str.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def get_available_flash_models(agy_bin: str, effort: str = "high") -> List[Tuple[Tuple[int, ...], str]]:
    """
    Runs `agy models` and finds all gemini flash models matching the effort tier.
    Returns sorted list of ((major, minor, ...), model_id).
    """
    try:
        res = subprocess.run(
            [agy_bin, "models"],
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
    except Exception as e:
        log.error("Failed to query `agy models`: %s", e)
        return []

    pattern = re.compile(
        r"^(gemini-([\d\.]+)-flash(?:-([a-zA-Z0-9]+))?)",
        re.IGNORECASE,
    )

    models: Dict[Tuple[int, ...], str] = {}

    for line in res.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Fetching"):
            continue
        parts = line.split()
        if not parts:
            continue
        model_id = parts[0]
        m = pattern.match(model_id)
        if m:
            ver_str = m.group(2)
            model_effort = m.group(3)
            if model_effort and model_effort.lower() != effort.lower():
                continue
            ver_tuple = parse_version(ver_str)
            if ver_tuple not in models or (model_effort and effort.lower() in model_id.lower()):
                models[ver_tuple] = model_id

    return sorted(models.items(), key=lambda x: x[0])


def parse_current_model(model_name: str) -> Tuple[Tuple[int, ...], str]:
    m = re.match(r"^gemini-([\d\.]+)-flash(?:-([a-zA-Z0-9]+))?", model_name, re.IGNORECASE)
    if m:
        return parse_version(m.group(1)), m.group(2) or ""
    return (0, 0), ""


def verify_model(agy_bin: str, model_id: str, effort: str) -> bool:
    """Run a test prompt to ensure the model functions and has quota."""
    log.info("Verifying candidate model '%s'...", model_id)
    cmd = [agy_bin, "-p", "say 1", "--model", model_id]
    if effort:
        cmd.extend(["--effort", effort])
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=45,
        )
        if res.returncode == 0 and res.stdout.strip():
            log.info("Model '%s' verified successfully.", model_id)
            return True
        log.warning("Model verification failed (exit %d): %s %s", res.returncode, res.stderr, res.stdout)
        return False
    except subprocess.TimeoutExpired:
        log.warning("Model verification timed out for '%s'", model_id)
        return False
    except Exception as e:
        log.warning("Model verification encountered error for '%s': %s", model_id, e)
        return False


def restart_service() -> bool:
    """Restarts oracle-discord.service via systemctl --user."""
    log.info("Restarting oracle-discord.service...")
    env = os.environ.copy()
    env["XDG_RUNTIME_DIR"] = "/run/user/1000"
    try:
        res = subprocess.run(
            ["systemctl", "--user", "restart", "oracle-discord"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        if res.returncode == 0:
            log.info("Successfully restarted oracle-discord.service")
            return True
        log.error("Failed to restart oracle-discord: %s %s", res.stderr, res.stdout)
        return False
    except Exception as e:
        log.error("Error executing systemctl restart: %s", e)
        return False


def check_and_upgrade_model(
    force: bool = False,
    check_only: bool = False,
    do_restart: bool = True,
) -> Dict[str, Any]:
    setup_file_logger()

    if not CONFIG_PATH.exists():
        log.error("Configuration file not found: %s", CONFIG_PATH)
        return {"upgraded": False, "error": "config_not_found"}

    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        log.error("Failed to read config.json: %s", e)
        return {"upgraded": False, "error": str(e)}

    ai_cfg = cfg.get("ai", {})
    current_model = ai_cfg.get("model", "gemini-3.7-flash-high")
    effort = ai_cfg.get("effort", "high")
    auto_cfg = ai_cfg.get("auto_upgrade", {})

    if not force and auto_cfg.get("enabled") is False:
        log.info("Auto-upgrade is disabled in config.json")
        return {"upgraded": False, "status": "disabled"}

    try:
        agy_bin = find_agy()
    except Exception as e:
        log.error("Error finding agy binary: %s", e)
        return {"upgraded": False, "error": str(e)}

    current_ver, _ = parse_current_model(current_model)
    log.info("Current model: '%s' (parsed version: %s)", current_model, current_ver)

    available = get_available_flash_models(agy_bin, effort=effort)
    if not available:
        log.warning("No Gemini Flash models found matching effort '%s'", effort)
        return {"upgraded": False, "status": "no_models_found"}

    log.info("Available Flash models: %s", [m[1] for m in available])

    best_ver, best_model = available[-1]
    log.info("Highest available Flash model: '%s' (version: %s)", best_model, best_ver)

    is_newer = best_ver > current_ver
    if not is_newer and not force:
        log.info("Current model '%s' is already up to date.", current_model)
        return {
            "upgraded": False,
            "current_model": current_model,
            "best_model": best_model,
            "status": "already_latest",
        }

    if check_only:
        log.info("[Check-only] Newer model available: '%s' -> '%s'", current_model, best_model)
        return {
            "upgraded": False,
            "newer_available": True,
            "current_model": current_model,
            "best_model": best_model,
            "status": "newer_available",
        }

    # Verify candidate
    if not verify_model(agy_bin, best_model, effort):
        log.error("Aborting upgrade: candidate model '%s' failed health verification.", best_model)
        return {
            "upgraded": False,
            "error": "verification_failed",
            "candidate": best_model,
        }

    # Update config.json
    cfg["ai"]["model"] = best_model
    if "auto_upgrade" not in cfg["ai"]:
        cfg["ai"]["auto_upgrade"] = {
            "enabled": True,
            "series": "flash",
            "effort": effort,
            "check_interval_seconds": 86400,
        }

    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        log.info("Updated %s with model '%s'", CONFIG_PATH, best_model)
    except Exception as e:
        log.error("Failed to write updated config.json: %s", e)
        return {"upgraded": False, "error": str(e)}

    # Record in last_changes.txt
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        note = (
            f"\n[{now_str}] Auto-upgraded Gemini Flash model:\n"
            f"• Upgraded from {current_model} to {best_model}\n"
        )
        with open(CHANGES_PATH, "a", encoding="utf-8") as f:
            f.write(note)
    except Exception as e:
        log.warning("Could not update last_changes.txt: %s", e)

    restarted = False
    if do_restart:
        restarted = restart_service()

    return {
        "upgraded": True,
        "old_model": current_model,
        "new_model": best_model,
        "restarted": restarted,
        "status": "upgraded",
    }


def main():
    parser = argparse.ArgumentParser(description="Oracle AI Model Auto-Upgrader")
    parser.add_argument("--check-only", action="store_true", help="Only check for updates without applying")
    parser.add_argument("--force", action="store_true", help="Force upgrade/verification even if version is same")
    parser.add_argument("--no-restart", action="store_true", help="Do not restart oracle-discord service after config update")
    args = parser.parse_args()

    res = check_and_upgrade_model(
        force=args.force,
        check_only=args.check_only,
        do_restart=not args.no_restart,
    )
    sys.exit(0 if (res.get("upgraded") or res.get("status") in ("already_latest", "newer_available")) else 1)


if __name__ == "__main__":
    main()
