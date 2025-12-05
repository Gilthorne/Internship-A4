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


def extract_authors_from_elsevier_json(text: str) -> str:
    """
    Extrait les auteurs depuis la réponse JSON de l'API Elsevier.

    Pour ton cas, coredata["dc:creator"] est une liste de dicts :
      { "@_fa": "true", "$": "Nom, Prénom" }

    On renvoie "Nom, Prénom; Nom2, Prénom2; ..."
    """
    try:
        data = json.loads(text)
    except Exception:
        return ""

    # Certains endpoints emballent dans "full-text-retrieval-response"
    ftr = data.get("full-text-retrieval-response")
    if isinstance(ftr, dict):
        core = ftr.get("coredata")
    else:
        core = data.get("coredata")

    if not isinstance(core, dict):
        return ""

    authors = []

    dc_creator = core.get("dc:creator")
    # Cas principal : liste de dicts
    if isinstance(dc_creator, list):
        for item in dc_creator:
            if isinstance(item, dict):
                name = item.get("$")
                if isinstance(name, str) and name.strip():
                    authors.append(name.strip())
            elif isinstance(item, str) and item.strip():
                authors.append(item.strip())
    # Cas plus simple : string
    elif isinstance(dc_creator, str) and dc_creator.strip():
        authors.append(dc_creator.strip())

    # Fallback léger : "creator" si jamais
    if not authors:
        creator = core.get("creator")
        if isinstance(creator, str) and creator.strip():
            authors.append(creator.strip())
        elif isinstance(creator, list):
            for c in creator:
                if isinstance(c, str) and c.strip():
                    authors.append(c.strip())

    # Déduplication + join
    seen = set()
    out = []
    for a in authors:
        if a not in seen:
            seen.add(a)
            out.append(a)

    return "; ".join(out)


def process_paper(entry, worker_id: int):
    """
    - On lit DOI, title, url depuis ResearchTestLinks.json.
    - On récupère auteurs + data links depuis l'API Elsevier (JSON).
    - Si DOI existe déjà :
        - DONE = 1 : on ignore.
        - DONE = 0 : on (ré)fait l'extraction puis DONE = 1.
    - Si DOI n'existe pas :
        - pas de data -> rien en CLASSIFICATION.
        - data -> CLASSIFICATION + EXTRACTION.
    """
    doi = entry.get('doi')
    if not doi:
        return

    title = entry.get('title', '')
    url = entry.get('url', '')

    paper_start = time.time()

    try:
        db = get_db_connection()
    except Exception as e:
        print(f"worker {worker_id}: db connect error: {e}", file=sys.stderr)
        return

    cur = db.cursor()
    session = requests.Session()

    # table CLASSIFICATION = (id, title, Authors, DOI, DONE)
    select_class_sql = "SELECT id, DONE FROM CLASSIFICATION WHERE DOI = %s"
    insert_class_sql = "INSERT INTO CLASSIFICATION (title, Authors, DOI, DONE) VALUES (%s, %s, %s, %s)"
    update_done_sql = "UPDATE CLASSIFICATION SET DONE = 1 WHERE id = %s"
    insert_extr_sql = "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)"

    try:
        # 0) Vérifier si le DOI existe déjà
        try:
            cur.execute(select_class_sql, (doi,))
            row = cur.fetchone()
        except Exception as e:
            print(f"worker {worker_id}: select_class_sql error for doi {doi}: {e}", file=sys.stderr)
            row = None

        if row:
            pid, done = row
            if done:
                elapsed = time.time() - paper_start
                print(f"worker {worker_id}: doi {doi} already DONE, skipping ({elapsed:.3f}s)")
                cur.close()
                db.close()
                return
            # DONE = 0 -> on va (ré)faire l'extraction et mettre DONE = 1 à la fin
        else:
            pid = None  # pas encore de ligne CLASSIFICATION

        # 1) Appel API Elsevier (JSON)
        content = fetch_elsevier(session, doi)
        if not content:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no content)")
            return

        # 1bis) Récupérer les auteurs depuis la page (API JSON)
        authors = extract_authors_from_elsevier_json(content)

        # 1ter) Récupérer les data links depuis la page (API JSON)
        files = extract_data_files(content)
        if not files:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no files)")
            return

        # 2) S'assurer d'avoir un pid dans CLASSIFICATION
        if pid is None:
            # DOI n'existait pas encore -> on insère
            try:
                cur.execute(insert_class_sql, (title, authors, doi, 0))  # DONE = 0 pour l'instant
                pid = cur.lastrowid
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"worker {worker_id}: insert_class_sql error for doi {doi}: {e}", file=sys.stderr)
                # Au cas où un autre thread l'a inséré entre-temps
                try:
                    cur.execute(select_class_sql, (doi,))
                    row2 = cur.fetchone()
                    pid = row2[0] if row2 else None
                except Exception as e2:
                    print(f"worker {worker_id}: second select_class_sql error for doi {doi}: {e2}", file=sys.stderr)
                    pid = None

        if pid is None:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no pid)")
            return

        # 3) Insérer dans EXTRACTION, puis marquer DONE = 1
        ex_rows = [(pid, url, link, 0) for link in files]
        try:
            cur.executemany(insert_extr_sql, ex_rows)
            cur.execute(update_done_sql, (pid,))
            db.commit()
        except Exception as e:
            print(f"worker {worker_id}: insert_extr/update_done error for doi {doi}: {e}", file=sys.stderr)
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
            worker_id = idx % num_workers  # juste pour le logging
            futures.append(executor.submit(process_paper, entry, worker_id))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"error in worker: {e}", file=sys.stderr)

    print("--- %s seconds ---" % (time.time() - start_time))


if __name__ == "__main__":
    main()