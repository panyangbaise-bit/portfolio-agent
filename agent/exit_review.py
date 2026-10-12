"""Background review after a holding is sold to zero."""

import logging
import threading

logger = logging.getLogger(__name__)


def schedule_exit_analysis(holding_id: int, txn_id: int) -> None:
    """Run the exit review off the request thread so the trade form returns."""
    thread = threading.Thread(
        target=_run_guarded,
        args=(holding_id, txn_id),
        daemon=True,
        name=f"exit-analysis-{holding_id}",
    )
    thread.start()


def _run_guarded(holding_id: int, txn_id: int) -> None:
    from agent.core import run_exit_analysis
    from notifier.telegram import notify
    from scheduler.jobs import _finish_job_run, _start_job_run

    run_id = _start_job_run("exit_analysis", "清仓分析")
    try:
        text = run_exit_analysis(holding_id, txn_id)
        try:
            notify(f"📤 清仓分析\n\n{text}")
        except Exception as exc:
            logger.warning("Exit analysis notify failed: %s", exc)
        _finish_job_run(run_id, "completed", (text or ""))
    except Exception as exc:
        logger.error("Exit analysis failed: %s", exc)
        _finish_job_run(run_id, "failed", str(exc))
