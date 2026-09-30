"""
Unit and functional tests for Oracle Discord bot.
"""
import asyncio
import json
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import oracle_bot
from backends import BackendResult, BaseAIBackend, register_backend


class TestOracleBotHelpers(unittest.TestCase):
    def test_fmt_elapsed(self):
        self.assertEqual(oracle_bot._fmt_elapsed(30), "30s")
        self.assertEqual(oracle_bot._fmt_elapsed(120), "2m")
        self.assertEqual(oracle_bot._fmt_elapsed(7200), "2.0h")
        self.assertEqual(oracle_bot._fmt_elapsed(172800), "2.0d")

    def test_strip_mention(self):
        mock_user = MagicMock()
        mock_user.id = 12345
        with patch.object(type(oracle_bot.bot), "user", new_callable=PropertyMock(return_value=mock_user)):
            text = "<@12345> hello <@!12345> world"
            stripped = oracle_bot._strip_mention(text)
            self.assertEqual(stripped, "hello  world")

    def test_status_text_short(self):
        text = "Hello world"
        self.assertEqual(oracle_bot._status_text(text), "Hello world")

    def test_status_text_truncate_at_newline(self):
        long_text = "line1\n" + ("x" * 2000) + "\nline3\nline4"
        truncated = oracle_bot._status_text(long_text)
        self.assertLessEqual(len(truncated), 1990)
        self.assertTrue(truncated.endswith("line4"))

    def test_send_chunks_empty(self):
        res = asyncio.run(oracle_bot._send_chunks(MagicMock(), ""))
        self.assertEqual(res, [])


class TestLazyStatus(unittest.IsolatedAsyncioTestCase):
    async def test_lazy_status_flow(self):
        mock_channel = MagicMock()
        mock_sent_msg = MagicMock()
        mock_sent_msg.edit = AsyncMock()
        mock_channel.send = AsyncMock(return_value=mock_sent_msg)

        status = oracle_bot._LazyStatus(mock_channel)
        self.assertIsNone(status.msg)

        # First set should send
        await status.set("Initial text")
        mock_channel.send.assert_called_once_with("Initial text")
        self.assertEqual(status.msg, mock_sent_msg)

        # Second set should edit
        await status.set("Updated text")
        mock_sent_msg.edit.assert_called_once_with(content="Updated text")


class TestSessionStore(unittest.TestCase):
    def test_save_and_load_sessions(self):
        test_file = Path("/tmp/test_oracle_sessions.json")
        try:
            with patch("oracle_bot.SESSIONS_FILE", test_file):
                data = {"123": {"session_id": "sid-1", "last_active": 100.0}}
                oracle_bot.save_sessions(data)
                loaded = oracle_bot.load_sessions()
                self.assertEqual(loaded, data)
        finally:
            if test_file.exists():
                test_file.unlink()


class TestChannelLocks(unittest.TestCase):
    def test_lock_for_channel(self):
        lock1 = oracle_bot._lock_for("chan-1")
        lock2 = oracle_bot._lock_for("chan-1")
        lock3 = oracle_bot._lock_for("chan-2")
        self.assertIs(lock1, lock2)
        self.assertIsNot(lock1, lock3)


class TestBotDispatchAndRouting(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_flow(self):
        mock_backend = MagicMock(spec=BaseAIBackend)
        mock_backend.stream_turn = AsyncMock(
            return_value=BackendResult(
                result="Hello user!",
                session_id="new-session-789",
                usage={"total_tokens": 100},
            )
        )
        mock_backend.get_context_fraction.return_value = 0.1
        mock_backend.mirror_session = MagicMock()

        mock_channel = MagicMock()
        mock_msg = MagicMock()
        mock_msg.id = 99999
        mock_channel.send = AsyncMock(return_value=mock_msg)

        oracle_bot.sessions.clear()
        with patch.object(oracle_bot, "ai_backend", mock_backend), \
             patch("oracle_bot.save_sessions"):
            await oracle_bot._dispatch(mock_channel, "hello", None, "chan-100")

        self.assertIn("chan-100", oracle_bot.sessions)
        self.assertEqual(oracle_bot.sessions["chan-100"]["session_id"], "new-session-789")
        mock_channel.send.assert_called()


class TestPresenceManagement(unittest.IsolatedAsyncioTestCase):
    def test_format_status_activity(self):
        mock_backend = MagicMock()
        mock_backend.name = "agy (gemini-3.7-flash-high)"
        with patch.object(oracle_bot, "ai_backend", mock_backend):
            with patch.dict(oracle_bot.sessions, {}, clear=True):
                self.assertEqual(oracle_bot._format_status_activity(), "agy (gemini-3.7-flash-high) · 0 sessions")
            with patch.dict(oracle_bot.sessions, {"c1": {}}, clear=True):
                self.assertEqual(oracle_bot._format_status_activity(), "agy (gemini-3.7-flash-high) · 1 session")
            with patch.dict(oracle_bot.sessions, {"c1": {}, "c2": {}}, clear=True):
                self.assertEqual(oracle_bot._format_status_activity(), "agy (gemini-3.7-flash-high) · 2 sessions")

    async def test_update_presence_online(self):
        with patch.object(oracle_bot.bot, "change_presence", new_callable=AsyncMock) as mock_presence, \
             patch.object(oracle_bot, "_quota_reset_at", 0.0), \
             patch.dict(oracle_bot.sessions, {"c1": {}}, clear=True):
            await oracle_bot._update_presence()
            mock_presence.assert_called_once()
            call_kwargs = mock_presence.call_args[1]
            self.assertEqual(call_kwargs["status"], oracle_bot.discord.Status.online)
            self.assertIn("1 session", call_kwargs["activity"].name)

    async def test_update_presence_quota_guarded(self):
        future_time = time.time() + 1000
        with patch.object(oracle_bot.bot, "change_presence", new_callable=AsyncMock) as mock_presence, \
             patch.object(oracle_bot, "_quota_reset_at", future_time):
            await oracle_bot._update_presence()
            mock_presence.assert_not_called()

    async def test_on_ready_no_greeting_dm(self):
        mock_owner = MagicMock()
        mock_dm = MagicMock()
        mock_dm.send = AsyncMock()
        mock_owner.create_dm = AsyncMock(return_value=mock_dm)

        mock_app = MagicMock()
        mock_app.owner = mock_owner

        mock_backend = MagicMock()
        mock_backend.startup_test = AsyncMock(return_value=BackendResult(success=True, session_id="s-1"))

        with patch.object(oracle_bot.bot, "application_info", AsyncMock(return_value=mock_app)), \
             patch.object(oracle_bot, "ai_backend", mock_backend), \
             patch.object(oracle_bot, "_update_presence", new_callable=AsyncMock) as mock_update_pres, \
             patch.object(oracle_bot, "_resume_interrupted", new_callable=AsyncMock):
            await oracle_bot.on_ready()
            mock_update_pres.assert_called_once_with(oracle_bot.discord.Status.online)
            mock_dm.send.assert_not_called()


class TestImageAndAttachmentFeatures(unittest.IsolatedAsyncioTestCase):
    def test_extract_image_attachments_all_formats(self):
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png") as f1, \
             tempfile.NamedTemporaryFile(suffix=".jpg") as f2, \
             tempfile.NamedTemporaryFile(suffix=".webp") as f3:
            
            raw_text = (
                f"Here are the options:\n"
                f"![Forerunner Sphere]({f1.name})\n"
                f"[ARTIFACT: test_avatar]\n"
                f"Path: file://{f2.name}\n"
                f"<image>{f3.name}</image>\n"
                f"[attachment: {f1.name}]\n"
                f"Check out this standalone path:\n"
                f"{f2.name}\n"
                f"And Path: {f3.name}\n"
                f"Final conclusion."
            )
            cleaned, found = oracle_bot._extract_image_attachments(raw_text)
            self.assertIn("**Forerunner Sphere**", cleaned)
            self.assertNotIn("ARTIFACT:", cleaned)
            self.assertIn("Final conclusion.", cleaned)
            self.assertEqual(len(found), 3)  # f1, f2, f3 deduplicated
            found_str = [str(p.resolve()) for p in found]
            self.assertIn(str(Path(f1.name).resolve()), found_str)
            self.assertIn(str(Path(f2.name).resolve()), found_str)
            self.assertIn(str(Path(f3.name).resolve()), found_str)

    async def test_on_message_inbound_attachment(self):
        mock_msg = MagicMock()
        mock_msg.author = MagicMock()
        mock_msg.author.bot = False
        mock_msg.author.id = 123456789012345678  # allowed
        mock_msg.channel = MagicMock(spec=oracle_bot.discord.DMChannel)
        mock_msg.channel.id = 987654321
        mock_msg.content = "What is this image?"
        
        mock_att = MagicMock()
        mock_att.filename = "homelab_rack.png"
        mock_att.size = 1024
        mock_att.save = AsyncMock()
        mock_msg.attachments = [mock_att]
        mock_msg.reference = None

        with patch.object(oracle_bot, "ALLOWED_IDS", {123456789012345678}), \
             patch.object(oracle_bot, "_dispatch_with_reactions", new_callable=AsyncMock) as mock_dispatch:
            await oracle_bot.on_message(mock_msg)
            mock_att.save.assert_called_once()
            mock_dispatch.assert_called_once()
            called_prompt = mock_dispatch.call_args[0][2]
            self.assertIn("What is this image?", called_prompt)
            self.assertIn("[Inbound Attachments]", called_prompt)
            self.assertIn("homelab_rack.png", called_prompt)


if __name__ == "__main__":
    unittest.main()
