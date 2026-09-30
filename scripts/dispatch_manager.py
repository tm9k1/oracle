#!/usr/bin/env python3
"""
Dispatch Manager for Dominion — handles cross-machine requests targeting Oracle.
Parses DISPATCH.md, detects due dispatches, tracks delivery state,
and sends interactive dispatch notifications to the sovereign on Discord.
"""
import argparse
import hashlib
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("oracle.dispatch")

DEFAULT_DISPATCH_FILE = Path("/mnt/hdd/notes/Dominion/DISPATCH.md")
STATE_FILE = Path("/home/tm9k1/.ai/dispatches_sent.json")


@dataclass
class Dispatch:
    id: str
    target: str
    title: str
    filed: str
    trigger: str
    due_date: Optional[str]  # ISO format YYYY-MM-DD
    what: str
    raw_block: str

    @property
    def is_due(self) -> bool:
        """Check if dispatch is due based on current date."""
        if not self.due_date:
            return False
        try:
            d = date.fromisoformat(self.due_date)
            return d <= date.today()
        except ValueError:
            return False

    def matches_target(self, target_name: str) -> bool:
        t = self.target.strip().lower()
        tn = target_name.strip().lower()
        return t == tn or tn in t or t in ("all", "any")


class DispatchManager:
    def __init__(self, dispatch_path: Optional[Path] = None, state_path: Optional[Path] = None):
        self.dispatch_path = Path(dispatch_path or DEFAULT_DISPATCH_FILE)
        self.state_path = Path(state_path or STATE_FILE)

    def load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Failed to load dispatch state %s: %s", self.state_path, e)
                return {}
        return {}

    def save_state(self, state: Dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Failed to save dispatch state %s: %s", self.state_path, e)

    def is_dispatched(self, dispatch_id: str) -> bool:
        state = self.load_state()
        return dispatch_id in state

    def mark_dispatched(self, dispatch: Dispatch, channel_id: Optional[str] = None, message_id: Optional[int] = None) -> None:
        state = self.load_state()
        state[dispatch.id] = {
            "target": dispatch.target,
            "title": dispatch.title,
            "due_date": dispatch.due_date,
            "sent_at": datetime.now().isoformat(),
            "channel_id": channel_id,
            "message_id": message_id,
        }
        self.save_state(state)
        log.info("Marked dispatch %s as sent", dispatch.id)

    def parse_dispatches(self) -> List[Dispatch]:
        """Parse pending dispatches from DISPATCH.md."""
        if not self.dispatch_path.exists():
            log.warning("Dispatch file does not exist: %s", self.dispatch_path)
            return []

        try:
            content = self.dispatch_path.read_text(encoding="utf-8")
        except Exception as e:
            log.error("Failed to read %s: %s", self.dispatch_path, e)
            return []

        # Find ## Pending section
        pending_match = re.search(r"^##\s+Pending\s*$", content, re.MULTILINE)
        if not pending_match:
            return []

        pending_text = content[pending_match.end():]
        # Stop at next major header if any
        next_h2 = re.search(r"^##\s+[^\n]+", pending_text, re.MULTILINE)
        if next_h2:
            pending_text = pending_text[:next_h2.start()]

        dispatches = []
        # Entries start with: ### → <target> — <title>
        # (Supports em-dash '—', en-dash '–', or hyphen '-')
        entry_pattern = re.compile(
            r"^###\s+→\s*([a-zA-Z0-9_\.-]+)\s*[—–-]\s*([^\n]+)",
            re.MULTILINE
        )

        matches = list(entry_pattern.finditer(pending_text))
        for i, match in enumerate(matches):
            target = match.group(1).strip()
            title = match.group(2).strip()
            start_pos = match.start()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(pending_text)
            block = pending_text[start_pos:end_pos].strip()

            filed_m = re.search(r"-\s+\*\*filed:\*\*\s*([^\n]+)", block, re.IGNORECASE)
            filed = filed_m.group(1).strip() if filed_m else ""

            trigger_m = re.search(r"-\s+\*\*(?:trigger|due|trigger\s*/\s*due):\*\*\s*([^\n]+)", block, re.IGNORECASE)
            trigger = trigger_m.group(1).strip() if trigger_m else ""

            due_date = None
            if trigger:
                date_m = re.search(r"(\d{4}-\d{2}-\d{2})", trigger)
                if date_m:
                    due_date = date_m.group(1)

            what_m = re.search(r"-\s+\*\*what:\*\*\s*(.+?)(?=\n-\s+\*\*|\Z)", block, re.DOTALL | re.IGNORECASE)
            what = what_m.group(1).strip() if what_m else ""

            slug_seed = f"{target}:{title}:{filed}"
            disp_id = hashlib.sha256(slug_seed.encode("utf-8")).hexdigest()[:12]

            dispatches.append(Dispatch(
                id=disp_id,
                target=target,
                title=title,
                filed=filed,
                trigger=trigger,
                due_date=due_date,
                what=what,
                raw_block=block
            ))

        return dispatches

    def get_pending_for(self, target: str = "oracle") -> List[Dispatch]:
        """Get all pending dispatches matching target."""
        all_d = self.parse_dispatches()
        return [d for d in all_d if d.matches_target(target)]

    def get_due_for(self, target: str = "oracle", ignore_already_sent: bool = True) -> List[Dispatch]:
        """Get dispatches that are due today or overdue."""
        pending = self.get_pending_for(target)
        due = [d for d in pending if d.is_due]
        if ignore_already_sent:
            due = [d for d in due if not self.is_dispatched(d.id)]
        return due

    def format_discord_message(self, dispatch: Dispatch) -> str:
        """Format a dispatch for presentation in a Discord DM."""
        due_str = f"Due: `{dispatch.due_date}`" if dispatch.due_date else f"Trigger: `{dispatch.trigger}`"
        msg = (
            f"📋 **Dominion Dispatch** (`{dispatch.target}` · {due_str})\n"
            f"**{dispatch.title}**\n\n"
            f"{dispatch.what}\n\n"
            f"_Reply directly to this message to record your update or answer._"
        )
        return msg


# Module-level convenience singleton
_manager = DispatchManager()

def get_due_oracle_dispatches(dispatch_file: Optional[Path] = None) -> List[Dispatch]:
    mgr = DispatchManager(dispatch_path=dispatch_file) if dispatch_file else _manager
    return mgr.get_due_for("oracle", ignore_already_sent=True)

def mark_oracle_dispatch_sent(dispatch: Dispatch, channel_id: Optional[str] = None, message_id: Optional[int] = None, state_path: Optional[Path] = None) -> None:
    mgr = DispatchManager(state_path=state_path) if state_path else _manager
    mgr.mark_dispatched(dispatch, channel_id=channel_id, message_id=message_id)


def main():
    parser = argparse.ArgumentParser(description="Dominion Dispatch Manager for Oracle")
    parser.add_argument("action", choices=["list", "due", "show"], default="list", nargs="?")
    parser.add_argument("--target", default="all", help="Target machine or service (default: all)")
    parser.add_argument("--id", help="Dispatch ID for 'show' action")
    parser.add_argument("--file", help="Custom DISPATCH.md path")
    args = parser.parse_args()

    dm = DispatchManager(dispatch_path=Path(args.file) if args.file else None)

    if args.action == "list":
        if args.target == "all":
            items = dm.parse_dispatches()
        else:
            items = dm.get_pending_for(args.target)
        print(f"Pending Dispatches ({len(items)}):")
        for idx, item in enumerate(items, 1):
            sent_tag = " [SENT]" if dm.is_dispatched(item.id) else ""
            due_tag = f" (Due: {item.due_date})" if item.due_date else f" ({item.trigger})"
            print(f" {idx}. [{item.id}] → {item.target}: {item.title}{due_tag}{sent_tag}")

    elif args.action == "due":
        target = "oracle" if args.target == "all" else args.target
        items = dm.get_due_for(target)
        print(f"Due Dispatches for {target} ({len(items)}):")
        for item in items:
            print(f" - [{item.id}] {item.title} (Due: {item.due_date})")

    elif args.action == "show":
        items = dm.parse_dispatches()
        matched = [i for i in items if i.id == args.id or (args.id and args.id.lower() in i.title.lower())]
        if not matched:
            print(f"No dispatch matching '{args.id}'")
            sys.exit(1)
        item = matched[0]
        print(dm.format_discord_message(item))


if __name__ == "__main__":
    main()
