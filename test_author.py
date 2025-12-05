import os
import json
import urllib.parse
import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv('ELSEVIER_API_KEY')

def debug_elsevier_json(doi: str):
    url = f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}'
    headers = {'X-ELS-APIKey': API_KEY, 'Accept': 'application/json'}
    r = requests.get(url, headers=headers, timeout=20)
    print("status:", r.status_code)
    data = r.json()
    # Afficher juste la partie coredata pour voir les champs
    ftr = data.get("full-text-retrieval-response")
    if isinstance(ftr, dict):
        core = ftr.get("coredata", {})
    else:
        core = data.get("coredata", {})
    print(json.dumps(core, indent=2))

debug_elsevier_json("10.1016/j.dib.2023.109876")