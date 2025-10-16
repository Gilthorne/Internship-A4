import urllib.request
import re
import sys
import os
import zipfile
import tempfile

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

def check_github_data(url_or_repo):
    """Vérifie si un repo GitHub contient des fichiers Excel/CSV SANS télécharger"""
    owner, repo = extract_github_info(url_or_repo)
    
    if not owner or not repo:
        print("URL GitHub non valide")
        return
    
    print(f"Analyse du repo GitHub: {owner}/{repo}")
    
    # Essayer les branches main et master
    for branch in ['main', 'master']:
        try:
            zip_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/{branch}.zip"
            
            with urllib.request.urlopen(zip_url, timeout=10) as response:
                with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as tmp_file:
                    tmp_file.write(response.read())
                    tmp_path = tmp_file.name
            
            # Vérifier le contenu du ZIP
            file_count = 0
            with zipfile.ZipFile(tmp_path, 'r') as zip_ref:
                files = zip_ref.namelist()
                excel_csv = [f for f in files if f.lower().endswith(('.xlsx', '.xls', '.csv'))]
                file_count = len(excel_csv)
            
            # Supprimer le ZIP immédiatement
            os.unlink(tmp_path)
            
            if file_count > 0:
                print(f"\n{file_count} fichier(s) Excel/CSV trouvé(s)")
                return
                
        except Exception as e:
            continue
    
    print("\n0 fichier(s) Excel/CSV trouvé(s)")

def main():
    if len(sys.argv) < 2:
        print("Usage: python github_scraper.py <GITHUB_URL_OR_REPO>")
        print("Exemples:")
        print("  python github_scraper.py https://github.com/user/repo")
        print("  python github_scraper.py user/repo")
        return
    
    check_github_data(sys.argv[1])

if __name__ == "__main__":
    main()