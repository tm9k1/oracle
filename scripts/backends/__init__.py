"""
Oracle modular AI backend registry and factory.
"""
from typing import Any, Optional, Type
from backends.base import BackendResult, BaseAIBackend
from backends.agy import AgyBackend
from backends.claude_cli import ClaudeCliBackend

BACKENDS: dict[str, Type[BaseAIBackend]] = {
    "agy": AgyBackend,
    "antigravity": AgyBackend,
    "claude": ClaudeCliBackend,
    "claude_cli": ClaudeCliBackend,
    "claude-cli": ClaudeCliBackend,
}


def register_backend(name: str, cls: Type[BaseAIBackend]):
    BACKENDS[name.lower()] = cls


def get_backend(
    backend_type: Optional[str] = None,
    model: Optional[str] = None,
    **kwargs: Any,
) -> BaseAIBackend:
    name = (backend_type or "agy").lower().strip()
    if name not in BACKENDS:
        available = ", ".join(sorted(set(BACKENDS.keys())))
        raise ValueError(
            f"Unknown AI backend '{backend_type}'. Available: {available}"
        )
    backend_cls = BACKENDS[name]
    return backend_cls(model=model, **kwargs)


__all__ = [
    "BackendResult",
    "BaseAIBackend",
    "AgyBackend",
    "ClaudeCliBackend",
    "register_backend",
    "get_backend",
    "BACKENDS",
]
