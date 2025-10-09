import urllib.request
import urllib.parse
import re
import json
import os
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

def get_zenodo_files(zenodo_id):
    """Récupère la liste des fichiers depuis la page Zenodo publique"""
    url = f"https://zenodo.org/records/{zenodo_id}"
    
    try:
        with urllib.request.urlopen(url) as response:
            html_content = response.read().decode('utf-8')
    except Exception as e:
        print(f"Erreur lors de l'accès à la page Zenodo: {e}")
        return []
    
    # Chercher les liens de téléchargement dans le HTML
    # Zenodo utilise des URLs comme: /records/ID/files/filename.xlsx?download=1
    file_pattern = r'/records/\d+/files/([^"\']+?\.(?:xlsx?|csv))(?:\?[^"\']*)?'
    matches = re.findall(file_pattern, html_content, re.IGNORECASE)
    
    # Utiliser un set pour éliminer les doublons
    unique_files = set()
    files = []
    
    for filename in matches:
        # Décoder les caractères URL encodés (comme %20 pour les espaces)
        decoded_filename = urllib.parse.unquote(filename)
        
        # Éviter les doublons
        if decoded_filename not in unique_files:
            unique_files.add(decoded_filename)
            
            # Encoder correctement l'URL pour le téléchargement
            encoded_filename = urllib.parse.quote(decoded_filename)
            download_url = f"https://zenodo.org/records/{zenodo_id}/files/{encoded_filename}?download=1"
            
            files.append({
                'filename': decoded_filename,  # Nom décodé pour l'affichage
                'url': download_url,           # URL encodée pour le téléchargement
                'type': 'Excel' if decoded_filename.lower().endswith(('.xlsx', '.xls')) else 'CSV'
            })
    
    return files

def download_file(file_info, download_dir="downloads"):
    """Télécharge un fichier"""
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
    
    filename = file_info['filename']
    url = file_info['url']
    filepath = os.path.join(download_dir, filename)
    
    # Vérifier si le fichier existe déjà
    if os.path.exists(filepath):
        return False  # Fichier déjà existant, ne pas télécharger
    
    try:
        urllib.request.urlretrieve(url, filepath)
        return True
    except Exception as e:
        print(f"Erreur téléchargement {filename}: {e}")
        return False

def process_zenodo_record(input_value, download=False):
    """Traite un record Zenodo et optionnellement télécharge les fichiers"""
    zenodo_id = extract_zenodo_id(input_value)
    
    if not zenodo_id:
        print("ID Zenodo non valide")
        return
    
    print(f"Analyse du record Zenodo: {zenodo_id}")
    print(f"URL: https://zenodo.org/records/{zenodo_id}")
    
    files = get_zenodo_files(zenodo_id)
    
    if not files:
        print("Aucun fichier Excel/CSV trouvé sur cette page Zenodo")
        return
    
    print(f"\n{len(files)} fichier(s) Excel/CSV unique(s) trouvé(s):")
    for i, file_info in enumerate(files, 1):
        print(f"   {i}. {file_info['type']}: {file_info['filename']}")
    
    if download:
        download_dir = "downloads"
        success_count = 0
        skipped_count = 0
        
        for file_info in files:
            filepath = os.path.join(download_dir, file_info['filename'])
            if os.path.exists(filepath):
                skipped_count += 1
            else:
                if download_file(file_info, download_dir):
                    success_count += 1
        
        print(f"\n{success_count} fichier(s) téléchargés")
        if skipped_count > 0:
            print(f"{skipped_count} fichier(s) ignorés (déjà existants)")
    else:
        print(f"\nPour télécharger, utilisez: python zenodo_scraper.py {input_value} --download")

def main():
    if len(sys.argv) < 2:
        print("Usage: python zenodo_scraper.py <ZENODO_URL_OR_DOI> [--download]")
        print("Exemples:")
        print("  python zenodo_scraper.py https://zenodo.org/records/17075237")
        print("  python zenodo_scraper.py 10.5281/zenodo.17075237")
        print("  python zenodo_scraper.py 17075237 --download")
        return
    
    input_value = sys.argv[1]
    download = '--download' in sys.argv
    
    process_zenodo_record(input_value, download)

if __name__ == "__main__":
    main()