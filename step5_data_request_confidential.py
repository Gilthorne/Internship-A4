import re
import sys

from pipeline_common import (
    fetch_elsevier_json,
    get_db_connection,
    log_doi_error,
    make_session,
    print_progress,
    run_threaded,
)


def extract_all_text_from_json(obj, depth=0, max_depth=10, collected_texts=None):
    """
    Recursively extract all string values from nested JSON structure.
    Filters strings longer than 20 chars to avoid metadata/keys.
    """
    if collected_texts is None:
        collected_texts = []
    
    if depth > max_depth:
        return collected_texts
    
    if isinstance(obj, str):
        if len(obj) > 20:
            collected_texts.append(obj)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            extract_all_text_from_json(value, depth + 1, max_depth, collected_texts)
    elif isinstance(obj, list):
        for item in obj:
            extract_all_text_from_json(item, depth + 1, max_depth, collected_texts)
    
    return collected_texts


def extract_full_text_content(data: dict) -> str:
    """
    Extract textual content from Elsevier Full Text API response.
    Falls back to recursive extraction if standard paths are empty.
    """
    content_parts = []

    try:
        full_text = data.get("full-text-retrieval-response") or {}
        
        if not full_text:
            texts = extract_all_text_from_json(data)
            return " ".join(texts)

        coredata = full_text.get("coredata") or {}
        
        # Main body text
        objects = full_text.get("objects") or {}
        if isinstance(objects, dict):
            body = objects.get("body") or {}
            if isinstance(body, dict):
                sections = body.get("sections") or []
                if isinstance(sections, list):
                    for section in sections:
                        if isinstance(section, dict):
                            text = section.get("$") or section.get("ce:para") or ""
                            if text:
                                content_parts.append(str(text))

        # Data availability statement
        data_avail = coredata.get("data-availability") or {}
        if isinstance(data_avail, dict):
            statement = data_avail.get("$") or ""
            if statement:
                content_parts.append(str(statement))

        # Acknowledgments
        ack = coredata.get("acknowledgment") or {}
        if isinstance(ack, dict):
            ack_text = ack.get("$") or ""
            if ack_text:
                content_parts.append(str(ack_text))

        # Fallback to recursive if nothing found
        if not content_parts:
            texts = extract_all_text_from_json(full_text)
            content_parts.extend(texts)

    except Exception as e:
        print(f"[STEP5] Error extracting text: {e}", file=sys.stderr)

    return " ".join(content_parts)


def check_pattern(text: str, pattern: str) -> bool:
    """
    Check if pattern appears in text (case-insensitive).
    """
    return re.search(pattern, text, re.IGNORECASE) is not None


def classify_data_availability(full_text: str) -> tuple[bool, bool]:
    """
    Simple pattern matching classification.
    
    Logic:
    - If "on request" found -> data_request = True
    - If "confidential" found AND NOT "on request" -> data_confidential = True
    - Otherwise both False
    
    Returns:
        (data_request, data_confidential)
    """
    data_request = False
    data_confidential = False
    
    # Check for "on request"
    if check_pattern(full_text, r"on\s+request"):
        data_request = True
    # Check for "confidential" only if "on request" not found
    elif check_pattern(full_text, r"confidential"):
        data_confidential = True
    
    return data_request, data_confidential


def _process_one_article(row, worker_id: int, total: int, counter: dict, lock):
    """
    Process one article to classify data availability.
    """
    pid, doi = row

    import pipeline_common
    pipeline_common.CURRENT_DOI = doi

    if not doi:
        with lock:
            counter["done"] += 1
            print_progress("[STEP 5] Classifying data availability", counter["done"], total)
        return

    db = get_db_connection()
    cur = db.cursor()
    session = make_session()

    data_request = False
    data_confidential = False

    try:
        # Fetch full text from Elsevier
        data = fetch_elsevier_json("article", doi, session)
        
        if data:
            full_text = extract_full_text_content(data)
            
            if full_text:
                data_request, data_confidential = classify_data_availability(full_text)

        # Update database
        cur.execute(
            "UPDATE CLASSIFICATION SET data_request=%s, data_confidential=%s WHERE id=%s",
            (data_request, data_confidential, pid),
        )
        db.commit()

    except Exception as e:
        db.rollback()
        print(f"[STEP5] PID {pid} DOI {doi}: ERROR {e}", file=sys.stderr)
        log_doi_error(doi, e, "STEP5 classification failed")

    finally:
        cur.close()
        db.close()
        with lock:
            counter["done"] += 1
            print_progress("[STEP 5] Classifying data availability", counter["done"], total)


def run():
    """
    Main function: process all articles with Has_data = 0 and both columns = 0
    """
    db = get_db_connection()
    cur = db.cursor()
    
    # Select only articles with Has_data = 0 AND data_request = 0 AND data_confidential = 0
    cur.execute(
        "SELECT id, DOI FROM CLASSIFICATION "
        "WHERE Has_data = 0 AND data_request = 0 AND data_confidential = 0"
    )
    rows = cur.fetchall()
    cur.close()
    db.close()

    print(f"[STEP5] Found {len(rows)} articles to classify")

    if not rows:
        print("[STEP5] No articles to process")
        return

    run_threaded(rows, _process_one_article, label="STEP5")


def main():
    run()


if __name__ == "__main__":
    main()
