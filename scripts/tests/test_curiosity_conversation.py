#!/usr/bin/env python3
"""
End-to-end sample conversation verification for Dominion Curiosity Engine in Oracle bot.

Tests:
1. /curiosity status and /curiosity survey commands.
2. Question delivery via DM.
3. Unrelated user message ("Keep an open ear") -> Oracle answers user request, retains pending question.
4. User answers curiosity question -> Oracle acknowledges answer, marks question answered, stages note to Dominion inbox.
5. Next question asked and skipped -> cleanly skipped without stalling.
"""
import asyncio
import json
import shutil
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import oracle_bot
from backends import BackendResult, BaseAIBackend
from curiosity_engine import (
    ActiveQuestion,
    CuriosityEngine,
    CuriosityQuestion,
)


class TestCuriosityConversation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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

        # Populate test Dominion files
        (self.entities_dir / "father.md").write_text(
            "# Family Member\n## What we know\n- Involved in house improvements.\n## Open questions\n- Other details — not recorded.\n",
            encoding="utf-8",
        )
        (self.entities_dir / "bunker.md").write_text(
            "# BUNKER (backup SSD)\n## Open questions\n- Its exact contents, model, and interface.\n",
            encoding="utf-8",
        )
        (self.mind_dir / "about-me.md").write_text(
            "# Preferences & Habits\n- Sleep routine\n- Waking earlier\n",
            encoding="utf-8",
        )
        (self.mind_dir / "ref_gadget_inventory.md").write_text(
            "# Gadget inventory\n- Oculus Quest 3\n- Snowsky Echo Mini\n",
            encoding="utf-8",
        )

        self.config_file.write_text(
            json.dumps(
                {
                    "curiosity": {
                        "enabled": True,
                        "questions_per_day": 2,
                        "min_gap_hours": 6,
                        "active_hours_start": 0,
                        "active_hours_end": 24,
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

        # Wire engine into oracle_bot
        oracle_bot.curiosity_engine = self.engine
        oracle_bot.ALLOWED_IDS = {123456789012345678}

    async def asyncTearDown(self):
        shutil.rmtree(self.temp_dir)

    async def test_full_curiosity_conversation_lifecycle(self):
        """
        Verify the full conversational curiosity flow:
        1. Query /curiosity status -> empty queue, no active question.
        2. Survey Dominion -> populates queue.
        3. Deliver curiosity question via DM.
        4. User sends unrelated inquiry -> Oracle answers inquiry, leaves question pending (open ear).
        5. User answers curiosity question -> Oracle records answer, stages note to Dominion inbox.
        6. Ask next question, user skips -> Question marked skipped.
        """
        mock_channel = MagicMock(spec=oracle_bot.discord.DMChannel)
        mock_channel.id = 123456789
        sent_messages = []

        async def fake_send(content=None, **kwargs):
            m = MagicMock()
            m.id = len(sent_messages) + 2000
            m.content = content
            m.channel = mock_channel
            sent_messages.append(m)
            return m

        mock_channel.send = AsyncMock(side_effect=fake_send)

        # ── 1. Test /curiosity status ─────────────────────────────────────────
        await oracle_bot._handle_curiosity_command(mock_channel, "/curiosity status")
        self.assertTrue(len(sent_messages) >= 1)
        status_msg = sent_messages[-1].content
        self.assertIn("Dominion Curiosity Status", status_msg)
        self.assertIn("**Active Question**: none", status_msg)

        # ── 2. Run survey and deliver first question ─────────────────────────
        await oracle_bot._handle_curiosity_command(mock_channel, "/curiosity ask")
        self.assertTrue(len(sent_messages) >= 2)
        question_msg = sent_messages[-1]
        self.assertIn("Dominion Curiosity", question_msg.content)

        active_q = self.engine.get_active_question()
        self.assertIsNotNone(active_q)
        self.assertEqual(active_q.status, "pending")
        initial_q_id = active_q.id

        # ── 3. Unrelated user message ("Keep an open ear") ────────────────────
        # User asks about docker containers rather than answering the curiosity question
        user_unrelated_msg = MagicMock(spec=oracle_bot.discord.Message)
        user_unrelated_msg.id = 3001
        user_unrelated_msg.author = MagicMock()
        user_unrelated_msg.author.id = 123456789012345678  # user
        user_unrelated_msg.author.bot = False
        user_unrelated_msg.channel = mock_channel
        user_unrelated_msg.content = "What is the status of docker containers on requiem?"
        user_unrelated_msg.reference = None

        mock_backend = MagicMock(spec=BaseAIBackend)
        mock_backend.name = "agy (gemini-3.8-flash-high)"
        mock_backend.stream_turn = AsyncMock(
            return_value=BackendResult(
                result="All 8 containers on requiem are running healthy with 0 restarts.",
                session_id="test-session-unrelated",
                usage={"total_tokens": 80},
            )
        )
        mock_backend.get_context_fraction.return_value = 0.1
        mock_backend.mirror_session = MagicMock()

        with patch.object(oracle_bot, "ai_backend", mock_backend), \
             patch("oracle_bot.save_sessions"), \
             patch("oracle_bot._react"), \
             patch("oracle_bot._react_done"):
            await oracle_bot.on_message(user_unrelated_msg)

        # Verify AI backend answered user's docker question directly
        self.assertTrue(len(sent_messages) >= 3)
        self.assertIn("All 8 containers", sent_messages[-1].content)

        # Verify backend received context about the pending curiosity question
        call_prompt = mock_backend.stream_turn.call_args.kwargs.get("prompt", "")
        self.assertIn("docker containers", call_prompt)
        self.assertIn("Dominion Curiosity", call_prompt)
        self.assertIn("Keep an open ear", call_prompt)

        # CRITICAL VERIFICATION: The curiosity question was NOT lost or overwritten!
        active_q_after_unrelated = self.engine.get_active_question()
        self.assertIsNotNone(active_q_after_unrelated)
        self.assertEqual(active_q_after_unrelated.id, initial_q_id)
        self.assertEqual(active_q_after_unrelated.status, "pending")

        # ── 4. User answers the curiosity question ───────────────────────────
        user_answer_msg = MagicMock(spec=oracle_bot.discord.Message)
        user_answer_msg.id = 3002
        user_answer_msg.author = MagicMock()
        user_answer_msg.author.id = 123456789012345678
        user_answer_msg.author.bot = False
        user_answer_msg.channel = mock_channel
        user_answer_msg.content = (
            "My father is finishing the kitchen cabinets and balcony tiling this week, aiming to wrap by mid-November."
        )
        # Simulate user replying to the question message
        user_answer_msg.reference = MagicMock()
        user_answer_msg.reference.message_id = question_msg.id
        mock_channel.fetch_message = AsyncMock(return_value=question_msg)

        mock_backend.stream_turn = AsyncMock(
            return_value=BackendResult(
                result="Good to hear the balcony tiling and kitchen cabinets will be wrapped by mid-November. I've staged this into Dominion.",
                session_id="test-session-answered",
                usage={"total_tokens": 100},
            )
        )

        with patch.object(oracle_bot, "ai_backend", mock_backend), \
             patch("oracle_bot.save_sessions"), \
             patch("oracle_bot._react"), \
             patch("oracle_bot._react_done"):
            await oracle_bot.on_message(user_answer_msg)

        # Verify AI responded to the answer
        self.assertTrue(len(sent_messages) >= 4)
        self.assertIn("Good to hear", sent_messages[-1].content)

        # Verify question is marked answered in state
        active_q_after_answer = self.engine.get_active_question()
        self.assertIsNone(active_q_after_answer)

        # Verify staged note in Dominion inbox
        staged_files = list(self.inbox_dir.glob("*.md"))
        self.assertEqual(len(staged_files), 1)
        staged_content = staged_files[0].read_text(encoding="utf-8")
        self.assertIn("status: pending-review", staged_content)
        self.assertIn("source: oracle-curiosity", staged_content)
        self.assertIn("kitchen cabinets and balcony tiling", staged_content)

        # ── 5. Next question delivery & skip flow ────────────────────────────
        await oracle_bot._handle_curiosity_command(mock_channel, "/curiosity ask")
        self.assertTrue(len(sent_messages) >= 5)
        new_q_msg = sent_messages[-1]
        self.assertIn("Dominion Curiosity", new_q_msg.content)

        new_active = self.engine.get_active_question()
        self.assertIsNotNone(new_active)
        self.assertNotEqual(new_active.id, initial_q_id)

        # User skips
        user_skip_msg = MagicMock(spec=oracle_bot.discord.Message)
        user_skip_msg.id = 3003
        user_skip_msg.author = MagicMock()
        user_skip_msg.author.id = 123456789012345678
        user_skip_msg.author.bot = False
        user_skip_msg.channel = mock_channel
        user_skip_msg.content = "skip that for now"
        user_skip_msg.reference = None

        with patch("oracle_bot.save_sessions"):
            await oracle_bot.on_message(user_skip_msg)

        # Verify skip confirmation was sent without calling AI backend
        self.assertTrue(len(sent_messages) >= 6)
        self.assertIn("skipped that question", sent_messages[-1].content.lower())

        # Verify question is cleared and marked skipped in history
        self.assertIsNone(self.engine.get_active_question())
        st = self.engine.load_state()
        history = st.get("history", [])
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["status"], "answered")
        self.assertEqual(history[1]["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
