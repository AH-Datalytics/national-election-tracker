"""
Database connection management for the National Election Tracker API.

Provides a read-only singleton connection for API use. Scrapers write to
the DB independently; the API never writes.
"""

import os
import sqlite3

DB_PATH = os.environ.get(
    "ELECTIONS_DB_PATH",
    os.path.join(os.path.dirname(__file__), "..", "data", "elections.db"),
)


def get_db() -> sqlite3.Connection:
    """Create a new database connection with optimal read settings."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-64000")  # 64 MB cache
    conn.execute("PRAGMA query_only=ON")
    return conn


# Singleton for read-only API use
_db: sqlite3.Connection | None = None


def get_readonly_db() -> sqlite3.Connection:
    """Return the singleton read-only connection, creating it on first call."""
    global _db
    if _db is None:
        _db = get_db()
    return _db
