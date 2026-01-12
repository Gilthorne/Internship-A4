import json
import sys

from pipeline_common import JSON_PATH, extract_doi_from_link, get_db_connection, logger, print_progress


def run(json_path: str = JSON_PATH):
    try:
        with open(json_path, encoding="utf-8") as f:
            links = json.load(f)
    except Exception as e:
        print(f"[STEP1] cannot read {json_path}: {e}", file=sys.stderr)
        logger.error("DOI N/A: STEP1 cannot read %s: %s", json_path, e)
        return

    entries = [e for e in links if isinstance(e, dict) and e.get("doi_link")]
    total = len(entries)
    done = 0

    db = get_db_connection()
    cur = db.cursor()

    select_sql = "SELECT id FROM CLASSIFICATION WHERE DOI = %s"
    insert_sql = (
        "INSERT INTO CLASSIFICATION (title, Authors, DOI, Open_Access, Has_data, DONE) "
        "VALUES (%s, %s, %s, %s, %s, %s)"
    )

    try:
        for entry in entries:
            doi = extract_doi_from_link(entry.get("doi_link"))
            title = entry.get("title") or "N/A"

            if not doi:
                done += 1
                print_progress("[STEP 1] Processing DOIs", done, total)
                continue

            try:
                cur.execute(select_sql, (doi,))
                if not cur.fetchone():
                    cur.execute(insert_sql, (title, "", doi, False, False, False))
                    db.commit()
            except Exception as e:
                db.rollback()
                print(f"[STEP1] Error inserting {doi}: {e}", file=sys.stderr)
                logger.error("DOI %s: STEP1 insert failed: %s", doi, e)

            done += 1
            print_progress("[STEP 1] Processing DOIs", done, total)

    finally:
        cur.close()
        db.close()


def main():
    run()


if __name__ == "__main__":
    main()
