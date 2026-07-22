"""
Database migration helper — apply schema changes without data loss.
Import and call in config or app init before using models.

Usage:
    from db.migrate import migrate
    migrate(engine)
"""

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

MIGRATIONS = [
    # Each entry: (version, sql_statement)
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
]


def migrate(engine):
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

        for version, sql in MIGRATIONS:
            if version not in applied:
                logger.info(f"Applying migration: {version}")
                try:
                    conn.execute(text(sql))
                    conn.execute(text("INSERT INTO _migrations (version) VALUES (:v)"), {"v": version})
                    conn.commit()
                    logger.info(f"Migration {version} applied.")
                except Exception as e:
                    # Column may already exist — skip
                    logger.warning(f"Migration {version} skipped: {e}")
                    conn.rollback()
