"""Normalize provider failures into tool-safe payloads."""

from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")


def error_payload(exc: BaseException, **extra: Any) -> dict:
    payload = {
        "error": type(exc).__name__,
        "message": str(exc) or type(exc).__name__,
    }
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload


def call_or_degrade(
    fn: Callable[..., T],
    *args: Any,
    empty: Optional[T] = None,
    extra: Optional[dict] = None,
    **kwargs: Any,
) -> Any:
    """Run a provider call; return ``empty`` or an error dict on failure."""
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        if empty is not None:
            return empty
        return error_payload(exc, **(extra or {}))
