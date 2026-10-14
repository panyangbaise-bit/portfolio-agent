"""
Database migration helper — apply schema changes without data loss.
Import and call in config or app init before using models.

Usage:
    from db.migrate import migrate
    migrate(engine)
"""

import json
import logging
from typing import Callable, Union

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine

logger = logging.getLogger(__name__)

MigrationStep = Union[str, Callable[[Connection], None]]


def _backfill_recommendation_session_ids(conn: Connection) -> None:
    """Relink orphan recommendations (session_id=0) using save_recommendation tool logs.

    Before InjectedState, the LLM never passed session_id and every saved
    recommendation defaulted to 0 — so Jobs detail could never show them.
    Tool-call rows already store the correct agent session_id + recommendation_id.
    """
    rows = conn.execute(
        text(
            """
            SELECT session_id, result_summary
            FROM agent_tool_calls
            WHERE tool_name = 'save_recommendation'
              AND session_id > 0
              AND result_summary IS NOT NULL
            """
        )
    ).fetchall()

    updates = []  # (session_id, recommendation_id)
    for session_id, result_summary in rows:
        try:
            payload = json.loads(result_summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        if isinstance(payload, dict) and payload.get("status") == "saved":
            rec_id = payload.get("recommendation_id")
            if isinstance(rec_id, int) and rec_id > 0:
                updates.append((session_id, rec_id))
            continue

        if isinstance(payload, dict) and payload.get("batch"):
            for item in payload.get("results") or []:
                if not isinstance(item, dict) or item.get("status") != "saved":
                    continue
                rec_id = item.get("recommendation_id")
                if isinstance(rec_id, int) and rec_id > 0:
                    updates.append((session_id, rec_id))

    for session_id, rec_id in updates:
        conn.execute(
            text(
                """
                UPDATE recommendations
                SET session_id = :sid
                WHERE id = :rid AND (session_id = 0 OR session_id IS NULL)
                """
            ),
            {"sid": session_id, "rid": rec_id},
        )


def _backfill_opening_buys(conn: Connection) -> None:
    """Give open holdings with an empty ledger an opening buy at current cost.

    Positions that already have sells are left alone: their residual cost is
    not the original purchase price, so inventing a buy would distort return.
    """
    rows = conn.execute(
        text(
            """
            SELECT h.id, h.shares, h.cost_basis, h.created_at
            FROM holdings h
            WHERE lower(coalesce(h.status, 'open')) != 'closed'
              AND coalesce(h.shares, 0) > 0
              AND coalesce(h.cost_basis, 0) > 0
              AND NOT EXISTS (
                    SELECT 1 FROM transactions t WHERE t.holding_id = h.id
              )
            """
        )
    ).fetchall()
    for holding_id, shares, cost_basis, created_at in rows:
        conn.execute(
            text(
                """
                INSERT INTO transactions
                    (holding_id, action, shares, price, date, notes)
                VALUES
                    (:hid, 'buy', :shares, :price, coalesce(:date, CURRENT_TIMESTAMP), 'opening')
                """
            ),
            {
                "hid": holding_id,
                "shares": shares,
                "price": cost_basis,
                "date": created_at,
            },
        )


def _create_memory_tables(conn):
    from db.models import ConversationMessage, MemoryDocument, MemoryChunk, MemoryCheckpoint, MemoryEmbedding
    for model in (ConversationMessage, MemoryDocument, MemoryChunk, MemoryCheckpoint, MemoryEmbedding):
        model.__table__.create(conn, checkfirst=True)
    conn.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(tokens)"))


MIGRATIONS = [
    # Each entry: (version, sql_statement | callable)
    # Version 1: add name column to holdings (added 2026-07-18)
    (
        "v1_add_holdings_name",
        "ALTER TABLE holdings ADD COLUMN name VARCHAR(100)",
    ),
    (
        "v2_agent_sessions_job_market",
        "ALTER TABLE agent_sessions ADD COLUMN job_id VARCHAR(40)",
    ),
    (
        "v2b_agent_sessions_market",
        "ALTER TABLE agent_sessions ADD COLUMN market VARCHAR(10)",
    ),
    (
        "v2c_agent_sessions_summary",
        "ALTER TABLE agent_sessions ADD COLUMN summary TEXT",
    ),
    (
        "v3_create_job_runs",
        """
        CREATE TABLE IF NOT EXISTS job_runs (
            id INTEGER PRIMARY KEY,
            job_id VARCHAR(40) NOT NULL,
            job_name VARCHAR(100) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'running',
            details TEXT,
            started_at DATETIME NOT NULL,
            ended_at DATETIME
        )
        """,
    ),
    (
        "v3b_job_runs_index",
        "CREATE INDEX IF NOT EXISTS ix_job_runs_job_started ON job_runs (job_id, started_at)",
    ),
    (
        "v4_holdings_status",
        "ALTER TABLE holdings ADD COLUMN status VARCHAR(20) DEFAULT 'open'",
    ),
    (
        "v5_create_watchlist",
        """
        CREATE TABLE IF NOT EXISTS watchlist_items (
            id INTEGER PRIMARY KEY,
            ticker VARCHAR(20) NOT NULL,
            name VARCHAR(100),
            market VARCHAR(10) NOT NULL,
            watch_reason TEXT,
            target_price_low FLOAT,
            target_price_high FLOAT,
            status VARCHAR(20) NOT NULL DEFAULT 'watching',
            priority VARCHAR(10) NOT NULL DEFAULT 'medium',
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
        """,
    ),
    (
        "v5b_watchlist_indexes",
        "CREATE INDEX IF NOT EXISTS ix_watchlist_status ON watchlist_items (status)",
    ),
    (
        "v5c_watchlist_ticker_index",
        "CREATE INDEX IF NOT EXISTS ix_watchlist_ticker ON watchlist_items (ticker)",
    ),
    (
        "v6_backfill_recommendation_session_ids",
        _backfill_recommendation_session_ids,
    ),
    (
        "v7_backfill_opening_buys",
        _backfill_opening_buys,
    ),
    (
        "v8_trading_discipline",
        """CREATE TABLE IF NOT EXISTS trading_discipline (
            id INTEGER PRIMARY KEY,
            content TEXT NOT NULL DEFAULT '',
            updated_at DATETIME NOT NULL
        )""",
    ),
    ("v9_memory", _create_memory_tables),
    ("v9b_session_run", "ALTER TABLE agent_sessions ADD COLUMN job_run_id INTEGER REFERENCES job_runs(id)"),
]


def migrate(engine: Engine):
    """Apply any pending migrations."""
    with engine.connect() as conn:
        # Ensure migration tracking table exists
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS _migrations (version TEXT PRIMARY KEY, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
        ))
        conn.commit()

        applied = {
            row[0]
            for row in conn.execute(text("SELECT version FROM _migrations")).fetchall()
        }

        for version, step in MIGRATIONS:
            if version not in applied:
                logger.info(f"Applying migration: {version}")
                try:
                    if callable(step):
                        step(conn)
                    else:
                        conn.execute(text(step))
                    conn.execute(text("INSERT INTO _migrations (version) VALUES (:v)"), {"v": version})
                    conn.commit()
                    logger.info(f"Migration {version} applied.")
                except Exception as e:
                    # Column may already exist — skip
                    logger.warning(f"Migration {version} skipped: {e}")
                    conn.rollback()
