import sys

from pipeline_common import (
    API_KEY,
    detect_source_website,
    extract_data_files,
    fetch_elsevier_json,
    get_db_connection,
    github_data_files_from_link,
    http_get_with_retries,
    log_doi_error,
    make_elsevier_object_download_url,
    make_session,
    map_files_to_elsevier_objects,
    parse_authors_from_coredata,
    print_progress,
    run_threaded,
    split_data_vs_other_links,
    zenodo_data_files_from_link,
)


def _process_one_paper(row, worker_id: int, total: int, counter: dict, lock):
    pid, title, doi, done_flag = row

    import pipeline_common

    pipeline_common.CURRENT_DOI = doi
    pipeline_common.CURRENT_PAPER = {"pid": pid, "doi": doi, "title": title, "worker": worker_id}

    if done_flag:
        with lock:
            counter["done"] += 1
            print_progress("[STEP 3] Extracting data links", counter["done"], total)
        return

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        data = fetch_elsevier_json("article", doi, session)
        if not data:
            return

        ftr = data.get("full-text-retrieval-response")
        if not isinstance(ftr, dict):
            return

        core = ftr.get("coredata") or {}
        if not isinstance(core, dict):
            return

        authors_str = parse_authors_from_coredata(core)
        open_access = (
            str(core.get("openaccessArticle", "")).lower() == "true"
            or str(core.get("openaccess", "")) == "1"
        )

        article_resp = http_get_with_retries(
            session,
            f"https://api.elsevier.com/content/article/doi/{doi}",
            {"X-ELS-APIKey": API_KEY, "Accept": "application/json"},
            doi=doi,
        )
        links = extract_data_files(article_resp.text) if article_resp else []

        objects_section = (ftr.get("objects") or {}).get("object")
        if objects_section:
            links = map_files_to_elsevier_objects(links, objects_section)

        links = [
            make_elsevier_object_download_url(l)
            if isinstance(l, str) and "api.elsevier.com/content/object/eid/" in l
            else l
            for l in links
        ]

        data_files, _ = split_data_vs_other_links(links)
        has_data = bool(data_files)

        base_url = f"https://doi.org/{doi}"
        rows_to_insert = []

        for l in links:
            src = detect_source_website(l)

            if src == "github":
                gh_files = github_data_files_from_link(l)
                if gh_files:
                    rows_to_insert.extend((pid, base_url, src, gf, False) for gf in gh_files)
                else:
                    rows_to_insert.append((pid, base_url, src, l, False))

            elif src == "zenodo":
                zen_files = zenodo_data_files_from_link(l)
                if zen_files:
                    rows_to_insert.extend((pid, base_url, src, zf, False) for zf in zen_files)
                else:
                    rows_to_insert.append((pid, base_url, src, l, False))

            else:
                rows_to_insert.append((pid, base_url, src, l, False))

        cur.execute(
            "UPDATE CLASSIFICATION SET Authors=%s, Open_Access=%s, Has_data=%s, DONE=%s WHERE id=%s",
            (authors_str, open_access, has_data, True, pid),
        )
        db.commit()

        if rows_to_insert:
            cur.executemany(
                "INSERT INTO EXTRACTION (pid, URL, source_website, data_link, done) "
                "VALUES (%s, %s, %s, %s, %s)",
                rows_to_insert,
            )
            db.commit()

    except Exception as e:
        db.rollback()
        print(f"[STEP3] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
        log_doi_error(doi, e, "STEP3 failed")

    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 3] Extracting data links", counter["done"], total)


def run():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute("SELECT id, title, DOI, DONE FROM CLASSIFICATION WHERE DONE = 0")
    rows = cur.fetchall()
    cur.close()
    db.close()

    run_threaded(rows, _process_one_paper, label="STEP3")


def main():
    run()


if __name__ == "__main__":
    main()
