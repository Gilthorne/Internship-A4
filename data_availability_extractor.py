import json
import re
import sys

def extract_data_availability_section(original_text):
    """Extrait spécifiquement la section Data Availability du texte"""
    
    # Patterns pour identifier la section Data Availability
    patterns = [
        # Pattern principal: Data availability suivi du contenu jusqu'à la prochaine section
        r'(?:Data\s+availability|Availability\s+of\s+data|Data\s+and\s+code\s+availability)\s*(.*?)(?=\s*(?:1\s+Introduction|Declaration\s+of\s+|CRediT\s+|Funding\s+|Acknowledgement|References|Appendix|$))',
        
        # Pattern plus strict pour éviter d'inclure l'introduction
        r'(?:Data\s+availability)[^\n]*\n+(.*?)(?=\s*\n\s*1\s+Introduction)',
        
        # Pattern encore plus spécifique
        r'(This\s+work\s+is\s+partly\s+based\s+on\s+data.*?Repository[^.]*\.)\s*(?=\s*1\s+Introduction)',
    ]
    
    for pattern in patterns:
        matches = re.search(pattern, original_text, re.IGNORECASE | re.DOTALL)
        if matches:
            section_text = matches.group(1).strip()
            # Vérifier que ce n'est pas trop long (signe qu'on a capturé l'introduction)
            if len(section_text) < 2000:  # Limite raisonnable pour une section Data Availability
                return section_text
    
    return None

def extract_repository_links(data_section):
    """Extrait les liens vers les dépôts de données depuis la section"""
    repositories = []
    
    if not data_section:
        return repositories
    
    # Patterns pour différents types de dépôts
    repo_patterns = {
        'BExIS': [
            r'Biodiversity\s+Exploratories\s+Information\s+System\s+BExIS',
            r'(https?://(?:www\.)?bexis\.uni-jena\.de/[^\s"\'<>)]+)',
        ],
        'Mendeley Data': [
            r'Mendeley\s+Data\s+Repository',
            r'(https?://(?:www\.)?data\.mendeley\.com/[^\s"\'<>)]+)',
            r'(10\.17632/[\w\d./]+)',
        ]
    }
    
    for repo_name, patterns in repo_patterns.items():
        found = False
        for pattern in patterns:
            if re.search(pattern, data_section, re.IGNORECASE):
                found = True
                # Si c'est un lien direct, l'extraire
                if pattern.startswith('(https') or pattern.startswith('(10'):
                    matches = re.findall(pattern, data_section, re.IGNORECASE)
                    for match in matches:
                        url = match.strip().rstrip('.,;:)')
                        
                        # Convertir DOI en URL si nécessaire
                        if url.startswith('10.17632/'):
                            url = f"https://doi.org/{url}"
                        
                        repositories.append({
                            'type': repo_name,
                            'url': url
                        })
                break
        
        # Si mention trouvée mais pas d'URL spécifique, ajouter URL générique
        if found and not any(repo['type'] == repo_name for repo in repositories):
            default_urls = {
                'BExIS': 'https://www.bexis.uni-jena.de',
                'Mendeley Data': 'https://data.mendeley.com'
            }
            if repo_name in default_urls:
                repositories.append({
                    'type': repo_name,
                    'url': default_urls[repo_name]
                })
    
    return repositories

def extract_mentioned_files(data_section):
    """Extrait les fichiers mentionnés dans la section Data Availability"""
    files = []
    
    if not data_section:
        return files
    
    # Patterns pour identifier les mentions de données
    data_mentions = [
        r'spectral\s+and\s+laboratory\s+data',
        r'datasets?\s+from\s+the\s+German\s+sites',
        r'full\s+spectral\s+and\s+laboratory\s+data',
    ]
    
    for pattern in data_mentions:
        matches = re.findall(pattern, data_section, re.IGNORECASE)
        for match in matches:
            files.append({
                'type': 'Dataset',
                'filename': match.strip()
            })
    
    return files

def main():
    # Lire le fichier JSON fourni
    json_file = 'd:\\Internship A4\\response_article.json'
    
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"Fichier {json_file} non trouvé")
        return
    except json.JSONDecodeError:
        print(f"Erreur lors du parsing du JSON")
        return
    
    # Extraire le texte original
    if 'full-text-retrieval-response' not in data:
        print("Clé 'full-text-retrieval-response' non trouvée")
        return
    
    original_text = data['full-text-retrieval-response'].get('originalText', '')
    
    if not original_text:
        print("Texte original non disponible")
        return
    
    # Extraire la section Data Availability
    data_section = extract_data_availability_section(original_text)
    
    if not data_section:
        result = {
            'doi': '10.1016/j.ecoinf.2025.103426',
            'data_availability_found': False,
            'message': 'Section Data Availability non trouvée'
        }
    else:
        # Analyser la section pour extraire les informations
        repository_links = extract_repository_links(data_section)
        files_mentioned = extract_mentioned_files(data_section)
        
        # Préparer le résultat final
        result = {
            'doi': '10.1016/j.ecoinf.2025.103426',
            'data_availability_section': {
                'text': data_section,
                'length_chars': len(data_section),
                'word_count': len(data_section.split())
            },
            'extracted_elements': {
                'repository_links': repository_links,
                'files_mentioned': files_mentioned
            },
            'summary': {
                'repositories_found': len(repository_links),
                'files_found': len(files_mentioned),
                'repository_types': list(set([repo['type'] for repo in repository_links]))
            }
        }
    
    # Afficher le JSON formaté de manière plus lisible
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == '__main__':
    main()
