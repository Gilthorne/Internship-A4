import os
import sys
import json
import csv
import time
import re
import subprocess
import argparse
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from urllib.parse import urlparse
import requests

# Configuration du logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(processName)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("data_filter.log"),
        logging.StreamHandler()
    ]
)

# Configuration globale
OUTPUT_DIR = "results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Patterns pour la détection directe des liens de données
DATA_REPOSITORIES = {
    'github': r'https?://(?:www\.)?github\.com/[\w\-\.]+/[\w\-\.]+\b',
    'zenodo': r'https?://(?:www\.)?zenodo\.org/records?/[\d]+\b',
    'mendeley': r'https?://(?:www\.)?data\.mendeley\.com/datasets/[\w\-/]+\b',
    }

# Extensions de fichiers à rechercher
DATA_FILES = ['.csv', '.xlsx', '.xls']

def check_doi_for_data_availability(doi, timeout=120):
    """Vérifie si un DOI contient des liens vers des données
    
    Args:
        doi (str): DOI à vérifier
        timeout (int): Timeout en secondes
        
    Returns:
        dict: Résultats de l'analyse
    """
    logger = logging.getLogger(f'Worker-{os.getpid()}')
    result = {
        'doi': doi,
        'has_data': False,
        'repositories': set(),
        'data_files': set(),
        'error': None,
        'processed_time': time.strftime('%Y-%m-%d %H:%M:%S'),
        'processing_time_seconds': 0
    }
    
    start_time = time.time()
    logger.info(f"Traitement du DOI: {doi}")
    
    try:
        # 1. Vérifier avec l'API Elsevier (test.py)
        try:
            api_result = subprocess.run(
                ['python', 'd:/Internship A4/test.py', doi], 
                capture_output=True, 
                text=True, 
                timeout=timeout,
                check=False
            )
            
            # Vérifier si des données ont été trouvées
            if "DONNÉES TROUVÉES!" in api_result.stdout:
                result['has_data'] = True
                
                # Extraire les URLs des dépôts
                for repo_type in ['GitHub', 'Zenodo', 'Mendeley Data']:
                    pattern = rf"{repo_type}: (https?://[^\s]+)"
                    matches = re.findall(pattern, api_result.stdout)
                    result['repositories'].update(matches)
                
                # Extraire les fichiers de données
                csv_excel_pattern = r"(Excel|CSV): ([^\n]+)"
                matches = re.findall(csv_excel_pattern, api_result.stdout)
                result['data_files'].update([m[1] for m in matches])
        
        except subprocess.TimeoutExpired:
            logger.warning(f"Timeout lors de l'exécution de test.py pour {doi}")
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution de test.py: {e}")
        
        # 2. Vérification directe avec les APIs (si nécessaire)
        # Cette section peut être développée pour faire des appels directs
        # aux APIs (GitHub, Zenodo, etc.) si nécessaire
        
        # Convertir les sets en listes pour le JSON
        result['repositories'] = list(result['repositories'])
        result['data_files'] = list(result['data_files'])
        
    except Exception as e:
        result['error'] = str(e)
        logger.error(f"Erreur lors du traitement de {doi}: {e}")
    finally:
        result['processing_time_seconds'] = round(time.time() - start_time, 2)
        logger.info(f"Traitement de {doi} terminé en {result['processing_time_seconds']}s")
    
    return result

def process_doi_batch(batch, output_file, worker_id):
    """Traite un lot de DOIs
    
    Args:
        batch (list): Liste de DOIs à traiter
        output_file (str): Fichier de sortie
        worker_id (int): ID du worker
        
    Returns:
        int: Nombre de DOIs avec données trouvées
    """
    logger = logging.getLogger(f'Worker-{os.getpid()}')
    logger.info(f"Worker {worker_id} démarré avec {len(batch)} DOIs")
    
    results = []
    data_found_count = 0
    
    for doi in batch:
        try:
            result = check_doi_for_data_availability(doi.strip())
            results.append(result)
            
            if result['has_data']:
                data_found_count += 1
        except Exception as e:
            logger.error(f"Erreur lors du traitement du DOI {doi}: {e}")
    
    # Enregistrer les résultats
    worker_output = os.path.join(OUTPUT_DIR, f"results_worker_{worker_id}.json")
    with open(worker_output, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)
    
    # Ajouter à la sortie principale de manière thread-safe
    if results:
        with open(output_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            for result in results:
                repositories = ','.join(result['repositories'])
                data_files = ','.join(result['data_files'])
                writer.writerow([
                    result['doi'],
                    "Oui" if result['has_data'] else "Non",
                    repositories,
                    data_files,
                    result['error'] or '',
                    result['processed_time'],
                    result['processing_time_seconds']
                ])
    
    logger.info(f"Worker {worker_id} terminé: {data_found_count}/{len(batch)} DOIs avec données")
    return data_found_count

def main():
    parser = argparse.ArgumentParser(description='Filtrage de DOIs pour recherche de données')
    parser.add_argument('input_file', help='Fichier contenant la liste des DOIs (un par ligne)')
    parser.add_argument('--workers', type=int, default=os.cpu_count(), 
                      help='Nombre de workers (défaut: nombre de CPUs)')
    parser.add_argument('--batch-size', type=int, default=10, 
                      help='Nombre de DOIs par lot (défaut: 10)')
    parser.add_argument('--output', default='data_results.csv',
                      help='Fichier de sortie CSV (défaut: data_results.csv)')
    args = parser.parse_args()
    
    # Vérifier si le fichier d'entrée existe
    if not os.path.exists(args.input_file):
        print(f"Erreur: Le fichier {args.input_file} n'existe pas.")
        return 1
    
    # Créer le fichier de sortie avec les en-têtes
    output_file = os.path.join(OUTPUT_DIR, args.output)
    with open(output_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['DOI', 'Données Disponibles', 'Dépôts', 'Fichiers', 
                        'Erreur', 'Date Traitement', 'Temps (s)'])
    
    # Lire la liste des DOIs
    with open(args.input_file, 'r', encoding='utf-8') as f:
        all_dois = [line.strip() for line in f if line.strip()]
    
    total_dois = len(all_dois)
    print(f"Démarrage du traitement de {total_dois} DOIs avec {args.workers} workers")
    
    # Découper en lots
    doi_batches = []
    for i in range(0, total_dois, args.batch_size):
        doi_batches.append(all_dois[i:i + args.batch_size])
    
    # Démarrer le pool de workers
    start_time = time.time()
    data_found_total = 0
    
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        # Soumettre les tâches
        futures = [
            executor.submit(process_doi_batch, batch, output_file, i) 
            for i, batch in enumerate(doi_batches)
        ]
        
        # Traiter les résultats au fur et à mesure
        for future in as_completed(futures):
            try:
                data_found_total += future.result()
            except Exception as e:
                logging.error(f"Erreur dans une tâche: {e}")
    
    elapsed_time = time.time() - start_time
    
    # Résumé
    print("\n" + "="*60)
    print(f"Traitement terminé en {elapsed_time:.2f} secondes")
    print(f"DOIs traités: {total_dois}")
    print(f"DOIs avec données trouvées: {data_found_total} ({data_found_total/total_dois*100:.1f}%)")
    print(f"Résultats enregistrés dans: {output_file}")
    print("="*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
