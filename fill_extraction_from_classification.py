import requests
from dotenv import load_dotenv
import os
import mysql.connector as sql
import urllib.parse
import re
import json

load_dotenv()
API_KEY = os.getenv('ELSEVIER_API_KEY')

db_connect = sql.connect(
    user=str(os.getenv('DB_USER')),
    password=str(os.getenv('DB_PASSWORD')),
    host=str(os.getenv('DB_HOST')),
    database=str(os.getenv('DB_NAME'))
)
cursor = db_connect.cursor(dictionary=True)


def extract_data_files(content_text: str):
    """
    Extrait:
      - fichiers CSV / Excel
      - liens GitHub / Zenodo / Mendeley / Elsevier
    Returns: (count, list_of_files)
    """
    patterns = [
        r'\b\w+\.csv\b',                      # .csv files
        r'\b\w+\.xlsx?\b',                    # .xls or .xlsx files
        r'https?://github\.com/[^\s"]+',      # GitHub links
        r'https?://zenodo\.org/[^\s"]+',      # Zenodo
        r'https?://data\.mendeley\.com/[^\s"]+',
        r'https?://(?:www\.)?elsevier\.com/[^\s"]+',
    ]

    files_found = []

    for pattern in patterns:
        matches = re.findall(pattern, content_text, re.IGNORECASE)
        files_found.extend(matches)

    # normalisation simple (URLs terminant par '.')
    normalized = [x.rstrip('.') for x in files_found]

    # Remove duplicates en gardant l'ordre
    seen = set()
    unique = []
    for x in normalized:
        if x not in seen:
            seen.add(x)
            unique.append(x)

    return len(unique), unique


# Charger le JSON pour retrouver l'URL à partir du DOI
with open('ResearchTestLinks.json', encoding='utf-8') as f:
    links_data = json.load(f)

# Construire un dict DOI -> url
doi_to_url = {entry["doi"]: entry["url"] for entry in links_data}


# 1) Récupérer tous les papiers de CLASSIFICATION où DONE = 0
#    ATTENTION: on ne demande plus URL, puisque la colonne n'existe pas
cursor.execute("SELECT id, DOI, title FROM CLASSIFICATION WHERE DONE = 0")
papers = cursor.fetchall()

for paper in papers:
    pid = paper["id"]
    doi = paper["DOI"]
    title = paper["title"]

    # récupérer l'URL correspondante depuis le JSON
    url = doi_to_url.get(doi, "")

    print(f"\n{title} (id={pid}, doi={doi})")

    try:
        response = requests.get(
            f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}',
            headers={
                'X-ELS-APIKey': API_KEY,
                'Accept': 'application/json'
            }
        )
    except Exception:
        print("  erreur: requête DOI")
        continue

    content_text = response.content.decode('utf-8', errors='ignore')

    count, files_list = extract_data_files(content_text)

    print(f"  Number of files and links found: {count}")
    print(f"  Files: {files_list}")

    # insérer une ligne dans EXTRACTION par data_link
    for data_link in files_list:
        try:
            sql_insert = """
                INSERT INTO EXTRACTION (pid, URL, data_link, done)
                VALUES (%s, %s, %s, %s)
            """
            cursor.execute(sql_insert, (pid, url, data_link, False))
            db_connect.commit()
        except Exception:
            print(f"  erreur: insertion EXTRACTION pour {data_link}")
            db_connect.rollback()

    # marquer le papier comme terminé dans CLASSIFICATION
    try:
        cursor.execute(
            "UPDATE CLASSIFICATION SET DONE = 1 WHERE id = %s",
            (pid,)
        )
        db_connect.commit()
    except Exception:
        print("  erreur: update DONE")
        db_connect.rollback()

cursor.close()
db_connect.close()