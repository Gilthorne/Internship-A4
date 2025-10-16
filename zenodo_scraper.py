import urllib.request
import urllib.parse
import re
import sys

def extract_zenodo_id(url_or_doi):
    """Extrait l'ID Zenodo depuis une URL ou DOI"""
    # Patterns pour différents formats
    patterns = [
        r'zenodo\.org/records?/(\d+)',     # https://zenodo.org/records/17075237
        r'zenodo\.org/record/(\d+)',       # https://zenodo.org/record/17075237
        r'10\.5281/zenodo\.(\d+)',         # DOI officiel Zenodo: 10.5281/zenodo.17075237
        r'zenodo\.(\d+)',                  # Format court: zenodo.17075237
        r'doi\.org/10\.5281/zenodo\.(\d+)', # URL DOI complète
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_doi)
        if match:
            return match.group(1)
    
    # Si c'est juste un numéro
    if url_or_doi.isdigit():
        return url_or_doi
        
    return None

def has_excel_csv_files(url_or_doi):
    """Vérifie si le record Zenodo contient des fichiers Excel ou CSV et retourne la liste"""
    zenodo_id = extract_zenodo_id(url_or_doi)
    
    if not zenodo_id:
        return False, []
    
    url = f"https://zenodo.org/records/{zenodo_id}"
    
    try:
        with urllib.request.urlopen(url) as response:
            html_content = response.read().decode('utf-8')
    except Exception as e:
        print(f"Erreur lors de l'accès à l'URL: {str(e)}")
        return False, []
    
    # Chercher les liens de téléchargement dans le HTML
    excel_pattern = r'/records/\d+/files/([^"\']+?\.(?:xlsx?|csv))(?:\?[^"\']*)?'
    matches = set(re.findall(excel_pattern, html_content, re.IGNORECASE))
    
    file_list = sorted(list(matches))
    return bool(file_list), file_list

def main():
    if len(sys.argv) < 2:
        print("Usage: python zenodo_scraper.py <ZENODO_URL_OR_DOI>")
        return False
    
    url_or_doi = sys.argv[1]
    has_files, file_list = has_excel_csv_files(url_or_doi)
    
    print(has_files)
    if has_files:
        print("Fichiers Excel/CSV trouvés:")
        for file in file_list:
            print(f"- {file}")
    else:
        print("Aucun fichier Excel/CSV trouvé")
    
    return has_files

if __name__ == "__main__":
    main()