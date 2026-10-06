"""
Unit tests for routine_manager.
"""
from datetime import datetime
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from routine_manager import Routine, RoutineManager


SAMPLE_ROUTINES = [
    {
        "id": "morning-check",
        "title": "Morning Check",
        "time": "08:00",
        "message": "Good morning routine check.",
        "enabled": True
    },
    {
        "id": "noon-check",
        "title": "Noon Check",
        "time": "12:00",
        "message": "Noon routine check.",
        "enabled": True
    },
    {
        "id": "disabled-check",
        "title": "Disabled Check",
        "time": "14:00",
        "message": "Disabled reminder.",
        "enabled": False
    }
]


class TestRoutineManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.routines_file = Path(self.temp_dir.name) / "routines.json"
        self.state_file = Path(self.temp_dir.name) / "routine_state.json"
        self.routines_file.write_text(json.dumps(SAMPLE_ROUTINES), encoding="utf-8")
        self.manager = RoutineManager(
            routines_path=self.routines_file,
            state_path=self.state_file
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_parse_routines(self):
        routines = self.manager.parse_routines()
        self.assertEqual(len(routines), 3)
        self.assertEqual(routines[0].id, "morning-check")
        self.assertEqual(routines[0].hour, 8)
        self.assertEqual(routines[0].minute, 0)
        self.assertTrue(routines[0].enabled)
        self.assertFalse(routines[2].enabled)

    def test_is_due_now(self):
        routine = Routine(
            id="test-1",
            title="Test",
            target_time="08:00",
            message="Test msg",
            enabled=True
        )
        # Exact time
        dt_exact = datetime(2026, 10, 6, 8, 0, 0)
        self.assertTrue(routine.is_due_now(dt_exact))

        # 5 mins later (within default 15 min window)
        dt_after = datetime(2026, 10, 6, 8, 5, 0)
        self.assertTrue(routine.is_due_now(dt_after))

        # 20 mins later (past window)
        dt_late = datetime(2026, 10, 6, 8, 20, 0)
        self.assertFalse(routine.is_due_now(dt_late))

        # 5 mins before (not yet due)
        dt_before = datetime(2026, 10, 6, 7, 55, 0)
        self.assertFalse(routine.is_due_now(dt_before))

    def test_mark_and_check_sent_today(self):
        routines = self.manager.parse_routines()
        r1 = routines[0]
        dt = datetime(2026, 10, 6, 8, 2, 0)

        self.assertFalse(self.manager.is_sent_today(r1.id, dt))
        self.manager.mark_routine_sent(r1, channel_id="123456", message_id=999)
        self.assertTrue(self.manager.is_sent_today(r1.id, dt))

        # Next day should not be marked sent
        next_day = datetime(2026, 10, 7, 8, 0, 0)
        self.assertFalse(self.manager.is_sent_today(r1.id, next_day))

    def test_get_due_routines(self):
        dt = datetime(2026, 10, 6, 12, 5, 0)
        due = self.manager.get_due_routines(dt)
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].id, "noon-check")

        # Mark sent and check again
        self.manager.mark_routine_sent(due[0])
        due_again = self.manager.get_due_routines(dt)
        self.assertEqual(len(due_again), 0)


if __name__ == "__main__":
    unittest.main()
