import urllib.request
import urllib.parse
import re
import zipfile
import os
import sys
import tempfile
import shutil

def extract_github_info(url_or_repo):
    """Extrait les informations GitHub depuis une URL ou nom de repo"""
    patterns = [
        r'github\.com/([^/]+)/([^/\s]+)',  # https://github.com/user/repo
        r'^([^/]+)/([^/\s]+)$',            # user/repo
    ]
    
    for pattern in patterns:
        match = re.search(pattern, url_or_repo)
        if match:
            return match.group(1), match.group(2)
    
    return None, None

def download_github_zip(owner, repo, download_dir="downloads"):
    """Télécharge le ZIP de la branche par défaut depuis GitHub"""
    # Essayer les branches communes dans l'ordre
    branches = ['main', 'master']
    
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        print(f"Dossier créé: {os.path.abspath(download_dir)}")
    
    for branch in branches:
        zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
        temp_zip = os.path.join(download_dir, f"{repo}-{branch}.zip")
        
        try:
            print(f"Tentative téléchargement branche '{branch}': {owner}/{repo}")
            print(f"URL: {zip_url}")
            urllib.request.urlretrieve(zip_url, temp_zip)
            print(f"ZIP téléchargé: {temp_zip}")
            return temp_zip
        except Exception as e:
            print(f"Échec branche '{branch}': {e}")
            # Supprimer le fichier partiel s'il existe
            if os.path.exists(temp_zip):
                os.remove(temp_zip)
            continue
    
    print(f"Aucune branche accessible trouvée pour {owner}/{repo}")
    return None

def extract_excel_csv_from_zip(zip_path, download_dir="downloads"):
    """Extrait seulement les fichiers Excel/CSV du ZIP"""
    extracted_files = []
    
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Lister tous les fichiers dans le ZIP
            all_files = zip_ref.namelist()
            
            # Filtrer pour ne garder que Excel/CSV
            excel_csv_files = [f for f in all_files if f.lower().endswith(('.xlsx', '.xls', '.csv'))]
            
            print(f"Fichiers Excel/CSV trouvés dans le ZIP: {len(excel_csv_files)}")
            
            for file_path in excel_csv_files:
                # Extraire juste le nom du fichier (sans le chemin du repo)
                filename = os.path.basename(file_path)
                
                # Éviter les doublons
                counter = 1
                base_filename = filename
                while os.path.exists(os.path.join(download_dir, filename)):
                    name, ext = os.path.splitext(base_filename)
                    filename = f"{name}_{counter}{ext}"
                    counter += 1
                
                # Extraire le fichier
                try:
                    with zip_ref.open(file_path) as source, open(os.path.join(download_dir, filename), 'wb') as target:
                        target.write(source.read())
                    
                    file_size = os.path.getsize(os.path.join(download_dir, filename))
                    print(f"Extrait: {filename} ({file_size} bytes)")
                    extracted_files.append({
                        'filename': filename,
                        'original_path': file_path,
                        'size': file_size,
                        'type': 'Excel' if filename.lower().endswith(('.xlsx', '.xls')) else 'CSV'
                    })
                except Exception as e:
                    print(f"Erreur extraction {file_path}: {e}")
        
        return extracted_files
        
    except Exception as e:
        print(f"Erreur lecture ZIP: {e}")
        return []

def process_github_repo(input_value, download=True):
    """Traite un repo GitHub et télécharge/extrait les fichiers Excel/CSV"""
    owner, repo = extract_github_info(input_value)
    
    if not owner or not repo:
        print("URL ou nom de repo GitHub non valide")
        print("Formats acceptés:")
        print("  - https://github.com/user/repo")
        print("  - user/repo")
        return
    
    print(f"Analyse du repo GitHub: {owner}/{repo}")
    print(f"URL: https://github.com/{owner}/{repo}")
    
    if not download:
        print("Mode téléchargement désactivé")
        return
    
    download_dir = "downloads"
    
    # Étape 1: Télécharger le ZIP
    zip_path = download_github_zip(owner, repo, download_dir)
    if not zip_path:
        print("Échec du téléchargement")
        return
    
    # Étape 2: Extraire les fichiers Excel/CSV
    extracted_files = extract_excel_csv_from_zip(zip_path, download_dir)
    
    # Étape 3: Supprimer le ZIP
    try:
        os.remove(zip_path)
        print(f"ZIP supprimé: {zip_path}")
    except:
        pass
    
    # Étape 4: Rapport final
    print(f"\n{len(extracted_files)} fichier(s) Excel/CSV extraits avec succès")
    print(f"Dossier: {os.path.abspath(download_dir)}")
    
    if extracted_files:
        print("\nFichiers extraits:")
        for file_info in extracted_files:
            print(f"   - {file_info['type']}: {file_info['filename']} ({file_info['size']} bytes)")
            print(f"     Origine: {file_info['original_path']}")
    
    # Vérification finale
    actual_files = [f for f in os.listdir(download_dir) if f.endswith(('.xlsx', '.xls', '.csv'))]
    print(f"\nFichiers Excel/CSV sur disque: {len(actual_files)}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python github_scraper.py <GITHUB_URL_OR_REPO>")
        print("Exemples:")
        print("  python github_scraper.py https://github.com/user/repo")
        print("  python github_scraper.py user/repo")
        print("  python github_scraper.py gergelydinya/AviTrack")
        return
    
    input_value = sys.argv[1]
    process_github_repo(input_value, download=True)

if __name__ == "__main__":
    main()
