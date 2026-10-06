"""
Base interface and dataclasses for modular Oracle AI backends.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional


@dataclass
class BackendResult:
    result: str = ""
    session_id: str = ""
    usage: dict[str, Any] = field(default_factory=dict)
    model_usage: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: Optional[str] = None

    def __getitem__(self, item: str) -> Any:
        """Dictionary-like access for backwards compatibility."""
        if hasattr(self, item):
            return getattr(self, item)
        if item in self.raw_data:
            return self.raw_data[item]
        raise KeyError(item)

    def get(self, item: str, default: Any = None) -> Any:
        """Dictionary-like get for backwards compatibility."""
        if hasattr(self, item):
            val = getattr(self, item)
            return val if val is not None else default
        return self.raw_data.get(item, default)


class BaseAIBackend(ABC):
    """Abstract base class for all AI backends (agy, claude-cli, api, etc.)."""

    def __init__(
        self,
        model: Optional[str] = None,
        working_dir: Optional[str] = None,
        timeout_seconds: int = 1500,
        **kwargs: Any,
    ):
        self.model = model
        self.working_dir = working_dir or str(Path.home())
        self.timeout_seconds = timeout_seconds
        self.extra_config = kwargs

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable backend identifier."""
        raise NotImplementedError

    @abstractmethod
    async def startup_test(self) -> BackendResult:
        """Quick blocking/async test on bot startup to verify backend health."""
        raise NotImplementedError

    @abstractmethod
    async def run_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
    ) -> BackendResult:
        """Run a non-streaming single turn."""
        raise NotImplementedError

    @abstractmethod
    async def stream_turn(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        on_text_delta: Optional[Callable[[str], Awaitable[None]]] = None,
        on_activity: Optional[Callable[[str], Awaitable[None]]] = None,
        periodic_status_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> BackendResult:
        """
        Run a streaming turn.
        - `on_text_delta`: called whenever new text content arrives
        - `on_activity`: called when agent activity changes (e.g. 'thinking', 'tool:run_command', 'generating')
        - `periodic_status_callback`: called periodically with (accumulated_text, current_activity)
        """
        raise NotImplementedError

    def get_context_fraction(self, result: BackendResult | dict) -> float:
        """Calculate fraction of context window used (0.0 to 1.0)."""
        return 0.0

    async def compact(
        self, session_id: str, system_prompt: Optional[str] = None
    ) -> Optional[BackendResult]:
        """Compact/summarize session if supported by the backend."""
        return None

    def mirror_session(self, session_id: str) -> None:
        """Mirror session transcripts to secondary project directories if needed."""
        pass
