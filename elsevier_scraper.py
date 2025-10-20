import sys
import os
import re
import requests
import urllib.parse
import urllib.request
from urllib.parse import urlparse
import subprocess

API_KEY = '5e0c4b89c3dc998fda16c52f50e7f4a2'

def extract_doi(url_or_doi):
    """Extrait le DOI depuis une URL ou DOI"""
    # Si l'URL est de ScienceDirect, extraire le PII et le convertir en DOI
    if 'sciencedirect.com' in url_or_doi:
        pii_match = re.search(r'pii/([^/&#?]+)', url_or_doi)
        if pii_match:
            pii = pii_match.group(1)
            try:
                pii_url = f'https://api.elsevier.com/content/article/pii/{pii}'
                headers = {'X-ELS-APIKey': API_KEY, 'Accept': 'application/json'}
                response = requests.get(pii_url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    if 'full-text-retrieval-response' in data:
                        doi = data['full-text-retrieval-response'].get('coredata', {}).get('prism:doi')
                        if doi:
                            return doi
            except:
                pass
    
    # Pattern standard pour DOI
    doi_pattern = r'10\.\d{4,}/[^\s?&#]+'
    match = re.search(doi_pattern, url_or_doi)
    return match.group(0) if match else None

def get_data_and_extract_files(doi):
    """Récupère les données et extrait les fichiers"""
    endpoints = {
        'article': f'https://api.elsevier.com/content/article/doi/{urllib.parse.quote(doi)}',
        'abstract': f'https://api.elsevier.com/content/abstract/doi/{urllib.parse.quote(doi)}',
        'search': f'https://api.elsevier.com/content/search/scopus?query=DOI({urllib.parse.quote(doi)})'
    }
    
    headers = {'X-ELS-APIKey': API_KEY, 'Accept': 'application/json'}
    file_urls = []
    external_repos = {'github': [], 'zenodo': [], 'mendeley': []}
    
    # Interroger chaque endpoint et extraire les URLs de fichiers
    for name, url in endpoints.items():
        try:
            response = requests.get(url, headers=headers)
            if response.status_code != 200:
                continue
                
            with open(f"response_{name}.json", "w", encoding="utf-8") as f:
                f.write(response.text)
            
            content = response.text
            download_links = re.findall(r'https?://[^\s"\'<>]+\.(?:xlsx?|csv)\b', content, re.IGNORECASE)
            file_urls.extend(download_links)
            
            # Chercher les liens vers les dépôts externes
            github_links = re.findall(r'https?://(?:www\.)?github\.com/[\w\-\.]+/[\w\-\.]+\b', content, re.IGNORECASE)
            zenodo_links = re.findall(r'https?://(?:www\.)?zenodo\.org/records?/[\d]+\b', content, re.IGNORECASE)
            mendeley_links = re.findall(r'https?://(?:www\.)?data\.mendeley\.com/datasets/[\w\d]+(/\d+)?\b', content, re.IGNORECASE)
            
            # Chercher les DOIs de Mendeley (format 10.17632/...)
            mendeley_dois = re.findall(r'10\.17632/[\w\d]+(/\d+)?', content)
            for doi in mendeley_dois:
                mendeley_links.append(f"https://doi.org/{doi}")
            
            # Nettoyer et ajouter les liens externes
            for link_list, repo_type in [(github_links, 'github'), (zenodo_links, 'zenodo'), (mendeley_links, 'mendeley')]:
                for link in link_list:
                    link = re.sub(r'[.,;:]$', '', link)
                    if link not in external_repos[repo_type]:
                        external_repos[repo_type].append(link)
            
            # Chercher les mentions de référence à des données externes dans le texte
            data_refs = re.findall(r'([^.]+\([^)]+, \d{4}\)[^.]*(?:data|repository|dataset|figshare|dryad|mendeley)[^.]*\.)', content, re.IGNORECASE)
            for ref in data_refs:
                doi_match = re.search(r'10\.\d{4,}/[a-zA-Z0-9./-]+', ref)
                if doi_match:
                    doi = doi_match.group(0)
                    if '10.17632/' in doi:  # Mendeley Data DOI
                        mendeley_url = f"https://doi.org/{doi}"
                        if mendeley_url not in external_repos['mendeley']:
                            external_repos['mendeley'].append(mendeley_url)
            
            # Extraire les objets si disponibles (uniquement pour article)
            if name == 'article' and 'full-text-retrieval-response' in content:
                try:
                    data = response.json()
                    if 'full-text-retrieval-response' in data:
                        full_text = data['full-text-retrieval-response']
                        if 'objects' in full_text and 'object' in full_text['objects']:
                            objects = full_text['objects']['object']
                            if not isinstance(objects, list):
                                objects = [objects]
                            
                            for obj in objects:
                                file_url = obj.get('$')
                                if file_url and any(ext in file_url.lower() for ext in ['.xlsx', '.xls', '.csv']):
                                    file_urls.append(file_url)
                except:
                    pass
        except:
            continue
    
    # Obtenir le PII à partir du DOI
    pii = None
    try:
        response = requests.get(endpoints['article'], headers=headers)
        if response.status_code == 200:
            data = response.json()
            if 'full-text-retrieval-response' in data:
                pii = data['full-text-retrieval-response'].get('coredata', {}).get('pii')
    except:
        pass
    
    if not pii:
        pii_match = re.search(r'S\d{4}\d+', doi)
        if pii_match:
            pii = pii_match.group(0)

    # Scraper la page web HTML pour les liens supplémentaires
    try:
        if pii:
            scidir_url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
        else:
            scidir_url = f"https://doi.org/{doi}"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml'
        }
        
        response = requests.get(scidir_url, headers=headers)
        if response.status_code == 200:
            html_content = response.text
            
            # Chercher les mentions de dépôts Mendeley dans le texte HTML
            mendeley_patterns = [
                r'((?:data|code|dataset|repository).{1,50}?(?:Mendeley\s*Data|10\.17632).{1,100}?)(?:<\/p>|<\/div>)',
                r'((?:Mendeley\s*Data|10\.17632).{1,100}?)(?:<\/p>|<\/div>)',
                r'(published in the Mendeley Data Repository.{1,100}?)(?:<\/p>|<\/div>)'
            ]
            
            for pattern in mendeley_patterns:
                matches = re.findall(pattern, html_content, re.IGNORECASE | re.DOTALL)
                for match in matches:
                    mendeley_doi_match = re.search(r'10\.17632/[\w\d]+(?:/\d+)?', match)
                    if mendeley_doi_match:
                        mendeley_url = f"https://doi.org/{mendeley_doi_match.group(0)}"
                        if mendeley_url not in external_repos['mendeley']:
                            external_repos['mendeley'].append(mendeley_url)
            
            # Chercher les sections pertinentes avec des regex
            data_sections = []
            section_patterns = [
                r'<section[^>]*>\s*<h\d[^>]*>Data availability</h\d>.*?</section>',
                r'<section[^>]*>\s*<h\d[^>]*>Supplementary data</h\d>.*?</section>',
                r'<section[^>]*>\s*<h\d[^>]*>Appendix [A-Z]</h\d>.*?</section>',
                r'<div[^>]*class="[^"]*download[^"]*"[^>]*>.*?</div>',
                r'<div[^>]*class="[^"]*extras[^"]*"[^>]*>.*?</div>'
            ]
            
            for pattern in section_patterns:
                sections = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                data_sections.extend(sections)
            
            # Extraire les liens des sections trouvées
            for section in data_sections:
                excel_links = re.findall(r'href="([^"]+\.(?:xlsx?|csv)[^"]*)"', section, re.IGNORECASE)
                for href in excel_links:
                    if href.startswith('/'):
                        href = f"https://www.sciencedirect.com{href}"
                    elif not href.startswith('http'):
                        href = urllib.parse.urljoin(scidir_url, href)
                    file_urls.append(href)
                
                # Chercher les liens des dépôts externes
                github_links = re.findall(r'href="(https?://(?:www\.)?github\.com/[\w\-\.]+/[\w\-\.]+\b[^"]*)"', section, re.IGNORECASE)
                zenodo_links = re.findall(r'href="(https?://(?:www\.)?zenodo\.org/records?/[\d]+\b[^"]*)"', section, re.IGNORECASE)
                mendeley_links = re.findall(r'href="(https?://(?:(?:www\.)?data\.mendeley\.com/datasets/[\w\d]+(?:/\d+)?|doi\.org/10\.17632/[\w\d]+(?:/\d+)?)\b[^"]*)"', section, re.IGNORECASE)
                
                for link in github_links:
                    link = re.sub(r'[.,;:]$', '', link)
                    if link not in external_repos['github']:
                        external_repos['github'].append(link)
                
                for link in zenodo_links:
                    link = re.sub(r'[.,;:]$', '', link)
                    if link not in external_repos['zenodo']:
                        external_repos['zenodo'].append(link)
                        
                for link in mendeley_links:
                    link = re.sub(r'[.,;:]$', '', link)
                    if link not in external_repos['mendeley']:
                        external_repos['mendeley'].append(link)
            
            # Sections spéciales
            special_patterns = [
                (r'<div[^>]*class="[^"]*download-all[^"]*"[^>]*>(.*?)</div>', r'href="([^"]+)"'),
                (r'<table[^>]*class="[^"]*table[^"]*mmc[^"]*"[^>]*>(.*?)</table>', r'href="([^"]+)"'),
                (r'Download\s+[^<>]*?<a[^>]*?href="([^"]+)"', None),
                (r'Download all<[^>]*>.*?<a[^>]*href="([^"]+)"', None),
                (r'Extras\s*\(\d+\)[^<]*<[^>]*>.*?<a[^>]*href="([^"]+)"', None)
            ]
            
            for pattern, subpattern in special_patterns:
                if subpattern:
                    matches = re.search(pattern, html_content, re.DOTALL | re.IGNORECASE)
                    if matches:
                        section = matches.group(1)
                        links = re.findall(subpattern, section)
                        for href in links:
                            if href.startswith('/'):
                                href = f"https://www.sciencedirect.com{href}"
                            elif not href.startswith('http'):
                                href = urllib.parse.urljoin(scidir_url, href)
                            file_urls.append(href)
                else:
                    links = re.findall(pattern, html_content, re.DOTALL | re.IGNORECASE)
                    for href in links:
                        if href.startswith('/'):
                            href = f"https://www.sciencedirect.com{href}"
                        elif not href.startswith('http'):
                            href = urllib.parse.urljoin(scidir_url, href)
                        file_urls.append(href)
    except:
        pass
    
    # Filtrer les URLs pour ne garder que les xlsx, xls et csv
    filtered_urls = []
    for url in file_urls:
        if re.search(r'\.(xlsx?|csv)(\?|$|\#)', url.lower()) or 'spreadsheet' in url.lower() or 'excel' in url.lower() or 'csv' in url.lower():
            filtered_urls.append(url)
    
    return list(set(filtered_urls)), external_repos

def download_files(file_urls, directory="downloads"):
    """Télécharge les fichiers"""
    os.makedirs(directory, exist_ok=True)
    downloaded_files = []
    
    headers = {
        'X-ELS-APIKey': API_KEY,
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': '*/*'
    }
    
    for url in file_urls:
        try:
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)
            
            if not filename or '.' not in filename:
                if 'xlsx' in url.lower():
                    filename = f"file_{abs(hash(url)) % 10000}.xlsx"
                elif 'xls' in url.lower():
                    filename = f"file_{abs(hash(url)) % 10000}.xls"
                elif 'csv' in url.lower():
                    filename = f"file_{abs(hash(url)) % 10000}.csv"
                else:
                    filename = f"file_{abs(hash(url)) % 10000}.dat"
            
            filepath = os.path.join(directory, filename)
            
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response:
                content = response.read()
                
                if content.startswith(b'<?xml') or content.startswith(b'<attachment-metadata'):
                    continue
                
                with open(filepath, 'wb') as f:
                    f.write(content)
                
                downloaded_files.append(filepath)
        except:
            pass
    
    return downloaded_files

def process_external_repos(external_repos):
    """Traite les liens externes GitHub, Zenodo et Mendeley trouvés dans les données Elsevier"""
    downloaded_files = []
    
    # Traiter les liens GitHub
    for github_url in external_repos['github'][:1]:
        try:
            result = subprocess.run(
                ['python', os.path.join(os.path.dirname(__file__), 'github_scraper.py'), github_url],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.stdout.strip().split('\n')[0].lower() == 'true':
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    try:
                        n_files = int(lines[1])
                        downloaded_files.extend(['github_file'] * n_files)
                    except ValueError:
                        pass
        except:
            pass
    
    # Traiter les liens Zenodo
    for zenodo_url in external_repos['zenodo'][:1]:
        try:
            result = subprocess.run(
                ['python', os.path.join(os.path.dirname(__file__), 'zenodo_scraper.py'), zenodo_url],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.stdout.strip().split('\n')[0].lower() == 'true':
                lines = result.stdout.strip().split('\n')
                if len(lines) > 1:
                    try:
                        n_files = int(lines[1])
                        downloaded_files.extend(['zenodo_file'] * n_files)
                    except ValueError:
                        pass
        except:
            pass
    
    # Traiter les liens Mendeley Data
    for mendeley_url in external_repos['mendeley'][:1]:
        try:
            # Pour Mendeley, télécharger les fichiers directement
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            
            # Si c'est un DOI, obtenir l'URL de redirection
            if 'doi.org' in mendeley_url:
                response = requests.head(mendeley_url, headers=headers, allow_redirects=True)
                if response.status_code == 200:
                    mendeley_url = response.url
            
            # Extraire l'ID du dataset
            dataset_id = None
            match = re.search(r'datasets/([\w\d]+)(?:/(\d+))?', mendeley_url)
            if match:
                dataset_id = match.group(1)
                version = match.group(2) if match.group(2) else '1'
                
                # Construire l'URL de l'API Mendeley
                api_url = f"https://data.mendeley.com/api/datasets/{dataset_id}/versions/{version}/files"
                response = requests.get(api_url, headers=headers)
                
                if response.status_code == 200:
                    files_data = response.json()
                    files_to_download = []
                    
                    # Filtrer les fichiers Excel/CSV
                    for file_info in files_data:
                        filename = file_info.get('filename', '')
                        if re.search(r'\.(xlsx?|csv)$', filename, re.IGNORECASE):
                            files_to_download.append({
                                'id': file_info.get('id'),
                                'filename': filename
                            })
                    
                    # Créer un dossier pour le dataset
                    mendeley_dir = os.path.join("downloads", f"mendeley_{dataset_id}")
                    os.makedirs(mendeley_dir, exist_ok=True)
                    
                    # Télécharger chaque fichier
                    for file_info in files_to_download:
                        file_url = f"https://data.mendeley.com/api/datasets/{dataset_id}/versions/{version}/files/{file_info['id']}/download"
                        file_path = os.path.join(mendeley_dir, file_info['filename'])
                        
                        try:
                            response = requests.get(file_url, headers=headers)
                            if response.status_code == 200:
                                with open(file_path, 'wb') as f:
                                    f.write(response.content)
                                downloaded_files.append(file_path)
                        except:
                            pass
        except:
            pass
    
    return downloaded_files

def main():
    if len(sys.argv) < 2:
        print(False)
        return False
    
    url_or_doi = sys.argv[1]
    
    # Extraire le DOI
    doi = extract_doi(url_or_doi)
    if not doi:
        print(False)
        return False
    
    # Récupérer les liens vers les fichiers and les dépôts externes
    file_urls, external_repos = get_data_and_extract_files(doi)
    
    # Télécharger les fichiers directs d'Elsevier
    downloaded_files = download_files(file_urls)
    
    # Traiter les dépôts externes (GitHub/Zenodo/Mendeley)
    if external_repos['github'] or external_repos['zenodo'] or external_repos['mendeley']:
        external_files = process_external_repos(external_repos)
        downloaded_files.extend(external_files)
    
    # Déterminer si des fichiers ont été trouvés
    has_files = bool(downloaded_files)
    
    # Afficher uniquement le résultat booléen et le nombre
    print(has_files)
    print(len(downloaded_files))
    
    return has_files

if __name__ == "__main__":
    main()
