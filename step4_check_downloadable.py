import sys
import re
import requests
from pipeline_common import (
    API_KEY,
    get_db_connection,
    http_get_with_retries,
    logger,
    make_elsevier_object_download_url,
    make_session,
    print_progress,
    run_threaded,
)


def is_data_link_downloadable(link: str, source: str, session: requests.Session) -> bool:
    if not isinstance(link, str) or not link.strip():
        return False

    if source == "elsevier" and "api.elsevier.com/content/object/eid/" in link:
        # Nettoyer l'URL des paramètres httpAccept et view problématiques
        clean_url = re.sub(r'[?&]httpAccept=[^&]*', '', link)
        clean_url = re.sub(r'[?&]view=[^&]*', '', clean_url)
        
        # Ajouter la clé API dans l'URL si absente
        separator = '&' if '?' in clean_url else '?'
        if 'apiKey=' not in clean_url: 
            clean_url = f"{clean_url}{separator}apiKey={API_KEY}"
        
        # Utiliser le header Accept au lieu du paramètre httpAccept
        headers = {
            "X-ELS-APIKey": API_KEY,
            "Accept": "text/csv, application/vnd.ms-excel, application/vnd. openxmlformats-officedocument.spreadsheetml. sheet, application/octet-stream, */*"
        }
        
        resp = http_get_with_retries(session, clean_url, headers)
        
        if not resp or resp.status_code != 200:
            return False

        clen = resp.headers.get("Content-Length")
        try:
            clen_int = int(clen) if clen is not None else None
        except ValueError:
            clen_int = None
        
        if clen_int is not None and clen_int <= 0:
            return False

        sample = resp.content[: 512]
        if not sample: 
            return False

        # Vérifier que ce n'est pas du HTML d'erreur
        text_sample = sample.decode("utf-8", errors="ignore").strip().lower()
        if text_sample.startswith("<html") or text_sample.startswith("<! doctype") or text_sample.startswith("<service-error"):
            return False

        return True

    if source == "zenodo": 
        try:
            resp = session.get(link, timeout=30)
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


def _process_one_link(row, worker_id: int, total: int, counter: dict, lock):
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
        logger.error("DOI N/A: STEP4 link error: %s", e)

    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 4] Checking downloads", counter["done"], total)


def run():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT pid, data_link, source_website FROM EXTRACTION WHERE done = 0")
    rows = cur.fetchall()
    cur.close()
    db.close()

    run_threaded(rows, _process_one_link, label="STEP4")


def main():
    run()


if __name__ == "__main__":
    main()
