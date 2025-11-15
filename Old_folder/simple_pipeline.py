import pandas as pd
import multiprocessing as mp
import os
import re
import subprocess
from urllib.parse import urlparse
import time

def process_link(link):
    """Traite un seul lien à travers toutes les étapes de la pipeline"""
    # Initialiser les résultats
    result = {
        "lien": link,
        "nom_article": extract_name(link),
        "source_valide": False,
        "contient_donnees": False,
        "convenable": False
    }
    
    # Étape 1: Vérifier la source
    result["source_valide"] = verifier_source(link)
    if not result["source_valide"]:
        return result
    
    # Étape 2: Vérifier présence de données
    result["contient_donnees"] = verifier_donnees(link)
    if not result["contient_donnees"]:
        return result
    
    # Étape 3: Si tout est bon, marquer comme convenable
    result["convenable"] = True
    
    return result

def verifier_source(link):
    """Vérifie si le lien provient d'une source valide (GitHub, Zenodo, Elsevier)"""
    domain = urlparse(link).netloc.lower()
    valid_sources = ['github.com', 'zenodo.org', 'elsevier.com', 'doi.org', 'sciencedirect.com']
    return any(source in domain for source in valid_sources)

def verifier_donnees(link):
    """Vérifie si le lien contient des données Excel/CSV en appelant les scrapers appropriés"""
    domain = urlparse(link).netloc.lower()
    
    # Sélectionner le scraper approprié en fonction du domaine
    if 'github.com' in domain:
        return appeler_scraper('github_scraper.py', link)
    elif 'zenodo.org' in domain:
        return appeler_scraper('zenodo_scraper.py', link)
    elif any(d in domain for d in ['elsevier.com', 'doi.org', 'sciencedirect.com']):
        return appeler_scraper('elsevier_scraper.py', link)
    
    return False

def appeler_scraper(scraper, link):
    """Appelle un scraper et vérifie s'il renvoie True ou False"""
    try:
        # Utiliser le chemin relatif au répertoire courant
        scraper_path = os.path.join(os.path.dirname(__file__), scraper)
        if not os.path.exists(scraper_path):
            scraper_path = scraper  # Utiliser juste le nom si le chemin n'existe pas
        
        # Exécuter le scraper
        result = subprocess.run(
            ['python', scraper_path, link],
            capture_output=True,
            text=True,
            timeout=120  # Timeout après 120 secondes
        )
        
        # Vérifier si la première ligne du résultat est "True"
        first_line = result.stdout.strip().split('\n')[0].lower()
        return first_line == "true"
    except Exception as e:
        print(f"Erreur lors de l'appel du scraper {scraper} pour {link}: {e}")
        return False

def extract_name(link):
    """Extrait un nom d'article simple à partir du lien"""
    parsed = urlparse(link)
    path = parsed.path
    
    # GitHub: user/repo
    if 'github.com' in parsed.netloc:
        parts = path.strip('/').split('/')
        if len(parts) >= 2:
            return f"{parts[0]}/{parts[1]}"
    
    # Zenodo: record ID
    elif 'zenodo.org' in parsed.netloc:
        match = re.search(r'/records?/(\d+)', path)
        if match:
            return f"Zenodo-{match.group(1)}"
    
    # Elsevier/DOI: dernier segment du DOI
    elif 'doi.org' in parsed.netloc or 'elsevier.com' in parsed.netloc:
        doi_match = re.search(r'10\.\d{4,}/[^\s/]+', link)
        if doi_match:
            return doi_match.group(0)
    
    # Par défaut, utiliser le dernier segment du chemin ou le domaine
    parts = path.strip('/').split('/')
    return parts[-1] if parts else parsed.netloc

def run_pipeline(links, output_file='resultats.xlsx', max_workers=None):
    """Exécute la pipeline en utilisant du multiprocessing"""
    print(f"Traitement de {len(links)} liens...")
    
    # Utiliser le nombre de cœurs disponibles par défaut
    if max_workers is None:
        max_workers = mp.cpu_count()
    
    print(f"Utilisation de {max_workers} processeurs")
    
    # Utiliser un pool pour le multiprocessing
    with mp.Pool(processes=max_workers) as pool:
        results = pool.map(process_link, links)
    
    # Créer un DataFrame à partir des résultats
    df = pd.DataFrame(results)
    
    # Sauvegarder dans un fichier Excel
    df.to_excel(output_file, index=False)
    print(f"Résultats sauvegardés dans {output_file}")
    
    # Afficher un résumé
    n_total = len(df)
    n_valid_source = df['source_valide'].sum()
    n_has_data = df['contient_donnees'].sum()
    n_suitable = df['convenable'].sum()
    
    print(f"\nRésumé:")
    print(f"- Liens totaux: {n_total}")
    print(f"- Sources valides: {n_valid_source}/{n_total}")
    print(f"- Contenant des données: {n_has_data}/{n_total}")
    print(f"- Convenables: {n_suitable}/{n_total}")
    
    return df

if __name__ == "__main__":
    import sys
    
    # Lire les liens à partir d'un fichier s'il est fourni
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
        with open(input_file, 'r') as f:
            links = [line.strip() for line in f if line.strip()]
    else:
        # Liste d'exemple de liens à tester
        links = [
            "https://github.com/xyluo25/exceltosqlserver",
            "https://zenodo.org/records/17075237",
            "   ",
            "https://example.com/invalid-source",
        ]
    
    # Nombre de processeurs à utiliser (si spécifié)
    max_workers = int(sys.argv[2]) if len(sys.argv) > 2 else None
    
    # Exécuter la pipeline
    df = run_pipeline(links, max_workers=max_workers)
