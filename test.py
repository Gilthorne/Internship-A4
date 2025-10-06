import json
import sys
import os
import re
import subprocess

def normalize_url(url):
    """Normalize URLs by removing trailing punctuation and standardizing format"""
    url = re.sub(r'[.,;:]$', '', url)
    return url

def extract_unique_repos(json_files):
    """Extract unique repository URLs from all JSON files"""
    unique_repos = set()
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                content = f.read()
            github_pattern = r'https?://(?:www\.)?github\.com/[\w\-\.]+/[\w\-\.]+\b'
            mendeley_pattern = r'https?://(?:www\.)?data\.mendeley\.com/datasets/[\w\-/]+\b'
            zenodo_pattern = r'https?://(?:www\.)?zenodo\.org/records?/[\d]+\b'
            # Also look for direct links to xlsx/csv in Zenodo
            zenodo_file_pattern = r'https?://(?:www\.)?zenodo\.org/record/\d+/files/[^"\s]+?\.(?:xlsx?|csv)\b'
            matches = (
                re.findall(github_pattern, content) +
                re.findall(mendeley_pattern, content) +
                re.findall(zenodo_pattern, content) +
                re.findall(zenodo_file_pattern, content)
            )
            for url in matches:
                unique_repos.add(normalize_url(url))
        except Exception as e:
            print(f"Erreur lors de l'analyse du fichier {json_file}: {e}")
    return unique_repos

def check_for_excel_csv_files(json_files):
    """Check for Excel/CSV files in JSON responses and also in Zenodo links"""
    excel_csv_files = []
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # Extract objects from full-text response
            objects = []
            if 'full-text-retrieval-response' in data:
                full_text = data.get('full-text-retrieval-response', {})
                objects_data = full_text.get('objects', {})
                objects = objects_data.get('object', [])
                if not isinstance(objects, list):
                    objects = [objects] if objects else []
            for obj in objects:
                mimetype = obj.get('@mimetype', '').lower()
                multimediatype = obj.get('@multimediatype', '').lower()
                file_url = obj.get('$', '')
                ref = obj.get('@ref', '')
                # Check for Excel files
                is_excel = any([
                    "excel" in mimetype,
                    "excel" in multimediatype,
                    "spreadsheet" in mimetype,
                    ".xlsx" in file_url.lower(),
                    ".xls" in file_url.lower(),
                ])
                # Check for CSV files
                is_csv = any([
                    "csv" in mimetype,
                    "csv" in multimediatype,
                    "comma separated" in multimediatype,
                    ".csv" in file_url.lower(),
                ])
                if is_excel or is_csv:
                    excel_csv_files.append({
                        "type": "Excel" if is_excel else "CSV",
                        "ref": ref or file_url
                    })
            # Also: scan for direct links to .xlsx/.csv in the JSON text (for Zenodo etc)
            with open(json_file, 'r', encoding='utf-8') as f:
                content = f.read()
            file_links = re.findall(r'https?://[^\s"]+?\.(?:xlsx?|csv)\b', content, re.IGNORECASE)
            for link in file_links:
                # Avoid duplicates
                if not any(link in f['ref'] for f in excel_csv_files):
                    ext = os.path.splitext(link)[1].lower()
                    excel_csv_files.append({
                        "type": "Excel" if ext in (".xlsx", ".xls") else "CSV",
                        "ref": link
                    })
        except Exception as e:
            pass
    return excel_csv_files

def main():
    if len(sys.argv) != 2:
        print("Usage: python test.py <DOI>")
        print("Exemple: python test.py 10.1016/j.seppur.2025.134949")
        return
    doi = sys.argv[1]
    print(f"🔍 Analyse des fichiers pour DOI: {doi}")
    try:
        subprocess.run(['php', 'd:/Internship A4/elsevier_parse.php', doi], check=True)
        print("✅ Script PHP exécuté avec succès")
    except subprocess.CalledProcessError:
        print("❌ Erreur lors de l'exécution du script PHP")
        return
    json_files = [
        'd:/Internship A4/response_article.json',
        'd:/Internship A4/response_abstract.json',
        'd:/Internship A4/response_search.json'
    ]
    excel_csv_files = check_for_excel_csv_files(json_files)
    repositories = extract_unique_repos(json_files)
    print("\n" + "=" * 60)
    if repositories or excel_csv_files:
        print("✅ DONNÉES TROUVÉES!")
        if excel_csv_files:
            print(f"📊 {len(excel_csv_files)} fichier(s) Excel/CSV:")
            already = set()
            for file in excel_csv_files:
                if file['ref'] not in already:
                    print(f"   - {file['type']}: {file['ref']}")
                    already.add(file['ref'])
        if repositories:
            print(f"🔗 {len(repositories)} lien(s) unique(s) vers des repositories de données:")
            for repo in sorted(repositories):
                repo_type = "GitHub" if "github.com" in repo else "Zenodo" if "zenodo.org" in repo else "Mendeley Data"
                print(f"   - {repo_type}: {repo}")
    else:
        print("❌ AUCUNE DONNÉE TROUVÉE")
        print("   Ni fichiers Excel/CSV, ni liens vers GitHub/Zenodo/Mendeley Data")

if __name__ == "__main__":
    main()