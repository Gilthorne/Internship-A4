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
                    # Déterminer la branche principale (main ou master)
                    branch = "main" if response.url.endswith("main?recursive=1") else "master"
                    excel_csv_files.append({
                        'path': path,
                        'filename': os.path.basename(path),
                        'url': f"https://raw.githubusercontent.com/{username}/{repo}/{branch}/{path}"
                    })
        
        return bool(excel_csv_files), excel_csv_files
    
    except Exception as e:
        print(f"Erreur: {str(e)}")
        return False, []

def download_files(file_list, repo_name):
    """Télécharge les fichiers Excel/CSV trouvés dans un dossier nommé d'après le dépôt"""
    # Créer un dossier nommé d'après le dépôt
    directory = f"downloads/{repo_name}"
    os.makedirs(directory, exist_ok=True)
    
    downloaded_files = []
    
    for file_info in file_list:
        try:
            url = file_info['url']
            filename = file_info['filename']
            
            # Gérer les doublons en ajoutant un suffixe numérique si nécessaire
            filepath = os.path.join(directory, filename)
            base, ext = os.path.splitext(filepath)
            counter = 1
            while os.path.exists(filepath):
                filepath = f"{base}_{counter}{ext}"
                counter += 1
            
            # Télécharger le fichier
            response = requests.get(url)
            if response.status_code != 200:
                continue
            
            with open(filepath, 'wb') as f:
                f.write(response.content)
            
            downloaded_files.append(filepath)
            
        except Exception:
            continue
    
    return downloaded_files

def main():
    if len(sys.argv) < 2:
        print("Usage: python github_scraper.py <GITHUB_REPO_URL>")
        return False
    
    github_url = sys.argv[1]
    
    # Extraire les informations du dépôt
    username, repo = extract_repo_info(github_url)
    if not username or not repo:
        print(False)
        return False
    
    repo_name = f"{username}_{repo}"
    
    # Vérifier la présence de fichiers Excel/CSV
    has_files, file_list = has_excel_csv_files(github_url)
    
    # Afficher le résultat booléen
    print(has_files)
    
    if has_files:
        # Télécharger automatiquement les fichiers dans un dossier unique
        downloaded = download_files(file_list, repo_name)
        print(f"{len(downloaded)}")
    else:
        print("0")
    
    return has_files

if __name__ == "__main__":
    main()