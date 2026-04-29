"""Health check endpoint."""

import os

from fastapi import APIRouter

from api.db import DB_PATH, get_readonly_db

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health_check():
    """
    API health check.

    Returns DB size, available states, election count, and last import time.
    """
    db = get_readonly_db()

    # DB file size
    try:
        db_size_mb = round(os.path.getsize(DB_PATH) / (1024 * 1024), 2)
    except OSError:
        db_size_mb = 0.0

    # States with data
    state_rows = db.execute("SELECT code FROM states ORDER BY code").fetchall()
    state_codes = [r["code"] for r in state_rows]

    # Election count
    election_count = db.execute("SELECT COUNT(*) AS cnt FROM elections").fetchone()["cnt"]

    # Last import
    last_import_row = db.execute(
        "SELECT finished_at FROM import_runs WHERE status IN ('success', 'success_with_warnings') "
        "ORDER BY finished_at DESC LIMIT 1"
    ).fetchone()
    last_import = last_import_row["finished_at"] if last_import_row else None

    return {
        "status": "ok",
        "db_size_mb": db_size_mb,
        "states": state_codes,
        "election_count": election_count,
        "last_import": last_import,
    }
