"""
Dominion Routine Manager for Oracle
Manages recurring daily routines (feeding schedules, habits, check-ins)
and checks for due reminders.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, time
import json
import logging
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

log = logging.getLogger("oracle.routine_manager")

DEFAULT_ROUTINES_FILE = Path("/home/tm9k1/.ai/routines.json")
DEFAULT_STATE_FILE = Path("/home/tm9k1/.ai/routine_state.json")


@dataclass
class Routine:
    id: str
    title: str
    target_time: str  # "HH:MM"
    message: str
    enabled: bool = True

    @property
    def hour(self) -> int:
        return int(self.target_time.split(":")[0])

    @property
    def minute(self) -> int:
        return int(self.target_time.split(":")[1])

    def is_due_now(self, now: Optional[datetime] = None, window_minutes: int = 15) -> bool:
        """
        Check if routine is due within window_minutes of target_time today.
        Allows catching a reminder if the bot was busy or checked within a short window.
        """
        if not self.enabled:
            return False

        if now is None:
            now = datetime.now()

        target_dt = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)
        diff_seconds = (now - target_dt).total_seconds()

        return 0 <= diff_seconds <= (window_minutes * 60)


class RoutineManager:
    def __init__(self, routines_path: Optional[Path] = None, state_path: Optional[Path] = None):
        self.routines_path = Path(routines_path or DEFAULT_ROUTINES_FILE)
        self.state_path = Path(state_path or DEFAULT_STATE_FILE)

    def load_state(self) -> Dict[str, Any]:
        if self.state_path.exists():
            try:
                return json.loads(self.state_path.read_text(encoding="utf-8"))
            except Exception as e:
                log.warning("Failed to load routine state %s: %s", self.state_path, e)
                return {}
        return {}

    def save_state(self, state: Dict[str, Any]) -> None:
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as e:
            log.error("Failed to save routine state %s: %s", self.state_path, e)

    def parse_routines(self) -> List[Routine]:
        if not self.routines_path.exists():
            log.warning("Routines file does not exist: %s", self.routines_path)
            return []

        try:
            data = json.loads(self.routines_path.read_text(encoding="utf-8"))
            routines = []
            for item in data:
                routines.append(Routine(
                    id=item.get("id", ""),
                    title=item.get("title", ""),
                    target_time=item.get("time", "00:00"),
                    message=item.get("message", ""),
                    enabled=item.get("enabled", True),
                ))
            return routines
        except Exception as e:
            log.error("Failed to read routines from %s: %s", self.routines_path, e)
            return []

    def is_sent_today(self, routine_id: str, now: Optional[datetime] = None) -> bool:
        if now is None:
            now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        state = self.load_state()
        last_sent = state.get(routine_id, {}).get("last_sent_date")
        return last_sent == today_str

    def mark_routine_sent(self, routine: Routine, channel_id: Optional[str] = None, message_id: Optional[int] = None) -> None:
        now = datetime.now()
        state = self.load_state()
        state[routine.id] = {
            "title": routine.title,
            "target_time": routine.target_time,
            "last_sent_at": now.isoformat(),
            "last_sent_date": now.strftime("%Y-%m-%d"),
            "channel_id": channel_id,
            "message_id": message_id,
        }
        self.save_state(state)
        log.info("Marked routine %s as sent for %s", routine.id, now.strftime("%Y-%m-%d"))

    def get_due_routines(self, now: Optional[datetime] = None) -> List[Routine]:
        if now is None:
            now = datetime.now()
        all_routines = self.parse_routines()
        due = []
        for r in all_routines:
            if r.is_due_now(now) and not self.is_sent_today(r.id, now):
                due.append(r)
        return due


# Singleton
_manager = RoutineManager()


def main():
    parser = argparse.ArgumentParser(description="Dominion Routine Manager for Oracle")
    parser.add_argument("action", choices=["list", "due", "show"], default="list", nargs="?")
    parser.add_argument("--id", help="Routine ID for 'show' action")
    parser.add_argument("--file", help="Custom routines.json path")
    args = parser.parse_args()

    rm = RoutineManager(routines_path=Path(args.file) if args.file else None)

    if args.action == "list":
        items = rm.parse_routines()
        print(f"Routines ({len(items)}):")
        for idx, item in enumerate(items, 1):
            sent_tag = " [SENT TODAY]" if rm.is_sent_today(item.id) else ""
            status = "enabled" if item.enabled else "disabled"
            print(f" {idx}. [{item.id}] {item.title} at {item.target_time} ({status}){sent_tag}")

    elif args.action == "due":
        items = rm.get_due_routines()
        print(f"Due Routines ({len(items)}):")
        for item in items:
            print(f" - [{item.id}] {item.title} ({item.target_time})")

    elif args.action == "show":
        items = rm.parse_routines()
        matched = [i for i in items if i.id == args.id or (args.id and args.id.lower() in i.title.lower())]
        if not matched:
            print(f"No routine matching '{args.id}'")
            sys.exit(1)
        item = matched[0]
        print(item.message)


if __name__ == "__main__":
    main()
