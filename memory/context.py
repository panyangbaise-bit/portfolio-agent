"""Invocation-local link from a scheduler run to its agent sessions."""
from contextvars import ContextVar
current_run_id = ContextVar("portfolio_job_run_id", default=None)
