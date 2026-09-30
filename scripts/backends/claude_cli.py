"""
Claude CLI backend implementation for Oracle.
Supports streaming Claude CLI NDJSON events, session resumption, and mirroring.
"""
import asyncio
import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from backends.base import BackendResult, BaseAIBackend

log = logging.getLogger("oracle.backend.claude_cli")

DEFAULT_MODEL = "sonnet"

_HOME_BUCKET = Path("/home/tm9k1/.claude/projects/-home-tm9k1")
_VSCODE_BUCKET = Path("/home/tm9k1/.claude/projects/-home-tm9k1-docker-compose-files")


def _find_claude(custom_path: Optional[str] = None) -> str:
    if custom_path and Path(custom_path).exists():
        return custom_path
    candidates = [
        "/home/tm9k1/.local/bin/claude",
        "/usr/local/bin/claude",
        "/usr/bin/claude",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    exts = sorted(
        Path("/home/tm9k1/.vscode-server/extensions").glob(
            "anthropic.claude-code-*/resources/native-binary/claude"
        )
    )
    if exts:
        return str(exts[-1])
    found = shutil.which("claude")
    if found:
        return found
    raise RuntimeError("claude binary not found in PATH or standard locations")


class ClaudeCliBackend(BaseAIBackend):
    """Backend driven by Anthropic Claude Code CLI (`claude`)."""

    def __init__(
        self,
        model: Optional[str] = None,
        claude_path: Optional[str] = None,
        working_dir: str = "/home/tm9k1",
        timeout_seconds: int = 1500,
        edit_interval: float = 5.0,
        **kwargs: Any,
    ):
        super().__init__(
            model=model or DEFAULT_MODEL,
            working_dir=working_dir,
            timeout_seconds=timeout_seconds,
            **kwargs,
        )
        self.binary = _find_claude(claude_path)
        self.edit_interval = edit_interval

    @property
    def name(self) -> str:
        return f"claude-cli ({self.model})"

    def _mirror_session(self, session_id: str):
        if not session_id:
            return
        for suffix in ("", ".jsonl"):
            src = _HOME_BUCKET / f"{session_id}{suffix}"
            dst = _VSCODE_BUCKET / f"{session_id}{suffix}"
            if src.exists() and not dst.exists():
                try:
                    dst.symlink_to(src)
                except Exception:
                    pass

    def mirror_session(self, session_id: str) -> None:
        self._mirror_session(session_id)

    def _build_cmd(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        output_format: str = "stream-json",
    ) -> list[str]:
        cmd = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            output_format,
            "--model",
            self.model or DEFAULT_MODEL,
            "--dangerously-skip-permissions",
            "--add-dir",
            "/",
        ]
        if output_format == "stream-json":
            cmd.append("--verbose")

        if session_id:
            cmd.extend(["--resume", session_id])
        elif system_prompt:
            cmd.extend(["--append-system-prompt", system_prompt])
        return cmd

    async def startup_test(self) -> BackendResult:
        return await self.run_turn("reply with just the word: ready", session_id=None)

    async def run_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> BackendResult:
        cmd = self._build_cmd(prompt, session_id, system_prompt, output_format="json")
        log.info("claude json %s session=%s", "resume" if session_id else "new", session_id or "-")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=min(self.timeout_seconds, 600),
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"claude turn timed out after {self.timeout_seconds}s")

        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if proc.returncode != 0:
            err_msg = stderr or stdout or f"exit code {proc.returncode}"
            log.error("claude failed (exit %d): %s", proc.returncode, err_msg[:400])
            if session_id and "no conversation found" in err_msg.lower():
                log.warning("session %s not found in claude, retrying fresh", session_id)
                return await self.run_turn(prompt, session_id=None, system_prompt=system_prompt)
            return BackendResult(
                result="",
                session_id=session_id or "",
                success=False,
                error=err_msg,
            )

        try:
            data = json.loads(stdout)
            sid = data.get("session_id", session_id or "")
            self._mirror_session(sid)
            return BackendResult(
                result=data.get("result", "").strip(),
                session_id=sid,
                usage=data.get("usage", {}),
                model_usage=data.get("modelUsage", {}),
                raw_data=data,
                success=True,
            )
        except json.JSONDecodeError:
            return BackendResult(
                result=stdout,
                session_id=session_id or "",
                raw_data={"raw_stdout": stdout},
                success=True,
            )

    async def stream_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        on_text_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        on_activity: Optional[Callable[[str], Awaitable[None]]] = None,
        periodic_status_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> BackendResult:
        cmd = self._build_cmd(prompt, session_id, system_prompt, output_format="stream-json")
        log.info("claude stream-%s session=%s", "resume" if session_id else "new", session_id or "-")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
        )

        state = {
            "text": "",
            "activity": "thinking",
            "session_id": session_id or "",
            "done": False,
            "usage": {},
            "model_usage": {},
            "raw_result": {},
        }

        async def periodic_updater():
            while not state["done"]:
                await asyncio.sleep(self.edit_interval)
                if state["done"]:
                    break
                if periodic_status_callback and state["text"]:
                    try:
                        await periodic_status_callback(state["text"], state["activity"])
                    except Exception as e:
                        log.debug("periodic updater callback error: %s", e)

        async def event_reader():
            if not proc.stdout:
                return
            async for raw in proc.stdout:
                line = raw.decode().strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue

                etype = ev.get("type", "")

                if etype == "assistant":
                    for block in ev.get("message", {}).get("content", []):
                        btype = block.get("type", "")
                        if btype == "text":
                            new = block.get("text", "")
                            if new:
                                if state["text"] and not state["text"].endswith("\n"):
                                    state["text"] += "\n"
                                state["text"] += new
                                state["activity"] = "generating"
                                if on_text_delta:
                                    await on_text_delta(new)
                        elif btype == "tool_use":
                            tool_name = block.get("name", "tool")
                            state["activity"] = f"tool:{tool_name}"
                            if on_activity:
                                await on_activity(state["activity"])

                elif etype == "user":
                    if state["activity"].startswith("tool:"):
                        state["activity"] = "thinking"
                        if on_activity:
                            await on_activity("thinking")

                elif etype == "result":
                    state["session_id"] = ev.get("session_id", state["session_id"])
                    if not state["text"]:
                        state["text"] = ev.get("result", "")
                    state["activity"] = "done"
                    state["usage"] = ev.get("usage", {})
                    state["model_usage"] = ev.get("modelUsage", {})
                    state["raw_result"] = ev

        updater = asyncio.create_task(periodic_updater())
        timed_out = False
        try:
            await asyncio.wait_for(event_reader(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            proc.kill()
        finally:
            state["done"] = True
            updater.cancel()

        await proc.wait()

        if timed_out:
            raise RuntimeError(f"claude stream timed out after {self.timeout_seconds}s")

        stderr = ""
        if proc.stderr:
            stderr = (await proc.stderr.read()).decode().strip()

        if proc.returncode != 0:
            log.error("claude stream failed (exit %d): %s", proc.returncode, stderr[:400])
            if session_id and "no conversation found" in stderr.lower():
                log.warning("claude session %s not found, retrying fresh", session_id)
                return await self.stream_turn(
                    prompt=prompt,
                    session_id=None,
                    system_prompt=system_prompt,
                    on_text_delta=on_text_delta,
                    on_activity=on_activity,
                    periodic_status_callback=periodic_status_callback,
                )
            raise RuntimeError(f"claude exit {proc.returncode}: {stderr[:400]}")

        self._mirror_session(state["session_id"])
        return BackendResult(
            result=state["text"].rstrip(),
            session_id=state["session_id"],
            usage=state["usage"],
            model_usage=state["model_usage"],
            raw_data=state["raw_result"],
            success=True,
        )

    def get_context_fraction(self, result: BackendResult | dict) -> float:
        usage = result.get("usage", {}) if isinstance(result, (BackendResult, dict)) else {}
        model_usage = result.get("model_usage", {}) if isinstance(result, (BackendResult, dict)) else {}
        tokens_used = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        context_window = 200_000
        for m in model_usage.values():
            if isinstance(m, dict) and "contextWindow" in m:
                context_window = m["contextWindow"]
                break
        return tokens_used / context_window if context_window else 0.0

    async def compact(self, session_id: str) -> Optional[BackendResult]:
        return await self.run_turn("/compact", session_id=session_id)
