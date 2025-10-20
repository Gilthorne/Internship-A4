import urllib.request
import urllib.parse
import re
import sys
import os
from concurrent.futures import ThreadPoolExecutor

def extract_zenodo_id(url_or_doi):
    """Extrait l'ID Zenodo depuis une URL ou DOI"""
    # Patterns pour différents formats
    patterns = [
        r'zenodo\.org/records?/(\d+)',
        r'zenodo\.org/record/(\d+)',
        r'10\.5281/zenodo\.(\d+)',
        r'zenodo\.(\d+)',
        r'doi\.org/10\.5281/zenodo\.(\d+)'
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_doi)
        if match:
            return match.group(1)
    
    return url_or_doi if url_or_doi.isdigit() else None

def has_excel_csv_files(url_or_doi):
    """Vérifie si le record Zenodo contient des fichiers Excel ou CSV"""
    zenodo_id = extract_zenodo_id(url_or_doi)
    if not zenodo_id:
        return False, []
    
    # Configurer l'opener avec un User-Agent pour éviter les blocages
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)
    
    # Essayer les deux formats d'URL
    urls = [
        f"https://zenodo.org/records/{zenodo_id}",
        f"https://zenodo.org/record/{zenodo_id}"
    ]
    
    html_content = ""
    for url in urls:
        try:
            with urllib.request.urlopen(url) as response:
                html_content = response.read().decode('utf-8')
                break
        except Exception:
            continue
    
    if not html_content:
        return False, []
    
    # Utiliser une expression régulière plus robuste pour trouver les fichiers
    file_list = []
    
    # Chercher dans les tables de fichiers
    table_rows = re.findall(r'<tr[^>]*>.*?<td[^>]*>(.*?)</td>.*?</tr>', html_content, re.DOTALL)
    for row in table_rows:
        file_match = re.search(r'>([^<>]+\.(?:xlsx?|csv))<', row, re.IGNORECASE)
        if file_match:
            file_list.append(file_match.group(1))
    
    # Chercher dans les liens
    href_matches = re.findall(r'href=["\'](?:/records?/\d+/files/|/api/records/\d+/files/)([^"\'>\s]+\.(?:xlsx?|csv))(?:\?[^"\']*)?["\']', html_content, re.IGNORECASE)
    file_list.extend(href_matches)
    
    # Chercher dans le texte
    text_matches = re.findall(r'>([^<>]+\.(?:xlsx?|csv))<', html_content, re.IGNORECASE)
    file_list.extend(text_matches)
    
    # Nettoyer et dédupliquer
    cleaned_files = []
    for file in file_list:
        cleaned = file.replace('&amp;', '&').replace('%20', ' ')
        if cleaned not in cleaned_files:
            cleaned_files.append(cleaned)
    
    return bool(cleaned_files), cleaned_files

def download_file(args):
    """Télécharge un seul fichier - pour le multithreading"""
    filename, base_urls, directory = args
    os.makedirs(directory, exist_ok=True)
    
    # Créer un opener avec User-Agent
    opener = urllib.request.build_opener()
    opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
    urllib.request.install_opener(opener)
    
    filepath = os.path.join(directory, filename)
    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    
    for base_url in base_urls:
        try:
            download_url = base_url + urllib.parse.quote(filename)
            urllib.request.urlretrieve(download_url, filepath)
            return filepath
        except Exception:
            continue
    
    return None

def download_files(file_list, zenodo_id, directory="downloads"):
    """Télécharge les fichiers Excel/CSV trouvés en parallèle"""
    if not file_list:
        return []
    
    base_urls = [
        f"https://zenodo.org/records/{zenodo_id}/files/",
        f"https://zenodo.org/record/{zenodo_id}/files/"
    ]
    
    # Utiliser du multithreading pour accélérer les téléchargements
    args_list = [(filename, base_urls, directory) for filename in file_list]
    downloaded_files = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        for i, result in enumerate(executor.map(download_file, args_list), 1):
            if result:
                downloaded_files.append(result)    
    return downloaded_files

def main():
    if len(sys.argv) < 2:
        print("Usage: python zenodo_scraper.py <ZENODO_URL_OR_DOI>")
        return False
    
    url_or_doi = sys.argv[1]
    has_files, file_list = has_excel_csv_files(url_or_doi)
    
    # Afficher le résultat booléen
    print(has_files)
    
    if has_files:
        print(f"{len(file_list)} fichier(s) Excel/CSV trouvé(s)")
        zenodo_id = extract_zenodo_id(url_or_doi)
        if zenodo_id:
            downloaded = download_files(file_list, zenodo_id)
            print(f"Téléchargement terminé: {len(downloaded)}/{len(file_list)} fichiers")
    else:
        print("Aucun fichier Excel/CSV trouvé")
    
    return has_files

if __name__ == "__main__":
    main()