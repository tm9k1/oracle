"""
End-to-end sample conversation verification for Dominion dispatches via Oracle bot.
"""
import asyncio
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock, patch

import oracle_bot
from backends import BackendResult, BaseAIBackend
from dispatch_manager import Dispatch, DispatchManager


TEST_DISPATCH_CONTENT = """# Dispatch — cross-machine requests

## Pending

### → oracle — check in on Contrite Witness de-Googled setup via Discord (~1 week out)

- **filed:** 2026-09-24, from `infinity`, at the sovereign's ask (*"ask me how it's going.. ask me a week from now via discord"*).
- **trigger / due:** ~2026-10-01 (one week after the 2026-09-24 de-Googling session).
- **what:** Ask user via Discord how [[contrite-witness]] is holding up under daily use:
  1. Real-world battery life & screen-on endurance (with RAM Plus off, Wi-Fi scanning off, AOD Tap-to-Show, and telemetry stripped).
  2. Background sync & notification reliability (Syncthing, Immich photo backups, WhatsApp, Slack, and Duo Mobile 2FA approvals).
  3. General system smoothness and whether any banking app or service showed regressions.
"""


class TestDispatchConversation(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = TemporaryDirectory()
        self.dispatch_file = Path(self.temp_dir.name) / "DISPATCH.md"
        self.state_file = Path(self.temp_dir.name) / "dispatches_sent.json"
        self.dispatch_file.write_text(TEST_DISPATCH_CONTENT, encoding="utf-8")

        self.manager = DispatchManager(
            dispatch_path=self.dispatch_file,
            state_path=self.state_file
        )

    async def asyncTearDown(self):
        self.temp_dir.cleanup()

    async def test_full_dispatch_conversation_flow(self):
        """
        Verify complete dispatch lifecycle:
        1. Query /dispatch list command.
        2. Proactively deliver dispatch via /dispatch send.
        3. User replies in Discord with status report.
        4. AI backend processes user reply and responds with analysis.
        """
        mock_channel = MagicMock(spec=oracle_bot.discord.DMChannel)
        mock_channel.id = 123456789
        sent_messages = []

        async def fake_send(content=None, **kwargs):
            m = MagicMock()
            m.id = len(sent_messages) + 1000
            m.content = content
            sent_messages.append(m)
            return m

        mock_channel.send = AsyncMock(side_effect=fake_send)

        # 1. Test /dispatch list
        with patch("oracle_bot.DispatchManager", return_value=self.manager):
            await oracle_bot._handle_dispatch_command(mock_channel, "/dispatch list")

        self.assertTrue(len(sent_messages) >= 1)
        list_msg = sent_messages[-1].content
        self.assertIn("Dominion Pending Dispatches", list_msg)
        self.assertIn("Contrite Witness", list_msg)

        # 2. Trigger dispatch delivery
        with patch("oracle_bot.DispatchManager", return_value=self.manager):
            await oracle_bot._handle_dispatch_command(mock_channel, "/dispatch send contrite")

        dispatch_msg = sent_messages[-1]
        self.assertIn("Dominion Dispatch", dispatch_msg.content)
        self.assertIn("Contrite Witness", dispatch_msg.content)
        self.assertIn("battery life", dispatch_msg.content)
        self.assertTrue(self.manager.is_dispatched(self.manager.get_pending_for("oracle")[0].id))

        # 3. Simulate Sovereign replying to this dispatch message
        user_reply = MagicMock(spec=oracle_bot.discord.Message)
        user_reply.author = MagicMock()
        user_reply.author.id = 123456789012345678
        user_reply.author.bot = False
        user_reply.channel = mock_channel
        user_reply.content = (
            "Battery life has been amazing! Getting 7.5 hours SOT. "
            "Syncthing and Immich backups run instantly in the background without delay. "
            "No banking app issues either."
        )
        user_reply.reference = MagicMock()
        user_reply.reference.message_id = dispatch_msg.id
        mock_channel.fetch_message = AsyncMock(return_value=dispatch_msg)

        # Mock AI backend response to the sovereign
        mock_backend = MagicMock(spec=BaseAIBackend)
        mock_backend.name = "agy (gemini-3.8-flash-high)"
        mock_backend.stream_turn = AsyncMock(
            return_value=BackendResult(
                result=(
                    "Glad to hear the S23 optimizations are holding up! "
                    "The 7.5h SOT confirms disabling RAM Plus and background Wi-Fi scanning made a measurable difference. "
                    "I will log this update into Dominion under contrite-witness."
                ),
                session_id="sample-conv-sess-123",
                usage={"total_tokens": 150}
            )
        )
        mock_backend.get_context_fraction.return_value = 0.1
        mock_backend.mirror_session = MagicMock()

        with patch.object(oracle_bot, "ALLOWED_IDS", {123456789012345678}), \
             patch.object(oracle_bot, "ai_backend", mock_backend), \
             patch("oracle_bot.save_sessions"), \
             patch("oracle_bot._react"), \
             patch("oracle_bot._react_done"):
            await oracle_bot.on_message(user_reply)

        # 4. Verify AI response was sent back to the user
        self.assertTrue(len(sent_messages) >= 3)
        final_reply = sent_messages[-1].content
        self.assertIn("S23 optimizations", final_reply)
        self.assertIn("7.5h SOT", final_reply)

        # Verify backend received the context of the dispatch
        call_prompt = mock_backend.stream_turn.call_args.kwargs.get("prompt", "")
        self.assertIn("Battery life has been amazing", call_prompt)
        self.assertIn("Dominion Dispatch", call_prompt)


if __name__ == "__main__":
    unittest.main()
