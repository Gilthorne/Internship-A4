#!/usr/bin/env python3
import os
import json
import re
import sys
import time
import urllib.parse
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl
from concurrent.futures import ThreadPoolExecutor, as_completed

import mysql.connector as sql
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELSEVIER_API_KEY")
JSON_PATH = "ResearchTestLinks.json"
NUM_WORKERS = 4

CURRENT_PAPER = None

# ================== Utils ==================

def get_db_connection():
    return sql.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        autocommit=False,
    )


def extract_doi_from_link(doi_link: str) -> str | None:
    if not doi_link:
        return None
    parsed = urllib.parse.urlparse(doi_link)
    path = parsed.path.lstrip("/")
    if path:
        return path
    parts = doi_link.split("doi.org/", 1)
    if len(parts) == 2 and parts[1]:
        return parts[1].lstrip("/")
    return None


def http_get_with_retries(session: requests.Session, url: str, headers: dict, max_retries: int = 5) -> requests.Response | None:
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, headers=headers)
            if 500 <= r.status_code < 600:
                last_err = requests.HTTPError(f"HTTP {r.status_code}")
                if attempt < max_retries:
                    time.sleep(3*attempt)
                    continue
                break
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            last_err = e
            if not (e.response is not None and 500 <= e.response.status_code < 600):
                return None
        except Exception as e:
            last_err = e
            return None
    print(f"[HTTP] {url}: giving up after retries ({last_err})", file=sys.stderr)
    return None


def make_session() -> requests.Session:
    return requests.Session()


# ================== STEP 1: JSON -> CLASSIFICATION ==================

def step1_load_classification():
    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            links = json.load(f)
    except Exception as e:
        print(f"[STEP1] cannot read {JSON_PATH}: {e}", file=sys.stderr)
        return

    entries = [e for e in links if e.get("doi_link")]

    db = get_db_connection()
    cur = db.cursor()

    select_sql = "SELECT id FROM CLASSIFICATION WHERE DOI = %s"
    insert_sql = (
        "INSERT INTO CLASSIFICATION (title, Authors, DOI, Open_Access, Has_data, DONE) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )

    for entry in entries:
        doi = extract_doi_from_link(entry.get("doi_link"))
        title = entry.get("title") or "N/A"
        if not doi:
            continue

        try:
            cur.execute(select_sql, (doi,))
            if cur.fetchone():
                continue
            cur.execute(insert_sql, (title, "", doi, False, False, False))
            db.commit()
            print(f"[STEP1] Inserted {doi}")
        except Exception as e:
            db.rollback()
            print(f"[STEP1] Error inserting {doi}: {e}", file=sys.stderr)

    cur.close()
    db.close()


# ================== STEP 2: Article API -> EXTRACTION ==================

PATTERNS = [
    r"\b\w+\.csv\b",
    r"\b\w+\.xlsx?\b",
    r"https?://(?:dx\.)?doi\.org/10\.\d{4,9}/zenodo\.\d+\b",
    r"https?://data.mendeley\.com/datasets/[^\s\"]+",
    r"https?://github\.com/[^\s\"]+",
    r"https?://zenodo\.org/[^\s\"]+",
    r"https?://(?:www\.)?elsevier\.com/[^\s\"]+",
]

IGNORED_LINKS = {
    "http://www.elsevier.com/open-access/userlicense/1.0/",
    "https://www.elsevier.com/locate/withdrawalpolicy",
    "https://www.elsevier.com/about/policies/article-withdrawal",
}


def extract_data_files(text: str):
    found = []
    for p in PATTERNS:
        found.extend(re.findall(p, text, re.IGNORECASE))
    normalized = [x.rstrip(".,);]") for x in found]
    seen, out = set(), []
    for x in normalized:
        if x.lower() in IGNORED_LINKS:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def map_files_to_elsevier_objects(files, objects_section):
    import os
    if not objects_section:
        return files
    if isinstance(objects_section, dict):
        multimedia_objects = [objects_section]
    else:
        multimedia_objects = list(objects_section)

    ref_to_url = {}
    for obj in multimedia_objects:
        if not isinstance(obj, dict):
            continue
        ref = obj.get("@ref")
        href = obj.get("$")
        if isinstance(ref, str) and href:
            ref_to_url[ref] = href

    out = []
    for f in files:
        base = os.path.splitext(os.path.basename(f))[0]
        out.append(ref_to_url.get(base, f))
    return out


def make_elsevier_object_download_url(api_url: str) -> str:
    import os
    try:
        parsed = urlparse(api_url)
    except Exception:
        return api_url
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in (".xlsx", ".xls"):
        mime = "application/excel"
    elif ext == ".csv":
        mime = "text/csv"
    else:
        return api_url
    query = dict(parse_qsl(parsed.query))
    query["view"] = "STANDARD"
    query["httpAccept"] = mime
    return urlunparse(parsed._replace(query=urlencode(query)))


def process_one_paper_step2(row, worker_id: int):
    global CURRENT_PAPER
    pid, title, doi, done = row
    start = time.time()
    CURRENT_PAPER = {"pid": pid, "doi": doi, "title": title, "worker": worker_id}

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        if done:
            print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: DONE, skip")
            return

        if not API_KEY:
            print("[STEP2] ELSEVIER_API_KEY missing", file=sys.stderr)
            return

        url = "https://api.elsevier.com/content/article/doi/" + urllib.parse.quote(doi)
        resp = http_get_with_retries(session, url, {"X-ELS-APIKey": API_KEY, "Accept": "application/json"})
        if not resp:
            print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: no response")
            return

        try:
            data = resp.json()
        except Exception as e:
            print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: JSON error {e}")
            return

        ftr = data.get("full-text-retrieval-response")
        if not isinstance(ftr, dict):
            print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: no full-text-retrieval-response")
            return

        core = ftr.get("coredata") or {}
        if not isinstance(core, dict):
            print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: no coredata")
            return

        # Authors
        authors = []
        dc_creator = core.get("dc:creator")
        if isinstance(dc_creator, list):
            for item in dc_creator:
                if isinstance(item, dict):
                    name = item.get("$")
                    if isinstance(name, str) and name.strip():
                        authors.append(name.strip())
                elif isinstance(item, str) and item.strip():
                    authors.append(item.strip())
        elif isinstance(dc_creator, str) and dc_creator.strip():
            authors.append(dc_creator.strip())
        creator = core.get("creator")
        if not authors:
            if isinstance(creator, str) and creator.strip():
                authors.append(creator.strip())
            elif isinstance(creator, list):
                for c in creator:
                    if isinstance(c, str) and c.strip():
                        authors.append(c.strip())
        uniq_authors, seen = [], set()
        for a in authors:
            if a and a not in seen:
                seen.add(a)
                uniq_authors.append(a)
        authors_str = "; ".join(uniq_authors)

        # Open access
        open_access = False
        if str(core.get("openaccessArticle", "")).lower() == "true":
            open_access = True
        elif str(core.get("openaccess", "")) == "1":
            open_access = True

        # Data links
        content_text = resp.text
        files = extract_data_files(content_text)
        objects_section = ftr.get("objects", {}).get("object")
        if objects_section:
            files = map_files_to_elsevier_objects(files, objects_section)
        files = [
            make_elsevier_object_download_url(f)
            if isinstance(f, str) and "api.elsevier.com/content/object/eid/" in f
            else f
            for f in files
        ]
        has_data = bool(files)

        # Update CLASSIFICATION
        cur.execute(
            "UPDATE CLASSIFICATION SET Authors=%s, Open_Access=%s, Has_data=%s, DONE=%s WHERE id=%s",
            (authors_str, open_access, has_data, True, pid),
        )
        db.commit()

        # EXTRACTION
        if has_data:
            cur.executemany(
                "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)",
                [(pid, f"https://doi.org/{doi}", link, 0) for link in files],
            )
            db.commit()

        print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: has_data={has_data} ({time.time()-start:.1f}s)")

    except Exception as e:
        db.rollback()
        print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
    finally:
        cur.close()
        db.close()


def step2_extract_data_links():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, title, DOI, DONE FROM CLASSIFICATION")
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(process_one_paper_step2, row, idx % NUM_WORKERS)
            for idx, row in enumerate(rows)
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP2] worker error: {e}", file=sys.stderr)


# ================== STEP 3: verify data_link ==================

def is_data_link_downloadable(link: str, session: requests.Session) -> bool:
    if not isinstance(link, str) or not link.strip():
        return False
    if "api.elsevier.com/content/object/eid/" not in link:
        return False
    url = make_elsevier_object_download_url(link)
    resp = http_get_with_retries(session, url, {"X-ELS-APIKey": API_KEY, "Accept": "*/*"})
    if not resp or resp.status_code != 200:
        return False

    ctype = (resp.headers.get("Content-Type") or "").lower()
    clen = resp.headers.get("Content-Length")
    try:
        clen_int = int(clen) if clen is not None else None
    except ValueError:
        clen_int = None
    if clen_int is not None and clen_int <= 0:
        return False

    sample = resp.content[:256]

    if (
        "application/excel" in ctype
        or "application/vnd.ms-excel" in ctype
        or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in ctype
    ):
        return bool(sample) and (
            sample.startswith(b"PK\x03\x04") or sample.startswith(b"\xD0\xCF\x11\xE0")
        )

    if "text/csv" in ctype or "text/plain" in ctype:
        text_sample = sample.decode("utf-8", errors="ignore").strip()
        if not text_sample:
            return False
        lower = text_sample.lower()
        if lower.startswith("<html") or lower.startswith("<!doctype html") or lower.startswith("<service-error"):
            return False
        return True

    return False


def _process_one_link_step3(row, worker_id: int):
    pid, link = row
    db = get_db_connection()
    cur = db.cursor()
    session = make_session()
    try:
        ok = is_data_link_downloadable(link, session)
        cur.execute("UPDATE EXTRACTION SET done=%s WHERE pid=%s AND data_link=%s", (int(ok), pid, link))
        db.commit()
        print(f"[STEP3][{worker_id}] PID {pid} link {link}: {ok}")
    except Exception as e:
        db.rollback()
        print(f"[STEP3][{worker_id}] PID {pid} link {link}: ERROR {e}", file=sys.stderr)
    finally:
        cur.close()
        db.close()


def step3_check_downloadable():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT pid, data_link FROM EXTRACTION WHERE done = 0")
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(_process_one_link_step3, row, idx % NUM_WORKERS)
            for idx, row in enumerate(rows)
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP3] worker error: {e}", file=sys.stderr)


# ================== STEP 4: Abstract API -> enrich CLASSIFICATION ==================

def fetch_abstract_by_doi(session: requests.Session, doi: str) -> dict | None:
    if not API_KEY:
        return None
    url = "https://api.elsevier.com/content/abstract/doi/" + urllib.parse.quote(doi)
    resp = http_get_with_retries(session, url, {"X-ELS-APIKey": API_KEY, "Accept": "application/json"})
    if not resp:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def extract_countries_from_abstract(data: dict) -> list[str]:
    countries: set[str] = set()
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    ag = head.get("author-group") or []
    if isinstance(ag, dict):
        ag = [ag]
    for g in ag:
        aff = g.get("affiliation") or {}
        if isinstance(aff, dict):
            aff = [aff]
        for a in aff:
            c = a.get("country")
            if isinstance(c, str) and c.strip():
                countries.add(c.strip())
    return sorted(countries)


def extract_organizations_from_abstract(data: dict) -> list[str]:
    orgs: set[str] = set()
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    ag = head.get("author-group") or []
    if isinstance(ag, dict):
        ag = [ag]
    for g in ag:
        aff = g.get("affiliation") or {}
        if isinstance(aff, dict):
            aff = [aff]
        for a in aff:
            org_list = a.get("organization") or []
            if isinstance(org_list, dict):
                org_list = [org_list]
            for o in org_list:
                if isinstance(o, dict):
                    name = o.get("$")
                    if isinstance(name, str) and name.strip():
                        orgs.add(name.strip())
    return sorted(orgs)


def extract_publication_year_from_abstract(data: dict) -> int | None:
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    source = head.get("source") or {}
    pubdate = source.get("publicationdate") or {}
    year_str = pubdate.get("year")
    if isinstance(year_str, str) and year_str.isdigit():
        return int(year_str)
    return None


def _process_one_paper_step4(row, worker_id: int):
    pid, doi = row
    if not doi:
        return
    db = get_db_connection()
    cur = db.cursor()
    session = make_session()
    try:
        data = fetch_abstract_by_doi(session, doi)
        if not data:
            return
        year = extract_publication_year_from_abstract(data)
        countries = extract_countries_from_abstract(data)
        orgs = extract_organizations_from_abstract(data)
        country_str = "; ".join(countries) if countries else None
        org_str = "; ".join(orgs) if orgs else None

        cur.execute(
            "UPDATE CLASSIFICATION SET Year=%s, Country=%s, Organization=%s WHERE id=%s",
            (year, country_str, org_str, pid),
        )
        db.commit()
        print(f"[STEP4][{worker_id}] PID {pid} DOI {doi}")
    except Exception as e:
        db.rollback()
        print(f"[STEP4][{worker_id}] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
    finally:
        cur.close()
        db.close()


def step4_enrich_with_abstract():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, DOI FROM CLASSIFICATION")
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(_process_one_paper_step4, row, idx % NUM_WORKERS)
            for idx, row in enumerate(rows)
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP4] worker error: {e}", file=sys.stderr)


# ================== Main ==================

def main():
    try:
        print("=== STEP 1 ===")
        step1_load_classification()
        print("=== STEP 2 ===")
        step4_enrich_with_abstract()
        print("=== STEP 3 ===")
        step2_extract_data_links()
        print("=== STEP 4 ===")
        step3_check_downloadable()
        print("=== ALL STEPS DONE ===")
    except KeyboardInterrupt:
        print("\nKeyboard interrupt.", file=sys.stderr)
        if CURRENT_PAPER:
            print(f"Last paper: {CURRENT_PAPER}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        if CURRENT_PAPER:
            print(f"Last paper: {CURRENT_PAPER}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()