#!/usr/bin/env python3
"""
batch_enrich_db.py – Batch-update CLASSIFICATION table with Year, Country, Authors.

Reads papers where Year / Country / Authors are missing, calls get_metadata()
for each DOI (Crossref primary, Elsevier secondary with rate-limiting), and
writes the results back to the database.

Usage:
    python batch_enrich_db.py
    python batch_enrich_db.py --limit 1000
    python batch_enrich_db.py --offset 500 --limit 1000
    python batch_enrich_db.py --batch-size 500

Optional arguments:
    --limit N       Process at most N papers (default: all)
    --offset N      Skip the first N matching rows (default: 0)
    --batch-size N  Commit progress every N papers (default: 1000)
"""

import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

from get_year_from_doi import get_metadata
from pipeline_common import get_db_connection, print_progress

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_LOG_DIR = "error_log"
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "batch_enrich_db.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(
            _LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
        ),
    ],
)
_log = logging.getLogger("batch_enrich_db")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_FETCH_SQL = (
    "SELECT id, DOI FROM CLASSIFICATION "
    "WHERE Year IS NULL "
    "  AND Country IS NULL "
    "  AND (Authors IS NULL OR Authors = '') "
    "  AND DOI IS NOT NULL"
)


def _fetch_rows(limit: int | None, offset: int) -> list[tuple]:
    """Return (id, DOI) rows that still need enrichment."""
    db = get_db_connection()
    cur = db.cursor()
    try:
        sql = _FETCH_SQL
        params: list = []
        if limit is not None:
            sql += " LIMIT %s OFFSET %s"
            params = [limit, offset]
        elif offset:
            sql += " OFFSET %s"
            params = [offset]
        _log.debug("Fetch query: %s  params=%s", sql, params)
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()
        db.close()
    _log.info("Fetched %d rows to process", len(rows))
    return rows


def _update_row(db, pid: int, year: int | None, country: str | None, authors: str | None) -> None:
    """UPDATE a single CLASSIFICATION row with the retrieved metadata."""
    cur = db.cursor()
    try:
        cur.execute(
            "UPDATE CLASSIFICATION SET Year=%s, Country=%s, Authors=%s WHERE id=%s",
            (year, country, authors, pid),
        )
        db.commit()
        _log.info(
            "UPDATE id=%d  Year=%s  Country=%s  Authors=%s",
            pid, year, country, authors,
        )
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Core processing loop
# ---------------------------------------------------------------------------

def _process_rows(rows: list[tuple], batch_size: int) -> tuple[int, int]:
    """
    Iterate over rows, call get_metadata() for each DOI, and persist results.

    Returns (total_updated, total_failures).
    """
    total = len(rows)
    updated = 0
    failures = 0
    batch_num = 0
    db = get_db_connection()

    try:
        for batch_start in range(0, total, batch_size):
            batch = rows[batch_start:batch_start + batch_size]
            batch_num += 1
            batch_total = len(batch)
            _log.info(
                "Batch %d: rows %d–%d (%d papers)",
                batch_num, batch_start + 1, batch_start + batch_total, batch_total,
            )
            print(f"\nBatch {batch_num}: processing {batch_total} papers…")

            for i, (pid, doi) in enumerate(batch):
                # Skip NULL/empty DOIs (safety guard; fetch query already filters them)
                if not doi or not doi.strip():
                    _log.debug("id=%d: skipping empty DOI", pid)
                    failures += 1
                    print_progress(f"[Batch {batch_num}]", i + 1, batch_total)
                    continue

                doi = doi.strip()
                _log.info("Processing id=%d  DOI=%s", pid, doi)
                t0 = time.monotonic()

                try:
                    meta, source = get_metadata(doi)
                except Exception as exc:
                    _log.error("id=%d  DOI=%s: get_metadata() raised: %s", pid, doi, exc)
                    failures += 1
                    print_progress(f"[Batch {batch_num}]", i + 1, batch_total)
                    continue

                elapsed = time.monotonic() - t0
                year = meta.get("year")
                authors_list = meta.get("authors") or []
                countries_list = meta.get("countries") or []

                _log.info(
                    "id=%d  DOI=%s  source=%s  year=%s  authors=%d  countries=%d  elapsed=%.2fs",
                    pid, doi, source, year, len(authors_list), len(countries_list), elapsed,
                )

                # Only write rows where at least one field was retrieved
                if year is None and not authors_list and not countries_list:
                    _log.warning(
                        "id=%d  DOI=%s: no metadata retrieved (source=%s)", pid, doi, source
                    )
                    failures += 1
                    print_progress(f"[Batch {batch_num}]", i + 1, batch_total)
                    continue

                authors_val = "; ".join(authors_list) if authors_list else None
                country_val = "; ".join(countries_list) if countries_list else None

                try:
                    _update_row(db, pid, year, country_val, authors_val)
                    updated += 1
                except Exception as exc:
                    _log.error("id=%d  DOI=%s: DB update failed: %s", pid, doi, exc)
                    failures += 1

                print_progress(f"[Batch {batch_num}]", i + 1, batch_total)

            _log.info(
                "Batch %d done  updated=%d  failures_so_far=%d", batch_num, updated, failures
            )
    finally:
        db.close()

    return updated, failures


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch-update CLASSIFICATION table with Year, Country, and Authors.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        metavar="N", help="Maximum number of papers to process (default: all)",
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        metavar="N", help="Skip the first N matching rows (default: 0)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        metavar="N", help="Papers per processing batch (default: 1000)",
    )
    args = parser.parse_args()

    _log.info(
        "batch_enrich_db started  limit=%s  offset=%s  batch_size=%s",
        args.limit, args.offset, args.batch_size,
    )

    rows = _fetch_rows(args.limit, args.offset)
    total = len(rows)

    if total == 0:
        print(
            "Nothing to process: no papers with missing Year/Country/Authors "
            "(or none remain after applying --limit/--offset)."
        )
        _log.info("No rows to process. Exiting.")
        return

    print(f"Found {total} papers to process.")

    t_start = time.monotonic()
    total_updated, total_failures = _process_rows(rows, args.batch_size)
    elapsed_total = time.monotonic() - t_start

    # Summary
    print(
        f"\nProcessed {total} papers. "
        f"Updated {total_updated}. "
        f"Failures: {total_failures}. "
        f"Elapsed: {elapsed_total:.1f}s"
    )
    print(f"Log file: {_LOG_FILE}")

    _log.info(
        "batch_enrich_db finished  processed=%d  updated=%d  failures=%d  elapsed=%.1fs",
        total, total_updated, total_failures, elapsed_total,
    )

    if total_failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
