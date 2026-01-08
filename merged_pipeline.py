#!/usr/bin/python3
import os
import json
import re
import sys
import time
import logging
import threading
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl, quote, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed

import mysql.connector as sql
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELSEVIER_API_KEY")
JSON_PATH = "ResearchTestLinks.json"
NUM_WORKERS = 4

CURRENT_PAPER = None
CURRENT_DOI = None

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # optional


def setup_error_logging(err_file: str | None = None):
    # Créer le dossier error_log s'il n'existe pas
    log_dir = "error_log"
    os.makedirs(log_dir, exist_ok=True)
    
    if err_file is None:
        ts = time.strftime("%Y%m%d_%H%M%S")
        err_file = os.path.join(log_dir, f"error_log_{ts}.log")

    root = logging.getLogger()
    root.setLevel(logging.ERROR)
    root.handlers.clear()
    root.propagate = False

    fmt = logging.Formatter("%(asctime)s %(levelname)s: %(message)s")
    h = RotatingFileHandler(err_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    h.setLevel(logging.ERROR)
    h.setFormatter(fmt)
    root.addHandler(h)
    return logging.getLogger(__name__),err_file


logger, ERROR_LOG_FILE = setup_error_logging()


def log_doi_error(doi: str | None, err: Exception, context: str = ""):
    doi = doi or "N/A"
    if context:
        logger.error("DOI %s: %s:  %s", doi, context, err)
    else:
        logger.error("DOI %s: Error %s", doi, err)


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
    parts = doi_link.split("doi.org/",1)
    if len(parts) == 2 and parts[1]:
        return parts[1].lstrip("/")
    return None


def http_get_with_retries(
    session: requests.Session,
    url: str,
    headers: dict,
    max_retries: int = 5,
    doi: str | None = None,
) -> requests.Response | None:
    last_err = None
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, headers=headers, timeout=30)

            if r.status_code == 429:
                retry_after = r.headers.get("Retry-After")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = min(120.0, 5.0 * (2 ** (attempt - 1)))

                if attempt < max_retries:
                    time.sleep(delay)
                    continue

                log_doi_error(doi, requests.HTTPError(f"HTTP 429 Too Many Requests (gave up after {attempt} tries)"), "HTTP error")
                return None

            if 500 <= r.status_code < 600:
                last_err = requests.HTTPError(f"HTTP {r.status_code}")
                if attempt < max_retries: 
                    time.sleep(min(30.0, 2.0 * attempt))
                    continue
                break

            r.raise_for_status()
            return r

        except requests.HTTPError as e:
            last_err = e
            log_doi_error(doi, e, "HTTP error")
            return None
        except Exception as e:
            last_err = e
            log_doi_error(doi, e, "Request failed")
            return None

    msg = f"[HTTP] giving up after retries ({last_err})"
    print(f"[HTTP] {url}: {msg}", file=sys.stderr)
    log_doi_error(doi, Exception(msg), "HTTP retries exhausted")
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


def print_progress(prefix: str, current: int, total: int, bar_width: int = 50):
    if total <= 0:
        bar = "-" * bar_width
        msg = f"{prefix} [{bar}] {current}/?  (0. 0%)"
    else:
        ratio = max(0.0, min(1.0, current / total))
        filled = int(bar_width * ratio)
        bar = "#" * filled + "-" * (bar_width - filled)
        pct = 100.0 * ratio
        msg = f"{prefix} [{bar}] {current}/{total} ({pct:.1f}%)"

    sys.stdout.write("\r" + msg)
    sys.stdout.flush()
    if total > 0 and current >= total:
        sys.stdout.write("\n")
        sys.stdout.flush()


# ================== Common Elsevier helpers ==================

def fetch_elsevier_json(endpoint: str, doi: str, session: requests.Session) -> dict | None:
    if not API_KEY or not doi:
        return None
    url = f"https://api.elsevier.com/content/{endpoint}/doi/" + quote(doi)
    resp = http_get_with_retries(session, url, {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}, doi=doi)
    if not resp:
        return None
    try:
        return resp.json()
    except Exception as e: 
        log_doi_error(doi, e, f"JSON decode failed ({endpoint})")
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
        logger.error("DOI N/A:  STEP1 cannot read %s:  %s", JSON_PATH, e)
        return

    entries = [e for e in links if e.get("doi_link")]
    total = len(entries)
    done = 0

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
            done += 1
            print_progress("[STEP 1] Processing DOIs", done, total)
            continue

        try:
            cur.execute(select_sql, (doi,))
            if not cur.fetchone():
                cur.execute(insert_sql, (title, "", doi, False, False, False))
                db.commit()
        except Exception as e:
            db.rollback()
            print(f"[STEP1] Error inserting {doi}: {e}", file=sys.stderr)
            log_doi_error(doi, e, "STEP1 insert failed")

        done += 1
        print_progress("[STEP 1] Processing DOIs", done, total)

    cur.close()
    db.close()


# ================== STEP 2: Abstract API -> enrich CLASSIFICATION ==================

def _normalize_to_list(item):
    """Convertit un dict en liste contenant ce dict, ou retourne la liste telle quelle."""
    return [item] if isinstance(item, dict) else (item if isinstance(item, list) else [])

def _get_abstract_metadata(data: dict) -> dict:
    """Extrait les métadonnées communes de la réponse abstract."""
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    return {"head": head, "bib": bib}

def extract_countries_from_abstract(data: dict) -> list[str]:
    countries: set[str] = set()
    metadata = _get_abstract_metadata(data)
    author_groups = _normalize_to_list(metadata["head"].get("author-group"))
    
    for group in author_groups:
        affiliations = _normalize_to_list(group.get("affiliation"))
        for aff in affiliations:
            country = aff.get("country")
            if isinstance(country, str) and country.strip():
                countries.add(country.strip())
    return sorted(countries)

def extract_organizations_from_abstract(data: dict) -> list[str]:
    orgs: set[str] = set()
    metadata = _get_abstract_metadata(data)
    author_groups = _normalize_to_list(metadata["head"].get("author-group"))
    
    for group in author_groups:
        affiliations = _normalize_to_list(group.get("affiliation"))
        for aff in affiliations:
            org_list = _normalize_to_list(aff.get("organization"))
            for org in org_list:
                if isinstance(org, dict):
                    name = org.get("$")
                    if isinstance(name, str) and name.strip():
                        orgs.add(name.strip())
    return sorted(orgs)


def extract_publication_year_from_abstract(data: dict) -> int | None:
    metadata = _get_abstract_metadata(data)
    source = metadata["head"].get("source") or {}
    pubdate = source.get("publicationdate") or {}
    year_str = pubdate.get("year")
    return int(year_str) if isinstance(year_str, str) and year_str.isdigit() else None


def _with_db_and_progress(func):
    """Décorateur pour gérer la connexion DB, les erreurs et la progression."""
    def wrapper(row, worker_id: int, total: int, counter: dict, lock: threading.Lock, progress_msg: str):
        db = get_db_connection()
        cur = db.cursor()
        session = make_session()
        
        try:
            func(row, cur, session)
            db.commit()
        except Exception as e:
            db.rollback()
            doi = getattr(row, '__iter__', None) and len(row) > 1 and row[1] or "N/A"
            print(f"[{progress_msg}] ERROR: {e}", file=sys.stderr)
            log_doi_error(doi, e, progress_msg)
        finally:
            cur.close()
            db.close()
            with lock:
                counter["done"] += 1
                print_progress(f"[{progress_msg}]", counter["done"], total)
    return wrapper

def _process_one_paper_step2(row, worker_id: int, total: int, counter: dict, lock: threading.Lock):
    global CURRENT_DOI
    pid, doi = row
    CURRENT_DOI = doi

    if not doi:
        with lock:
            counter["done"] += 1
            print_progress("[STEP 2] Enriching abstracts", counter["done"], total)
        return

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        data = fetch_elsevier_json("abstract", doi, session)
        if data:
            year = extract_publication_year_from_abstract(data)
            countries = extract_countries_from_abstract(data)
            orgs = extract_organizations_from_abstract(data)

            cur.execute(
                "UPDATE CLASSIFICATION SET Year=%s, Country=%s, Organization=%s WHERE id=%s",
                (year, "; ".join(countries) if countries else None,
                 "; ".join(orgs) if orgs else None, pid),
            )
            db.commit()
    except Exception as e:
        db.rollback()
        print(f"[STEP2] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
        log_doi_error(doi, e, "STEP2 update failed")
    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 2] Enriching abstracts", counter["done"], total)


def step2_enrich_with_abstract():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, DOI FROM CLASSIFICATION WHERE Year IS NULL AND Country IS NULL AND Organization IS NULL")
    rows = cur.fetchall()
    cur.close()
    db.close()

    total = len(rows)
    counter = {"done": 0}
    lock = threading.Lock()

    ex = ThreadPoolExecutor(max_workers=NUM_WORKERS)
    futures = []
    try:
        for idx, row in enumerate(rows):
            futures.append(ex.submit(_process_one_paper_step2, row, idx % NUM_WORKERS, total, counter, lock))

        for f in as_completed(futures):
            f.result()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        msg = f"KeyboardInterrupt.  Last DOI: {CURRENT_DOI or 'N/A'} (error log: {ERROR_LOG_FILE})"
        print(msg, file=sys.stderr)
        logger.error("DOI %s: KeyboardInterrupt", CURRENT_DOI or "N/A")
        for f in futures:
            f.cancel()
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


# ================== STEP 3: Article API -> EXTRACTION ==================

def _clean_unicode_and_url(text: str) -> str:
    """Nettoie les caractères Unicode problématiques et les suffixes parasites d'une URL."""
    if not text:
        return text
    
    # Décoder les caractères URL-encodés
    text = unquote(text)
    
    # Retirer les caractères Unicode problématiques
    replacements = [
        ('\\u201c', ''), ('\\u201d', ''), ('\u201c', ''), ('\u201d', ''),
        ('\\u2019', ''), ('\u2019', ''), ('⟩', ''), ('〉', '')
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    
    # Retirer les suffixes parasites
    text = re.sub(r'\.(http:|https:).*$', '', text)
    text = re.sub(r'(date|Date|DATE)$', '', text)
    
    return text.strip()

PATTERNS = [
    r"\b\w+\. csv\b",
    r"\b\w+\.xlsx?\b",
    r"https?://(?:dx\.)?doi\.org/10\.\d{4,9}/zenodo\.\d+",
    r"https?://data\.mendeley\.com/datasets/[^\s\"'<>]+",
    r"https?://github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9._-]+(?:/[^\s\"'<>]*)?",
    r"https?://zenodo\.org/[^\s\"'<>]+",
    r"https?://(?:www\.)?elsevier\.com/[^\s\"'<>]+",
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
    
    # Normaliser et nettoyer les liens
    normalized = [_clean_unicode_and_url(x.rstrip(".,);]\"'")) for x in found]
    
    # Dédupliquer et filtrer les liens ignorés
    seen, out = set(), []
    for x in normalized:
        if x and x.lower() not in IGNORED_LINKS and x not in seen:
            seen.add(x)
            out.append(x)
    return out


DATA_FILE_EXTENSIONS = (".csv", ".xls", ".xlsx", ".json")

def is_data_file(link: str) -> bool:
    """Vérifie si un lien pointe vers un fichier de données."""
    return isinstance(link, str) and any(link.lower().endswith(ext) for ext in DATA_FILE_EXTENSIONS)

def split_data_vs_other_links(links):
    data_files = [link for link in links if is_data_file(link)]
    other_links = [link for link in links if not is_data_file(link)]
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


def make_elsevier_object_download_url(api_url:  str) -> str:
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
        base = base[:-len("/content")]
    return base + "?download=1"


def zenodo_data_files_from_link(link: str):
    rec_id = zenodo_record_id(link)
    if not rec_id:
        return []
    try:
        r = requests.get(f"https://zenodo.org/api/records/{rec_id}", timeout=20)
        r.raise_for_status()
    except Exception as e:
        logger.error("DOI N/A: Zenodo record fetch error: %s", e)
        return []

    out = []
    for f in r.json().get("files", []):
        name = f.get("key") or f.get("filename") or ""
        if not is_data_file(name):
            continue
        links = f.get("links") or {}
        api_url = links.get("download") or links.get("self")
        if api_url:
            out.append(api_link_to_front_download(api_url))
    return out


def parse_github_repo(arg: str):
    if not arg or not isinstance(arg, str):
        return None, None
    
    # Nettoyer l'URL
    arg = _clean_unicode_and_url(arg).rstrip('.,;:  /')
    
    if arg.startswith("http"):
        try:
            p = urlparse(arg)
            if 'github.com' not in p.netloc.lower():
                return None, None
            
            parts = p.path.strip("/").split("/")
            if len(parts) >= 2:
                owner, repo = parts[0], parts[1].removesuffix(".git")
                
                # Validation - rejeter si caractères invalides
                if owner and repo and not any(c in owner+repo for c in ['<', '>', '"', "'", ' ']):
                    return owner, repo
        except Exception: 
            return None, None
    elif "/" in arg:
        parts = arg.split("/", 1)
        if len(parts) == 2:
            owner = parts[0]
            repo = parts[1].split()[0] if ' ' in parts[1] else parts[1]
            if owner and repo:
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
    except Exception as e:
        logger.error("DOI N/A: GitHub listing error: %s", e)
        return []

    data_paths = [
        e["path"] for e in tree.get("tree", [])
        if e.get("type") == "blob" and is_data_file(e.get("path", ""))
    ]

    return [f"https://github.com/{owner}/{repo}/blob/{ref}/{p}" for p in data_paths]


def _process_one_paper_step3(row, worker_id: int, total: int, counter: dict, lock: threading.Lock):
    global CURRENT_PAPER, CURRENT_DOI
    pid, title, doi, done_flag = row
    CURRENT_DOI = doi
    CURRENT_PAPER = {"pid": pid, "doi": doi, "title": title, "worker": worker_id}

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        if done_flag:
            return

        data = fetch_elsevier_json("article", doi, session)
        if not data:
            return

        ftr = data.get("full-text-retrieval-response")
        if not isinstance(ftr, dict):
            return

        core = ftr.get("coredata") or {}
        if not isinstance(core, dict):
            return

        authors_str = parse_authors_from_coredata(core)
        open_access = (
            str(core.get("openaccessArticle", "")).lower() == "true"
            or str(core.get("openaccess", "")) == "1"
        )

        article_resp = http_get_with_retries(
            session,
            f"https://api.elsevier.com/content/article/doi/{quote(doi)}",
            {"X-ELS-APIKey": API_KEY, "Accept": "application/json"},
            doi=doi,
        )
        links = extract_data_files(article_resp.text) if article_resp else []

        objects_section = ftr.get("objects", {}).get("object")
        if objects_section: 
            links = map_files_to_elsevier_objects(links, objects_section)

        links = [
            make_elsevier_object_download_url(l)
            if isinstance(l, str) and "api.elsevier.com/content/object/eid/" in l
            else l
            for l in links
        ]

        data_files, _ = split_data_vs_other_links(links)
        has_data = bool(data_files)

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

            else:
                rows_to_insert.append((pid, base_url, src, l, False))

        cur.execute(
            "UPDATE CLASSIFICATION SET Authors=%s, Open_Access=%s, Has_data=%s, DONE=%s WHERE id=%s",
            (authors_str, open_access, has_data, True, pid),
        )
        db.commit()

        if rows_to_insert:
            cur.executemany(
                "INSERT INTO EXTRACTION (pid, URL, source_website, data_link, done) "
                "VALUES (%s, %s, %s, %s, %s)",
                rows_to_insert,
            )
            db.commit()

    except Exception as e: 
        db.rollback()
        print(f"[STEP3] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
        log_doi_error(doi, e, "STEP3 failed")
    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 3] Extracting data links", counter["done"], total)


def step3_extract_data_links():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, title, DOI, DONE FROM CLASSIFICATION WHERE DONE = 0")
    rows = cur.fetchall()
    cur.close()
    db.close()

    total = len(rows)
    counter = {"done": 0}
    lock = threading.Lock()

    ex = ThreadPoolExecutor(max_workers=NUM_WORKERS)
    futures = []
    try:
        for idx, row in enumerate(rows):
            futures.append(ex.submit(_process_one_paper_step3, row, idx % NUM_WORKERS, total, counter, lock))

        for f in as_completed(futures):
            f.result()
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        msg = f"KeyboardInterrupt. Last DOI: {CURRENT_DOI or 'N/A'} (error log: {ERROR_LOG_FILE})"
        print(msg, file=sys.stderr)
        logger.error("DOI %s: KeyboardInterrupt", CURRENT_DOI or "N/A")
        for f in futures:
            f.cancel()
        ex.shutdown(wait=False, cancel_futures=True)
        raise
    finally:
        ex.shutdown(wait=False, cancel_futures=True)


# ================== STEP 4: verify data_link ==================

def is_data_link_downloadable(link: str, source: str, session: requests.Session) -> bool:
    if not isinstance(link, str) or not link.strip():
        return False

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
            if lower.startswith("<html") or lower.startswith("<! doctype html") or lower.startswith("<service-error"):
                return False
            return True

        return False

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

    if source == "github":
        try:
            resp = session.get(link, timeout=20)
        except Exception:
            return False
        return resp.status_code == 200

    return False


def _process_one_link_step4(row, worker_id: int, total: int, counter: dict, lock: threading.Lock):
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
    except Exception as e:
        db.rollback()
        print(f"[STEP4] PID {pid} link {link}: ERROR {e}", file=sys.stderr)
        logger.error("DOI N/A:  STEP4 link error:  %s", e)
    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 4] Checking downloads", counter["done"], total)


def step4_check_downloadable():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT pid, data_link, source_website FROM EXTRACTION WHERE done = 0")
    rows = cur.fetchall()
    cur.close()
    db.close()

    total = len(rows)
    counter = {"done": 0}
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as ex:
        futures = [
            ex.submit(_process_one_link_step4, row, idx % NUM_WORKERS, total, counter, lock)
            for idx, row in enumerate(rows)
        ]
        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP4] worker error: {e}", file=sys.stderr)
                logger.error("DOI N/A: STEP4 worker error: %s", e)


# ================== Main ==================

def main():
    try:
        print("=== STEP 1 ===")
        step1_load_classification()
        print("=== STEP 2 ===")
        #step2_enrich_with_abstract()
        print("=== STEP 3 ===")
        step3_extract_data_links()
        print("=== STEP 4 ===")
        step4_check_downloadable()
        print("=== ALL STEPS DONE ===")
    except KeyboardInterrupt:
        sys.stdout.write("\n")
        sys.stdout.flush()
        msg = f"Keyboard interrupt. Last DOI: {CURRENT_DOI or 'N/A'} (error log:  {ERROR_LOG_FILE})"
        print(msg, file=sys.stderr)
        logger.error("DOI %s: KeyboardInterrupt", CURRENT_DOI or "N/A")
        sys.exit(1)
    except Exception as e:
        sys.stdout.write("\n")
        sys.stdout.flush()
        print(f"Fatal error: {e}", file=sys.stderr)
        log_doi_error(CURRENT_DOI, e, "Fatal error")
        raise


if __name__ == "__main__":
    main()