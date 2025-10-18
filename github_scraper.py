import re
import sys
import requests
import os
from urllib.parse import urlparse

def extract_repo_info(github_url):
    """Extrait le nom d'utilisateur et le nom du repo à partir d'une URL GitHub"""
    # Nettoyer l'URL
    parsed_url = urlparse(github_url)
    if parsed_url.netloc != 'github.com':
        return None, None
    
    # Extraire les parties du chemin
    path_parts = [part for part in parsed_url.path.split('/') if part]
    if len(path_parts) < 2:
        return None, None
    
    # Les deux premières parties sont l'utilisateur et le repo
    return path_parts[0], path_parts[1]

def has_excel_csv_files(github_url):
    """Vérifie si le dépôt GitHub contient des fichiers Excel/CSV et retourne la liste"""
    username, repo = extract_repo_info(github_url)
    
    if not username or not repo:
        print(f"URL GitHub invalide: {github_url}")
        return False, []
    
    # Utiliser l'API GitHub pour récupérer les fichiers
    api_url = f"https://api.github.com/repos/{username}/{repo}/git/trees/main?recursive=1"
    
    try:
        response = requests.get(api_url)
        
        # Si main n'est pas trouvé, essayer avec master
        if response.status_code == 404:
            api_url = f"https://api.github.com/repos/{username}/{repo}/git/trees/master?recursive=1"
            response = requests.get(api_url)
        
        if response.status_code != 200:
            print(f"Erreur lors de l'accès au dépôt: {response.status_code}")
            return False, []
        
        data = response.json()
        
        if "tree" not in data:
            print("Structure de réponse API inattendue")
            return False, []
        
        # Chercher les fichiers Excel/CSV
        excel_csv_files = []
        for item in data["tree"]:
            if item["type"] == "blob":
                path = item["path"]
                if re.search(r'\.(xlsx?|csv)$', path, re.IGNORECASE):
                    excel_csv_files.append({
                        'path': path,
                        'url': f"https://raw.githubusercontent.com/{username}/{repo}/main/{path}"
                    })
        
        return bool(excel_csv_files), excel_csv_files
    
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return False, []

def download_files(file_list, directory="downloads"):
    """Télécharge les fichiers Excel/CSV trouvés"""
    os.makedirs(directory, exist_ok=True)
    downloaded_files = []
    
    for file_info in file_list:
        try:
            path = file_info['path']
            url = file_info['url']
            
            print(f"Téléchargement de {path}...")
            
            # Créer les sous-répertoires si nécessaire
            filepath = os.path.join(directory, path)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # Télécharger le fichier
            response = requests.get(url)
            if response.status_code != 200:
                print(f"Erreur: HTTP {response.status_code}")
                continue
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            print(f"Fichier téléchargé: {filepath}")
            downloaded_files.append(filepath)
            
        except Exception as e:
            print(f"Erreur lors du téléchargement de {file_info['path']}: {str(e)}")
    
    return downloaded_files

def main():
    if len(sys.argv) < 2:
        print("Usage: python github_scraper.py <GITHUB_REPO_URL> [--download]")
        return False
    
    github_url = sys.argv[1]
    download_option = "--download" in sys.argv
    
    has_files, file_list = has_excel_csv_files(github_url)
    
    print(has_files)
    
    if has_files:
        print(f"{len(file_list)} fichier(s) Excel/CSV trouvé(s):")
        for file in file_list:
            print(f"- {file['path']}")
        
        # Télécharger les fichiers si demandé
        if download_option:
            print("\nTéléchargement des fichiers...")
            downloaded = download_files(file_list)
            print(f"\n{len(downloaded)}/{len(file_list)} fichiers téléchargés avec succès.")
    else:
        print("Aucun fichier Excel/CSV trouvé")
    
    return has_files

if __name__ == "__main__":
    main()