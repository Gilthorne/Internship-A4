import sys
import os
import re
import requests
import urllib.parse
import urllib.request
from urllib.parse import urlparse

API_KEY = '5e0c4b89c3dc998fda16c52f50e7f4a2'

def extract_doi(url_or_doi):
    """Extrait le DOI depuis une URL ou DOI"""
    doi_pattern = r'10\.\d{4,}/[^\s]+'
    match = re.search(doi_pattern, url_or_doi)
    return match.group(0) if match else None

def get_data_and_extract_files(doi):
    """Récupère les données et extrait les fichiers"""
    # Préparer les endpoints
    endpoints = {
        'article': f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}',
        'abstract': f'https://api.elsevier.com/content/abstract/doi/{urllib.parse.quote(doi)}',
        'search': f'https://api.elsevier.com/content/search/scopus?query=DOI({urllib.parse.quote(doi)})'
    }
    
    headers = {'X-ELS-APIKey': API_KEY, 'Accept': 'application/json'}
    file_urls = []
    
    # Interroger chaque endpoint et extraire les URLs de fichiers
    for name, url in endpoints.items():
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                continue
                
            # Sauvegarder la réponse pour analyse ultérieure
            with open(f"response_{name}.json", "w", encoding="utf-8") as f:
                f.write(response.text)
            
            # Chercher les liens vers des fichiers Excel/CSV
            content = response.text
            download_links = re.findall(r'https?://[^\s"\'<>]+\.(?:xlsx?|csv)\b', content, re.IGNORECASE)
            file_urls.extend(download_links)
            
            # Extraire les objets si disponibles (uniquement pour article)
            if name == 'article' and 'full-text-retrieval-response' in content:
                try:
                    data = response.json()
                    if 'full-text-retrieval-response' in data:
                        full_text = data['full-text-retrieval-response']
                        if 'objects' in full_text and 'object' in full_text['objects']:
                            objects = full_text['objects']['object']
                            if not isinstance(objects, list):
                                objects = [objects]
                            
                            for obj in objects:
                                file_url = obj.get('$')
                                if file_url and any(ext in file_url.lower() for ext in ['.xlsx', '.xls', '.csv']):
                                    file_urls.append(file_url)
                except:
                    pass
        except:
            continue
    
    return list(set(file_urls))  # Retourner une liste sans doublons

def download_files(file_urls, directory="downloads"):
    """Télécharge les fichiers"""
    os.makedirs(directory, exist_ok=True)
    downloaded_files = []
    
    headers = {
        'X-ELS-APIKey': API_KEY,
        'User-Agent': 'Mozilla/5.0',
        'Accept': '*/*'
    }
    
    for url in file_urls:
        try:
            # Obtenir le nom de fichier à partir de l'URL
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)
            
            # Créer un nom de fichier valide si nécessaire
            if not filename or '.' not in filename:
                if 'xlsx' in url.lower():
                    filename = f"file_{abs(hash(url)) % 10000}.xlsx"
                elif 'xls' in url.lower():
                    filename = f"file_{abs(hash(url)) % 10000}.xls"
                elif 'csv' in url.lower():
                    filename = f"file_{abs(hash(url)) % 10000}.csv"
                else:
                    filename = f"file_{abs(hash(url)) % 10000}.dat"
            
            filepath = os.path.join(directory, filename)
            
            # Télécharger le fichier
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                content = response.read()
                
                # Ignorer les fichiers XML qui sont souvent des métadonnées
                if content.startswith(b'<?xml') or content.startswith(b'<attachment-metadata'):
                    continue
                
                with open(filepath, 'wb') as f:
                    f.write(content)
                
                downloaded_files.append(filepath)
        except:
            continue
    
    return downloaded_files

def main():
    if len(sys.argv) < 2:
        print("Usage: python elsevier_scraper.py <DOI_OR_URL> [--download]")
        return False
    
    url_or_doi = sys.argv[1]
    download_option = "--download" in sys.argv
    
    # Extraire le DOI
    doi = extract_doi(url_or_doi)
    if not doi:
        print(False)
        return False
    
    # Récupérer les liens vers les fichiers
    file_urls = get_data_and_extract_files(doi)
    has_files = bool(file_urls)
    
    # Afficher d'abord le résultat booléen
    print(has_files)
    
    # Télécharger les fichiers si demandé
    if has_files and download_option:
        downloaded = download_files(file_urls)
        for file_path in downloaded:
            print(f"Téléchargé: {file_path}")
    elif has_files:
        for url in file_urls:
            print(f"Fichier trouvé: {url}")
    
    return has_files

if __name__ == "__main__":
    main()
