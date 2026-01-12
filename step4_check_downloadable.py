import sys

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


def is_data_link_downloadable(link: str, source: str, session) -> bool:
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
            return bool(sample) and (sample.startswith(b"PK\x03\x04") or sample.startswith(b"\xD0\xCF\x11\xE0"))

        if "text/csv" in ctype or "text/plain" in ctype:
            text_sample = sample.decode("utf-8", errors="ignore").strip()
            if not text_sample:
                return False
            lower = text_sample.lower()
            if lower.startswith("<html") or lower.startswith("<!doctype html") or lower.startswith("<service-error"):
                return False
            return True

        return False

    if source == "zenodo":
        try:
            resp = session.get(link, timeout=30)
        except Exception:
            return False
        if resp.status_code != 200:
            return False
        if "text/html" in (resp.headers.get("Content-Type") or "").lower():
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
