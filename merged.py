import os
import json
import re
import urllib.parse
import sys
import time
from dotenv import load_dotenv
import requests
import mysql.connector as sql
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
API_KEY = os.getenv('ELSEVIER_API_KEY')
JSON_PATH = 'ResearchTestLinks.json'

patterns = [
    r'\b\w+\.csv\b',
    r'\b\w+\.xlsx?\b',
    r'https?://(?:dx\.)?doi\.org/10\.\d{4,9}/zenodo\.\d+\b',
    r'https?://data.mendeley\.com/datasets/[^\s"]+',
    r'https?://github\.com/[^\s"]+',
    r'https?://zenodo\.org/[^\s"]+',
    r'https?://(?:www\.)?elsevier\.com/[^\s"]+',
]


def extract_data_files(text: str):
    found = []
    for p in patterns:
        found.extend(re.findall(p, text, re.IGNORECASE))
    normalized = [x.rstrip('.') for x in found]
    seen = set()
    out = []
    for x in normalized:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def fetch_elsevier(session: requests.Session, doi: str):
    url = f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}'
    headers = {'X-ELS-APIKey': API_KEY, 'Accept': 'application/json'}
    try:
        r = session.get(url, headers=headers, timeout=20)
        return r.content.decode('utf-8', errors='ignore')
    except Exception:
        return ""


def get_db_connection():
    return sql.connect(
        user=str(os.getenv('DB_USER')),
        password=str(os.getenv('DB_PASSWORD')),
        host=str(os.getenv('DB_HOST')),
        database=str(os.getenv('DB_NAME')),
        autocommit=False,
    )


def process_paper(entry, worker_id: int):
    """
    Multithreaded unit of work.

    Behavior matches original single-threaded logic:
    - If no data files found in Elsevier content -> do NOT insert into CLASSIFICATION.
    - If data files found -> ensure a CLASSIFICATION row exists (DONE=1) and insert EXTRACTION rows.
    """
    doi = entry.get('doi')
    if not doi:
        return

    title = entry.get('title', '')
    url = entry.get('url', '')

    paper_start = time.time()

    # Each task gets its own DB connection and HTTP session
    try:
        db = get_db_connection()
    except Exception as e:
        print(f"worker {worker_id}: db connect error: {e}", file=sys.stderr)
        return

    cur = db.cursor()
    session = requests.Session()

    insert_class_sql = "INSERT INTO CLASSIFICATION (title, DOI, DONE) VALUES (%s, %s, %s)"
    select_id_sql = "SELECT id FROM CLASSIFICATION WHERE DOI = %s"
    update_done_sql = "UPDATE CLASSIFICATION SET DONE = 1 WHERE id = %s"
    insert_extr_sql = "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)"

    try:
        # 1) Fetch Elsevier content
        content = fetch_elsevier(session, doi)
        if not content:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no content)")
            return

        files = extract_data_files(content)
        if not files:
            # Match original behavior: do NOT insert into CLASSIFICATION if no data
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no files)")
            return

        # 2) Ensure CLASSIFICATION row exists (only for papers with data)
        pid = None
        try:
            cur.execute(insert_class_sql, (title, doi, 1))
            pid = cur.lastrowid
            db.commit()
        except Exception:
            # Likely duplicate DOI – row already exists
            db.rollback()
            try:
                cur.execute(select_id_sql, (doi,))
                row = cur.fetchone()
                pid = row[0] if row else None
            except Exception as e:
                print(f"worker {worker_id}: select_id_sql error for doi {doi}: {e}", file=sys.stderr)
                pid = None

            if pid is not None:
                # Make sure DONE is set to 1 (idempotent)
                try:
                    cur.execute(update_done_sql, (pid,))
                    db.commit()
                except Exception:
                    db.rollback()

        if pid is None:
            # Could not get or create CLASSIFICATION row, give up on this DOI
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no pid)")
            return

        # 3) Insert EXTRACTION rows (pid, URL, data_link, done=0)
        ex_rows = [(pid, url, link, 0) for link in files]
        try:
            cur.executemany(insert_extr_sql, ex_rows)
            db.commit()
        except Exception as e:
            print(f"worker {worker_id}: insert_extr_sql error for doi {doi}: {e}", file=sys.stderr)
            db.rollback()

        elapsed = time.time() - paper_start
        print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi}")

    finally:
        cur.close()
        db.close()


def main():
    try:
        with open(JSON_PATH, encoding='utf-8') as f:
            links = json.load(f)
    except Exception as e:
        print(f"error: cannot read {JSON_PATH}: {e}", file=sys.stderr)
        return

    # Only papers with a DOI are candidates
    entries = [e for e in links if e.get('doi')]

    num_workers = 4

    start_time = time.time()

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = []
        for idx, entry in enumerate(entries):
            worker_id = idx % num_workers  # just for log labeling
            futures.append(executor.submit(process_paper, entry, worker_id))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"error in worker: {e}", file=sys.stderr)

    print("--- %s seconds ---" % (time.time() - start_time))


if __name__ == "__main__":
    main()