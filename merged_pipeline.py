#!/usr/bin/env python3
import os
import json
import re
import sys
import time
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl, quote
from concurrent.futures import ThreadPoolExecutor, as_completed

import mysql.connector as sql
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELSEVIER_API_KEY")
JSON_PATH = "ResearchTestLinks.json"
NUM_WORKERS = 4

CURRENT_PAPER = None

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # optionnel

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
    parsed = urlparse(doi_link)
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
            r = session.get(url, headers=headers, timeout=30)
            if 500 <= r.status_code < 600:
                last_err = requests.HTTPError(f"HTTP {r.status_code}")
                if attempt < max_retries:
                    time.sleep(3 * attempt)
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


def detect_source_website(link: str) -> str:
    if not isinstance(link, str):
        return "other"
    low = link.lower()
    if "github.com" in low:
        return "github"
    if "zenodo.org" in low or ("doi.org/10." in low and "/zenodo." in low):
        return "zenodo"
    if "data.mendeley.com" in low:
        return "mendeley"
    if "api.elsevier.com" in low or "elsevier.com" in low:
        return "elsevier"
    return "other"


# ================== Common Elsevier helpers ==================

def fetch_elsevier_json(endpoint: str, doi: str, session: requests.Session) -> dict | None:
    """endpoint: 'article' ou 'abstract'."""
    if not API_KEY or not doi:
        return None
    url = f"https://api.elsevier.com/content/{endpoint}/doi/" + quote(doi)
    resp = http_get_with_retries(session, url, {"X-ELS-APIKey": API_KEY, "Accept": "application/json"})
    if not resp:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def parse_authors_from_coredata(core: dict) -> str:
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

    uniq, seen = [], set()
    for a in authors:
        if a and a not in seen:
            seen.add(a)
            uniq.append(a)
    return "; ".join(uniq)


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


# ================== STEP 2: Abstract API -> enrich CLASSIFICATION ==================

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


def _process_one_paper_step2(row, worker_id: int):
    pid, doi = row
    if not doi:
        return

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        data = fetch_elsevier_json("abstract", doi, session)
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
        print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}")
    except Exception as e:
        db.rollback()
        print(f"[STEP2][{worker_id}] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
    finally:
        cur.close()
        db.close()


def step2_enrich_with_abstract():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, DOI FROM CLASSIFICATION")
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(_process_one_paper_step2, row, idx % NUM_WORKERS)
            for idx, row in enumerate(rows)
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP2] worker error: {e}", file=sys.stderr)


# ================== STEP 3: Article API -> EXTRACTION ==================

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


def split_data_vs_other_links(links):
    exts = (".csv", ".xls", ".xlsx", ".json")
    data_files = []
    other_links = []
    for link in links:
        if not isinstance(link, str):
            other_links.append(link)
            continue
        low = link.lower()
        if any(low.endswith(ext) for ext in exts):
            data_files.append(link)
        else:
            other_links.append(link)
    return data_files, other_links


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


# ------- Zenodo helpers -------

def zenodo_record_id(s: str) -> str | None:
    s = s.strip()
    m = re.search(r"zenodo\.(\d+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    if s.startswith("http"):
        p = urlparse(s)
        parts = p.path.strip("/").split("/")
        if len(parts) >= 2 and parts[-2] in {"record", "records"} and parts[-1].isdigit():
            return parts[-1]
    return None


def api_link_to_front_download(url: str) -> str:
    if "/api/records/" not in url or "/files/" not in url:
        return url
    base = url.replace("/api/records/", "/records/")
    if base.endswith("/content"):
        base = base[: -len("/content")]
    return base + "?download=1"


def zenodo_data_files_from_link(link: str):
    rec_id = zenodo_record_id(link)
    if not rec_id:
        return []
    try:
        r = requests.get(f"https://zenodo.org/api/records/{rec_id}", timeout=20)
        r.raise_for_status()
    except Exception:
        return []

    exts = (".csv", ".xls", ".xlsx", ".json")
    out = []
    for f in r.json().get("files", []):
        name = f.get("key") or f.get("filename") or ""
        if not any(name.lower().endswith(ext) for ext in exts):
            continue
        links = f.get("links") or {}
        api_url = links.get("download") or links.get("self") or ""
        if not api_url:
            continue
        front_url = api_link_to_front_download(api_url)
        out.append(front_url)
    return out


# ------- GitHub helpers -------

def parse_github_repo(arg: str):
    if arg.startswith("http"):
        p = urlparse(arg)
        parts = p.path.strip("/").split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            if repo.endswith(".git"):
                repo = repo[:-4]
            return owner, repo
    if "/" in arg and not arg.startswith("http"):
        owner, repo = arg.split("/", 1)
        return owner, repo
    return None, None


def gh_get(path, params=None):
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    r = requests.get(GITHUB_API + path, headers=headers, params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def github_data_files_from_link(link: str):
    owner, repo = parse_github_repo(link)
    if not owner or not repo:
        return []

    try:
        repo_info = gh_get(f"/repos/{owner}/{repo}")
        ref = repo_info.get("default_branch", "main")
        tree = gh_get(f"/repos/{owner}/{repo}/git/trees/{ref}", params={"recursive": "1"})
    except Exception:
        return []

    exts = (".csv", ".xls", ".xlsx", ".json")
    data_paths = [
        e["path"] for e in tree.get("tree", [])
        if e.get("type") == "blob" and e.get("path", "").lower().endswith(exts)
    ]

    return [f"https://github.com/{owner}/{repo}/blob/{ref}/{p}" for p in data_paths]


def process_one_paper_step3(row, worker_id: int):
    global CURRENT_PAPER
    pid, title, doi, done = row
    start = time.time()
    CURRENT_PAPER = {"pid": pid, "doi": doi, "title": title, "worker": worker_id}

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        if done:
            print(f"[STEP3][{worker_id}] PID {pid} DOI {doi}: DONE, skip")
            return

        data = fetch_elsevier_json("article", doi, session)
        if not data:
            print(f"[STEP3][{worker_id}] PID {pid} DOI {doi}: no response")
            return

        ftr = data.get("full-text-retrieval-response")
        if not isinstance(ftr, dict):
            print(f"[STEP3][{worker_id}] PID {pid} DOI {doi}: no full-text-retrieval-response")
            return

        core = ftr.get("coredata") or {}
        if not isinstance(core, dict):
            print(f"[STEP3][{worker_id}] PID {pid} DOI {doi}: no coredata")
            return

        # Authors & Open access
        authors_str = parse_authors_from_coredata(core)
        open_access = (
            str(core.get("openaccessArticle", "")).lower() == "true"
            or str(core.get("openaccess", "")) == "1"
        )

        # Extraction des liens dans le texte
        content_text = session.get(  # on réutilise le texte brut
            f"https://api.elsevier.com/content/article/doi/{quote(doi)}",
            headers={"X-ELS-APIKey": API_KEY, "Accept": "application/json"},
            timeout=30,
        ).text
        links = extract_data_files(content_text)

        # Map mmcX.* vers objets Elsevier
        objects_section = ftr.get("objects", {}).get("object")
        if objects_section:
            links = map_files_to_elsevier_objects(links, objects_section)

        # Normaliser les objets Elsevier (Object Retrieval)
        links = [
            make_elsevier_object_download_url(l)
            if isinstance(l, str) and "api.elsevier.com/content/object/eid/" in l
            else l
            for l in links
        ]

        # Séparation data-links / autres (sert à Has_data uniquement)
        data_files, _ = split_data_vs_other_links(links)
        has_data = bool(data_files)

        # Construction des lignes pour EXTRACTION: logique par source
        base_url = f"https://doi.org/{doi}"
        rows_to_insert = []

        for l in links:
            src = detect_source_website(l)

            if src == "github":
                gh_files = github_data_files_from_link(l)
                if gh_files:
                    for gf in gh_files:
                        rows_to_insert.append((pid, base_url, src, gf, False))
                else:
                    rows_to_insert.append((pid, base_url, src, l, False))

            elif src == "zenodo":
                zen_files = zenodo_data_files_from_link(l)
                if zen_files:
                    for zf in zen_files:
                        rows_to_insert.append((pid, base_url, src, zf, False))
                else:
                    rows_to_insert.append((pid, base_url, src, l, False))

            else:  # mendeley, elsevier, other
                rows_to_insert.append((pid, base_url, src, l, False))

        # Update CLASSIFICATION
        cur.execute(
            "UPDATE CLASSIFICATION SET Authors=%s, Open_Access=%s, Has_data=%s, DONE=%s WHERE id=%s",
            (authors_str, open_access, has_data, True, pid),
        )
        db.commit()

        # EXTRACTION
        if rows_to_insert:
            cur.executemany(
                "INSERT INTO EXTRACTION (pid, URL, source_website, data_link, done) "
                "VALUES (%s, %s, %s, %s, %s)",
                rows_to_insert,
            )
            db.commit()

        print(f"[STEP3][{worker_id}] PID {pid} DOI {doi}: has_data={has_data} ({time.time() - start:.1f}s)")

    except Exception as e:
        db.rollback()
        print(f"[STEP3][{worker_id}] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
    finally:
        cur.close()
        db.close()


def step3_extract_data_links():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, title, DOI, DONE FROM CLASSIFICATION")
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(process_one_paper_step3, row, idx % NUM_WORKERS)
            for idx, row in enumerate(rows)
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP3] worker error: {e}", file=sys.stderr)


# ================== STEP 4: verify data_link ==================

def is_data_link_downloadable(link: str, source: str, session: requests.Session) -> bool:
    if not isinstance(link, str) or not link.strip():
        return False

    # Elsevier objects
    if source == "elsevier" and "api.elsevier.com/content/object/eid/" in link:
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

    # Zenodo
    if source == "zenodo":
        try:
            resp = session.get(link, timeout=20)
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        ctype = (resp.headers.get("Content-Type") or "").lower()
        if "text/html" in ctype:
            return False
        return bool(resp.content)

    # GitHub
    if source == "github":
        try:
            resp = session.get(link, timeout=20)
        except Exception:
            return False
        return resp.status_code == 200

    # autres (mendeley, other) : pas testés
    return False


def _process_one_link_step4(row, worker_id: int):
    pid, link, source = row
    db = get_db_connection()
    cur = db.cursor()
    session = make_session()
    try:
        ok = is_data_link_downloadable(link, source, session)
        cur.execute(
            "UPDATE EXTRACTION SET done=%s WHERE pid=%s AND data_link=%s",
            (int(ok), pid, link),
        )
        db.commit()
        print(f"[STEP4][{worker_id}] PID {pid} source {source} link {link}: {ok}")
    except Exception as e:
        db.rollback()
        print(f"[STEP4][{worker_id}] PID {pid} link {link}: ERROR {e}", file=sys.stderr)
    finally:
        cur.close()
        db.close()


def step4_check_downloadable():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT pid, data_link, source_website FROM EXTRACTION WHERE done = 0")
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(_process_one_link_step4, row, idx % NUM_WORKERS)
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
        step2_enrich_with_abstract()
        print("=== STEP 3 ===")
        step3_extract_data_links()
        print("=== STEP 4 ===")
        step4_check_downloadable()
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