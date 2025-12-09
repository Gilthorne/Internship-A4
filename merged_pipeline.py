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
NUM_WORKERS = 4  # nombre de workers pour la step 2

CURRENT_PAPER = None  # mis à jour dans les workers

# ================== Utilitaires communs ==================

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


def fetch_elsevier(session: requests.Session, doi: str) -> str:
    url = f"https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}"
    headers = {"X-ELS-APIKey": API_KEY, "Accept": "application/json"}
    try:
        r = session.get(url, headers=headers, timeout=20)
        return r.content.decode("utf-8", errors="ignore")
    except Exception:
        return ""


def extract_data_files(text: str):
    found = []
    for p in patterns:
        found.extend(re.findall(p, text, re.IGNORECASE))

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


def map_files_to_elsevier_objects(files, objects_section):
    """
    Map file names like 'mmc6.xlsx' to the corresponding Elsevier object URLs.
    """
    import os

    if not objects_section:
        return files

    if isinstance(objects_section, dict):
        multimedia_objects = [objects_section]
    elif isinstance(objects_section, list):
        multimedia_objects = objects_section
    else:
        return files

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
    Transforme une URL d'objet Elsevier en URL Object Retrieval (view=STANDARD, bon httpAccept).
    """
    import os

    try:
        parsed = urlparse(api_url)
    except Exception:
        return api_url

    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        mime = "application/excel"
    elif ext == ".csv":
        mime = "text/csv"
    else:
        # autre type: on laisse le lien tel quel
        return api_url

    query = dict(parse_qsl(parsed.query))
    query["view"] = "STANDARD"
    query["httpAccept"] = mime

    new_query = urlencode(query)
    return urlunparse(parsed._replace(query=new_query))


def is_data_link_downloadable(link: str, session: requests.Session) -> bool:
    """
    Vérifie si un data_link Elsevier (api.elsevier.com/content/object/eid/...)
    correspond bien à un Excel ou un CSV téléchargeable.

    Comportement:
    - Si le lien N'EST PAS un objet Elsevier -> False.
    - Si c'est un objet Elsevier:
        * construit l'URL Object Retrieval (view=STANDARD + httpAccept Excel/CSV)
        * exige:
            - status 200
            - Content-Length > 0 (si présent)
            - Content-Type cohérent (Excel ou CSV)
            - contenu non vide, avec signature plausible :
                - Excel : ZIP OOXML (PK..) ou vieux XLS (D0 CF 11 E0 ...)
                - CSV  : texte non vide, pas une page d'erreur HTML/XML évidente
    """
    if not isinstance(link, str) or not link.strip():
        return False

    # On ne traite que les objets Elsevier ; les autres liens (Zenodo, GitHub, etc.) retournent False
    if "api.elsevier.com/content/object/eid/" not in link:
        return False

    url = make_elsevier_object_download_url(link)
    headers = {
        "X-ELS-APIKey": API_KEY,
        "Accept": "*/*",
    }

    try:
        resp = session.get(url, headers=headers, stream=True, timeout=20)
    except Exception:
        return False

    if resp.status_code != 200:
        return False

    ctype = (resp.headers.get("Content-Type") or "").lower()
    clen = resp.headers.get("Content-Length")
    try:
        clen_int = int(clen) if clen is not None else None
    except ValueError:
        clen_int = None

    # Taille nulle => pas bon
    if clen_int is not None and clen_int <= 0:
        return False

    sample = resp.content[:256]  # petit échantillon

    # ==== Cas Excel (XLS/XLSX) ====
    if (
        "application/excel" in ctype
        or "application/vnd.ms-excel" in ctype
        or "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" in ctype
    ):
        if not sample:
            return False

        # XLSX OOXML (ZIP)
        if sample.startswith(b"PK\x03\x04"):
            return True

        # Vieux XLS (compound binary)
        if sample.startswith(b"\xD0\xCF\x11\xE0\xA1\xB1\x1A\xE1"):
            return True

        # Autre binaire non vide : on reste prudent, on ne le valide pas
        return False

    # ==== Cas CSV / texte ====
    if "text/csv" in ctype or "text/plain" in ctype:
        text_sample = sample.decode("utf-8", errors="ignore").strip()
        if not text_sample:
            return False

        lower = text_sample.lower()
        # Éviter les pages d'erreur HTML/XML évidentes
        if lower.startswith("<html") or lower.startswith("<!doctype html") or lower.startswith("<service-error"):
            return False

        # Check très basique de "ressemblance CSV" (présence de séparateurs)
        if ("," in text_sample) or (";" in text_sample) or ("\t" in text_sample):
            return True

        # Sinon: texte non vide mais pas forcément CSV → on peut rester permissif
        return True

    # Autre Content-Type: on ne considère pas que c'est notre Excel/CSV cible
    return False


# ================== Étape 1 ==================

def step1_load_classification():
    """
    Étape 1 :
    - Lit ResearchTestLinks.json
    - Insère dans CLASSIFICATION (DONE=0, Has_data=0) si DOI pas déjà présent.
    """
    try:
        with open(JSON_PATH, encoding="utf-8") as f:
            links = json.load(f)
    except Exception as e:
        print(f"[STEP1] error: cannot read {JSON_PATH}: {e}", file=sys.stderr)
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
        doi_link = entry.get("doi_link")
        doi = extract_doi_from_link(doi_link)
        title = entry.get("title", "") or "N/A"
        if not doi:
            continue

        try:
            cur.execute(select_sql, (doi,))
            row = cur.fetchone()
            if row:
                continue  # déjà présent

            # Authors="", Open_Access=False, Has_data=False, DONE=False
            cur.execute(insert_sql, (title, "", doi, False, False, False))
            db.commit()
            print(f"[STEP1] Inserted DOI {doi} into CLASSIFICATION")
        except Exception as e:
            db.rollback()
            print(f"[STEP1] Error inserting DOI {doi}: {e}", file=sys.stderr)

    cur.close()
    db.close()


# ================== Étape 2 (multi‑threadée, avec worker_id & CURRENT_PAPER) ==================

def process_one_paper_step2(row, worker_id: int):
    """
    Fonction appelée dans les workers.
    row: (id, title, DOI, DONE)
    Remplit EXTRACTION si data, met Has_data=True si data, DONE=True dans CLASSIFICATION.
    Chaque worker ouvre sa propre connexion DB + Session.
    """
    global CURRENT_PAPER

    pid, title, doi, done = row
    start = time.time()

    # Met à jour CURRENT_PAPER pour le debug en cas de crash
    CURRENT_PAPER = {"pid": pid, "doi": doi, "title": title, "worker": worker_id}

    db = get_db_connection()
    cur = db.cursor()
    session = requests.Session()

    try:
        if done:
            elapsed = time.time() - start
            print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: already DONE, skipping ({elapsed:.3f}s)")
            return

        content = fetch_elsevier(session, doi)
        if not content:
            elapsed = time.time() - start
            print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: no content from Elsevier ({elapsed:.3f}s)")
            return

        try:
            data = json.loads(content)
        except Exception as e:
            elapsed = time.time() - start
            print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: JSON parse error: {e} ({elapsed:.3f}s)", file=sys.stderr)
            return

        ftr = data.get("full-text-retrieval-response")
        if not isinstance(ftr, dict):
            elapsed = time.time() - start
            print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: no full-text-retrieval-response ({elapsed:.3f}s)")
            return

        core = ftr.get("coredata")
        if not isinstance(core, dict):
            elapsed = time.time() - start
            print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: no coredata ({elapsed:.3f}s)")
            return

        # 1) Auteurs + OpenAccess
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
        uniq = []
        for a in authors_list:
            if a and a not in seen:
                seen.add(a)
                uniq.append(a)
        authors_str = "; ".join(uniq)

        open_access = False
        oa_article = core.get("openaccessArticle")
        oa_flag = core.get("openaccess")
        if isinstance(oa_article, str) and oa_article.lower() == "true":
            open_access = True
        elif isinstance(oa_flag, str) and oa_flag == "1":
            open_access = True

        # 2) Liens data : regex sur le JSON complet
        files = extract_data_files(content)

        # 3) Map mmcX.xlsx -> URLs d'objets Elsevier quand possible
        objects_section = ftr.get("objects", {}).get("object")
        if objects_section:
            files = map_files_to_elsevier_objects(files, objects_section)

        # 3bis) Normaliser les URLs d'objets Elsevier (Object Retrieval)
        normalized_files = []
        for link in files:
            if isinstance(link, str) and "api.elsevier.com/content/object/eid/" in link:
                normalized_files.append(make_elsevier_object_download_url(link))
            else:
                normalized_files.append(link)
        files = normalized_files

        has_data = bool(files)

        # 4) Mettre à jour CLASSIFICATION (Authors, OA, Has_data, DONE=True)
        update_class_sql = (
            "UPDATE CLASSIFICATION SET Authors = %s, Open_Access = %s, Has_data = %s, DONE = %s "
            "WHERE id = %s"
        )
        try:
            cur.execute(update_class_sql, (authors_str, open_access, has_data, True, pid))
            db.commit()
        except Exception as e:
            db.rollback()
            elapsed = time.time() - start
            print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: error updating CLASSIFICATION: {e} ({elapsed:.3f}s)", file=sys.stderr)
            return

        # 5) Insérer dans EXTRACTION si on a des fichiers
        if files:
            insert_extr_sql = (
                "INSERT INTO EXTRACTION (pid, URL, data_link, done) VALUES (%s, %s, %s, %s)"
            )
            # done = 0 ici ; la vérification se fait en Step 3
            ex_rows = [(pid, f"https://doi.org/{doi}", link, 0) for link in files]
            try:
                cur.executemany(insert_extr_sql, ex_rows)
                db.commit()
            except Exception as e:
                db.rollback()
                elapsed = time.time() - start
                print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: error inserting EXTRACTION: {e} ({elapsed:.3f}s)", file=sys.stderr)
                return

        elapsed = time.time() - start
        print(f"[STEP2][worker {worker_id}] PID {pid} DOI {doi}: has_data={has_data} in {elapsed:.3f}s")

    finally:
        cur.close()
        db.close()


def step2_extract_data_links():
    db = get_db_connection()
    cur = db.cursor()

    select_sql = "SELECT id, title, DOI, DONE FROM CLASSIFICATION"
    cur.execute(select_sql)
    rows = cur.fetchall()
    cur.close()
    db.close()

    with ThreadPoolExecutor(max_workers=NUM_WORKERS) as executor:
        futures = []
        for idx, row in enumerate(rows):
            worker_id = idx % NUM_WORKERS
            futures.append(executor.submit(process_one_paper_step2, row, worker_id))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[STEP2] worker error: {e}", file=sys.stderr)


# ================== Step 3 ==================

def step3_check_downloadable():
    db = get_db_connection()
    cur = db.cursor()
    session = requests.Session()

    select_sql = "SELECT pid, data_link FROM EXTRACTION WHERE done = 0"
    update_sql = "UPDATE EXTRACTION SET done = %s WHERE pid = %s AND data_link = %s"

    cur.execute(select_sql)
    rows = cur.fetchall()

    for pid, link in rows:
        ok = is_data_link_downloadable(link, session)
        try:
            cur.execute(update_sql, (int(ok), pid, link))
            db.commit()
        except Exception as e:
            db.rollback()
            print(f"[STEP3] PID {pid} link {link}: error updating done: {e}", file=sys.stderr)
        print(f"[STEP3] PID {pid} link {link}: downloadable={ok}")

    cur.close()
    db.close()


def main():
    try:
        print("=== STEP 1: load CLASSIFICATION from JSON ===")
        step1_load_classification()
        print("=== STEP 2: extract data links into EXTRACTION (multithread, workers logged) ===")
        step2_extract_data_links()
        print("=== STEP 3: check which data_link are downloadable (Elsevier Excel/CSV only) ===")
        step3_check_downloadable()
        print("=== ALL STEPS DONE ===")
    except KeyboardInterrupt:
        print("\nKeyboard interrupt detected.", file=sys.stderr)
        if CURRENT_PAPER is not None:
            print(
                "Last paper in progress:\n"
                f"  PID      : {CURRENT_PAPER.get('pid')}\n"
                f"  DOI      : {CURRENT_PAPER.get('doi')}\n"
                f"  Title    : {CURRENT_PAPER.get('title')}\n"
                f"  Worker   : {CURRENT_PAPER.get('worker')}",
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
                f"  PID      : {CURRENT_PAPER.get('pid')}\n"
                f"  DOI      : {CURRENT_PAPER.get('doi')}\n"
                f"  Title    : {CURRENT_PAPER.get('title')}\n"
                f"  Worker   : {CURRENT_PAPER.get('worker')}",
                file=sys.stderr,
            )
        raise


if __name__ == "__main__":
    main()