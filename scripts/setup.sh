#!/usr/bin/env bash
# Oracle One-Command Setup Script for Linux / macOS
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AI_DIR="$(dirname "$SCRIPT_DIR")"
cd "$AI_DIR"

echo "======================================================"
echo "           🔮 Setting up Oracle                     "
echo "======================================================"

# 1. Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "Creating virtual environment in .venv..."
    python3 -m venv .venv
fi

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Install dependencies
echo "Installing dependencies..."
pip install --upgrade pip -q
pip install -r scripts/requirements.txt -q

# 4. Run onboarding
python3 scripts/onboard.py "$@"
