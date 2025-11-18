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
    Extrait:
      - fichiers CSV / Excel
      - liens GitHub / Zenodo / Mendeley / Elsevier
    (les ZIP ne sont pas retournés dans la liste finale)
    Returns: (count, list_of_files)
    """
    # Ce qu'on garde en sortie
    patterns_keep = [
        r'\b\w+\.csv\b',                      # .csv files
        r'\b\w+\.xlsx?\b',                    # .xls or .xlsx files
        r'https?://github\.com/[^\s"]+',      # GitHub links
        r'https?://zenodo\.org/[^\s"]+',      # Zenodo
        r'https?://data\.mendeley\.com/[^\s"]+',
        r'https?://(?:www\.)?elsevier\.com/[^\s"]+',
    ]

    # On détecte aussi les .zip pour filtrer éventuellement plus tard si tu veux,
    # mais on NE les retourne PAS dans files_list
    pattern_zip = r'https?://[^\s"]+\.zip\b'

    files_found = []

    # 1) fichiers / liens à garder
    for pattern in patterns_keep:
        matches = re.findall(pattern, content_text, re.IGNORECASE)
        files_found.extend(matches)

    # 2) détection éventuelle de zip (si tu veux les exploiter plus tard)
    zip_urls = re.findall(pattern_zip, content_text, re.IGNORECASE)
    # pour l'instant: on ne fait rien avec zip_urls, et surtout on
    # ne les ajoute pas à files_found

    # normalisation simple pour URLs avec '.' à la fin
    normalized = [x.rstrip('.') for x in files_found]

    # Remove duplicates en gardant l'ordre
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