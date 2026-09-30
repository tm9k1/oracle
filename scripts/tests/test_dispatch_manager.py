"""
Unit and functional tests for dispatch_manager.
"""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from dispatch_manager import Dispatch, DispatchManager


SAMPLE_DISPATCH_MD = """# Dispatch — cross-machine requests

## Pending

### → oracle — check in on Contrite Witness de-Googled setup via Discord (~1 week out)

- **filed:** 2026-09-24, from `infinity`, at the sovereign's ask (*"ask me how it's going"*).
- **trigger / due:** ~2026-10-01 (one week after the 2026-09-24 de-Googling session).
- **what:** Ask user via Discord how [[contrite-witness]] is holding up under daily use:
  1. Real-world battery life & screen-on endurance.
  2. Background sync & notification reliability.

### → requiem — capture the facts the ETERNITY migration needs (read-only, ~20 min)

- **filed:** 2026-07-30, from `hb4okhz`.
- **what:** record into Dominion.

### → oracle — immediate test dispatch

- **filed:** 2026-09-24, from `infinity`.
- **trigger / due:** 2026-09-20 (already past).
- **what:** This is an immediate test.
"""


class TestDispatchManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.dispatch_file = Path(self.temp_dir.name) / "DISPATCH.md"
        self.state_file = Path(self.temp_dir.name) / "dispatches_sent.json"
        self.dispatch_file.write_text(SAMPLE_DISPATCH_MD, encoding="utf-8")
        self.manager = DispatchManager(
            dispatch_path=self.dispatch_file,
            state_path=self.state_file
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_dispatches(self):
        dispatches = self.manager.parse_dispatches()
        self.assertEqual(len(dispatches), 3)

        d1 = dispatches[0]
        self.assertEqual(d1.target, "oracle")
        self.assertIn("Contrite Witness", d1.title)
        self.assertEqual(d1.due_date, "2026-10-01")
        self.assertIn("battery life", d1.what)

        d2 = dispatches[1]
        self.assertEqual(d2.target, "requiem")
        self.assertIsNone(d2.due_date)

    def test_get_pending_for(self):
        oracle_dispatches = self.manager.get_pending_for("oracle")
        self.assertEqual(len(oracle_dispatches), 2)
        requiem_dispatches = self.manager.get_pending_for("requiem")
        self.assertEqual(len(requiem_dispatches), 1)

    def test_get_due_for(self):
        due_dispatches = self.manager.get_due_for("oracle")
        # 2026-09-20 is <= 2026-09-24 (today), 2026-10-01 is > 2026-09-24
        self.assertEqual(len(due_dispatches), 1)
        self.assertEqual(due_dispatches[0].title, "immediate test dispatch")

    def test_mark_dispatched_and_state_persistence(self):
        due = self.manager.get_due_for("oracle")
        self.assertEqual(len(due), 1)
        item = due[0]

        self.assertFalse(self.manager.is_dispatched(item.id))
        self.manager.mark_dispatched(item, channel_id="dm-1234", message_id=5678)
        self.assertTrue(self.manager.is_dispatched(item.id))

        # Subsequent check should filter it out
        due_after = self.manager.get_due_for("oracle")
        self.assertEqual(len(due_after), 0)

        # But get_pending_for still sees it in markdown
        pending = self.manager.get_pending_for("oracle")
        self.assertEqual(len(pending), 2)

    def test_format_discord_message(self):
        dispatches = self.manager.parse_dispatches()
        msg = self.manager.format_discord_message(dispatches[0])
        self.assertIn("Dominion Dispatch", msg)
        self.assertIn("oracle", msg)
        self.assertIn("Contrite Witness", msg)
        self.assertIn("battery life", msg)


if __name__ == "__main__":
    unittest.main()
