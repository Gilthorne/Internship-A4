#!/usr/bin/env python3
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
    # on reconstruit l'URL Elsevier à partir du DOI "nu"
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


def extract_doi_from_link(doi_link: str) -> str | None:
    """
    Extrait le DOI "nu" depuis un doi_link du type:
      https://doi.org/10.35341/afet.1295681
    Renvoie "10.35341/afet.1295681" ou None si échec.
    """
    if not doi_link:
        return None

    # 1) passer par urlparse pour enlever le schéma / host
    parsed = urllib.parse.urlparse(doi_link)
    path = parsed.path.lstrip('/')  # "10.35341/afet.1295681"

    if path:
        return path

    # fallback ultra simple au cas où
    # (garde la partie après le dernier "/")
    parts = doi_link.split('doi.org/', 1)
    if len(parts) == 2 and parts[1]:
        return parts[1].lstrip('/')
    return None


def process_paper(entry, worker_id: int):
    """
    - doi_link, title, citations viennent du JSON.
    - DOI "nu" est extrait de doi_link.
    - Auteurs, Open_Access, data links viennent de l'API Elsevier (JSON).
    - Si DOI existe déjà :
        - DONE = 1 : on ignore.
        - DONE = 0 : on (ré)fait l'extraction puis DONE = 1.
    - Si DOI n'existe pas :
        - pas de data -> rien en CLASSIFICATION.
        - data -> CLASSIFICATION + EXTRACTION.
    """
    doi_link = entry.get('doi_link')
    doi = extract_doi_from_link(doi_link)

    if not doi:
        # pas de DOI exploitable -> on ignore
        return

    # titre fourni dans le JSON d'entrée (fallback)
    title_from_json = entry.get('title', '')
    # pour les tables EXTRACTION.URL, on utilise le doi_link
    url = doi_link or ''

    paper_start = time.time()

    try:
        db = get_db_connection()
    except Exception as e:
        print(f"worker {worker_id}: db connect error: {e}", file=sys.stderr)
        return

    cur = db.cursor()
    session = requests.Session()

    # table CLASSIFICATION = (id, title, Authors, DOI, Open_Access, DONE)
    select_class_sql = "SELECT id, DONE FROM CLASSIFICATION WHERE DOI = %s"
    insert_class_sql = (
        "INSERT INTO CLASSIFICATION (title, Authors, DOI, Open_Access, DONE) "
        "VALUES (%s, %s, %s, %s, %s)"
    )
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

        # 1) Appel API Elsevier (JSON) à partir du DOI nu
        content = fetch_elsevier(session, doi)
        if not content:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no content)")
            return

        # 1bis) Parser le JSON une fois
        try:
            data = json.loads(content)
        except Exception:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (invalid JSON)")
            return

        # Récupérer coredata
        ftr = data.get("full-text-retrieval-response")
        if isinstance(ftr, dict):
            core = ftr.get("coredata")
        else:
            core = data.get("coredata")

        if not isinstance(core, dict):
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no coredata)")
            return

        # Auteurs
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

        seen = set()
        authors_out = []
        for a in authors_list:
            if a not in seen:
                seen.add(a)
                authors_out.append(a)
        authors_str = "; ".join(authors_out)

        # Titre (on prend en priorité celui de l'API)
        title_text = None
        title_val = core.get("dc:title") if core.get("dc:title") is not None else core.get("title")
        if isinstance(title_val, str) and title_val.strip():
            title_text = title_val.strip()
        elif isinstance(title_val, dict):
            for k in ("$", "title", "text"):
                v = title_val.get(k)
                if isinstance(v, str) and v.strip():
                    title_text = v.strip()
                    break
        elif isinstance(title_val, list):
            for item in title_val:
                if isinstance(item, str) and item.strip():
                    title_text = item.strip()
                    break
                elif isinstance(item, dict):
                    for k in ("$", "title", "text"):
                        v = item.get(k)
                        if isinstance(v, str) and v.strip():
                            title_text = v.strip()
                            break
                    if title_text:
                        break

        if not title_text:
            title_text = title_from_json or 'N/A'

        # Open Access
        oa_article = core.get("openaccessArticle")
        oa_flag = core.get("openaccess")
        if isinstance(oa_article, str) and oa_article.lower() == "true":
            open_access = True
        elif isinstance(oa_flag, str) and oa_flag == "1":
            open_access = True
        else:
            open_access = False

        # Data links
        files = extract_data_files(content)
        if not files:
            elapsed = time.time() - paper_start
            print(f"worker {worker_id}: timing {elapsed:.3f}s for doi {doi} (no files)")
            return

        # 2) S'assurer d'avoir un pid dans CLASSIFICATION
        if pid is None:
            try:
                cur.execute(
                    insert_class_sql,
                    (title_text, authors_str, doi, open_access, 0),  # DONE = 0 pour l'instant
                )
                pid = cur.lastrowid
                db.commit()
            except Exception as e:
                db.rollback()
                print(f"worker {worker_id}: insert_class_sql error for doi {doi}: {e}", file=sys.stderr)
                # Au cas où un autre thread a inséré entre-temps
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
        #    URL = doi_link (colonne inchangée)
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

    # on ne filtre plus sur 'doi', mais sur 'doi_link'
    entries = [e for e in links if e.get('doi_link')]

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
    main()