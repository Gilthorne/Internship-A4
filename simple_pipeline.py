import pandas as pd
import multiprocessing as mp
from urllib.parse import urlparse
import os
import requests
from bs4 import BeautifulSoup

# --- Étape 0 : Créer le DataFrame global ---
df_articles = pd.DataFrame(columns=["nom_article", "lien"])

# --- Étape 1 : Vérifier si le lien vient d'une source scientifique ---
def filtrer_source(lien: str):
    sources = ["github", "elsevier", "mendeley", "zenodo"]
    return lien if any(src in lien.lower() for src in sources) else None

# --- Étape 2 : Vérifier si la page contient un fichier de données ---
def filtrer_donnees(lien: str):
    extensions = [".csv", ".xls", ".xlsx"]
    try:
        # Télécharge la page HTML
        response = requests.get(lien, timeout=10)
        if response.status_code != 200:
            return None

        # Parse le HTML
        soup = BeautifulSoup(response.text, "html.parser")

        # Cherche tous les liens <a href="...">
        for a in soup.find_all("a", href=True):
            href = a["href"].lower()
            if any(ext in href for ext in extensions):
                return lien  # On garde le lien si un fichier est trouvé

    except Exception:
        return None

    return None

# --- Étape 3 : Extraire le nom de l'article depuis le lien ---
def extraire_nom_article(lien: str):
    parsed = urlparse(lien)
    nom = os.path.basename(parsed.path)
    nom = os.path.splitext(nom)[0]
    if not nom:
        nom = parsed.netloc
    return nom

# --- Pipeline ---
pipeline = [filtrer_source, filtrer_donnees, extraire_nom_article]

def appliquer_pipeline(lien: str):
    # Étape 1
    lien = pipeline[0](lien)
    if lien is None:
        return None

    # Étape 2
    lien = pipeline[1](lien)
    if lien is None:
        return None

    # Étape 3
    nom = pipeline[2](lien)
    return {"nom_article": nom, "lien": lien}

# --- Multiprocessing ---
def run_pipeline(liens):
    with mp.Pool(processes=2) as pool:
        resultats = pool.map(appliquer_pipeline, liens)

    resultats = [r for r in resultats if r is not None]
    return pd.DataFrame(resultats)

# --- Exemple d'utilisation ---
if __name__ == "__main__":
    liens = [
        "https://github.com/pandas-dev/pandas",  # devrait contenir des .csv
        "https://github.com/numpy/numpy",        # peut contenir .csv dans docs
        "https://zenodo.org/record/123456",      # test zenodo
        "https://elsevier.com/open-access/ai-research",  # test elsevier
        "https://mendeley.com/library/ai-dataset",        # test mendeley
        "https://example.com/fake-link",         # sera rejeté
    ]

    df_articles = run_pipeline(liens)
    print(df_articles)
