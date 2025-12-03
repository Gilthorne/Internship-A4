import os
import json
import re
import urllib.parse
import sys
import time
from dotenv import load_dotenv
import requests
import mysql.connector as sql
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

load_dotenv()
API_KEY = os.getenv('ELSEVIER_API_KEY')
JSON_PATH = 'ResearchTestLinks.json'
NUM_THREADS = 4


patterns = [
    r'\b\w+\.csv\b', r'\b\w+\.xlsx?\b',
    r'https?://(?:dx\.)?doi\.org/10\.\d{4,9}/zenodo\.\d+\b',
    r'https?://data.mendeley\.com/datasets/[^\s"]+', r'https?://github\.com/[^\s"]+',
    r'https?://zenodo\.org/[^\s"]+', r'https?://(?:www\.)?elsevier\.com/[^\s"]+',
]

thread_local = threading.local()

def get_thread_resources():
    thread_name = threading.current_thread().name
    if not hasattr(thread_local, 'session'):
        thread_local.session = requests.Session()
        try:
            thread_local.db = sql.connect(
                user=str(os.getenv('DB_USER')), password=str(os.getenv('DB_PASSWORD')),
                host=str(os.getenv('DB_HOST')), database=str(os.getenv('DB_NAME')),
                autocommit=False
            )
        except Exception as e:
            print(f"[{thread_name}] error: db connect: {e}", file=sys.stderr)
            thread_local.db = None
    return thread_local.session, thread_local.db

def close_thread_resources():
    if hasattr(thread_local, 'session'):
        thread_local.session.close()
    if hasattr(thread_local, 'db') and thread_local.db:
        thread_local.db.close()

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
        r.raise_for_status()
        return r.content.decode('utf-8', errors='ignore')
    except requests.exceptions.RequestException as e:
        # NOUVEAU: On récupère le nom du thread pour un log plus clair
        thread_name = threading.current_thread().name
        print(f"[{thread_name}] error: fetch failed for doi {doi}: {e}", file=sys.stderr)
        return ""
    except Exception as e:
        thread_name = threading.current_thread().name
        print(f"[{thread_name}] error: unexpected error during fetch for doi {doi}: {e}", file=sys.stderr)
        return ""

def process_paper(paper_info: dict):
    thread_name = threading.current_thread().name
    
    doi = paper_info.get('doi')
    if not doi:
        return f"[{thread_name}] Skipped: no DOI provided in {paper_info}"

    paper_start = time.time()
    
    session, db = get_thread_resources()
    if not db:
        return f"[{thread_name}] Failed for {doi}: no DB connection."
    
    cur = db.cursor()

    content = fetch_elsevier(session, doi)
    if not content:
        elapsed = time.time() - paper_start
        cur.close()
        return f"[{thread_name}] timing: {elapsed:.3f}s for doi {doi} (no content)"

    files = extract_data_files(content)
    if not files:
        elapsed = time.time() - paper_start
        cur.close()
        return f"[{thread_name}] timing: {elapsed:.3f}s for doi {doi} (no files found)"

    title = paper_info.get('title', '')
    url = paper_info.get('url', '')
    pid = paper_info.get('pid')

    insert_class_sql = "INSERT INTO CLASSIFICATION (title, DOI, DONE) VALUES (%s, %s, %s)"
    select_id_sql = "SELECT id FROM CLASSIFICATION WHERE DOI = %s"
    update_done_sql = "UPDATE CLASSIFICATION SET DONE = 1 WHERE id = %s"
    insert_extr_sql = "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)"

    if not pid:
        try:
            cur.execute(insert_class_sql, (title, doi, 1))
            pid = cur.lastrowid
            db.commit()
        except Exception:
            db.rollback()
            try:
                cur.execute(select_id_sql, (doi,))
                pid = cur.fetchone()[0]
            except Exception:
                pid = None
    
    if pid:
        try:
            rows = [(pid, url, link, 0) for link in files]
            if rows:
                cur.executemany(insert_extr_sql, rows)
            cur.execute(update_done_sql, (pid,))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[{thread_name}] error: db update failed for pid {pid}, doi {doi}: {e}", file=sys.stderr)

    cur.close()
    elapsed = time.time() - paper_start
    return f"[{thread_name}] timing: {elapsed:.3f}s for doi {doi} (processed)"


def main():
    try:
        with open(JSON_PATH, encoding='utf-8') as f:
            links_from_json = json.load(f)
    except Exception as e:
        print(f"error: cannot read {JSON_PATH}: {e}", file=sys.stderr)
        return
    
    papers_to_process = {e['doi']: e for e in links_from_json if e.get('doi')}

    try:
        db_main = sql.connect(
            user=str(os.getenv('DB_USER')), password=str(os.getenv('DB_PASSWORD')),
            host=str(os.getenv('DB_HOST')), database=str(os.getenv('DB_NAME'))
        )
        cur = db_main.cursor()
        cur.execute("SELECT id, DOI FROM CLASSIFICATION WHERE DONE = 0")
        for pid, doi in cur.fetchall():
            if doi not in papers_to_process:
                papers_to_process[doi] = {'doi': doi, 'pid': pid, 'url': '', 'title': ''}
        cur.close()
        db_main.close()
    except Exception as e:
        print(f"error: main db connect or select: {e}", file=sys.stderr)
    
    paper_list = list(papers_to_process.values())
    print(f"Found {len(paper_list)} unique papers to process with {NUM_THREADS} threads.")

    # --- Phase de traitement ---
    # NOUVEAU: Ajout de 'thread_name_prefix' pour nommer les threads automatiquement.
    with ThreadPoolExecutor(
        max_workers=NUM_THREADS, 
        initializer=get_thread_resources,
        thread_name_prefix='PaperProcessor'  # Donne des noms comme 'PaperProcessor_0', '_1', etc.
    ) as executor:
        future_to_paper = {executor.submit(process_paper, paper): paper for paper in paper_list}

        for future in as_completed(future_to_paper):
            paper_doi = future_to_paper[future].get('doi')
            try:
                result = future.result()
                print(result) # Le résultat contient déjà le nom du thread
            except Exception as exc:
                # NOUVEAU: On ajoute le préfixe [MainThread] pour les erreurs récupérées ici
                print(f"[MainThread] error: paper {paper_doi} generated an exception: {exc}", file=sys.stderr)
    
    close_thread_resources()

if __name__ == "__main__":
    start_time = time.time()
    main()
    print("--- %s seconds ---" % (time.time() - start_time))