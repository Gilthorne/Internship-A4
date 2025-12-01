import requests
import json
from dotenv import load_dotenv
import os
import mysql.connector as sql
import urllib.parse
import re

load_dotenv()
API_KEY = os.getenv('ELSEVIER_API_KEY')

input_files = open('ResearchTestLinks.json', encoding='utf-8')
json_decode = json.load(input_files)

db_connect = sql.connect(
    user=str(os.getenv('DB_USER')),
    password=str(os.getenv('DB_PASSWORD')),
    host=str(os.getenv('DB_HOST')),
    database=str(os.getenv('DB_NAME'))
)

cursor = db_connect.cursor()


def extract_data_files(content_text: str):
    """
    Extracts:
      - CSV / Excel files
      - GitHub / Zenodo / Mendeley / Elsevier links
    (ZIP files are NOT returned in the final list)
    Returns: (count, list_of_files)
    """
    # What we keep in output
    patterns_keep = [
        r'\b\w+\.csv\b',                      # .csv files
        r'\b\w+\.xlsx?\b',                    # .xls or .xlsx files
        r'https?://(?:dx\.)?doi\.org/10\.\d{4,9}/zenodo\.\d+\b',
        r'https?://data.mendeley.com/datasets/[^\s"]+',
        r'https?://github\.com/[^\s"]+',      # GitHub links
        r'https?://zenodo\.org/[^\s"]+',      # Zenodo
        r'https?://data\.mendeley\.com/[^\s"]+',
        r'https?://(?:www\.)?elsevier\.com/[^\s"]+',
    ]

    # We also detect .zip files for potential filtering later,
    # but we do NOT return them in files_list
    pattern_zip = r'https?://[^\s"]+\.zip\b'

    files_found = []

    # 1) files / links to keep
    for pattern in patterns_keep:
        matches = re.findall(pattern, content_text, re.IGNORECASE)
        files_found.extend(matches)

    # 2) potential detection of zip files
    zip_urls = re.findall(pattern_zip, content_text, re.IGNORECASE)
    # for now: we do nothing with zip_urls, and especially we
    # do not add them to files_found

    # simple normalization for URLs with '.' at the end
    normalized = [x.rstrip('.') for x in files_found]

    # Remove duplicates while preserving order
    seen = set()
    unique = []
    for x in normalized:
        if x not in seen:
            seen.add(x)
            unique.append(x)

    return len(unique), unique


for entry in json_decode:
    url = entry['url']
    doi = entry['doi']
    title = entry['title']

    try:
        response = requests.get(
            f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}',
            headers={
                'X-ELS-APIKey': API_KEY,
                'Accept': 'application/json'
            }
        )
    except Exception:
        print(f"\n{title}")
        print("  erreur: requête DOI")
        continue

    content_text = response.content.decode('utf-8', errors='ignore')

    count, files_list = extract_data_files(content_text)

    print(f"\n{title}")
    print(f"  Number of files and links found: {count}")
    print(f"  Files: {files_list}")

    if count > 0:
        try:
            sql_insert = "INSERT INTO CLASSIFICATION (title, DOI, DONE) VALUES (%s, %s, %s)"
            cursor.execute(sql_insert, (title, doi, False))
            db_connect.commit()
        except Exception:
            print("  erreur: insertion DB")
            db_connect.rollback()

cursor.close()
db_connect.close()