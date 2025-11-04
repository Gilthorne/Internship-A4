import requests
import re
import os
import sys
from urllib.parse import urlparse, urljoin

def eprint(*args, **kwargs):
    """Print to stderr instead of stdout"""
    print(*args, file=sys.stderr, **kwargs)

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False
    eprint("Warning: BeautifulSoup not installed. Install with: pip install beautifulsoup4")

class GenericDataScraper:
    """
    Generic scraper for data repositories like Dryad, Figshare, OSF, etc.
    Detects Excel/CSV files from HTML and downloads them.
    """
    
    def __init__(self, url):
        self.url = url
        self.domain = urlparse(url).netloc
        self.found_files = []
    
    def resolve_doi(self, url):
        """Résout un DOI vers l'URL finale"""
        if 'doi.org' in url:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                response = requests.head(url, headers=headers, allow_redirects=True, timeout=10)
                resolved_url = response.url
                eprint(f"DOI resolved: {url} -> {resolved_url}")
                return resolved_url
            except:
                return url
        return url
    
    def get_page_content(self):
        """Récupère le contenu HTML de la page"""
        # Résoudre les DOIs
        actual_url = self.resolve_doi(self.url)
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(actual_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                return response.text
            else:
                eprint(f"HTTP {response.status_code}")
                return None
        except Exception as e:
            eprint(f"Error fetching page: {e}")
            return None
    
    def extract_files_from_html(self, html):
        """Extrait les fichiers Excel/CSV depuis le HTML"""
        if not html:
            return []
        
        files = []
        
        # Méthode 1: Regex simple (sans BeautifulSoup)
        # Chercher les patterns de fichiers CSV/Excel
        file_patterns = [
            r'href=["\']([^"\']*\.(?:xlsx?|csv)(?:\?[^"\']*)?)["\']',
            r'href=["\']([^"\']*download[^"\']*)["\'][^>]*>([^<]*\.(?:xlsx?|csv))',
            r'([^\s"\'<>]+\.(?:xlsx?|csv))',
        ]
        
        for pattern in file_patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    url_part = match[0] if match[0] else match[1] if len(match) > 1 else ''
                else:
                    url_part = match
                
                if url_part and len(url_part) > 4:
                    # Construire l'URL complète
                    if url_part.startswith('http'):
                        full_url = url_part
                    else:
                        full_url = urljoin(self.url, url_part)
                    
                    # Extraire le nom de fichier
                    filename = os.path.basename(urlparse(url_part).path)
                    if not filename:
                        filename = url_part
                    
                    if re.search(r'\.(xlsx?|csv)$', filename, re.IGNORECASE):
                        files.append({
                            'filename': filename,
                            'url': full_url,
                            'source': 'regex'
                        })
        
        # Méthode 2: BeautifulSoup si disponible
        if HAS_BS4:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                
                # Chercher tous les liens
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    text = link.get_text(strip=True)
                    
                    # Vérifier l'extension
                    if re.search(r'\.(xlsx?|csv)(\?|$)', href, re.IGNORECASE) or \
                       re.search(r'\.(xlsx?|csv)$', text, re.IGNORECASE):
                        
                        full_url = urljoin(self.url, href)
                        filename = text if re.search(r'\.(xlsx?|csv)$', text, re.IGNORECASE) else \
                                  os.path.basename(urlparse(href).path)
                        
                        files.append({
                            'filename': filename,
                            'url': full_url,
                            'source': 'beautifulsoup'
                        })
                
                # Dryad spécifique - chercher dans les tables
                for row in soup.find_all('tr'):
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        first_cell = cells[0].get_text(strip=True)
                        if re.search(r'\.(xlsx?|csv)$', first_cell, re.IGNORECASE):
                            download_link = row.find('a', href=re.compile(r'download|file'))
                            if download_link:
                                full_url = urljoin(self.url, download_link['href'])
                                files.append({
                                    'filename': first_cell,
                                    'url': full_url,
                                    'source': 'table'
                                })
            except Exception as e:
                eprint(f"BeautifulSoup parsing error: {e}")
        
        # Dédupliquer
        seen_urls = set()
        unique_files = []
        for file in files:
            if file['url'] not in seen_urls:
                seen_urls.add(file['url'])
                unique_files.append(file)
                eprint(f"Found: {file['filename']} ({file['source']})")
        
        return unique_files
    
    def download_file(self, file_info, directory="downloads"):
        """Télécharge un fichier"""
        os.makedirs(directory, exist_ok=True)
        
        filename = file_info['filename']
        url = file_info['url']
        
        # Nettoyer le nom de fichier
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filepath = os.path.join(directory, filename)
        
        # Éviter les doublons
        base, ext = os.path.splitext(filepath)
        counter = 1
        while os.path.exists(filepath):
            filepath = f"{base}_{counter}{ext}"
            counter += 1
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, stream=True, timeout=60)
            
            if response.status_code == 200:
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = os.path.getsize(filepath)
                eprint(f"  ✓ {filename} ({file_size:,} bytes)")
                return filepath
            else:
                eprint(f"  ✗ {filename}: HTTP {response.status_code}")
                return None
        except Exception as e:
            eprint(f"  ✗ {filename}: {e}")
            return None
    
    def run(self, download=True):
        """Exécute le scraper"""
        eprint(f"Generic Data Scraper - {self.domain}")
        
        # 1. Récupérer le HTML
        html = self.get_page_content()
        if not html:
            return False, []
        
        # 2. Extraire les fichiers
        self.found_files = self.extract_files_from_html(html)
        
        if not self.found_files:
            eprint("No Excel/CSV files found")
            return False, []
        
        eprint(f"Found {len(self.found_files)} file(s)")
        
        # 3. Télécharger si demandé
        downloaded = []
        if download:
            eprint("Downloading files...")
            for file_info in self.found_files:
                result = self.download_file(file_info)
                if result:
                    downloaded.append(result)
        
        return len(self.found_files) > 0, downloaded


def main():
    if len(sys.argv) < 2:
        print("False")
        print("0")
        eprint("Usage: python generic_data_scraper.py <URL>")
        sys.exit(1)
    
    url = sys.argv[1]
    
    scraper = GenericDataScraper(url)
    has_files, downloaded = scraper.run(download=True)
    
    # Output format for pipeline
    print("True" if has_files else "False")
    print(len(scraper.found_files) if has_files else "0")
    
    sys.exit(0)


if __name__ == "__main__":
    main()