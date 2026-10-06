"""
Antigravity CLI (agy) backend implementation for Oracle.
Supports streaming NDJSON events, session resumption, tool execution,
and model selection.
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

log = logging.getLogger("oracle.backend.agy")

DEFAULT_MODEL = "gemini-3.8-flash-high"
DEFAULT_EFFORT = "high"


def _find_agy(custom_path: Optional[str] = None) -> str:
    if custom_path and Path(custom_path).exists():
        return custom_path
    candidates = [
        str(Path.home() / ".local/bin/agy"),
        "/usr/local/bin/agy",
        "/usr/bin/agy",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    found = shutil.which("agy")
    if found:
        return found
    raise RuntimeError("agy binary not found in PATH or standard locations")


class AgyBackend(BaseAIBackend):
    """Backend driven by the Antigravity CLI (`agy`)."""

    def __init__(
        self,
        model: Optional[str] = None,
        effort: Optional[str] = None,
        agy_path: Optional[str] = None,
        working_dir: Optional[str] = None,
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
        self.effort = effort or DEFAULT_EFFORT
        self.binary = _find_agy(agy_path)
        self.edit_interval = edit_interval

    @property
    def name(self) -> str:
        return f"agy ({self.model})"

    def _build_cmd(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        output_format: str = "stream-json",
    ) -> list[str]:
        cmd = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            output_format,
            "--dangerously-skip-permissions",
            "--add-dir",
            "/",
        ]
        if self.model:
            cmd.extend(["--model", self.model])
        if self.effort:
            cmd.extend(["--effort", self.effort])
        if session_id:
            cmd.extend(["--conversation", session_id])
        return cmd

    def _prepare_prompt(
        self,
        prompt: str,
        session_id: Optional[str],
        system_prompt: Optional[str],
    ) -> str:
        if not session_id and system_prompt:
            return (
                f"[SYSTEM INSTRUCTIONS]\n"
                f"{system_prompt}\n"
                f"[END SYSTEM INSTRUCTIONS]\n\n"
                f"{prompt}"
            )
        return prompt

    async def startup_test(self) -> BackendResult:
        """Run a fast test prompt without session ID to verify agy CLI works."""
        return await self.run_turn("reply with just the word: ready", session_id=None)

    async def run_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> BackendResult:
        full_prompt = self._prepare_prompt(prompt, session_id, system_prompt)
        cmd = self._build_cmd(full_prompt, session_id, output_format="json")

        log.info("agy json %s session=%s", "resume" if session_id else "new", session_id or "-")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.working_dir,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError(f"agy turn timed out after {self.timeout_seconds}s")

        stdout = stdout_bytes.decode().strip()
        stderr = stderr_bytes.decode().strip()

        if proc.returncode != 0:
            err_msg = stderr or stdout or f"exit code {proc.returncode}"
            log.error("agy json failed (exit %d): %s", proc.returncode, err_msg[:400])
            if session_id and ("not found" in err_msg.lower() or "subscriber fell behind" in err_msg.lower()):
                log.warning("session %s unusable in agy (%s), retrying fresh", session_id, err_msg[:200])
                return await self.run_turn(prompt, session_id=None, system_prompt=system_prompt)
            return BackendResult(
                result="",
                session_id=session_id or "",
                success=False,
                error=err_msg,
            )

        try:
            data = json.loads(stdout)
            return BackendResult(
                result=data.get("response", "").strip(),
                session_id=data.get("conversation_id", session_id or ""),
                usage=data.get("usage", {}),
                raw_data=data,
                success=data.get("status") == "SUCCESS",
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
        _is_retry: bool = False,
    ) -> BackendResult:
        full_prompt = self._prepare_prompt(prompt, session_id, system_prompt)
        cmd = self._build_cmd(full_prompt, session_id, output_format="stream-json")

        log.info("agy stream-%s session=%s", "resume" if session_id else "new", session_id or "-")

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
            "raw_result": {},
            "error": None,
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

                etype = ev.get("event", "")
                if etype == "init":
                    cid = ev.get("conversation_id", "")
                    if cid:
                        state["session_id"] = cid

                elif etype == "step_update":
                    update = ev.get("step_update", {})
                    cid = update.get("conversation_id", "")
                    if cid:
                        state["session_id"] = cid

                    stype = update.get("step_type", "")
                    sstate = update.get("state", "")

                    if stype == "agent_response":
                        delta = update.get("text_delta", "")
                        if delta:
                            state["text"] += delta
                            state["activity"] = "generating"
                            if on_text_delta:
                                await on_text_delta(delta)
                        if "usage" in update:
                            state["usage"] = update["usage"]

                    elif stype == "tool":
                        tool_name = (
                            update.get("tool_name")
                            or update.get("tool_info", {}).get("name")
                            or "tool"
                        )
                        if sstate == "ACTIVE":
                            state["activity"] = f"tool:{tool_name}"
                        elif sstate == "DONE":
                            state["activity"] = "thinking"
                        if on_activity:
                            await on_activity(state["activity"])

                    elif stype == "system_message":
                        if on_activity:
                            await on_activity("thinking")

                elif etype == "result":
                    res = ev.get("result", {})
                    state["session_id"] = res.get("conversation_id", state["session_id"])
                    if not state["text"]:
                        state["text"] = res.get("response", "")
                    state["usage"] = res.get("usage", state["usage"])
                    state["raw_result"] = res
                    state["activity"] = "done"

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
            raise RuntimeError(f"agy stream timed out after {self.timeout_seconds}s")

        stderr = ""
        if proc.stderr:
            stderr = (await proc.stderr.read()).decode().strip()

        if proc.returncode != 0:
            log.error("agy stream failed (exit %d): %s", proc.returncode, stderr[:400])
            err_lower = stderr.lower()
            if session_id and ("not found" in err_lower or "no conversation" in err_lower):
                log.warning("agy session %s not found, retrying fresh", session_id)
                return await self.stream_turn(
                    prompt=prompt,
                    session_id=None,
                    system_prompt=system_prompt,
                    on_text_delta=on_text_delta,
                    on_activity=on_activity,
                    periodic_status_callback=periodic_status_callback,
                )
            is_transient = any(term in err_lower for term in (
                "connection to the agent was interrupted",
                "subscriber fell behind updates",
                "broken pipe",
                "connection reset",
            ))
            if session_id and is_transient and not _is_retry:
                log.warning("Transient agy connection error on session %s, retrying once in 2s...", session_id)
                await asyncio.sleep(2)
                return await self.stream_turn(
                    prompt=prompt,
                    session_id=session_id,
                    system_prompt=system_prompt,
                    on_text_delta=on_text_delta,
                    on_activity=on_activity,
                    periodic_status_callback=periodic_status_callback,
                    _is_retry=True,
                )
            if session_id and is_transient and _is_retry:
                log.warning("agy session %s repeatedly failed with stream error (%s), falling back to fresh session", session_id, stderr[:200])
                return await self.stream_turn(
                    prompt=prompt,
                    session_id=None,
                    system_prompt=system_prompt,
                    on_text_delta=on_text_delta,
                    on_activity=on_activity,
                    periodic_status_callback=periodic_status_callback,
                    _is_retry=False,
                )
            raise RuntimeError(f"agy exit {proc.returncode}: {stderr[:400]}")

        final_text = state["text"].rstrip()
        return BackendResult(
            result=final_text,
            session_id=state["session_id"],
            usage=state["usage"],
            raw_data=state["raw_result"],
            success=True,
        )

    def get_context_fraction(self, result: BackendResult | dict) -> float:
        session_id = None
        if isinstance(result, BackendResult):
            session_id = result.session_id
        elif isinstance(result, dict):
            session_id = result.get("session_id") or result.get("conversation_id")

        model_str = (self.model or "").lower()
        if "gemini" in model_str:
            context_window = 1_000_000
        elif "claude" in model_str:
            context_window = 200_000
        elif "gpt-oss" in model_str:
            context_window = 128_000
        else:
            context_window = 1_000_000

        # Primary: Measure active transcript size on disk (bytes // 4 ~= tokens)
        if session_id:
            tpath = Path.home() / f".gemini/antigravity-cli/brain/{session_id}/.system_generated/logs/transcript.jsonl"
            if tpath.exists():
                try:
                    approx_tokens = tpath.stat().st_size // 4
                    return approx_tokens / context_window if context_window else 0.0
                except OSError:
                    pass

        # Fallback: single-turn input tokens (never cumulative total_tokens)
        usage = result.get("usage", {}) if isinstance(result, (BackendResult, dict)) else {}
        input_tokens = usage.get("input_tokens", 0)
        return input_tokens / context_window if context_window else 0.0

    def _fallback_transcript_summary(self, session_id: str, max_chars: int = 12000) -> str:
        """Extract recent conversation turns from transcript.jsonl as context summary fallback."""
        tpath = Path.home() / f".gemini/antigravity-cli/brain/{session_id}/.system_generated/logs/transcript.jsonl"
        if not tpath.exists():
            return ""
        turns = []
        try:
            with open(tpath, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        step = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    source = step.get("source")
                    stype = step.get("type")
                    content = step.get("content", "")
                    if not content or not isinstance(content, str):
                        continue
                    content = re.sub(r"\[SYSTEM INSTRUCTIONS\].*?\[END SYSTEM INSTRUCTIONS\]", "", content, flags=re.DOTALL)
                    content = re.sub(r"<USER_REQUEST>", "", content)
                    content = re.sub(r"</USER_REQUEST>", "", content)
                    content = content.strip()
                    if not content:
                        continue
                    if source == "USER_EXPLICIT" or stype == "USER_INPUT":
                        turns.append(f"User: {content[:1000]}")
                    elif source == "MODEL" and stype == "PLANNER_RESPONSE":
                        turns.append(f"Oracle: {content[:1000]}")
        except Exception as e:
            log.warning("Error reading transcript for compaction fallback: %s", e)
            return ""

        if not turns:
            return ""
        recent = turns[-15:]
        summary_text = "\n\n".join(recent)
        if len(summary_text) > max_chars:
            summary_text = summary_text[-max_chars:]
        return f"Recent conversation excerpt:\n{summary_text}"

    async def compact(
        self, session_id: str, system_prompt: Optional[str] = None
    ) -> Optional[BackendResult]:
        """
        Compact an agy session:
        1. Request a high-density summary of active state and decisions from the current session.
        2. Fall back to transcript extraction if session is already unresponsive/stalled.
        3. Seed a fresh session (session_id=None) with the summary context.
        4. Return the new session's BackendResult.
        """
        log.info("Starting agy session compaction for %s", session_id[:8])
        summary = ""
        summary_prompt = (
            "Please provide a concise, high-density summary of our conversation so far for seamless context transfer into a fresh session. "
            "Cover: active tasks and their state, key decisions made, user preferences or feedback expressed, and any pending items or questions. "
            "Output only the concise summary without conversational filler or greetings."
        )

        try:
            res = await self.run_turn(summary_prompt, session_id=session_id)
            if res and res.success and res.result:
                summary = res.result.strip()
        except Exception as e:
            log.warning("Failed to get conversational summary from session %s: %s", session_id[:8], e)

        if not summary:
            log.info("Falling back to transcript extraction for session %s", session_id[:8])
            summary = self._fallback_transcript_summary(session_id)

        init_prompt = (
            "[PRIOR CONVERSATION CONTEXT SUMMARY]\n"
            f"{summary or 'Previous session was compacted. Ready for new instructions.'}\n\n"
            "[DIRECTIVE]\n"
            "Acknowledge receipt in one short sentence (e.g. 'Prior context loaded. Ready to continue.') to initialize this fresh session."
        )

        try:
            new_res = await self.run_turn(init_prompt, session_id=None, system_prompt=system_prompt)
            if new_res and new_res.session_id:
                log.info("Compacted session %s into fresh session %s", session_id[:8], new_res.session_id[:8])
                return new_res
        except Exception as e:
            log.error("Failed to initialize new session during compaction: %s", e)

        return None
