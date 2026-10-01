#!/usr/bin/env python3
"""
Unit tests for Dominion Curiosity Engine.
"""
import json
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from curiosity_engine import (
    ActiveQuestion,
    CuriosityEngine,
    CuriosityQuestion,
    DominionSurveyor,
)


class TestCuriosityEngine(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.dominion_root = Path(self.temp_dir) / "Dominion"
        self.entities_dir = self.dominion_root / "entities"
        self.mind_dir = self.dominion_root / "mind"
        self.inbox_dir = self.mind_dir / "inbox"
        self.state_file = Path(self.temp_dir) / "curiosity_state.json"
        self.config_file = Path(self.temp_dir) / "config.json"

        self.entities_dir.mkdir(parents=True, exist_ok=True)
        self.mind_dir.mkdir(parents=True, exist_ok=True)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        # Create mock entity files
        (self.entities_dir / "father.md").write_text(
            "# Family Member\n## What we know\n- House improvements.\n## Open questions\n- Other details — not recorded.\n",
            encoding="utf-8",
        )
        (self.entities_dir / "spartan.md").write_text(
            "---\nid: spartan\ntitle: SPARTAN\n---\n# SPARTAN\n## Open questions\n- Whether its Tailscale node is still enrolled in the tailnet.\n",
            encoding="utf-8",
        )
        (self.entities_dir / "bunker.md").write_text(
            "# BUNKER\n## Open questions\n- Its exact contents, model, and interface.\n",
            encoding="utf-8",
        )
        (self.entities_dir / "wedding.md").write_text(
            "# Wedding (2026-11-25)\n## Open questions\n- None load-bearing.\n",
            encoding="utf-8",
        )

        # Create mock mind notes
        (self.mind_dir / "about-me.md").write_text(
            "# Preferences & Habits\n- Sleep schedule\n- Waking earlier\n",
            encoding="utf-8",
        )
        (self.mind_dir / "ref_gadget_inventory.md").write_text(
            "# Gadgets\n- Oculus Quest 3\n- Snowsky Echo Mini\n- ESP32\n",
            encoding="utf-8",
        )

        # Create mock planning chamber
        (self.dominion_root / "PLANNING-CHAMBER.md").write_text(
            "# Planning Chamber\n- Wedding 2026-11-25\n- Syncthing versioning decision\n",
            encoding="utf-8",
        )

        self.config_file.write_text(
            json.dumps(
                {
                    "curiosity": {
                        "enabled": True,
                        "questions_per_day": 2,
                        "min_gap_hours": 6,
                        "active_hours_start": 10,
                        "active_hours_end": 22,
                        "survey_interval_days": 7,
                    }
                }
            ),
            encoding="utf-8",
        )

        self.engine = CuriosityEngine(
            dominion_root=self.dominion_root,
            state_path=self.state_file,
            config_path=self.config_file,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_surveyor_finds_open_questions_and_topics(self):
        surveyor = DominionSurveyor(self.dominion_root)
        questions = surveyor.survey_all()
        self.assertTrue(len(questions) >= 5)

        topics = {q.topic for q in questions}
        self.assertIn("father", topics)
        self.assertIn("spartan", topics)
        self.assertIn("bunker", topics)
        self.assertIn("about-me", topics)
        self.assertIn("ref-gadget-inventory", topics)

    def test_run_survey_populates_queue(self):
        queued = self.engine.run_survey(force=True)
        self.assertTrue(len(queued) >= 5)
        st = self.engine.load_state()
        self.assertEqual(len(st["queued_questions"]), len(queued))
        self.assertGreater(st["last_survey_at"], 0)

    def test_pop_next_question_sets_active(self):
        self.engine.run_survey(force=True)
        initial_count = len(self.engine.load_state()["queued_questions"])

        q = self.engine.pop_next_question()
        self.assertIsNotNone(q)
        self.assertIsInstance(q, ActiveQuestion)
        self.assertEqual(q.status, "pending")

        st = self.engine.load_state()
        self.assertEqual(len(st["queued_questions"]), initial_count - 1)
        self.assertIsNotNone(st["active_question"])
        self.assertEqual(st["active_question"]["id"], q.id)
        self.assertEqual(st["daily_stats"]["count"], 1)

    def test_should_ask_now_disciplines(self):
        # 1. With active question pending, should_ask_now must return False (never bury unanswered Q)
        self.engine.run_survey(force=True)
        self.engine.pop_next_question()

        active_time = datetime(2026, 9, 24, 14, 0, 0)
        should_ask, reason = self.engine.should_ask_now(now_dt=active_time)
        self.assertFalse(should_ask)
        self.assertEqual(reason, "active_question_pending")

        # 2. Clear active question, check quiet hours (e.g. 3 AM)
        self.engine.skip_active_question()
        night_time = datetime(2026, 9, 24, 3, 0, 0)
        should_ask, reason = self.engine.should_ask_now(now_dt=night_time)
        self.assertFalse(should_ask)
        self.assertIn("outside_active_hours", reason)

        # 3. During waking hours with min gap met
        day_time = datetime(2026, 9, 24, 15, 0, 0)
        # Advance history asked_at so min gap is met
        st = self.engine.load_state()
        st["history"][-1]["asked_at"] = day_time.timestamp() - 30000
        self.engine.save_state(st)

        should_ask, reason = self.engine.should_ask_now(now_dt=day_time)
        self.assertTrue(should_ask)
        self.assertEqual(reason, "ask")

    def test_classify_intent(self):
        self.engine.run_survey(force=True)
        # Ensure active question is father-house-improvements for testing topic alignment
        st = self.engine.load_state()
        qq = st.get("queued_questions", [])
        for idx, item in enumerate(qq):
            if item.get("topic") == "father":
                father_item = qq.pop(idx)
                qq.insert(0, father_item)
                break
        st["queued_questions"] = qq
        self.engine.save_state(st)
        q = self.engine.pop_next_question()
        self.engine.register_message_sent(message_id=9999, channel_id="dm123")

        # Skip commands
        self.assertEqual(self.engine.classify_intent("skip"), "skip")
        self.assertEqual(self.engine.classify_intent("pass"), "skip")
        self.assertEqual(self.engine.classify_intent("not now"), "skip")
        self.assertEqual(self.engine.classify_intent("/curiosity skip"), "skip")

        # Unrelated commands / queries (open ear)
        self.assertEqual(self.engine.classify_intent("what is the disk usage on requiem?"), "unrelated")
        self.assertEqual(self.engine.classify_intent("docker ps"), "unrelated")
        self.assertEqual(self.engine.classify_intent("can you restart the bot?"), "unrelated")

        # Meta-feedback should be classified as unrelated rather than hijacking curiosity
        self.assertEqual(self.engine.classify_intent("bro this dispatch should have been processed by you"), "unrelated")
        self.assertEqual(self.engine.classify_intent("keep it like a natural conversation don't show impl detail"), "unrelated")

        # Answer to curiosity question with topic alignment
        self.assertEqual(
            self.engine.classify_intent("My father is remodeling the kitchen and balcony, should be done in November."),
            "answer",
        )
        # Explicit Discord reply to message ID
        self.assertEqual(
            self.engine.classify_intent("Going well!", reply_to_message_id=9999),
            "answer",
        )

    def test_record_answer_and_stage_to_inbox(self):
        self.engine.run_survey(force=True)
        q = self.engine.pop_next_question()

        user_ans = "The kitchen and balcony renovation is moving along well, expected completion mid-November."
        aq, staged_path = self.engine.record_answer(user_ans, auto_stage=True)

        self.assertEqual(aq.status, "answered")
        self.assertEqual(aq.user_answer, user_ans)
        self.assertIsNotNone(staged_path)
        self.assertTrue(staged_path.exists())

        # Verify staged note contents
        staged_content = staged_path.read_text(encoding="utf-8")
        self.assertIn("status: pending-review", staged_content)
        self.assertIn("source: oracle-curiosity", staged_content)
        self.assertIn(user_ans, staged_content)
        self.assertIn(q.question, staged_content)

        # Verify state: active question cleared, added to history
        st = self.engine.load_state()
        self.assertIsNone(st["active_question"])
        self.assertEqual(len(st["history"]), 1)
        self.assertEqual(st["history"][0]["status"], "answered")

    def test_skip_active_question(self):
        self.engine.run_survey(force=True)
        q = self.engine.pop_next_question()
        skipped = self.engine.skip_active_question("user_passed")

        self.assertEqual(skipped.status, "skipped")
        st = self.engine.load_state()
        self.assertIsNone(st["active_question"])
        self.assertEqual(len(st["history"]), 1)
        self.assertEqual(st["history"][0]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
