import os
import json
import re
import urllib.parse
import sys
import time
from dotenv import load_dotenv
import requests
import mysql.connector as sql

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
        r = session.get(url, headers=headers)
        return r.content.decode('utf-8', errors='ignore')
    except Exception:
        return ""


def main():
    try:
        with open(JSON_PATH, encoding='utf-8') as f:
            links = json.load(f)
    except Exception as e:
        print(f"error: cannot read {JSON_PATH}: {e}", file=sys.stderr)
        return

    doi_to_url = {e.get('doi'): e.get('url', '') for e in links if e.get('doi')}

    try:
        db = sql.connect(
            user=str(os.getenv('DB_USER')),
            password=str(os.getenv('DB_PASSWORD')),
            host=str(os.getenv('DB_HOST')),
            database=str(os.getenv('DB_NAME')),
            autocommit=False,
        )
    except Exception as e:
        print(f"error: db connect: {e}", file=sys.stderr)
        return

    cur = db.cursor()
    session = requests.Session()

    processed = set()

    # Phase 1: process JSON entries (fetch once, insert CLASSIFICATION and EXTRACTION, mark DONE)
    insert_class_sql = "INSERT INTO CLASSIFICATION (title, DOI, DONE) VALUES (%s, %s, %s)"
    select_id_sql = "SELECT id FROM CLASSIFICATION WHERE DOI = %s"
    update_done_sql = "UPDATE CLASSIFICATION SET DONE = 1 WHERE id = %s"
    insert_extr_sql = "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)"

    for e in links:
        doi = e.get('doi')
        if not doi:
            continue
        if doi in processed:
            continue

        paper_start = time.time()

        content = fetch_elsevier(session, doi)
        if not content:
            processed.add(doi)
            elapsed = time.time() - paper_start
            print(f"timing: {elapsed:.3f}s for doi {doi}")
            continue
        files = extract_data_files(content)
        if not files:
            processed.add(doi)
            elapsed = time.time() - paper_start
            print(f"timing: {elapsed:.3f}s for doi {doi}")
            continue

        title = e.get('title', '')
        url = e.get('url', '')

        pid = None
        try:
            cur.execute(insert_class_sql, (title, doi, 1))
            pid = cur.lastrowid
            db.commit()
        except Exception:
            db.rollback()
            try:
                cur.execute(select_id_sql, (doi,))
                row = cur.fetchone()
                pid = row[0] if row else None
                if pid:
                    try:
                        cur.execute(update_done_sql, (pid,))
                        db.commit()
                    except Exception:
                        db.rollback()
            except Exception:
                pid = None

        if pid:
            rows = [(pid, url, link, 0) for link in files]
            try:
                cur.executemany(insert_extr_sql, rows)
                db.commit()
            except Exception:
                db.rollback()

        processed.add(doi)
        elapsed = time.time() - paper_start
        print(f"timing: {elapsed:.3f}s for doi {doi}")

    # Phase 2: process remaining CLASSIFICATION WHERE DONE = 0
    try:
        cur.execute("SELECT id, DOI FROM CLASSIFICATION WHERE DONE = 0")
        rows = cur.fetchall()
    except Exception as e:
        print(f"error: select CLASSIFICATION: {e}", file=sys.stderr)
        cur.close()
        db.close()
        return

    for row in rows:
        pid, doi = row[0], row[1]
        if doi in processed:
            continue

        paper_start = time.time()

        content = fetch_elsevier(session, doi)
        if not content:
            processed.add(doi)
            elapsed = time.time() - paper_start
            print(f"timing: {elapsed:.3f}s for doi {doi}")
            continue
        files = extract_data_files(content)
        if files:
            url = doi_to_url.get(doi, "")
            ex_rows = [(pid, url, link, 0) for link in files]
            try:
                cur.executemany(insert_extr_sql, ex_rows)
                cur.execute(update_done_sql, (pid,))
                db.commit()
            except Exception:
                db.rollback()
        processed.add(doi)
        elapsed = time.time() - paper_start
        print(f"timing: {elapsed:.3f}s for doi {doi}")

    cur.close()
    db.close()


if __name__ == "__main__":
    start_time = time.time()
    main()
    print("--- %s seconds ---" % (time.time() - start_time))