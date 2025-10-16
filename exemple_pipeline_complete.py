from pipeline import Pipeline
from simple_filter import filter_dois, save_results
import json

def etape1_chargement(input_file):
    """Étape 1: Charger la liste des DOIs"""
    print(f"Chargement du fichier: {input_file}")
    with open(input_file, 'r') as f:
        dois = [line.strip() for line in f if line.strip()]
    print(f"  {len(dois)} DOIs chargés")
    return dois

def etape2_filtrage(dois):
    """Étape 2: Filtrer les DOIs avec données"""
    results = filter_dois(dois, workers=4)
    return results

def etape3_sauvegarde(results):
    """Étape 3: Sauvegarder les résultats"""
    save_results(results, 'pipeline_results.json')
    
    # Créer aussi une liste simple des DOIs avec données
    with open('dois_with_data.txt', 'w') as f:
        for item in results['with_data']:
            f.write(f"{item['doi']}\n")
            for repo in item['repos']:
                f.write(f"  {repo}\n")
    
    print(f"Liste des DOIs avec données: dois_with_data.txt")
    return results

# Exécution
if __name__ == "__main__":
    pipeline = Pipeline("Filtrage de données scientifiques")
    
    pipeline.add_step("Chargement des DOIs", etape1_chargement)
    pipeline.add_step("Filtrage des données", etape2_filtrage)
    pipeline.add_step("Sauvegarde des résultats", etape3_sauvegarde)
    
    # Lancer la pipeline
    final_results = pipeline.run("doi_list.txt")
    
    # Afficher le résumé
    pipeline.summary()
    
    # Statistiques finales
    print(f"\nStatistiques finales:")
    print(f"  Total DOIs: {final_results['total']}")
    print(f"  Avec données: {len(final_results['with_data'])} ({len(final_results['with_data'])/final_results['total']*100:.1f}%)")
