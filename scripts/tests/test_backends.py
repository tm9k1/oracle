"""
Unit and integration tests for Oracle modular AI backends.
"""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backends import (
    AgyBackend,
    BackendResult,
    BaseAIBackend,
    ClaudeCliBackend,
    get_backend,
    register_backend,
)


class TestBackendRegistry(unittest.TestCase):
    def test_get_agy_backend(self):
        backend = get_backend("agy")
        self.assertIsInstance(backend, AgyBackend)
        self.assertTrue(backend.model.startswith("gemini-3."))

    def test_get_claude_backend(self):
        backend = get_backend("claude", model="sonnet")
        self.assertIsInstance(backend, ClaudeCliBackend)
        self.assertEqual(backend.model, "sonnet")

    def test_custom_backend_registration(self):
        class DummyBackend(BaseAIBackend):
            @property
            def name(self) -> str:
                return "dummy"

            async def startup_test(self) -> BackendResult:
                return BackendResult(result="ok")

            async def run_turn(self, prompt, session_id=None, system_prompt=None):
                return BackendResult(result=f"echo: {prompt}")

            async def stream_turn(self, prompt, session_id=None, system_prompt=None, **kwargs):
                return BackendResult(result=f"stream: {prompt}")

        register_backend("dummy", DummyBackend)
        b = get_backend("dummy")
        self.assertIsInstance(b, DummyBackend)

    def test_unknown_backend(self):
        with self.assertRaises(ValueError):
            get_backend("nonexistent-backend-xyz")


class TestBackendResult(unittest.TestCase):
    def test_dict_like_access(self):
        res = BackendResult(
            result="Hello world",
            session_id="sess-123",
            usage={"input_tokens": 10, "output_tokens": 20},
            raw_data={"custom_key": "val"},
        )
        self.assertEqual(res["result"], "Hello world")
        self.assertEqual(res["session_id"], "sess-123")
        self.assertEqual(res["custom_key"], "val")
        self.assertEqual(res.get("nonexistent", "fallback"), "fallback")


class TestAgyBackend(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = AgyBackend(model="gemini-3.7-flash-high", effort="high")

    def test_build_cmd(self):
        cmd = self.backend._build_cmd("test prompt", session_id="abc-123", output_format="stream-json")
        self.assertIn("-p", cmd)
        self.assertIn("test prompt", cmd)
        self.assertIn("--output-format", cmd)
        self.assertIn("stream-json", cmd)
        self.assertIn("--conversation", cmd)
        self.assertIn("abc-123", cmd)
        self.assertIn("--model", cmd)
        self.assertIn("gemini-3.7-flash-high", cmd)
        self.assertIn("--effort", cmd)
        self.assertIn("high", cmd)

    def test_prepare_prompt_new_session(self):
        p = self.backend._prepare_prompt("user query", session_id=None, system_prompt="System instructions")
        self.assertIn("[SYSTEM INSTRUCTIONS]", p)
        self.assertIn("System instructions", p)
        self.assertIn("user query", p)

    def test_prepare_prompt_resume_session(self):
        p = self.backend._prepare_prompt("user query", session_id="abc-123", system_prompt="System instructions")
        self.assertEqual(p, "user query")

    def test_context_fraction(self):
        res = BackendResult(
            usage={"input_tokens": 500_000, "output_tokens": 100_000, "total_tokens": 600_000}
        )
        frac = self.backend.get_context_fraction(res)
        self.assertAlmostEqual(frac, 0.5, places=2)

    async def test_stream_turn_mocked(self):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.wait = AsyncMock(return_value=0)

        lines = [
            b'{"event":"init","conversation_id":"cid-999"}\n',
            b'{"event":"step_update","step_update":{"conversation_id":"cid-999","step_type":"agent_response","text_delta":"Hello "}}\n',
            b'{"event":"step_update","step_update":{"conversation_id":"cid-999","step_type":"agent_response","text_delta":"there!"}}\n',
            b'{"event":"step_update","step_update":{"conversation_id":"cid-999","step_type":"tool","tool_name":"run_command","state":"ACTIVE"}}\n',
            b'{"event":"step_update","step_update":{"conversation_id":"cid-999","step_type":"tool","tool_name":"run_command","state":"DONE"}}\n',
            b'{"event":"result","result":{"conversation_id":"cid-999","status":"SUCCESS","response":"Hello there!","usage":{"total_tokens":50}}}\n',
        ]

        async def async_iter():
            for line in lines:
                yield line

        mock_proc.stdout = async_iter()
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.read = AsyncMock(return_value=b"")

        deltas = []
        activities = []

        async def on_delta(d):
            deltas.append(d)

        async def on_act(a):
            activities.append(a)

        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
            res = await self.backend.stream_turn(
                "hi",
                session_id=None,
                on_text_delta=on_delta,
                on_activity=on_act,
            )

        self.assertEqual(res.result, "Hello there!")
        self.assertEqual(res.session_id, "cid-999")
        self.assertEqual("".join(deltas), "Hello there!")
        self.assertIn("tool:run_command", activities)
        self.assertIn("thinking", activities)


class TestClaudeCliBackend(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = ClaudeCliBackend(model="sonnet")

    def test_build_cmd(self):
        cmd = self.backend._build_cmd("prompt", session_id=None, system_prompt="Sys", output_format="stream-json")
        self.assertIn("-p", cmd)
        self.assertIn("prompt", cmd)
        self.assertIn("--append-system-prompt", cmd)
        self.assertIn("Sys", cmd)

    def test_context_fraction(self):
        res = BackendResult(
            usage={"input_tokens": 100_000, "output_tokens": 20_000},
            model_usage={"model": {"contextWindow": 200_000}},
        )
        frac = self.backend.get_context_fraction(res)
        self.assertAlmostEqual(frac, 0.6, places=2)


if __name__ == "__main__":
    unittest.main()
