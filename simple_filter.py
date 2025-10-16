import os
import re
import json
import subprocess
from multiprocessing import Pool, cpu_count

# Patterns pour détecter les dépôts de données
PATTERNS = {
    'github': r'github\.com/[\w\-\.]+/[\w\-\.]+',
    'zenodo': r'zenodo\.org/record[s]?/\d+',
    'mendeley': r'data\.mendeley\.com/datasets/[\w\-/]+',
}

def check_doi(doi):
    """Vérifie un DOI via test.py"""
    try:
        result = subprocess.run(
            ['python', 'test.py', doi],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        # Chercher les patterns dans la sortie
        has_data = False
        found_repos = []
        
        for repo_type, pattern in PATTERNS.items():
            matches = re.findall(pattern, result.stdout)
            if matches:
                has_data = True
                found_repos.extend([f"{repo_type}: {m}" for m in set(matches)])
        
        return {
            'doi': doi,
            'has_data': has_data,
            'repos': found_repos
        }
        
    except Exception as e:
        return {
            'doi': doi,
            'has_data': False,
            'repos': [],
            'error': str(e)
        }

def filter_dois(doi_list, workers=None):
    """Filtre une liste de DOIs en parallèle"""
    if workers is None:
        workers = min(cpu_count(), 8)
    
    print(f"Filtrage de {len(doi_list)} DOIs avec {workers} workers...")
    
    with Pool(workers) as pool:
        results = pool.map(check_doi, doi_list)
    
    # Séparer les résultats
    with_data = [r for r in results if r['has_data']]
    without_data = [r for r in results if not r['has_data']]
    
    print(f"\nRésultats:")
    print(f"  Avec données: {len(with_data)}")
    print(f"  Sans données: {len(without_data)}")
    
    return {
        'total': len(doi_list),
        'with_data': with_data,
        'without_data': without_data
    }

def save_results(results, output_file):
    """Sauvegarde les résultats dans un fichier JSON"""
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"\nRésultats sauvegardés: {output_file}")

# Utilisation autonome
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python simple_filter.py <fichier_dois.txt>")
        sys.exit(1)
    
    # Lire les DOIs
    with open(sys.argv[1], 'r') as f:
        dois = [line.strip() for line in f if line.strip()]
    
    # Filtrer
    results = filter_dois(dois)
    
    # Sauvegarder
    save_results(results, 'filtered_results.json')
