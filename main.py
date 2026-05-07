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

import asyncio
import importlib.util
import logging
import os
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
    from pipeline.refresh_schools import fetch
    logger.info("Step 1/3  Refreshing school list from GuideK12...")
    asyncio.run(fetch(str(SCHOOLS_PATH)))
    logger.info("Step 1/3  Done → %s", SCHOOLS_PATH)


def step_scrape_addresses(logger: logging.Logger) -> None:
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
    from pipeline.build_binary import build
    logger.info("Step 3/3  Building binary from slim JSON...")
    build(str(ADDRESSES_SLIM), str(ADDRESSES_BIN))
    logger.info("Step 3/3  Done → %s", ADDRESSES_BIN)


# ── Git push ─────────────────────────────────────────────────

def git_push_changes(logger: logging.Logger) -> None:
    if os.getenv("SKIP_GIT_PUSH"):
        logger.info("SKIP_GIT_PUSH is set — skipping commit/push")
        return

    files_to_stage = [
        str(SCHOOLS_PATH),
        str(ADDRESSES_SLIM),
        str(ADDRESSES_BIN),
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
    logger, timestamp = setup_logging()
    logger.info("=== PPS school data refresh pipeline started ===")
    start = datetime.now()

    try:
        backup_data_files(logger, timestamp)
        step_refresh_schools(logger)
        step_scrape_addresses(logger)
        step_build_binary(logger)
        git_push_changes(logger)
    except (Exception, SystemExit) as exc:
        logger.exception("Pipeline failed: %s", exc)
        sys.exit(1)

    elapsed = (datetime.now() - start).total_seconds()
    logger.info("=== Pipeline complete in %.0fs ===", elapsed)


if __name__ == "__main__":
    main()
