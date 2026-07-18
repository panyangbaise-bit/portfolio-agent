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
