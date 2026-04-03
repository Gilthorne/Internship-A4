#!/usr/bin/env python3
"""
get_year_from_doi.py – Extract publication metadata (year, authors, countries) from a DOI.

Primary  : Crossref API (free, no authentication required)
           → returns year + authors; country is not available via Crossref.
Fallback : Elsevier API (requires ELSEVIER_API_KEY; rate-limit respected)
           → returns year + authors + countries from a single request.

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

def _metadata_from_crossref(doi: str) -> dict | None:
    """
    Query the Crossref API and return a metadata dict, or None on failure.

    Returned dict keys:
        year      (int | None)
        authors   (list[str])  – "Family Given" formatted names
        countries (list[str])  – always empty; Crossref does not expose country data

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

    # --- Year ---
    year: int | None = None
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
            _log.info("Crossref: year=%d (field=%s) for DOI %s", year, date_key, doi)
            break

    # --- Authors ---
    # Each item: {"given": "...", "family": "...", "affiliation": [...]}
    authors: list[str] = []
    for author in message.get("author") or []:
        if not isinstance(author, dict):
            continue
        family = (author.get("family") or "").strip()
        given  = (author.get("given")  or "").strip()
        if family and given:
            authors.append(f"{family} {given}")
        elif family:
            authors.append(family)
        elif given:
            authors.append(given)

    _log.info("Crossref: %d authors found for DOI %s", len(authors), doi)
    return {"year": year, "authors": authors, "countries": []}


# ---------------------------------------------------------------------------
# Elsevier helper
# ---------------------------------------------------------------------------

def _metadata_from_elsevier(doi: str, api_key: str) -> dict | None:
    """
    Query the Elsevier Abstract Retrieval API and return a metadata dict,
    or None on failure.  Rate-limits itself to ≤ 5 000 req/h.

    Returned dict keys:
        year      (int | None)
        authors   (list[str])  – "Family Given" formatted names
        countries (list[str])  – unique countries from affiliation data
                                 (available in the same response, no extra call)
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

    arr = data.get("abstracts-retrieval-response") or {}

    # --- Year (from coredata) ---
    core = arr.get("coredata") or {}
    year: int | None = None
    cover_date = core.get("prism:coverDate") or core.get("prism:coverDisplayDate") or ""
    if isinstance(cover_date, str) and len(cover_date) >= 4:
        year_str = cover_date[:4]
        if year_str.isdigit():
            year = int(year_str)
            _log.info("Elsevier: year=%d (coverDate=%s) for DOI %s", year, cover_date, doi)

    # --- Authors ---
    # Path: abstracts-retrieval-response → authors → author (list or dict)
    authors: list[str] = []
    authors_section = arr.get("authors") or {}
    raw_authors = authors_section.get("author") or []
    if isinstance(raw_authors, dict):
        raw_authors = [raw_authors]
    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        # Prefer preferred-name block; fall back to top-level fields
        pref = author.get("preferred-name") or author
        surname   = (pref.get("ce:surname")     or "").strip()
        given     = (pref.get("ce:given-name")  or
                     pref.get("ce:initials")    or "").strip()
        if surname and given:
            authors.append(f"{surname} {given}")
        elif surname:
            authors.append(surname)
        elif given:
            authors.append(given)
    _log.info("Elsevier: %d authors found for DOI %s", len(authors), doi)

    # --- Countries (same response, no extra API call) ---
    # Path: abstracts-retrieval-response → affiliation (list or dict)
    countries: list[str] = []
    raw_affiliations = arr.get("affiliation") or []
    if isinstance(raw_affiliations, dict):
        raw_affiliations = [raw_affiliations]
    seen_countries: set[str] = set()
    for aff in raw_affiliations:
        if not isinstance(aff, dict):
            continue
        country = (aff.get("affiliation-country") or "").strip()
        if country and country not in seen_countries:
            seen_countries.add(country)
            countries.append(country)
    _log.info("Elsevier: %d countries found for DOI %s", len(countries), doi)

    return {"year": year, "authors": authors, "countries": countries}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_metadata(doi: str) -> tuple[dict, str]:
    """
    Return ``(metadata_dict, source_label)``.

    *metadata_dict* always contains:
        year      (int | None)
        authors   (list[str])
        countries (list[str])  – empty when Crossref is used (not available)

    *source_label* describes which API produced the result,
    or an error message if both APIs failed.
    """
    doi = doi.strip()

    # 1. Crossref (primary)
    meta = _metadata_from_crossref(doi)
    if meta is not None and meta.get("year") is not None:
        return meta, "Crossref API (free, generous rate limits)"

    # Keep Crossref partial results (authors found but no year) as a fallback pool
    crossref_partial = meta  # may be None

    # 2. Elsevier (fallback)
    api_key = os.getenv("ELSEVIER_API_KEY")
    if api_key:
        els_meta = _metadata_from_elsevier(doi, api_key)
        if els_meta is not None:
            # Merge: use Crossref authors if Elsevier returned none
            if not els_meta["authors"] and crossref_partial:
                els_meta["authors"] = crossref_partial.get("authors", [])
            return els_meta, "Elsevier API (rate-limited: 5 000 req/h)"

    # Both failed or only Crossref partial data available
    if crossref_partial is not None:
        # We have authors but no year; return what we have
        label = (
            "Crossref API – authors only (year not found; "
            + ("ELSEVIER_API_KEY not set" if not api_key else "Elsevier also failed")
            + ")"
        )
        return crossref_partial, label

    empty: dict = {"year": None, "authors": [], "countries": []}
    if not api_key:
        return empty, "Crossref returned no result and ELSEVIER_API_KEY is not set"
    return empty, "Both Crossref and Elsevier returned no metadata for this DOI"


# ---------------------------------------------------------------------------
# CLI presentation
# ---------------------------------------------------------------------------

_BOX_WIDTH = 68  # inner width of the result box (wider to fit author names)


def _print_result(doi: str, meta: dict, source: str) -> None:
    year      = meta.get("year")
    authors   = meta.get("authors") or []
    countries = meta.get("countries") or []

    top    = "┌" + "─" * _BOX_WIDTH + "┐"
    mid    = "├" + "─" * _BOX_WIDTH + "┤"
    bottom = "└" + "─" * _BOX_WIDTH + "┘"

    indent = 2
    label_width = 12
    value_indent = indent + label_width

    def rows(label: str, value: str) -> list[str]:
        """Return one or more box rows, wrapping long values without truncation."""
        max_value_width = _BOX_WIDTH - value_indent
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
            content = " " * (indent if i == 0 else value_indent)
            if i == 0:
                content += f"{label:<{label_width}}" + line
            else:
                content += line
            result.append("│" + content.ljust(_BOX_WIDTH) + "│")
        return result

    # Format authors as "Family G; Family G; ..." — truncate list display at 5
    MAX_AUTHORS_SHOWN = 5
    if authors:
        shown = authors[:MAX_AUTHORS_SHOWN]
        authors_str = "; ".join(shown)
        if len(authors) > MAX_AUTHORS_SHOWN:
            authors_str += f" … (+{len(authors) - MAX_AUTHORS_SHOWN} more)"
    else:
        authors_str = "N/A"

    countries_str = "; ".join(countries) if countries else "N/A (not available via this API)"

    print(top)
    for line in rows("DOI:", doi):
        print(line)
    print(mid)
    for line in rows("Year:", str(year) if year is not None else "NOT FOUND"):
        print(line)
    for line in rows("Authors:", authors_str):
        print(line)
    for line in rows("Countries:", countries_str):
        print(line)
    for line in rows("Source:", source):
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

    if not doi.startswith("10."):
        print(f"Warning: '{doi}' does not look like a valid DOI (should start with '10.').",
              file=sys.stderr)

    print(f"DOI: {doi}")
    print("Querying APIs…")

    meta, source = get_metadata(doi)

    year      = meta.get("year")
    authors   = meta.get("authors") or []
    countries = meta.get("countries") or []

    if year is not None:
        print(f"✓ Year = {year}  |  Authors: {len(authors)}  |  Countries: {len(countries) or 'N/A'}  |  Source: {source}")
    else:
        print(f"✗ Year not found. Authors: {len(authors)}  |  Source: {source}", file=sys.stderr)

    print()
    _print_result(doi, meta, source)

    if year is None:
        sys.exit(2)


if __name__ == "__main__":
    main()
