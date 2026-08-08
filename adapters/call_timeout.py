"""Wall-clock timeouts that do not block on hung worker threads."""

from concurrent.futures import TimeoutError as FuturesTimeout
from typing import Any, Callable, TypeVar

try:
    from langsmith.utils import ContextThreadPoolExecutor as _PoolExecutor
except ImportError:  # pragma: no cover
    from concurrent.futures import ThreadPoolExecutor as _PoolExecutor

T = TypeVar("T")


def run_with_timeout(
    fn: Callable[..., T],
    timeout: float,
    *args: Any,
    default: Any = None,
    **kwargs: Any,
) -> Any:
    """Run ``fn(*args, **kwargs)`` with a deadline; abandon the worker on timeout.

    Uses ``shutdown(wait=False)`` so a hung HTTP/akshare call cannot stall the
    caller after the deadline (stdlib ``with ThreadPoolExecutor`` waits).
    """
    pool = _PoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout)
        except FuturesTimeout:
            return default
        except Exception:
            # Treat provider errors like timeouts for degrade-friendly callers.
            return default
    finally:
        pool.shutdown(wait=False)


def run_with_timeout_or_flag(
    fn: Callable[..., T],
    timeout: float,
    *args: Any,
    **kwargs: Any,
):
    """Like ``run_with_timeout`` but returns ``(value, timed_out)``.

    Exceptions from ``fn`` propagate (only wall-clock timeout sets the flag).
    """
    pool = _PoolExecutor(max_workers=1)
    try:
        future = pool.submit(fn, *args, **kwargs)
        try:
            return future.result(timeout=timeout), False
        except FuturesTimeout:
            return None, True
    finally:
        pool.shutdown(wait=False)
