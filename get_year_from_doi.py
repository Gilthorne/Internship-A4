#!/usr/bin/env python3
"""
get_year_from_doi.py – Extract publication year from a DOI.

Primary  : Crossref API (free, no authentication required)
Fallback : Elsevier API (requires ELSEVIER_API_KEY; rate-limit respected)

Usage:
    python get_year_from_doi.py 10.1038/nature12373
"""

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

import requests
from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CROSSREF_TIMEOUT = 15          # seconds
ELSEVIER_TIMEOUT = 15          # seconds
# Exact interval derived from the 5 000 req/hour quota (3600 / 5000 = 0.72 s).
# Using the full quota value keeps us just within the limit without any margin;
# the comment in the problem statement ("~1.4 req/s") was an approximation.
ELSEVIER_MIN_INTERVAL = 3600 / 5000  # 0.72 s between requests

# Crossref Polite Pool contact email.  Override via CROSSREF_CONTACT_EMAIL env var
# to comply with Crossref's guidelines (https://api.crossref.org/swagger-ui/index.html).
CROSSREF_CONTACT = os.getenv("CROSSREF_CONTACT_EMAIL", "contact@example.com")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_log_dir = "error_log"
os.makedirs(_log_dir, exist_ok=True)
_log_file = os.path.join(_log_dir, "get_year_from_doi.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        RotatingFileHandler(_log_file, maxBytes=2_000_000, backupCount=2, encoding="utf-8"),
    ],
)
_log = logging.getLogger("get_year_from_doi")

# ---------------------------------------------------------------------------
# Rate-limit state for Elsevier
# ---------------------------------------------------------------------------

_elsevier_last_call: float = 0.0


def _elsevier_rate_limit() -> None:
    """Block until the minimum inter-request interval has elapsed."""
    global _elsevier_last_call
    elapsed = time.monotonic() - _elsevier_last_call
    wait = ELSEVIER_MIN_INTERVAL - elapsed
    if wait > 0:
        _log.debug("Elsevier rate-limit: sleeping %.3f s", wait)
        time.sleep(wait)
    _elsevier_last_call = time.monotonic()


# ---------------------------------------------------------------------------
# Crossref helper
# ---------------------------------------------------------------------------

def _year_from_crossref(doi: str) -> int | None:
    """
    Query the Crossref API and return the publication year, or None on failure.

    Crossref is free, requires no API key, and has generous rate limits.
    """
    url = f"https://api.crossref.org/works/{doi}"
    _log.debug("Crossref request: GET %s", url)

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": f"get_year_from_doi/1.0 (mailto:{CROSSREF_CONTACT})"},
            timeout=CROSSREF_TIMEOUT,
        )
    except requests.Timeout:
        _log.warning("Crossref request timed out for DOI %s", doi)
        return None
    except requests.RequestException as exc:
        _log.warning("Crossref request failed for DOI %s: %s", doi, exc)
        return None

    _log.debug("Crossref response: HTTP %s", resp.status_code)

    if resp.status_code == 404:
        _log.info("Crossref: DOI %s not found (404)", doi)
        return None

    if resp.status_code == 429:
        _log.warning("Crossref: rate-limit hit (429) for DOI %s", doi)
        return None

    if not resp.ok:
        _log.warning("Crossref: HTTP %s for DOI %s", resp.status_code, doi)
        return None

    try:
        data = resp.json()
    except ValueError as exc:
        _log.warning("Crossref: JSON decode error for DOI %s: %s", doi, exc)
        return None

    message = data.get("message") or {}

    # Try published-print → date-parts first, then published-online, then issued
    for date_key in ("published-print", "published-online", "issued", "created"):
        date_obj = message.get(date_key)
        if not isinstance(date_obj, dict):
            continue
        parts = date_obj.get("date-parts")
        if not parts or not isinstance(parts, list):
            continue
        first = parts[0]
        if isinstance(first, list) and first and isinstance(first[0], int):
            year = first[0]
            _log.info("Crossref: found year %d (field=%s) for DOI %s", year, date_key, doi)
            return year

    _log.info("Crossref: no year found in response for DOI %s", doi)
    return None


# ---------------------------------------------------------------------------
# Elsevier helper
# ---------------------------------------------------------------------------

def _year_from_elsevier(doi: str, api_key: str) -> int | None:
    """
    Query the Elsevier Abstract Retrieval API and return the publication year,
    or None on failure.  Rate-limits itself to ≤ 1.4 req/s.
    """
    _elsevier_rate_limit()

    url = f"https://api.elsevier.com/content/abstract/doi/{doi}"
    headers = {"X-ELS-APIKey": api_key, "Accept": "application/json"}
    _log.debug("Elsevier request: GET %s", url)

    try:
        resp = requests.get(url, headers=headers, timeout=ELSEVIER_TIMEOUT)
    except requests.Timeout:
        _log.warning("Elsevier request timed out for DOI %s", doi)
        return None
    except requests.RequestException as exc:
        _log.warning("Elsevier request failed for DOI %s: %s", doi, exc)
        return None

    _log.debug("Elsevier response: HTTP %s", resp.status_code)

    if resp.status_code == 404:
        _log.info("Elsevier: DOI %s not found (404)", doi)
        return None

    if resp.status_code == 401:
        _log.error("Elsevier: invalid or missing API key for DOI %s", doi)
        return None

    if resp.status_code == 429:
        retry_after = resp.headers.get("Retry-After", "?")
        _log.warning("Elsevier: rate-limit hit (429) for DOI %s (Retry-After: %s)", doi, retry_after)
        return None

    if not resp.ok:
        _log.warning("Elsevier: HTTP %s for DOI %s", resp.status_code, doi)
        return None

    try:
        data = resp.json()
    except ValueError as exc:
        _log.warning("Elsevier: JSON decode error for DOI %s: %s", doi, exc)
        return None

    # Navigate: abstracts-retrieval-response → coredata → prism:coverDate
    core = (data.get("abstracts-retrieval-response") or {}).get("coredata") or {}

    cover_date = core.get("prism:coverDate") or core.get("prism:coverDisplayDate") or ""
    if isinstance(cover_date, str) and len(cover_date) >= 4:
        year_str = cover_date[:4]
        if year_str.isdigit():
            year = int(year_str)
            _log.info("Elsevier: found year %d (coverDate=%s) for DOI %s", year, cover_date, doi)
            return year

    _log.info("Elsevier: no year found in response for DOI %s", doi)
    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_year(doi: str) -> tuple[int | None, str]:
    """
    Return ``(year, source_label)`` where *source_label* describes which API
    produced the result, or ``(None, error_message)`` on complete failure.
    """
    doi = doi.strip()

    # 1. Crossref (primary)
    year = _year_from_crossref(doi)
    if year is not None:
        return year, "Crossref API (free, generous rate limits)"

    # 2. Elsevier (fallback)
    api_key = os.getenv("ELSEVIER_API_KEY")
    if not api_key:
        return None, "Crossref returned no result and ELSEVIER_API_KEY is not set"

    year = _year_from_elsevier(doi, api_key)
    if year is not None:
        return year, "Elsevier API (rate-limited: 5 000 req/h)"

    return None, "Both Crossref and Elsevier returned no publication year for this DOI"


# ---------------------------------------------------------------------------
# CLI presentation
# ---------------------------------------------------------------------------

_BOX_WIDTH = 52  # inner width of the result box


def _print_result(doi: str, year: int | None, source: str) -> None:
    top    = "┌" + "─" * _BOX_WIDTH + "┐"
    mid    = "├" + "─" * _BOX_WIDTH + "┤"
    bottom = "└" + "─" * _BOX_WIDTH + "┘"

    indent = 2
    label_width = 10
    value_indent = indent + label_width  # column where value text starts

    def rows(label: str, value: str) -> list[str]:
        """Return one or more box rows, wrapping long values without truncation."""
        max_value_width = _BOX_WIDTH - value_indent
        # Split value into chunks that fit the available width; break long words
        words = value.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = (current + " " + word).lstrip() if current else word
            if len(candidate) <= max_value_width:
                current = candidate
            else:
                if current:
                    lines.append(current)
                # Break a word that is longer than the available width across lines
                while len(word) > max_value_width:
                    lines.append(word[:max_value_width])
                    word = word[max_value_width:]
                current = word
        if current:
            lines.append(current)
        if not lines:
            lines = [""]

        result = []
        for i, line in enumerate(lines):
            if i == 0:
                content = " " * indent + f"{label:<{label_width}}" + line
            else:
                content = " " * value_indent + line
            result.append("│" + content.ljust(_BOX_WIDTH) + "│")
        return result

    print(top)
    for line in rows("DOI:", doi):
        print(line)
    print(mid)
    if year is not None:
        for line in rows("Year:", str(year)):
            print(line)
        for line in rows("Source:", source):
            print(line)
    else:
        for line in rows("Year:", "NOT FOUND"):
            print(line)
        for line in rows("Reason:", source):
            print(line)
    print(bottom)


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python get_year_from_doi.py <DOI>", file=sys.stderr)
        print("Example: python get_year_from_doi.py 10.1038/nature12373", file=sys.stderr)
        sys.exit(1)

    doi = sys.argv[1].strip()

    if not doi:
        print("Error: DOI argument is empty.", file=sys.stderr)
        sys.exit(1)

    # Basic sanity check: a DOI starts with "10."
    if not doi.startswith("10."):
        print(f"Warning: '{doi}' does not look like a valid DOI (should start with '10.').",
              file=sys.stderr)

    print(f"DOI: {doi}")
    print("Querying APIs…")

    year, source = get_year(doi)

    # Inline success/failure indication before the table
    if year is not None:
        print(f"✓ Year = {year}  |  Source: {source}")
    else:
        print(f"✗ Could not retrieve year: {source}", file=sys.stderr)

    print()
    _print_result(doi, year, source)

    if year is None:
        sys.exit(2)


if __name__ == "__main__":
    main()
