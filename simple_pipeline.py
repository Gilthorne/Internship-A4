import subprocess

# Définir les étapes de la pipeline sous forme de commandes
pipeline_steps = [
    # Chaque étape est une commande shell (python ou php)
    ["python", "test.py", "10.1016/j.cub.2020.06.022"],           # Vérifie les données d'un DOI
    ["python", "zenodo_scraper.py", "10.5281/zenodo.17075237", "--download"],  # Télécharge les fichiers Zenodo
    ["python", "github_scraper.py", "gergelydinya/AviTrack"],     # Télécharge les fichiers GitHub
    ["php", "llm.php", "10.1016/j.cub.2020.06.022"],              # Analyse LLM sur un DOI
]

def run_pipeline(steps):
    for i, cmd in enumerate(steps, 1):
        print(f"\n--- Étape {i}/{len(steps)} ---")
        print("Commande:", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True)
        print("Sortie:")
        print(result.stdout[:500])  # Affiche les 500 premiers caractères
        if result.returncode != 0:
            print("Erreur:", result.stderr)
            break

if __name__ == "__main__":
    run_pipeline(pipeline_steps)
