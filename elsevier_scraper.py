import urllib.request
import re
import sys
import os
import subprocess
import json

def extract_doi(url_or_doi):
    """Extrait le DOI depuis une URL ou DOI"""
    doi_pattern = r'10\.\d{4,}/[^\s]+'
    match = re.search(doi_pattern, url_or_doi)
    if match:
        return match.group(0)
    return None

def check_elsevier_data(url_or_doi):
    """Vérifie si un article Elsevier contient des données"""
    doi = extract_doi(url_or_doi)
    
    if not doi:
        print("DOI non valide")
        return
    
    print(f"Analyse de l'article Elsevier: {doi}")
    
    # Appeler elsevier_parse.php pour générer les JSONs
    try:
        subprocess.run(
            ['php', 'd:/Internship A4/elsevier_parse.php', doi],
            capture_output=True,
            text=True,
            timeout=60,
            cwd='d:/Internship A4',
            check=False
        )
    except:
        pass
    
    # Vérifier les fichiers JSON générés
    json_files = [
        'd:/Internship A4/response_article.json',
        'd:/Internship A4/response_abstract.json',
        'd:/Internship A4/response_search.json'
    ]
    
    file_count = 0
    repo_links = []
    
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
            
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Ignorer les fichiers d'erreur
            if 'service-error' in content or 'RESOURCE_NOT_FOUND' in content:
                continue
            
            # Chercher des patterns Excel/CSV
            excel_csv = re.findall(r'\.(?:xlsx?|csv)\b', content, re.IGNORECASE)
            file_count += len(set(excel_csv))
            
            # Chercher des liens COMPLETS vers GitHub/Zenodo/Mendeley (avec https://)
            github_links = re.findall(r'https://github\.com/[\w\-\.]+/[\w\-\.]+', content, re.IGNORECASE)
            zenodo_links = re.findall(r'https://zenodo\.org/records?/\d+', content, re.IGNORECASE)
            mendeley_links = re.findall(r'https://data\.mendeley\.com/datasets/[\w\-/]+', content, re.IGNORECASE)
            
            repo_links.extend(github_links + zenodo_links + mendeley_links)
        except:
            pass
    
    # Retirer les doublons
    repo_links = list(set(repo_links))
    
    print(f"\n{file_count} fichier(s) Excel/CSV trouvé(s)")
    if repo_links:
        print(f"{len(repo_links)} lien(s) vers des dépôts:")
        for link in repo_links:
            print(f"   - {link}")

def main():
    if len(sys.argv) < 2:
        print("Usage: python elsevier_scraper.py <DOI_OR_URL>")
        print("Exemples:")
        print("  python elsevier_scraper.py 10.1016/j.ecoinf.2025.103419")
        print("  python elsevier_scraper.py https://doi.org/10.1016/j.ecoinf.2025.103419")
        return
    
    check_elsevier_data(sys.argv[1])

if __name__ == "__main__":
    main()
