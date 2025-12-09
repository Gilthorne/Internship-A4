#!/usr/bin/env python3
import os
import json
import re
import urllib.parse
import sys
import time
from urllib.parse import urlparse, urlencode, urlunparse, parse_qsl

from dotenv import load_dotenv
import requests
import mysql.connector as sql
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
API_KEY = os.getenv("ELSEVIER_API_KEY")
JSON_PATH = "ResearchTestLinks.json"

CURRENT_PAPER = None  # updated in process_paper

patterns = [
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
    for p in patterns:
        found.extend(re.findall(p, text, re.IGNORECASE))

    # Clean common trailing punctuation
    normalized = [x.rstrip(".,);]") for x in found]

    seen = set()
    out = []
    for x in normalized:
        if x.lower() in IGNORED_LINKS:
            continue
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fetch_elsevier(session: requests.Session, doi: str) -> str:
    url = f"https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}"
    headers = {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}
    try:
        r = session.get(url, headers=headers, timeout=20)
        return r.content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def get_db_connection():
    return sql.connect(
        user=str(os.getenv("DB_USER")),
        password=str(os.getenv("DB_PASSWORD")),
        host=str(os.getenv("DB_HOST")),
        database=str(os.getenv("DB_NAME")),
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


def map_files_to_elsevier_objects(files, objects_section):
    """
    Map file names like 'mmc6.xlsx' to the corresponding Elsevier object URLs.

    files: list of strings, e.g. ['mmc2.xlsx', 'mmc6.xlsx', ...]
    objects_section: value of data['full-text-retrieval-response']['objects']['object']
                     (can be a dict or a list of dicts)

    Returns a new list where 'mmc6.xlsx' is replaced by its $ URL when possible.
    """
    if not objects_section:
        return files

    # Normalize to a list
    if isinstance(objects_section, dict):
        multimedia_objects = [objects_section]
    elif isinstance(objects_section, list):
        multimedia_objects = objects_section
    else:
        return files

    # Build ref -> url map
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
        base = os.path.splitext(os.path.basename(f))[0]  # 'mmc6.xlsx' -> 'mmc6'
        if base in ref_to_url:
            out.append(ref_to_url[base])
        else:
            out.append(f)
    return out


def make_elsevier_object_download_url(api_url: str) -> str:
    """
    Take an Elsevier object API URL like:
      https://api.elsevier.com/content/object/eid/1-s2.0-...-mmc6.xlsx?httpAccept=%2A%2F%2A

    and force parameters to actually return the binary object (Excel/CSV) via the Object Retrieval API:
      - view=STANDARD
      - httpAccept=application/excel or text/csv
    """
    try:
        parsed = urlparse(api_url)
    except Exception:
        return api_url

    # Choose mime type based on extension
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        mime = "application/excel"
    elif ext == ".csv":
        mime = "text/csv"
    else:
        # unsupported, keep as is
        return api_url

    query = dict(parse_qsl(parsed.query))
    query["view"] = "STANDARD"
    query["httpAccept"] = mime

    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def is_data_link_downloadable(link: str, session: requests.Session) -> bool:
    """
    Vérifie si un data_link est téléchargeable.
    - Pour les objets Elsevier (api.elsevier.com/content/object/eid/...), on construit une URL view=STANDARD
      avec le bon httpAccept, puis on check status + premiers octets.
    - Pour les autres liens, on tente un GET simple (status 200 seulement).
    """
    if not isinstance(link, str):
        return False

    # Cas Elsevier Object Retrieval
    if "api.elsevier.com/content/object/eid/" in link:
        url = make_elsevier_object_download_url(link)
        headers = {
            "X-ELS-APIKey": API_KEY,
            "Accept": "*/*",
        }
        try:
            resp = session.get(url, headers=headers, stream=True, timeout=15)
        except Exception:
            return False

        if resp.status_code != 200:
            return False

        ctype = (resp.headers.get("Content-Type") or "").lower()
        sample = resp.content[:64]

        # Excel OOXML (ZIP)
        if sample.startswith(b"PK\x03\x04"):
            return True
        # CSV / texte simple
        if "text/csv" in ctype or "text/plain" in ctype:
            return True

        return False

    # Cas générique : on tente un GET rapide sans auth
    try:
        resp = session.get(link, stream=True, timeout=10)
    except Exception:
        return False

    return resp.status_code == 200


def process_paper(entry, worker_id: int):
    global CURRENT_PAPER

    doi_link = entry.get("doi_link")
    doi = extract_doi_from_link(doi_link)
    title_json = entry.get("title", "") or "N/A"

    if not doi:
        return

    CURRENT_PAPER = {"doi": doi, "doi_link": doi_link, "title": title_json}

    url = doi_link or ""
    start = time.time()

    try:
        db = get_db_connection()
    except Exception as e:
        print(f"worker {worker_id}: DB connect error: {e}", file=sys.stderr)
        return

    cur = db.cursor()
    session = requests.Session()

    # CLASSIFICATION = (id, title, Authors, DOI, Open_Access, Has_data, DONE)
    select_class_sql = "SELECT id, DONE FROM CLASSIFICATION WHERE DOI = %s"
    insert_class_sql = (
        "INSERT INTO CLASSIFICATION (title, Authors, DOI, Open_Access, Has_data, DONE) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )
    update_done_sql = (
        "UPDATE CLASSIFICATION SET Open_Access = %s, Has_data = %s, DONE = %s WHERE id = %s"
    )
    insert_extr_sql = (
        "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)"
    )
    update_extr_done_sql = "UPDATE EXTRACTION SET done = %s WHERE pid = %s AND data_link = %s"

    try:
        # 0) Check if DOI already exists
        try:
            cur.execute(select_class_sql, (doi,))
            row = cur.fetchone()
        except Exception as e:
            print(f"worker {worker_id}: select_class_sql error for DOI {doi}: {e}", file=sys.stderr)
            row = None

        if row:
            pid, done = row
            if done:
                elapsed = time.time() - start
                print(f"worker {worker_id}: DOI {doi} already DONE, skipping ({elapsed:.3f}s)")
                return
        else:
            pid = None

        # 1) Get API response + coredata
        content = fetch_elsevier(session, doi)
        data = None
        ftr = None
        if not content:
            core = None
        else:
            try:
                data = json.loads(content)
                ftr = data.get("full-text-retrieval-response")
                core = ftr.get("coredata") if isinstance(ftr, dict) else data.get("coredata")
                if not isinstance(core, dict):
                    core = None
            except Exception:
                core = None

        # Default values
        authors_str = ""
        open_access = False
        files = []

        # 3) If we have a valid core, extract authors / OA / links
        if core:
            authors_list = []
            dc_creator = core.get("dc:creator")
            if isinstance(dc_creator, list):
                for item in dc_creator:
                    if isinstance(item, dict):
                        name = item.get("$")
                        if isinstance(name, str) and name.strip():
                            authors_list.append(name.strip())
                    elif isinstance(item, str) and item.strip():
                        authors_list.append(item.strip())
            elif isinstance(dc_creator, str) and dc_creator.strip():
                authors_list.append(dc_creator.strip())

            creator = core.get("creator")
            if not authors_list:
                if isinstance(creator, str) and creator.strip():
                    authors_list.append(creator.strip())
                elif isinstance(creator, list):
                    for c in creator:
                        if isinstance(c, str) and c.strip():
                            authors_list.append(c.strip())

            # simple dedup
            seen = set()
            uniq = []
            for a in authors_list:
                if a and a not in seen:
                    seen.add(a)
                    uniq.append(a)
            authors_str = "; ".join(uniq)

            # Open Access
            oa_article = core.get("openaccessArticle")
            oa_flag = core.get("openaccess")
            if isinstance(oa_article, str) and oa_article.lower() == "true":
                open_access = True
            elif isinstance(oa_flag, str) and oa_flag == "1":
                open_access = True

            # Links: run regex on full JSON response (broader coverage)
            files = extract_data_files(content)

            # Map mmcX.xlsx-style names to Elsevier object URLs when possible
            objects_section = None
            if isinstance(ftr, dict):
                objects_section = ftr.get("objects", {}).get("object")
            if objects_section:
                files = map_files_to_elsevier_objects(files, objects_section)

            # Convert Elsevier object URLs to direct Object Retrieval download URLs (épurés)
            download_files = []
            for link in files:
                if isinstance(link, str) and "api.elsevier.com/content/object/eid/" in link:
                    download_files.append(make_elsevier_object_download_url(link))
                else:
                    download_files.append(link)
            files = download_files

        has_data = bool(files)

        # 4) Ensure we have a pid in CLASSIFICATION
        if pid is None:
            try:
                cur.execute(
                    insert_class_sql,
                    (title_json, authors_str, doi, open_access, has_data, 0),
                )
                pid = cur.lastrowid
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"worker {worker_id}: insert_class_sql error for DOI {doi}: {e}", file=sys.stderr)
                try:
                    cur.execute("SELECT id FROM CLASSIFICATION WHERE DOI = %s", (doi,))
                    row2 = cur.fetchone()
                    pid = row2[0] if row2 else None
                except Exception as e2:
                    print(f"worker {worker_id}: second select id error for DOI {doi}: {e2}", file=sys.stderr)
                    pid = None

        if pid is None:
            elapsed = time.time() - start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for DOI {doi} (no pid)")
            return

        # 5) Insert into EXTRACTION if we have files
        if files:
            ex_rows = [(pid, url, link, 0) for link in files]
            try:
                cur.executemany(insert_extr_sql, ex_rows)
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"worker {worker_id}: insert_extr error for DOI {doi}: {e}", file=sys.stderr)
                elapsed = time.time() - start
                print(
                    f"worker {worker_id}: timing {elapsed:.3f}s for DOI {doi} (error inserting extraction)"
                )
                return

            # 5bis) Pour chaque data_link, tester si téléchargeable et mettre EXTRACTION.done à 1 si oui
            for link in files:
                try:
                    ok = is_data_link_downloadable(link, session)
                    cur.execute(update_extr_done_sql, (int(ok), pid, link))
                except Exception as e:
                    print(f"worker {worker_id}: update_extr_done_sql error for DOI {doi}, link {link}: {e}", file=sys.stderr)
            db.commit()

        # 6) Mark DONE + Has_data dans CLASSIFICATION (inchangé : DONE toujours True ici)
        try:
            cur.execute(update_done_sql, (open_access, has_data, True, pid))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"worker {worker_id}: update_done_sql error for DOI {doi}: {e}", file=sys.stderr)

        elapsed = time.time() - start
        print(f"worker {worker_id}: timing {elapsed:.3f}s for DOI {doi} (has_data={has_data})")

    finally:
        cur.close()
        db.close()


def main():
    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            links = json.load(f)
    except Exception as e:
        print(f"error: cannot read {JSON_PATH}: {e}", file=sys.stderr)
        return

    entries = [e for e in links if e.get("doi_link")]

    num_workers = 4
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for idx, entry in enumerate(entries):
            worker_id = idx % num_workers
            futures.append(executor.submit(process_paper, entry, worker_id))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"error in worker: {e}", file=sys.stderr)

    print("--- %s seconds ---" % (time.time() - start_time))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nKeyboard interrupt detected.", file=sys.stderr)
        if CURRENT_PAPER is not None:
            print(
                "Last paper in progress:\n"
                f"  DOI      : {CURRENT_PAPER.get('doi')}\n"
                f"  DOI link : {CURRENT_PAPER.get('doi_link')}\n"
                f"  Title    : {CURRENT_PAPER.get('title')}",
                file=sys.stderr,
            )
        else:
            print("No paper had started yet.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\nFatal error: {e}", file=sys.stderr)
        if CURRENT_PAPER is not None:
            print(
                "Last paper in progress:\n"
                f"  DOI      : {CURRENT_PAPER.get('doi')}\n"
                f"  DOI link : {CURRENT_PAPER.get('doi_link')}\n"
                f"  Title    : {CURRENT_PAPER.get('title')}",
                file=sys.stderr,
            )
        raise