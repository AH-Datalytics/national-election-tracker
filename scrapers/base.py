"""
National Election Tracker -- Abstract Base Scraper

All state scrapers inherit from StateScraper.  It provides:
  - SQLite connection helpers (WAL mode, foreign keys)
  - Import-run provenance (create / finish / quality checks)
  - Source-file logging with SHA-256 hashes
  - Pre-run DB backup
  - Idempotency check (skip already-imported elections)
"""

from abc import ABC, abstractmethod
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import time
from datetime import datetime, timezone

log = logging.getLogger(__name__)


class StateScraper(ABC):
    """Abstract base class for every state scraper."""

    def __init__(self, db_path: str, config: dict):
        self.db_path = db_path
        self.config = config
        self.state = config["state"]

    # ------------------------------------------------------------------
    # Abstract interface -- each state must implement
    # ------------------------------------------------------------------

    @abstractmethod
    def list_elections(self) -> list[dict]:
        """Return a list of election metadata dicts from the config / API."""
        ...

    @abstractmethod
    def fetch_election(self, election_id: str) -> dict:
        """Fetch and ingest a single election's data.  Returns summary dict."""
        ...

    # ------------------------------------------------------------------
    # Database helpers
    # ------------------------------------------------------------------

    def get_db(self) -> sqlite3.Connection:
        """Open a connection with WAL mode and foreign keys enabled."""
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------
    # Import-run provenance
    # ------------------------------------------------------------------

    def create_import_run(self, conn: sqlite3.Connection, election_key: str | None = None) -> int:
        """Insert a new import_runs row with status='running'. Returns the run id."""
        c = conn.execute(
            "INSERT INTO import_runs (state, election_key, started_at, status) VALUES (?, ?, ?, 'running')",
            (self.state, election_key, datetime.now(timezone.utc).isoformat()),
        )
        return c.lastrowid

    def log_source_file(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        url: str,
        data: bytes,
        filename: str | None = None,
    ) -> None:
        """Record a fetched file in source_files with its SHA-256 hash."""
        sha = hashlib.sha256(data).hexdigest()
        conn.execute(
            "INSERT INTO source_files (import_run_id, url, filename, sha256, size_bytes, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                url,
                filename or url.split("/")[-1],
                sha,
                len(data),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    def finish_import_run(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        status: str,
        record_counts: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Mark an import run as finished (success / failed)."""
        conn.execute(
            "UPDATE import_runs SET finished_at=?, status=?, record_counts=?, error_message=? WHERE id=?",
            (
                datetime.now(timezone.utc).isoformat(),
                status,
                json.dumps(record_counts) if record_counts else None,
                error,
                run_id,
            ),
        )

    def log_quality_check(
        self,
        conn: sqlite3.Connection,
        run_id: int,
        check_name: str,
        passed: bool,
        details: dict | None = None,
    ) -> None:
        """Record a data-quality check result."""
        conn.execute(
            "INSERT INTO data_quality_checks (import_run_id, check_name, passed, details) "
            "VALUES (?, ?, ?, ?)",
            (
                run_id,
                check_name,
                1 if passed else 0,
                json.dumps(details) if details else None,
            ),
        )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    def is_election_imported(self, conn: sqlite3.Connection, election_key: str) -> bool:
        """Return True if election_key already has a successful import run."""
        row = conn.execute(
            "SELECT id FROM import_runs WHERE election_key = ? AND status = 'success'",
            (election_key,),
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------
    # Backup
    # ------------------------------------------------------------------

    def backup_db(self) -> str:
        """Copy the database file to data/backups/ with a timestamp suffix."""
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = os.path.join(os.path.dirname(self.db_path), "backups")
        os.makedirs(backup_dir, exist_ok=True)
        dest = os.path.join(backup_dir, f"elections-{ts}.db")
        shutil.copy2(self.db_path, dest)
        log.info(f"Backup created: {dest}")
        return dest
