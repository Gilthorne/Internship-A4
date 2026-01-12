import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import mysql.connector as sql
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("ELSEVIER_API_KEY")
JSON_PATH = os.getenv("JSON_PATH", "ResearchTestLinks.json")
NUM_WORKERS = int(os.getenv("NUM_WORKERS", "4"))

GITHUB_API = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

CURRENT_DOI: str | None = None
CURRENT_PAPER = None


def setup_error_logging(err_file: str | None = None):
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
    handler = RotatingFileHandler(err_file, maxBytes=5_000_000, backupCount=3, encoding="utf-8")
    handler.setLevel(logging.ERROR)
    handler.setFormatter(fmt)
    root.addHandler(handler)

    return logging.getLogger(__name__), err_file


logger, ERROR_LOG_FILE = setup_error_logging()


def log_doi_error(doi: str | None, err: Exception, context: str = ""):
    doi = doi or "N/A"
    if context:
        logger.error("DOI %s: %s: %s", doi, context, err)
    else:
        logger.error("DOI %s: Error %s", doi, err)


def get_db_connection():
    return sql.connect(
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        database=os.getenv("DB_NAME"),
        autocommit=False,
    )


def make_session() -> requests.Session:
    return requests.Session()


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


def http_get_with_retries(
    session: requests.Session,
    url: str,
    headers: dict,
    max_retries: int = 5,
    doi: str | None = None,
) -> requests.Response | None:
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, headers=headers, timeout=30)

            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                try:
                    delay = float(retry_after)
                except (TypeError, ValueError):
                    delay = min(120.0, 5.0 * (2 ** (attempt - 1)))

                if attempt < max_retries:
                    time.sleep(delay)
                    continue

                log_doi_error(
                    doi,
                    requests.HTTPError(
                        f"HTTP 429 Too Many Requests (gave up after {attempt} tries)"
                    ),
                    "HTTP error",
                )
                return None

            if 500 <= resp.status_code < 600:
                last_err = requests.HTTPError(f"HTTP {resp.status_code}")
                if attempt < max_retries:
                    time.sleep(min(30.0, 2.0 * attempt))
                    continue
                break

            resp.raise_for_status()
            return resp

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


def print_progress(prefix: str, current: int, total: int, bar_width: int = 50):
    if total <= 0:
        bar = "-" * bar_width
        msg = f"{prefix} [{bar}] {current}/? (0.0%)"
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


def fetch_elsevier_json(endpoint: str, doi: str, session: requests.Session) -> dict | None:
    if not API_KEY or not doi:
        return None
    url = f"https://api.elsevier.com/content/{endpoint}/doi/" + quote(doi)
    resp = http_get_with_retries(
        session,
        url,
        {"X-ELS-APIKey": API_KEY, "Accept": "application/json"},
        doi=doi,
    )
    if not resp:
        return None
    try:
        return resp.json()
    except Exception as e:
        log_doi_error(doi, e, f"JSON decode failed ({endpoint})")
        return None


def parse_authors_from_coredata(core: dict) -> str:
    authors: list[str] = []

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

    uniq: list[str] = []
    seen: set[str] = set()
    for a in authors:
        if a and a not in seen:
            seen.add(a)
            uniq.append(a)
    return "; ".join(uniq)


PATTERNS = [
    r"\b\w+\.csv\b",
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


def extract_data_files(text: str):
    found: list[str] = []
    for p in PATTERNS:
        found.extend(re.findall(p, text, re.IGNORECASE))

    normalized: list[str] = []
    for x in found:
        x = x.rstrip(".,);]\"'")
        x = unquote(x)
        x = x.replace("\\u201c", "").replace("\\u201d", "").replace("\u201c", "").replace("\u201d", "")
        x = x.replace("\\u2019", "").replace("\u2019", "")
        x = x.replace("⟩", "").replace("〉", "")
        x = re.sub(r"\.(http:|https:).*$", "", x)
        x = re.sub(r"(date|Date|DATE)$", "", x)
        x = x.strip()
        normalized.append(x)

    seen: set[str] = set()
    out: list[str] = []
    for x in normalized:
        if not x or x.lower() in IGNORED_LINKS:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def split_data_vs_other_links(links):
    exts = (".csv", ".xls", ".xlsx", ".json")
    data_files, other_links = [], []
    for link in links:
        if isinstance(link, str) and any(link.lower().endswith(ext) for ext in exts):
            data_files.append(link)
        else:
            other_links.append(link)
    return data_files, other_links


def map_files_to_elsevier_objects(files, objects_section):
    import os

    if not objects_section:
        return files
    multimedia_objects = [objects_section] if isinstance(objects_section, dict) else list(objects_section)

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
        r = requests.get(f"https://zenodo.org/api/records/{rec_id}", timeout=30)
        r.raise_for_status()
    except Exception as e:
        logger.error("DOI N/A: Zenodo record fetch error: %s", e)
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
        out.append(api_link_to_front_download(api_url))
    return out


def remove_camelcase_suffix(repo_name: str, original_repo: str) -> str:
    match = re.search(r"^([a-z0-9._-]+?)([A-Z][a-zA-Z]+)$", repo_name)
    if not match:
        return repo_name

    base = match.group(1)
    suffix = match.group(2)
    if base.lower().replace("-", "").replace("_", "").replace(".", "") in suffix.lower():
        return base
    if len(suffix) > 2 and suffix[0].isupper():
        return base
    return repo_name


def is_valid_github_component(s: str) -> bool:
    if not s:
        return False
    if any(c in s for c in ['<', '>', '"', "'", ' ', "\\", '?', '*', ':', '|']):
        return False
    if s.strip('.') == '':
        return False

    invalid_patterns = [
        r"^https?://",
        r"^www\.",
        r"\.com$",
        r"\.org$",
        r"\.(The|the)$",
        r"\d{5,}$",
    ]
    for pattern in invalid_patterns:
        if re.search(pattern, s):
            return False
    return True


def parse_github_repo(arg: str):
    if not arg or not isinstance(arg, str):
        return None, None

    arg = arg.strip()
    original_arg = arg
    arg = unquote(arg)
    arg = arg.replace("\\u201c", "").replace("\\u201d", "").replace("\u201c", "").replace("\u201d", "")
    arg = arg.replace("\\u2019", "").replace("\u2019", "")
    arg = arg.replace("⟩", "").replace("〉", "")
    arg = re.sub(r"\.(http:|https:).*$", "", arg)
    arg = re.sub(r"(date|Date|DATE)$", "", arg)
    arg = arg.rstrip(".,;: /")

    if arg.lower().count("http://") > 1 or arg.lower().count("https://") > 1:
        match = re.search(
            r"(https?://github\.com/[a-zA-Z0-9_-]+/[a-zA-Z0-9._-]+)",
            arg,
            re.IGNORECASE,
        )
        if match:
            arg = match.group(1)
        else:
            return None, None

    if arg.startswith("http"):
        try:
            p = urlparse(arg)
            if "github.com" not in p.netloc.lower():
                return None, None

            parts = p.path.strip("/").split("/")
            if parts and parts[0] in [
                "stars",
                "orgs",
                "users",
                "topics",
                "search",
                "trending",
                "features",
            ]:
                return None, None

            if len(parts) >= 2:
                owner, repo = parts[0], parts[1]
                if repo.endswith(".git"):
                    repo = repo[:-4]

                repo = re.sub(r"(date|Date|DATE)$", "", repo)
                repo = re.sub(r"\.(com|org|net)$", "", repo, flags=re.IGNORECASE)
                repo = remove_camelcase_suffix(repo, original_arg)

                if len(repo) > 5 and repo[-1].islower() and repo[-2] in "aeiou":
                    test_repo = repo[:-1]
                    if not test_repo.endswith(("a", "i", "o")):
                        repo = test_repo

                if is_valid_github_component(owner) and is_valid_github_component(repo):
                    return owner, repo

        except Exception:
            return None, None

    if "/" in arg and not arg.startswith("http"):
        parts = arg.split("/", 1)
        if len(parts) == 2:
            owner, repo = parts[0], parts[1]
            repo = repo.split()[0] if " " in repo else repo
            repo = re.sub(r"(date|Date|DATE)$", "", repo)
            repo = re.sub(r"\.(com|org|net)$", "", repo, flags=re.IGNORECASE)
            repo = remove_camelcase_suffix(repo, original_arg)
            if is_valid_github_component(owner) and is_valid_github_component(repo):
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
        tree = gh_get(
            f"/repos/{owner}/{repo}/git/trees/{ref}",
            params={"recursive": "1"},
        )
    except requests.HTTPError as e:
        if getattr(e.response, "status_code", None) == 409:
            logger.error("DOI N/A: GitHub listing error (repo too large): %s", e)
        else:
            logger.error("DOI N/A: GitHub listing error: %s", e)
        return []
    except Exception as e:
        logger.error("DOI N/A: GitHub listing error: %s", e)
        return []

    exts = (".csv", ".xls", ".xlsx", ".json")
    data_paths = [
        e["path"]
        for e in tree.get("tree", [])
        if e.get("type") == "blob" and e.get("path", "").lower().endswith(exts)
    ]

    return [f"https://github.com/{owner}/{repo}/blob/{ref}/{p}" for p in data_paths]


def run_threaded(rows, worker_func, label: str):
    total = len(rows)
    counter = {"done": 0}
    lock = threading.Lock()

    ex = ThreadPoolExecutor(max_workers=NUM_WORKERS)
    futures = []
    try:
        for idx, row in enumerate(rows):
            futures.append(ex.submit(worker_func, row, idx % NUM_WORKERS, total, counter, lock))
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
