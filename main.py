"""
Monthly PPS school data refresh pipeline.

Pipeline steps:
  1. refresh_schools  — fetch current school list from GuideK12 → data/schools.json
  2. scraper-v2       — map every Pittsburgh address to its assigned schools
                        → data/addresses_full.json + data/addresses_slim.json
  3. build_binary     — encode slim JSON to compact binary → data/addresses.bin

Logs to logs/pipeline_YYYYMMDD_HHMMSS.log (file is kept locally; not committed).

Environment variables:
  SKIP_GIT_PUSH=1   — run the pipeline without committing or pushing (useful locally)
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).parent

SCHOOLS_PATH    = ROOT / "data" / "schools.json"
ADDRESSES_INPUT = ROOT / "address-data" / "pittsburgh_addresses.json"
ADDRESSES_FULL  = ROOT / "data" / "addresses_full.json"
ADDRESSES_SLIM  = ROOT / "data" / "addresses_slim.json"
ADDRESSES_BIN   = ROOT / "data" / "addresses.bin"


# ── Logging ───────────────────────────────────────────────────

def setup_logging() -> tuple[logging.Logger, str]:
    """
    Initializes the pipeline logger and creates a timestamped log file.

    Creates the logs/ directory if absent, then attaches a file handler
    (logs/pipeline_YYYYMMDD_HHMMSS.log) and a stdout handler to the
    'pps_pipeline' logger.  The log file is local-only and never committed.

    Returns:
        logger: Configured Logger instance shared across all pipeline steps.
        timestamp: ISO-compact timestamp string (YYYYMMDD_HHMMSS) reused as
            the backup directory suffix so the log and backup share the same key.
    """
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = logs_dir / f"pipeline_{timestamp}.log"

    logger = logging.getLogger("pps_pipeline")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    logger.info("Log file: %s", log_file)
    return logger, timestamp


# ── Backup ───────────────────────────────────────────────────

def backup_data_files(logger: logging.Logger, timestamp: str) -> None:
    """
    Copies existing data files to a timestamped backup directory before the
    pipeline overwrites them.

    Backs up schools.json, addresses_full.json, addresses_slim.json, and
    addresses.bin — whichever currently exist — into backups/data/<timestamp>/.
    Files that do not exist yet are silently skipped.  The backup is taken
    before any pipeline step runs, so it always reflects the last successfully
    committed dataset.

    Args:
        logger: Pipeline logger for status messages.
        timestamp: Compact timestamp string (YYYYMMDD_HHMMSS) used as the
            backup subdirectory name, shared with the log file so the two are
            trivially correlated.
    """
    files_to_backup = [
        SCHOOLS_PATH,
        ADDRESSES_FULL,
        ADDRESSES_SLIM,
        ADDRESSES_BIN,
    ]

    existing = [f for f in files_to_backup if f.exists()]
    if not existing:
        logger.info("Backup  No existing data files found — skipping")
        return

    backup_dir = ROOT / "backups" / "data" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    for src in existing:
        dest = backup_dir / src.name
        shutil.copy2(src, dest)
        logger.info("Backup  %s → %s", src.relative_to(ROOT), dest.relative_to(ROOT))


# ── Pipeline steps ────────────────────────────────────────────

def step_refresh_schools(logger: logging.Logger) -> None:
    """
    Pipeline step 1: fetches the current school list from GuideK12 and writes
    it to disk.

    Delegates to pipeline/refresh_schools.fetch(), which makes a
    session-authenticated POST to the GuideK12 API, normalizes the response
    into the preprocessed schools.json format, and writes the result to
    SCHOOLS_PATH.

    Args:
        logger: Pipeline logger for progress messages.

    Raises:
        SystemExit: Propagated from refresh_schools.fetch() if the API returns
            a non-JSON or empty response.
    """
    from pipeline.refresh_schools import fetch
    logger.info("Step 1/3  Refreshing school list from GuideK12...")
    asyncio.run(fetch(str(SCHOOLS_PATH)))
    logger.info("Step 1/3  Done → %s", SCHOOLS_PATH)


def step_scrape_addresses(logger: logging.Logger) -> None:
    """
    Pipeline step 2: maps every Pittsburgh address to its assigned schools via
    the GuideK12 API.

    Loads scraper-v2.py via importlib because the hyphen in the filename
    prevents a normal import statement.  Runs the async scraper with
    concurrency=50, which POSTs each address's lat/lng to the GuideK12 spatial
    API and records the returned school assignments.  Writes both a full JSON
    file (ADDRESSES_FULL) and a compact slim JSON file (ADDRESSES_SLIM).
    Expect this step to take several minutes for the full ~116k-address dataset.

    Args:
        logger: Pipeline logger for progress messages.
    """
    # scraper-v2.py has a hyphen so it can't be imported with normal import syntax
    spec = importlib.util.spec_from_file_location(
        "scraper_v2", ROOT / "pipeline" / "scraper-v2.py"
    )
    scraper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scraper)

    logger.info(
        "Step 2/3  Mapping addresses to schools "
        "(concurrency=50, this may take several minutes)..."
    )
    asyncio.run(
        scraper.run(
            str(ADDRESSES_INPUT),
            str(SCHOOLS_PATH),
            str(ADDRESSES_FULL),
            concurrency=50,
            slim_output_path=str(ADDRESSES_SLIM),
        )
    )
    logger.info("Step 2/3  Done → %s", ADDRESSES_SLIM)


def step_build_binary(logger: logging.Logger) -> None:
    """
    Pipeline step 3: encodes addresses_slim.json into the compact PPSb binary
    format.

    Delegates to pipeline/build_binary.build(), which produces a binary file
    roughly 3x smaller than the slim JSON and parseable in near-zero time by
    the browser's DataView API.  The output is written to ADDRESSES_BIN.

    Args:
        logger: Pipeline logger for progress messages.
    """
    from pipeline.build_binary import build
    logger.info("Step 3/3  Building binary from slim JSON...")
    build(str(ADDRESSES_SLIM), str(ADDRESSES_BIN))
    logger.info("Step 3/3  Done → %s", ADDRESSES_BIN)


# ── Index date update ─────────────────────────────────────────

def update_index_date(logger: logging.Logger) -> None:
    """
    Rewrites the 'Data last updated' line in index.html with the current month
    and year.

    Searches for the pattern '<em>Data last updated: …</em>' using a regex and
    replaces the date portion with strftime('%B %Y') (e.g. 'May 2026').
    No-ops if the pattern is absent or the date is already current, so running
    the pipeline twice in the same month produces no spurious diff.

    Args:
        logger: Pipeline logger for status messages.
    """
    index_path = ROOT / "index.html"
    date_str = datetime.now().strftime("%B %Y")
    content = index_path.read_text(encoding="utf-8")
    updated = re.sub(
        r"(<em>Data last updated: )([^<]+)(</em>)",
        rf"\g<1>{date_str}.\g<3>",
        content,
    )
    if updated == content:
        logger.info("Index date already current — no change")
        return
    index_path.write_text(updated, encoding="utf-8")
    logger.info("Updated 'Data last updated' in index.html → %s", date_str)


# ── Git push ─────────────────────────────────────────────────

def git_push_changes(logger: logging.Logger) -> None:
    """
    Stages updated data files and index.html, commits, and pushes to the remote.

    Stages schools.json, addresses_slim.json, addresses.bin, and index.html.
    Skips the commit entirely if 'git diff --cached' reports no changes, so a
    month where the source data is unchanged produces no empty commit.  The
    commit message includes the current date for traceability.

    Set the environment variable SKIP_GIT_PUSH=1 to bypass this step entirely,
    which is useful when running the pipeline locally to inspect data output
    without affecting the remote repository.

    Args:
        logger: Pipeline logger for status messages.

    Raises:
        subprocess.CalledProcessError: If git add, commit, or push exits
            non-zero.
    """
    if os.getenv("SKIP_GIT_PUSH"):
        logger.info("SKIP_GIT_PUSH is set — skipping commit/push")
        return

    files_to_stage = [
        str(SCHOOLS_PATH),
        str(ADDRESSES_SLIM),
        str(ADDRESSES_BIN),
        str(ROOT / "index.html"),
    ]

    subprocess.run(["git", "add", *files_to_stage], check=True, cwd=ROOT)

    # Exit cleanly if there's nothing new to commit
    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )
    if diff.returncode == 0:
        logger.info("No data changes detected — skipping commit")
        return

    date_str = datetime.now().strftime("%Y-%m-%d")
    subprocess.run(
        [
            "git", "commit", "-m",
            f"chore: automated monthly school data refresh ({date_str})",
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(["git", "push"], check=True, cwd=ROOT)
    logger.info("Changes committed and pushed to remote")


# ── Entry point ───────────────────────────────────────────────

def main() -> None:
    """
    Entry point for the monthly PPS school data refresh pipeline.

    Runs backup → refresh_schools → scrape_addresses → build_binary →
    update_index_date → git_push in sequence.  Any unhandled exception or
    SystemExit is caught, logged with a full traceback, and converted to
    sys.exit(1) so the GitHub Actions step is marked as failed.  Elapsed
    time is logged on successful completion.
    """
    logger, timestamp = setup_logging()
    logger.info("=== PPS school data refresh pipeline started ===")
    start = datetime.now()

    try:
        backup_data_files(logger, timestamp)
        step_refresh_schools(logger)
        step_scrape_addresses(logger)
        step_build_binary(logger)
        update_index_date(logger)
        git_push_changes(logger)
    except (Exception, SystemExit) as exc:
        logger.exception("Pipeline failed: %s", exc)
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("=== Pipeline complete in %.0fs ===", elapsed)


if __name__ == "__main__":
    main()
