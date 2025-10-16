import pandas as pd
import multiprocessing as mp
from urllib.parse import urlparse
import subprocess
import re

# --- Étape 1: Filtrer par source ---
def filtrer_source(lien: str):
    """Garde seulement les liens des sources scientifiques"""
    sources = ["github.com", "elsevier.com", "mendeley.com", "zenodo.org", "doi.org"]
    return lien if any(src in lien.lower() for src in sources) else None

# --- Étape 2: Vérifier si le lien contient des données ---
def verifier_donnees(lien: str):
    """Vérifie si le lien contient des fichiers Excel/CSV"""
    lien_lower = lien.lower()
    
    # GitHub
    if "github.com" in lien_lower:
        return verifier_scraper(lien, 'github_scraper.py')
    
    # Zenodo
    elif "zenodo.org" in lien_lower:
        return verifier_scraper(lien, 'zenodo_scraper.py')
    
    # Elsevier
    elif "elsevier.com" in lien_lower or "doi.org" in lien_lower:
        return verifier_elsevier(lien)
    
    # Mendeley
    elif "mendeley.com" in lien_lower:
        return verifier_scraper(lien, 'mendeley_scraper.py')
    
    return None

def verifier_scraper(lien: str, scraper_name: str):
    """Vérifie un lien avec un scraper donné"""
    try:
        result = subprocess.run(
            ['python', f'd:/Internship A4/{scraper_name}', lien],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # Chercher si des fichiers ont été trouvés
        match = re.search(r'(\d+) fichier\(s\) Excel/CSV', result.stdout)
        if match and int(match.group(1)) > 0:
            return lien
            
    except:
        pass
    
    return None

def verifier_elsevier(lien: str):
    """Vérifie un article Elsevier et extrait les liens vers dépôts"""
    try:
        result = subprocess.run(
            ['python', 'd:/Internship A4/elsevier_scraper.py', lien],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Chercher des fichiers Excel/CSV
        file_match = re.search(r'(\d+) fichier\(s\) Excel/CSV trouvé\(s\)', result.stdout)
        if file_match and int(file_match.group(1)) > 0:
            return lien
        
        # Chercher des liens vers dépôts externes
        if "lien(s) vers des dépôts:" in result.stdout:
            # Extraire les liens
            github_links = re.findall(r'https://github\.com/[\w\-\.]+/[\w\-\.]+', result.stdout)
            zenodo_links = re.findall(r'https://zenodo\.org/records?/\d+', result.stdout)
            mendeley_links = re.findall(r'https://data\.mendeley\.com/datasets/[\w\-/]+', result.stdout)
            
            all_links = github_links + zenodo_links + mendeley_links
            
            # Vérifier chaque lien trouvé avec le scraper approprié
            for repo_link in all_links:
                if 'github.com' in repo_link:
                    if verifier_scraper(repo_link, 'github_scraper.py'):
                        return lien
                elif 'zenodo.org' in repo_link:
                    if verifier_scraper(repo_link, 'zenodo_scraper.py'):
                        return lien
                elif 'mendeley.com' in repo_link:
                    if verifier_scraper(repo_link, 'mendeley_scraper.py'):
                        return lien
        
    except Exception as e:
        print(f"Erreur lors de la vérification Elsevier: {e}")
    
    return None

# --- Étape 3: Extraire le nom de l'article ---
def extraire_nom(lien: str):
    """Extrait un nom simple depuis le lien"""
    parsed = urlparse(lien)
    
    # GitHub: user/repo
    if "github.com" in lien:
        parts = parsed.path.strip('/').split('/')
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    
    # Zenodo: record ID
    elif "zenodo.org" in lien:
        match = re.search(r'/records?/(\d+)', lien)
        if match:
            return f"Zenodo-{match.group(1)}"
    
    # Elsevier: DOI
    elif "elsevier.com" in lien or "doi.org" in lien:
        doi_match = re.search(r'10\.\d{4,}/[^\s]+', lien)
        if doi_match:
            return doi_match.group(0)
    
    # Mendeley
    elif "mendeley.com" in lien:
        match = re.search(r'datasets/([^/\s]+)', lien)
        if match:
            return f"Mendeley-{match.group(1)}"
    
    # Par défaut
    return parsed.path.strip('/').split('/')[-1] or parsed.netloc

# --- Pipeline complète ---
def traiter_lien(lien: str):
    """Applique toutes les étapes de la pipeline"""
    # Étape 1: Filtrer source
    lien = filtrer_source(lien)
    if not lien:
        return None
    
    # Étape 2: Vérifier données
    lien = verifier_donnees(lien)
    if not lien:
        return None
    
    # Étape 3: Extraire nom
    nom = extraire_nom(lien)
    
    return {"nom_article": nom, "lien": lien}

# --- Exécution parallèle ---
def run_pipeline(liens, workers=2):
    """Traite une liste de liens en parallèle"""
    print(f"Traitement de {len(liens)} liens avec {workers} workers...")
    
    with mp.Pool(processes=workers) as pool:
        resultats = pool.map(traiter_lien, liens)
    
    # Filtrer les None
    resultats = [r for r in resultats if r is not None]
    
    print(f"\nRésultats: {len(resultats)}/{len(liens)} liens validés")
    
    return pd.DataFrame(resultats)

# --- Exemple d'utilisation ---
if __name__ == "__main__":
    liens = [
        "https://github.com/gergelydinya/AviTrack",
        "https://zenodo.org/record/17075237",
        "https://doi.org/10.1016/j.ecoinf.2025.103419",
        "https://example.com/fake-link",
        "https://github.com/numpy/numpy",
    ]
    
    df = run_pipeline(liens, workers=5)
    print("\n" + "="*60)
    print("Base de données des articles avec données:")
    print("="*60)
    print(df)
    
    # Sauvegarder dans un CSV
    df.to_csv("articles_avec_donnees.csv", index=False)
    print("\nSauvegardé dans: articles_avec_donnees.csv")
