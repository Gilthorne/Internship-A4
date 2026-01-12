import sys

from pipeline_common import (
    CURRENT_DOI,
    fetch_elsevier_json,
    get_db_connection,
    log_doi_error,
    make_session,
    print_progress,
    run_threaded,
)


def extract_countries_from_abstract(data: dict) -> list[str]:
    countries: set[str] = set()
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    ag = head.get("author-group") or []
    if isinstance(ag, dict):
        ag = [ag]

    for g in ag:
        aff = g.get("affiliation") or {}
        if isinstance(aff, dict):
            aff = [aff]
        for a in aff:
            c = a.get("country")
            if isinstance(c, str) and c.strip():
                countries.add(c.strip())
    return sorted(countries)


def extract_organizations_from_abstract(data: dict) -> list[str]:
    orgs: set[str] = set()
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    ag = head.get("author-group") or []
    if isinstance(ag, dict):
        ag = [ag]

    for g in ag:
        aff = g.get("affiliation") or {}
        if isinstance(aff, dict):
            aff = [aff]
        for a in aff:
            org_list = a.get("organization") or []
            if isinstance(org_list, dict):
                org_list = [org_list]
            for o in org_list:
                if isinstance(o, dict):
                    name = o.get("$")
                    if isinstance(name, str) and name.strip():
                        orgs.add(name.strip())
    return sorted(orgs)


def extract_publication_year_from_abstract(data: dict) -> int | None:
    arr = data.get("abstracts-retrieval-response") or {}
    item = arr.get("item") or {}
    bib = item.get("bibrecord") or {}
    head = bib.get("head") or {}
    source = head.get("source") or {}
    pubdate = source.get("publicationdate") or {}
    year_str = pubdate.get("year")
    if isinstance(year_str, str) and year_str.isdigit():
        return int(year_str)
    return None


def _process_one_paper(row, worker_id: int, total: int, counter: dict, lock):
    pid, doi = row
    # update global for ctrl+c message
    import pipeline_common

    pipeline_common.CURRENT_DOI = doi

    if not doi:
        with lock:
            counter["done"] += 1
            print_progress("[STEP 2] Enriching abstracts", counter["done"], total)
        return

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    try:
        data = fetch_elsevier_json("abstract", doi, session)
        if data:
            year = extract_publication_year_from_abstract(data)
            countries = extract_countries_from_abstract(data)
            orgs = extract_organizations_from_abstract(data)

            country_str = "; ".join(countries) if countries else None
            org_str = "; ".join(orgs) if orgs else None

            cur.execute(
                "UPDATE CLASSIFICATION SET Year=%s, Country=%s, Organization=%s WHERE id=%s",
                (year, country_str, org_str, pid),
            )
            db.commit()

    except Exception as e:
        db.rollback()
        print(f"[STEP2] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
        log_doi_error(doi, e, "STEP2 update failed")

    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 2] Enriching abstracts", counter["done"], total)


def run():
    db = get_db_connection()
    cur = db.cursor()
    cur.execute(
        "SELECT id, DOI FROM CLASSIFICATION "
        "WHERE Year IS NULL AND Country IS NULL AND Organization IS NULL"
    )
    rows = cur.fetchall()
    cur.close()
    db.close()

    run_threaded(rows, _process_one_paper, label="STEP2")


def main():
    run()


if __name__ == "__main__":
    main()
