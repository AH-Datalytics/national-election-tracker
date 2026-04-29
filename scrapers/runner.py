"""
National Election Tracker -- Runner CLI

Unified CLI for all scraping operations: historical imports, live polling,
database maintenance, and status reporting.

Usage:
    python scrapers/runner.py scrape --state IN                              # all IN archives
    python scrapers/runner.py scrape --state IN --election 2024General       # single election
    python scrapers/runner.py scrape --state IN --workers 3 --ramp           # multi-worker ramp-up
    python scrapers/runner.py scrape --all --workers 2                       # all states, 2 workers
    python scrapers/runner.py live --state OH                                # poll OH live
    python scrapers/runner.py live --state IN                                # poll IN live
    python scrapers/runner.py import-la                                      # one-time LA import
    python scrapers/runner.py import-la --source /path/to/la.db             # custom source
    python scrapers/runner.py backup                                         # snapshot DB
    python scrapers/runner.py status                                         # show import_runs summary
"""

import argparse
import importlib
import json
import logging
import os
import signal
import shutil
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "scrapers"))

from schema import DEFAULT_DB_PATH

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scraper registry -- lazily loaded via importlib
# ---------------------------------------------------------------------------

# Each entry: state_code -> (module_name, class_name, config_filename)
# Module names are bare (not package-qualified) since scrapers/ is on sys.path.
SCRAPERS = {
    "IN": ("indiana", "IndianaScraper", "indiana.yaml"),
    "OH": ("ohio_live", "OhioLiveScraper", "ohio.yaml"),
}


def get_scraper_class(state: str):
    """Lazily import and return the scraper class for a given state code."""
    if state not in SCRAPERS:
        available = sorted(SCRAPERS.keys())
        raise ValueError(
            f"No scraper registered for state '{state}'. "
            f"Available: {available}"
        )
    module_path, class_name, _config = SCRAPERS[state]
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def load_config(state: str) -> dict:
    """Load the YAML config for a state from scrapers/configs/."""
    import yaml

    # Look up config filename from registry; fall back to {state}.yaml
    if state in SCRAPERS:
        _mod, _cls, config_filename = SCRAPERS[state]
    else:
        config_filename = f"{state.lower()}.yaml"

    config_path = os.path.join(
        REPO_ROOT, "scrapers", "configs", config_filename
    )
    if not os.path.exists(config_path):
        raise FileNotFoundError(
            f"Config file not found: {config_path}\n"
            f"  Create scrapers/configs/{config_filename} first."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Adaptive Worker Pool
# ---------------------------------------------------------------------------


class AdaptiveWorkerPool:
    """
    Manages concurrent scraper execution with adaptive scaling.

    Starts slow, ramps up on consecutive successes, backs off on errors,
    and pauses between batches. Inspired by SwimPulse's scraper patterns.
    """

    def __init__(
        self,
        max_workers: int = 4,
        initial_workers: int = 1,
        ramp_up: bool = True,
        ramp_after: int = 5,
        batch_size: int = 3,
        batch_pause: int = 10,
    ):
        self.max_workers = max_workers
        self.active_workers = initial_workers
        self.ramp_up = ramp_up
        self.ramp_after = ramp_after
        self.batch_size = batch_size
        self.batch_pause = batch_pause
        self.consecutive_successes = 0
        self.consecutive_errors = 0
        self.pause_until = 0
        self.total_processed = 0
        self.total_errors = 0
        self._lock = threading.Lock()

    def on_success(self):
        """Record a successful operation and maybe ramp up workers."""
        with self._lock:
            self.consecutive_successes += 1
            self.consecutive_errors = 0
            self.total_processed += 1
            if self.ramp_up and self.consecutive_successes >= self.ramp_after:
                if self.active_workers < self.max_workers:
                    self.active_workers += 1
                    log.info(f"Ramping up to {self.active_workers} workers")
                self.consecutive_successes = 0

    def on_error(self, status_code: int | None = None):
        """Record an error and maybe back off."""
        with self._lock:
            self.consecutive_successes = 0
            self.consecutive_errors += 1
            self.total_errors += 1
            if status_code == 429 or self.consecutive_errors >= 3:
                self.active_workers = max(1, self.active_workers - 1)
                pause_seconds = min(60 * self.consecutive_errors, 300)
                self.pause_until = time.time() + pause_seconds
                log.warning(
                    f"Backing off: {self.active_workers} worker(s), "
                    f"pausing {pause_seconds}s"
                )

    def should_pause(self) -> bool:
        """Check if we are in a pause period after errors."""
        if time.time() < self.pause_until:
            remaining = self.pause_until - time.time()
            log.info(f"Paused, {remaining:.0f}s remaining...")
            return True
        return False

    def should_batch_pause(self) -> bool:
        """Check if we should pause between batches to be respectful."""
        return (
            self.total_processed > 0
            and self.total_processed % self.batch_size == 0
        )

    def summary(self) -> str:
        """Return a human-readable summary of pool activity."""
        return (
            f"Processed: {self.total_processed}, "
            f"Errors: {self.total_errors}, "
            f"Active workers: {self.active_workers}/{self.max_workers}"
        )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _fmt_count(n: int) -> str:
    """Format a number with K/M suffix for compact display."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    elif n >= 1_000:
        return f"{n / 1_000:.0f}K"
    return str(n)


def _fmt_result(index: int, total: int, state: str, slug: str, result: dict) -> str:
    """Format a single election result for progress display."""
    if result.get("skipped"):
        return f"[{index}/{total}] {state} {slug} -- skipped (already imported)"
    if result.get("error"):
        return f"[{index}/{total}] {state} {slug} -- FAILED: {result['error']}"

    races = result.get("races", 0)
    votes = result.get("votes_county", 0) + result.get("votes_precinct", 0)
    return (
        f"[{index}/{total}] {state} {slug} -- "
        f"{races:,} races, {_fmt_count(votes)} votes -- OK"
    )


# ---------------------------------------------------------------------------
# Command: scrape
# ---------------------------------------------------------------------------


def cmd_scrape(args) -> int:
    """Scrape historical election data for one or more states."""
    db_path = args.db_path

    if not os.path.exists(db_path):
        log.error(
            f"Database not found: {db_path}\n"
            "  Run 'python scrapers/schema.py' first to create the schema."
        )
        return 1

    # Determine which states to process
    if args.all:
        states = sorted(SCRAPERS.keys())
    elif args.state:
        states = [args.state.upper()]
    else:
        log.error("Specify --state XX or --all")
        return 1

    # Collect all (state, archive) pairs to process
    tasks = []
    for state in states:
        try:
            config = load_config(state)
            scraper_cls = get_scraper_class(state)
            scraper = scraper_cls(db_path, config)
            archives = scraper.list_elections()

            if args.election:
                match = [a for a in archives if a["slug"] == args.election]
                if not match:
                    slugs = [a["slug"] for a in archives]
                    log.error(
                        f"Election '{args.election}' not found for {state}. "
                        f"Available: {slugs}"
                    )
                    return 1
                archives = match

            for archive in archives:
                tasks.append((state, scraper, archive))

        except (ValueError, FileNotFoundError) as e:
            log.error(str(e))
            return 1

    if not tasks:
        log.info("No elections to process.")
        return 0

    total = len(tasks)
    log.info(f"Scrape: {total} election(s) across {len(states)} state(s)")
    log.info(f"Database: {db_path}")
    log.info("=" * 60)

    # Build adaptive pool from config (use first state's config for pool settings)
    first_config = tasks[0][1].config
    scraping_cfg = first_config.get("scraping", {})
    pool = AdaptiveWorkerPool(
        max_workers=args.workers,
        initial_workers=1 if args.ramp else args.workers,
        ramp_up=args.ramp,
        ramp_after=scraping_cfg.get("ramp_after_successes", 5),
        batch_size=scraping_cfg.get("batch_size", 3),
        batch_pause=scraping_cfg.get("batch_pause_seconds", 10),
    )

    results = []
    errors = []

    if args.workers <= 1:
        # --- Sequential mode ---
        for i, (state, scraper, archive) in enumerate(tasks, 1):
            slug = archive["slug"]

            # Check for pause
            while pool.should_pause():
                time.sleep(5)

            try:
                result = scraper.fetch_election(archive, force=args.force)
                pool.on_success()
                results.append(result)
                log.info(_fmt_result(i, total, state, slug, result))
            except Exception as e:
                status_code = None
                if hasattr(e, "response") and hasattr(e.response, "status_code"):
                    status_code = e.response.status_code
                pool.on_error(status_code)
                err_result = {"error": str(e), "election_key": f"{state}-{slug}"}
                results.append(err_result)
                errors.append((state, slug, str(e)))
                log.error(_fmt_result(i, total, state, slug, err_result))

            # Rate limiting
            if i < total:
                if pool.should_batch_pause():
                    pause_secs = scraping_cfg.get("batch_pause_seconds", 10)
                    log.info(f"Batch pause: {pause_secs}s...")
                    time.sleep(pause_secs)
                else:
                    delay = scraping_cfg.get("delay_seconds", 2.0)
                    time.sleep(delay)
    else:
        # --- Parallel mode with adaptive pool ---
        task_index = 0
        completed = 0

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}

            def submit_next():
                nonlocal task_index
                while task_index < len(tasks) and len(futures) < pool.active_workers:
                    state, scraper, archive = tasks[task_index]
                    future = executor.submit(
                        scraper.fetch_election, archive, args.force
                    )
                    futures[future] = (task_index + 1, state, archive)
                    task_index += 1

            # Initial submission
            submit_next()

            while futures:
                # Wait for any one to complete
                done_futures = []
                for f in list(futures.keys()):
                    if f.done():
                        done_futures.append(f)

                if not done_futures:
                    time.sleep(0.5)
                    continue

                for future in done_futures:
                    idx, state, archive = futures.pop(future)
                    slug = archive["slug"]
                    completed += 1

                    try:
                        result = future.result()
                        pool.on_success()
                        results.append(result)
                        log.info(_fmt_result(idx, total, state, slug, result))
                    except Exception as e:
                        status_code = None
                        if hasattr(e, "response") and hasattr(e.response, "status_code"):
                            status_code = e.response.status_code
                        pool.on_error(status_code)
                        err_result = {"error": str(e), "election_key": f"{state}-{slug}"}
                        results.append(err_result)
                        errors.append((state, slug, str(e)))
                        log.error(_fmt_result(idx, total, state, slug, err_result))

                # Check for pause
                while pool.should_pause():
                    time.sleep(5)

                # Batch pause
                if pool.should_batch_pause():
                    pause_secs = scraping_cfg.get("batch_pause_seconds", 10)
                    log.info(f"Batch pause: {pause_secs}s...")
                    time.sleep(pause_secs)

                # Submit more work if available
                submit_next()

    # --- Summary ---
    log.info("=" * 60)
    log.info("SCRAPE SUMMARY")
    log.info("=" * 60)

    imported = [r for r in results if not r.get("skipped") and not r.get("error")]
    skipped = [r for r in results if r.get("skipped")]

    total_races = sum(r.get("races", 0) for r in imported)
    total_choices = sum(r.get("choices", 0) for r in imported)
    total_county_votes = sum(r.get("votes_county", 0) for r in imported)
    total_precinct_votes = sum(r.get("votes_precinct", 0) for r in imported)

    log.info(f"  Elections imported:  {len(imported)}")
    log.info(f"  Elections skipped:   {len(skipped)}")
    log.info(f"  Errors:              {len(errors)}")
    log.info(f"  Total races:         {total_races:,}")
    log.info(f"  Total choices:       {total_choices:,}")
    log.info(f"  Total county votes:  {total_county_votes:,}")
    log.info(f"  Total precinct votes: {total_precinct_votes:,}")
    log.info(f"  Worker pool: {pool.summary()}")

    if errors:
        log.info("  Failed elections:")
        for state, slug, err in errors:
            log.info(f"    - {state} {slug}: {err}")

    return 1 if errors else 0


# ---------------------------------------------------------------------------
# Command: live
# ---------------------------------------------------------------------------


# Global flag for graceful shutdown
_shutdown = threading.Event()


def _signal_handler(signum, frame):
    """Handle Ctrl-C for graceful shutdown during live polling."""
    log.info("Shutdown signal received, finishing current poll...")
    _shutdown.set()


def cmd_live(args) -> int:
    """Poll live election results for a state."""
    state = args.state.upper()
    db_path = args.db_path

    if not os.path.exists(db_path):
        log.error(f"Database not found: {db_path}")
        return 1

    try:
        config = load_config(state)
        scraper_cls = get_scraper_class(state)
    except (ValueError, FileNotFoundError) as e:
        log.error(str(e))
        return 1

    scraper = scraper_cls(db_path, config)

    # Get poll interval from config
    scraping_cfg = config.get("scraping", {})
    poll_interval = scraping_cfg.get("poll_interval_seconds", 180)

    log.info(f"Live polling: {state}")
    log.info(f"Poll interval: {poll_interval}s")
    log.info(f"Database: {db_path}")
    log.info("Press Ctrl-C to stop.")
    log.info("=" * 60)

    # Register signal handler
    signal.signal(signal.SIGINT, _signal_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _signal_handler)

    poll_count = 0
    consecutive_errors = 0

    while not _shutdown.is_set():
        poll_count += 1
        poll_start = time.time()
        ts = datetime.now().strftime("%H:%M:%S")

        try:
            # Scrapers that support live polling should implement fetch_live()
            # or we fall back to fetch_election with the current election config
            if hasattr(scraper, "fetch_live"):
                result = scraper.fetch_live()
            else:
                # For scrapers without explicit live support, use the most
                # recent election from config with force=True
                archives = scraper.list_elections()
                if not archives:
                    log.error("No elections configured for live polling")
                    return 1
                result = scraper.fetch_election(archives[0], force=True)

            elapsed = time.time() - poll_start
            consecutive_errors = 0

            races = result.get("races", 0)
            votes = result.get("votes_county", 0) + result.get("votes_precinct", 0)
            log.info(
                f"[{ts}] Poll #{poll_count}: "
                f"{races:,} races, {_fmt_count(votes)} votes "
                f"({elapsed:.1f}s)"
            )

        except Exception as e:
            elapsed = time.time() - poll_start
            consecutive_errors += 1
            log.error(f"[{ts}] Poll #{poll_count}: ERROR ({elapsed:.1f}s): {e}")

            # Exponential backoff on consecutive errors
            if consecutive_errors >= 5:
                extra_wait = min(60 * consecutive_errors, 600)
                log.warning(
                    f"  {consecutive_errors} consecutive errors, "
                    f"extra wait {extra_wait}s"
                )
                _shutdown.wait(timeout=extra_wait)

        # Wait for next poll (or shutdown)
        _shutdown.wait(timeout=poll_interval)

    log.info(f"Live polling stopped after {poll_count} polls.")
    return 0


# ---------------------------------------------------------------------------
# Command: import-la
# ---------------------------------------------------------------------------


def cmd_import_la(args) -> int:
    """Run the Louisiana data import."""
    # Import the LA import module (bare name since scrapers/ is on sys.path)
    from louisiana_import import run_import, DEFAULT_SOURCE, DEFAULT_TARGET

    source = args.source or DEFAULT_SOURCE
    target = args.target or args.db_path

    log.info(f"Louisiana import")
    log.info(f"  Source: {source}")
    log.info(f"  Target: {target}")
    log.info("=" * 60)

    try:
        run_import(source, target)
        return 0
    except Exception as e:
        log.error(f"Louisiana import failed: {e}")
        return 1


# ---------------------------------------------------------------------------
# Command: backup
# ---------------------------------------------------------------------------


def cmd_backup(args) -> int:
    """Create a timestamped backup of the database."""
    db_path = args.db_path

    if not os.path.exists(db_path):
        log.error(f"Database not found: {db_path}")
        return 1

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(os.path.dirname(db_path), "backups")
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, f"elections-{ts}.db")

    db_size = os.path.getsize(db_path)
    log.info(f"Backing up database ({db_size:,} bytes)...")
    shutil.copy2(db_path, dest)
    log.info(f"Backup created: {dest}")

    # Show existing backups
    backups = sorted(
        f for f in os.listdir(backup_dir) if f.endswith(".db")
    )
    log.info(f"Total backups in {backup_dir}: {len(backups)}")
    if len(backups) > 5:
        log.info(f"  (oldest: {backups[0]}, newest: {backups[-1]})")

    return 0


# ---------------------------------------------------------------------------
# Command: status
# ---------------------------------------------------------------------------


def cmd_status(args) -> int:
    """Show a summary of import runs from the database."""
    db_path = args.db_path

    if not os.path.exists(db_path):
        log.error(f"Database not found: {db_path}")
        return 1

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Overall DB stats
    db_size = os.path.getsize(db_path)
    election_count = conn.execute("SELECT COUNT(*) FROM elections").fetchone()[0]
    race_count = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    choice_count = conn.execute("SELECT COUNT(*) FROM choices").fetchone()[0]

    print(f"Database: {db_path} ({db_size:,} bytes)")
    print(f"Elections: {election_count:,}  |  Races: {race_count:,}  |  Choices: {choice_count:,}")
    print("=" * 80)

    # Import runs grouped by state
    rows = conn.execute("""
        SELECT state, election_key, status, started_at, finished_at,
               record_counts, error_message
        FROM import_runs
        ORDER BY state, started_at DESC
    """).fetchall()

    if not rows:
        print("No import runs found.")
        conn.close()
        return 0

    # Group by state
    by_state = {}
    for row in rows:
        state = row["state"]
        if state not in by_state:
            by_state[state] = []
        by_state[state].append(row)

    for state in sorted(by_state.keys()):
        state_rows = by_state[state]
        success_count = sum(1 for r in state_rows if r["status"] in ("success", "success_with_warnings"))
        failed_count = sum(1 for r in state_rows if r["status"] == "failed")
        running_count = sum(1 for r in state_rows if r["status"] == "running")

        # State-level stats
        state_elections = conn.execute(
            "SELECT COUNT(*) FROM elections WHERE state = ?", (state,)
        ).fetchone()[0]
        state_races = conn.execute("""
            SELECT COUNT(*) FROM races r
            JOIN elections e ON r.election_id = e.id
            WHERE e.state = ?
        """, (state,)).fetchone()[0]

        print(f"\n{state} -- {state_elections} elections, {state_races:,} races")
        print(f"  Import runs: {len(state_rows)} total "
              f"({success_count} success, {failed_count} failed, {running_count} running)")
        print(f"  {'Election Key':<35} {'Status':<25} {'Races':>8} {'Choices':>8} {'Started':>22}")
        print(f"  {'-' * 35} {'-' * 25} {'-' * 8} {'-' * 8} {'-' * 22}")

        # Show most recent run per election_key
        seen_keys = set()
        for row in state_rows:
            ekey = row["election_key"] or "(bulk import)"
            if ekey in seen_keys:
                continue
            seen_keys.add(ekey)

            status = row["status"]
            if status == "success":
                status_display = "success"
            elif status == "success_with_warnings":
                status_display = "success (warnings)"
            elif status == "failed":
                err = row["error_message"] or ""
                status_display = f"FAILED: {err[:30]}" if err else "FAILED"
            else:
                status_display = status

            counts = {}
            if row["record_counts"]:
                try:
                    counts = json.loads(row["record_counts"])
                except (json.JSONDecodeError, TypeError):
                    pass

            races = counts.get("races", "-")
            choices = counts.get("choices", "-")
            started = row["started_at"] or "-"
            # Trim the timezone info for display
            if started != "-" and len(started) > 19:
                started = started[:19]

            print(f"  {ekey:<35} {status_display:<25} {str(races):>8} {str(choices):>8} {started:>22}")

    # Overall totals
    print("\n" + "=" * 80)
    total_runs = len(rows)
    total_success = sum(1 for r in rows if r["status"] in ("success", "success_with_warnings"))
    total_failed = sum(1 for r in rows if r["status"] == "failed")
    print(
        f"Total: {total_runs} import runs "
        f"({total_success} success, {total_failed} failed) "
        f"across {len(by_state)} state(s)"
    )

    conn.close()
    return 0


# ---------------------------------------------------------------------------
# CLI argument parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="runner.py",
        description="National Election Tracker -- unified CLI for scraping operations.",
    )
    parser.add_argument(
        "--db-path",
        default=DEFAULT_DB_PATH,
        help=f"Path to SQLite database (default: {DEFAULT_DB_PATH})",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # --- scrape ---
    sp_scrape = subparsers.add_parser(
        "scrape",
        help="Scrape historical election data",
    )
    sp_scrape_group = sp_scrape.add_mutually_exclusive_group(required=True)
    sp_scrape_group.add_argument(
        "--state", help="State code (e.g. IN, OH)"
    )
    sp_scrape_group.add_argument(
        "--all", action="store_true", help="Process all registered states"
    )
    sp_scrape.add_argument(
        "--election", help="Single election slug (e.g. 2024General)"
    )
    sp_scrape.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Max concurrent workers (default: 1)",
    )
    sp_scrape.add_argument(
        "--ramp",
        action="store_true",
        help="Enable adaptive ramp-up (start with 1 worker, increase on success)",
    )
    sp_scrape.add_argument(
        "--force",
        action="store_true",
        help="Re-import even if already done",
    )

    # --- live ---
    sp_live = subparsers.add_parser(
        "live",
        help="Poll live election results",
    )
    sp_live.add_argument(
        "--state",
        required=True,
        help="State code (e.g. IN, OH)",
    )

    # --- import-la ---
    sp_la = subparsers.add_parser(
        "import-la",
        help="Import Louisiana data from existing LA tracker DB",
    )
    sp_la.add_argument(
        "--source",
        default=None,
        help="Path to source Louisiana DB (default: auto-detected)",
    )
    sp_la.add_argument(
        "--target",
        default=None,
        help="Path to target national DB (default: data/elections.db)",
    )

    # --- backup ---
    subparsers.add_parser(
        "backup",
        help="Create a timestamped backup of the database",
    )

    # --- status ---
    subparsers.add_parser(
        "status",
        help="Show import runs summary",
    )

    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "scrape": cmd_scrape,
        "live": cmd_live,
        "import-la": cmd_import_la,
        "backup": cmd_backup,
        "status": cmd_status,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
