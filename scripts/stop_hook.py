#!/usr/bin/env python3
"""
Claude Code stop hook — runs after every session.
Passes stdin to update_kb.py which does the heavy lifting.
"""
import sys
import subprocess
from pathlib import Path

def main():
    stdin_data = sys.stdin.read()
    script = Path(__file__).parent / "update_kb.py"
    result = subprocess.run(
        [sys.executable, str(script)],
        input=stdin_data,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        # Write errors to log but don't block Claude from stopping
        log_path = Path("/home/tm9k1/.ai/logs/stop_hook_errors.log")
        with open(log_path, "a") as f:
            f.write(result.stderr + "\n")

if __name__ == "__main__":
    main()
