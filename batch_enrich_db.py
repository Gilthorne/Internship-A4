#!/usr/bin/env python3
"""
batch_enrich_db.py – Batch-update CLASSIFICATION table with Year, Country, Authors.

This script processes papers with missing metadata (Year, Country, Authors) and
enriches them using Crossref and Elsevier APIs.

Usage:
    python batch_enrich_db.py
    python batch_enrich_db.py --limit 1000
    python batch_enrich_db.py --batch-size 500
"""

import argparse
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

from get_year_from_doi import get_metadata
from pipeline_common import get_db_connection

load_dotenv()

# ---------------------------------------------------------------------------
# Logging Configuration
# ---------------------------------------------------------------------------

_LOG_DIR = "error_log"
os.makedirs(_LOG_DIR, exist_ok=True)
_LOG_FILE = os.path.join(_LOG_DIR, "batch_enrich_db.log")

# Create and configure logger
_log = logging.getLogger("batch_enrich_db")
_log.setLevel(logging.INFO)
_log.handlers.clear()

# File handler (detailed logs)
file_handler = RotatingFileHandler(
    _LOG_FILE, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)
_log.addHandler(file_handler)

# Console handler (info-level logs)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(
    logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")
)
_log.addHandler(console_handler)

_log.propagate = False

# ---------------------------------------------------------------------------
# Database Helpers
# ---------------------------------------------------------------------------

_FETCH_SQL = (
    "SELECT id, DOI FROM CLASSIFICATION "
    "WHERE Year IS NULL "
    "  AND Country IS NULL "
    "  AND (Authors IS NULL OR Authors = '') "
    "  AND DOI IS NOT NULL"
)


def fetch_rows(limit: int | None, offset: int) -> list[tuple]:
    """Retrieve rows requiring enrichment from the database."""
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
        
        cur.execute(sql, params)
        rows = cur.fetchall()
    finally:
        cur.close()
        db.close()
    
    _log.info(f"Retrieved {len(rows)} papers for enrichment")
    return rows


def update_row(
    db, 
    paper_id: int, 
    year: int | None, 
    country: str | None, 
    authors: str | None
) -> None:
    """Update a single paper record in the database."""
    cur = db.cursor()
    try:
        cur.execute(
            "UPDATE CLASSIFICATION SET Year=%s, Country=%s, Authors=%s WHERE id=%s",
            (year, country, authors, paper_id),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Processing Logic
# ---------------------------------------------------------------------------

def process_rows(rows: list[tuple], batch_size: int) -> tuple[int, int]:
    """
    Process rows and update database with retrieved metadata.
    
    Returns:
        Tuple of (total_updated, total_failures)
    """
    total_papers = len(rows)
    total_updated = 0
    total_failures = 0
    batch_number = 0
    db = get_db_connection()

    try:
        for batch_start in range(0, total_papers, batch_size):
            batch = rows[batch_start:batch_start + batch_size]
            batch_number += 1
            batch_size_actual = len(batch)
            
            _log.info("")
            _log.info("-" * 80)
            _log.info(
                f"Processing batch {batch_number}: "
                f"papers {batch_start + 1} to {batch_start + batch_size_actual}"
            )
            _log.info("-" * 80)

            batch_updated = 0
            batch_failures = 0

            for item_index, (paper_id, doi) in enumerate(batch, 1):
                # Validate DOI
                if not doi or not doi.strip():
                    _log.debug(f"Paper {paper_id}: Skipping empty DOI")
                    batch_failures += 1
                    continue

                doi = doi.strip()
                
                # Log start of processing
                _log.info(f"[{item_index:4d}/{batch_size_actual:4d}] Processing DOI: {doi}")
                start_time = time.monotonic()

                # Fetch metadata
                try:
                    metadata, source = get_metadata(doi)
                except Exception as exc:
                    _log.error(f"                 | Error retrieving metadata: {exc}")
                    batch_failures += 1
                    continue

                elapsed_seconds = time.monotonic() - start_time
                
                # Extract metadata fields
                publication_year = metadata.get("year")
                authors_list = metadata.get("authors") or []
                countries_list = metadata.get("countries") or []

                # Format for display
                authors_display = ", ".join(authors_list) if authors_list else "N/A"
                countries_display = ", ".join(countries_list) if countries_list else "N/A"

                # Log retrieved metadata
                _log.info(
                    f"                 | Year: {publication_year} | "
                    f"Authors: {authors_display} | "
                    f"Countries: {countries_display} | "
                    f"Time: {elapsed_seconds:.2f}s"
                )
                _log.info(
                    f"                 | Source: {source}"
                )

                # Skip if no metadata retrieved
                if publication_year is None and not authors_list and not countries_list:
                    _log.warning(f"                 | No metadata retrieved, skipping update")
                    batch_failures += 1
                    continue

                # Format for database
                authors_for_db = "; ".join(authors_list) if authors_list else None
                countries_for_db = "; ".join(countries_list) if countries_list else None

                # Update database
                try:
                    update_row(db, paper_id, publication_year, countries_for_db, authors_for_db)
                    batch_updated += 1
                    total_updated += 1
                    _log.debug(f"                 | Database record updated successfully")
                except Exception as exc:
                    _log.error(f"                 | Database update failed: {exc}")
                    batch_failures += 1
                    total_failures += 1

            total_failures += batch_failures

            # Batch summary
            _log.info("")
            _log.info(
                f"Batch {batch_number} complete: "
                f"Updated {batch_updated}, Failed {batch_failures}"
            )
            _log.info(
                f"Cumulative: Updated {total_updated}, Failed {total_failures}"
            )
            _log.info("")
            
            # Pause between batches
            num_batches = (total_papers // batch_size) + (1 if total_papers % batch_size else 0)
            if batch_number < num_batches:
                _log.info("Waiting 10 seconds before next batch...")
                time.sleep(10)
                
    finally:
        db.close()

    return total_updated, total_failures


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Batch-enrich paper metadata (Year, Country, Authors) from Crossref and Elsevier APIs.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        metavar="N", help="Maximum number of papers to process (default: all)",
    )
    parser.add_argument(
        "--offset", type=int, default=0,
        metavar="N", help="Skip first N matching papers (default: 0)",
    )
    parser.add_argument(
        "--batch-size", type=int, default=1000,
        metavar="N", help="Papers per batch (default: 1000)",
    )
    args = parser.parse_args()

    # Log start
    _log.info("")
    _log.info("=" * 80)
    _log.info("BATCH ENRICHMENT PROCESS STARTED")
    _log.info("=" * 80)
    _log.info(f"Configuration: limit={args.limit}, offset={args.offset}, batch_size={args.batch_size}")
    _log.info("")

    # Fetch rows
    rows = fetch_rows(args.limit, args.offset)
    total_papers = len(rows)

    if total_papers == 0:
        _log.warning("No papers found requiring enrichment.")
        return

    _log.info(f"Total papers to process: {total_papers:,}")
    _log.info("")

    # Process
    start_time = time.monotonic()
    total_updated, total_failures = process_rows(rows, args.batch_size)
    elapsed_seconds = time.monotonic() - start_time

    # Log completion
    _log.info("")
    _log.info("=" * 80)
    _log.info("BATCH ENRICHMENT PROCESS COMPLETED")
    _log.info("=" * 80)
    _log.info(f"Total papers processed:     {total_papers:,}")
    _log.info(f"Successfully updated:       {total_updated:,}")
    _log.info(f"Failed:                     {total_failures:,}")
    if total_papers > 0:
        success_rate = (total_updated / total_papers) * 100
        _log.info(f"Success rate:               {success_rate:.1f}%")
    _log.info(f"Total execution time:       {elapsed_seconds:.1f}s ({elapsed_seconds/60:.1f} minutes)")
    if total_papers > 0:
        avg_time = elapsed_seconds / total_papers
        _log.info(f"Average time per paper:     {avg_time:.3f}s")
    _log.info(f"Log file:                   {_LOG_FILE}")
    _log.info("=" * 80)
    _log.info("")

    # Exit with error if there were failures
    if total_failures > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
