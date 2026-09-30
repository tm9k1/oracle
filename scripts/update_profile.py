#!/usr/bin/env python3
"""One-shot script to set Oracle's Discord username and avatar."""
import base64, json, sys
from pathlib import Path
import urllib.request, urllib.error

AI_DIR = Path("/home/tm9k1/.ai")

def read_token() -> str:
    for line in (AI_DIR / ".env").read_text().splitlines():
        if line.startswith("DISCORD_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("DISCORD_TOKEN not found in .env")

def discord_patch(token: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        data=data,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "OracleBot/1.0",
        },
        method="PATCH",
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def fetch_avatar_b64(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "OracleBot/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = resp.read()
    return base64.b64encode(data).decode()

token = read_token()

# ── Avatar ────────────────────────────────────────────────────────────────────
# Dark oracle-themed bot avatar from DiceBear (bottts-neutral, deep space palette)
avatar_url = (
    "https://api.dicebear.com/9.x/bottts-neutral/png"
    "?seed=oracle-bot&size=256&backgroundColor=0d1117"
    "&eyes=eva&mouth=diagram&texture=circuits"
)
print("Fetching avatar...")
try:
    b64 = fetch_avatar_b64(avatar_url)
    avatar_data = f"data:image/png;base64,{b64}"
except Exception as e:
    print(f"Avatar fetch failed ({e}), skipping avatar update")
    avatar_data = None

# ── Update profile ────────────────────────────────────────────────────────────
payload = {"username": "Oracle"}
if avatar_data:
    payload["avatar"] = avatar_data

print("Updating Discord profile...")
try:
    result = discord_patch(token, payload)
    print(f"Done — username: {result['username']}#{result['discriminator']}")
    if "avatar" in result and result["avatar"]:
        print(f"Avatar: https://cdn.discordapp.com/avatars/{result['id']}/{result['avatar']}.png")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"HTTP {e.code}: {body}")
    sys.exit(1)
