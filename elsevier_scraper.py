import sys
import re
import json
import requests
import urllib.parse
import os

# Configuration
API_KEY = '5e0c4b89c3dc998fda16c52f50e7f4a2'

def extract_doi_from_url(url):
    """Extrait un DOI d'une URL"""
    doi_pattern = r'10\.\d{4,}/[^\s?&#]+'
    match = re.search(doi_pattern, url)
    return match.group(0) if match else None

def get_elsevier_data(doi):
    """Récupère les données d'un article Elsevier via API"""
    # Construction de l'URL de l'API
    api_url = f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}?view=FULL'
    
    # Entêtes de la requête
    headers = {'X-ELS-APIKey': API_KEY, 'Accept': 'application/json'}
    
    # Effectuer la requête
    response = requests.get(api_url, headers=headers)
    
    if response.status_code != 200:
        print(f"Erreur lors de l'accès à l'API: {response.status_code}")
        return None
    
    return response.json()

def find_excel_csv_files(data):
    """Trouve les fichiers Excel/CSV dans les données de l'API"""
    excel_csv_files = []
    
    # Vérifier si les données API sont disponibles
    if not data or 'full-text-retrieval-response' not in data:
        return excel_csv_files
    
    # Examiner les objets associés à l'article
    full_text = data['full-text-retrieval-response']
    if 'objects' in full_text and 'object' in full_text['objects']:
        objects = full_text['objects']['object']
        if not isinstance(objects, list):
            objects = [objects]
        
        for obj in objects:
            file_url = obj.get('$')
            if not file_url:
                continue
            
            ref = obj.get('@ref', '')
            mimetype = obj.get('@mimetype', '').lower()
            
            # Vérifier si c'est un fichier Excel/CSV
            is_excel = any(x in file_url.lower() or x in mimetype.lower() for x in ['.xlsx', '.xls', 'excel', 'spreadsheet'])
            is_csv = any(x in file_url.lower() or x in mimetype.lower() for x in ['.csv', 'csv'])
            
            if is_excel or is_csv:
                file_type = 'Excel' if is_excel else 'CSV'
                excel_csv_files.append({
                    'type': file_type,
                    'ref': ref,
                    'url': file_url
                })
    
    return excel_csv_files

def extract_data_availability_section(original_text):
    """Extrait spécifiquement la section Data Availability du texte"""
    # Liste des patterns pour trouver la section Data Availability
    data_section_patterns = [
        # Format commun avec titre et section qui suit
        r'(?:Data availability|Availability of data|Data and code availability)(?:\s*|:\s*)(.*?)(?=(?:\n\s*\n\s*[A-Z][A-Za-z\s]+(?::|\.)\s*|\Z))',
        # Format simple avec titre Data
        r'(?:^|\n)(?:Data)(?:\s+|:\s*)(.*?)(?=(?:\n\s*\n\s*[A-Z][A-Za-z\s]+(?::|\.)\s*|\Z))',
        # Format où Data availability est dans une section juste avant les references
        r'(?:Data\s*Availability|Availability\s*of\s*Data)[^\n]*\n+(.*?)(?=\s*\n\s*References\s*\n)',
        # Format générique qui cherche des paragraphes mentionnant les données
        r'(?:The data used in this|All data are available|Data are available)([^.]+(?:\.[^.]+){0,10}?)(?=\s*\n\s*\n|\Z)',
    ]
    
    # Recherche avec tous les patterns
    for pattern in data_section_patterns:
        matches = re.search(pattern, original_text, re.IGNORECASE | re.DOTALL)
        if matches:
            return matches.group(1).strip()
    
    return None

def find_correct_bexis_url(text, data_availability_section=None):
    """Trouve l'URL BExIS correcte en donnant la priorité aux formats spécifiques"""
    # Rechercher d'abord dans la section Data Availability si disponible
    if data_availability_section:
        # Patterns BExIS spécifiques pour la section Data Availability
        data_section_patterns = [
            # Liens explicites
            r'(https?://(?:www\.)?bexis\.uni-jena\.de/[^\s"\'<>)]+)',
            # Descriptions avec URLs
            r'(?:BExIS|Biodiversity Exploratories Information System)[^\n.]*?(https?://[^\s"\'<>)]+)',
            # Autres formats de BExIS
            r'(?:data (?:is|are) available (?:at|on|via)[^\n.]*?)(?:BExIS|Biodiversity Exploratories)[^\n.]*?(https?://[^\s"\'<>)]+)',
        ]
        
        for pattern in data_section_patterns:
            matches = re.findall(pattern, data_availability_section, re.IGNORECASE)
            if matches:
                # Nettoyer l'URL
                bexis_url = matches[0].strip()
                if isinstance(bexis_url, tuple):  # Si le pattern a des groupes multiples
                    bexis_url = bexis_url[-1].strip()
                return bexis_url.rstrip('.,:;')
    
    # Si rien n'est trouvé dans la section Data Availability, chercher dans le texte complet
    # Liste des patterns BExIS par ordre de priorité
    bexis_patterns = [
        # Format spécifique avec dataset ID
        r'https?://(?:www\.)?bexis\.uni-jena\.de/(?:ddm|data/ShowData)\.aspx\?DatasetId=\d+',
        # Format avec path de données
        r'https?://(?:www\.)?bexis\.uni-jena\.de/(?:PublicData|data/PublicData|ddm/Data)/[^\s\)"\'<>]+',
        # Format avec chemin climatique spécifique
        r'https?://(?:www\.)?bexis\.uni-jena\.de/[^\s\)"\'<>]*/(?:Climate|ClimateData)[^\s\)"\'<>]*',
        # Formats généraux (dernier recours)
        r'https?://(?:www\.)?bexis\.uni-jena\.de/[^\s\)"\'<>]+',
    ]
    
    # Chercher chaque pattern
    for pattern in bexis_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        if matches:
            # Nettoyer l'URL
            bexis_url = matches[0].strip()
            return bexis_url.rstrip('.,:;')
    
    # URL par défaut si aucun match spécifique n'est trouvé
    return "https://www.bexis.uni-jena.de"

def extract_mendeley_data_link(text, data_availability_section=None):
    """Extrait le lien Mendeley Data correctement formaté"""
    # Chercher d'abord dans la section Data Availability si disponible
    if data_availability_section:
        # Chercher un DOI Mendeley
        doi_pattern = r'10\.17632/[\w\d./]+'
        doi_match = re.search(doi_pattern, data_availability_section)
        
        if doi_match:
            doi = doi_match.group(0)
            return f"https://doi.org/{doi}"
        
        # Chercher une URL Mendeley directe
        mendeley_pattern = r'https?://data\.mendeley\.com/datasets/[\w\d./]+'
        mendeley_match = re.search(mendeley_pattern, data_availability_section)
        
        if mendeley_match:
            return mendeley_match.group(0)
    
    # Si rien n'est trouvé dans la section Data Availability, chercher dans le texte complet
    # Chercher un DOI Mendeley
    doi_pattern = r'10\.17632/[\w\d./]+'
    doi_match = re.search(doi_pattern, text)
    
    if doi_match:
        doi = doi_match.group(0)
        return f"https://doi.org/{doi}"
    
    # Chercher une URL Mendeley directe
    mendeley_pattern = r'https?://data\.mendeley\.com/datasets/[\w\d./]+'
    mendeley_match = re.search(mendeley_pattern, text)
    
    if mendeley_match:
        return mendeley_match.group(0)
    
    return None

def extract_data_repositories(data):
    """Extrait les liens vers les dépôts de données (BExIS, Mendeley Data, etc.)"""
    repo_links = []
    
    # Vérifier si les données API sont disponibles
    if not data or 'full-text-retrieval-response' not in data:
        return repo_links
    
    # Obtenir le texte complet
    full_text = data['full-text-retrieval-response']
    original_text = full_text.get('originalText', '')
    
    if not original_text:
        return repo_links
    
    # 1. D'abord, extraire la section Data Availability
    data_section = extract_data_availability_section(original_text)
    
    # Debug: afficher la section data availability
    print("\n--- SECTION DATA AVAILABILITY ---")
    print(data_section or "Section non trouvée")
    print("--- FIN SECTION ---\n")
    
    # 2. Chercher BExIS - donner la priorité aux formats spécifiques
    bexis_url = find_correct_bexis_url(original_text, data_section)
    if bexis_url:
        repo_links.append({
            "type": "BExIS",
            "url": bexis_url,
            "context": "Data Repository"
        })
    
    # 3. Chercher Mendeley Data
    mendeley_url = extract_mendeley_data_link(original_text, data_section)
    if mendeley_url:
        repo_links.append({
            "type": "Mendeley Data",
            "url": mendeley_url,
            "context": "Data Repository"
        })
    
    # 4. Chercher Zenodo
    zenodo_pattern = r'https?://(?:www\.)?zenodo\.org/records?/(\d+)'
    zenodo_doi_pattern = r'10\.5281/zenodo\.(\d+)'
    
    # Chercher d'abord dans la section Data Availability
    if data_section:
        zenodo_match = re.search(zenodo_pattern, data_section)
        if zenodo_match:
            repo_links.append({
                "type": "Zenodo",
                "url": f"https://zenodo.org/record/{zenodo_match.group(1)}",
                "context": "Data Repository"
            })
        else:
            zenodo_doi_match = re.search(zenodo_doi_pattern, data_section)
            if zenodo_doi_match:
                repo_links.append({
                    "type": "Zenodo",
                    "url": f"https://doi.org/10.5281/zenodo.{zenodo_doi_match.group(1)}",
                    "context": "Data Repository"
                })
    
    # Si rien n'est trouvé dans la section Data, chercher dans le texte complet
    if not any(link["type"] == "Zenodo" for link in repo_links):
        zenodo_match = re.search(zenodo_pattern, original_text)
        if zenodo_match:
            repo_links.append({
                "type": "Zenodo",
                "url": f"https://zenodo.org/record/{zenodo_match.group(1)}",
                "context": "Data Repository"
            })
        else:
            zenodo_doi_match = re.search(zenodo_doi_pattern, original_text)
            if zenodo_doi_match:
                repo_links.append({
                    "type": "Zenodo",
                    "url": f"https://doi.org/10.5281/zenodo.{zenodo_doi_match.group(1)}",
                    "context": "Data Repository"
                })
    
    return repo_links

def main(url_or_doi):
    """Fonction principale pour analyser un article Elsevier"""
    # Extraire le DOI si une URL est fournie
    doi = extract_doi_from_url(url_or_doi) if 'http' in url_or_doi else url_or_doi
    
    if not doi:
        print("Aucun DOI valide n'a été trouvé")
        return False
    
    # Récupérer les données de l'API
    data = get_elsevier_data(doi)
    
    if not data:
        print("Impossible de récupérer les données de l'article")
        return False
    
    # Rechercher les fichiers Excel/CSV
    excel_csv_files = find_excel_csv_files(data)
    
    # Rechercher les liens vers des dépôts de données
    repo_links = extract_data_repositories(data)
    
    # Vérifier si des fichiers ou dépôts ont été trouvés
    has_data = len(excel_csv_files) > 0 or len(repo_links) > 0
    
    # Imprimer le résultat au format JSON
    result = {
        "doi": doi,
        "excel_csv_files": excel_csv_files,
        "repository_links": repo_links,
        "has_data": has_data
    }
    
    # Afficher le résultat booléen (pour le pipeline)
    print(has_data)
    
    # Sauvegarder les résultats dans un fichier JSON
    output_file = f"elsevier_result_{doi.replace('/', '_')}.json"
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2)
    
    print(f"Résultats sauvegardés dans {output_file}")
    
    return has_data

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python elsevier_scraper.py <URL_OR_DOI>")
        sys.exit(1)
    
    url_or_doi = sys.argv[1]
    result = main(url_or_doi)
    sys.exit(0 if result else 1)
