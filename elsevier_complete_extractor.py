import PyPDF2
import re
import requests
import sys
import os
import json
from typing import List, Dict, Optional
from datetime import datetime
import subprocess
from urllib.parse import urlparse

def eprint(*args, **kwargs):
    """Print to stderr instead of stdout"""
    print(*args, file=sys.stderr, **kwargs)

class ElsevierCompleteExtractor:
    """
    Complete Elsevier article extractor:
    - Downloads Excel/CSV files
    - Extracts Data Availability section links
    """
    
    def __init__(self, doi: str, api_key: str = None):
        self.doi = doi
        self.api_key = api_key or "5e0c4b89c3dc998fda16c52f50e7f4a2"
        self.pii = None
        self.article_title = None
        self.downloads_dir = "downloads"
        self.article_folder = None
        self.pdf_path = None
        self.downloaded_files = []
        self.extracted_links = []
        self.full_api_data = None
        self.secondary_downloads = 0
        
        if not os.path.exists(self.downloads_dir):
            os.makedirs(self.downloads_dir)
    
    def clean_filename(self, filename: str) -> str:
        """Clean filename for filesystem compatibility."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100].strip()
    
    def get_article_metadata(self) -> bool:
        """Retrieve article metadata."""
        if not self.doi:
            return False
        
        clean_doi = self.doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
        
        eprint(f"Fetching metadata for DOI: {clean_doi}")
        
        url_full = f"https://api.elsevier.com/content/article/doi/{clean_doi}?view=FULL"
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json"
        }
        
        try:
            response = requests.get(url_full, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'full-text-retrieval-response' in data:
                    core_data = data['full-text-retrieval-response'].get('coredata', {})
                    self.pii = core_data.get('pii')
                    self.article_title = core_data.get('dc:title', 'article')
                    
                    clean_title = self.clean_filename(self.article_title)
                    self.article_folder = os.path.join(self.downloads_dir, clean_title)
                    os.makedirs(self.article_folder, exist_ok=True)
                    
                    self.full_api_data = data
                    return True
                
                return False
            else:
                eprint(f"Error: HTTP {response.status_code}")
                return False
        
        except Exception as e:
            eprint(f"Error: {e}")
            return False
    
    def download_file(self, url: str, filename: str, headers: dict = None) -> bool:
        """Download a file."""
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=60)
            
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                return True
            return False
        except:
            return False
    
    def download_excel_csv_files(self) -> List[Dict]:
        """Download all Excel/CSV files."""
        if not self.full_api_data:
            return []
        
        objects = self.full_api_data['full-text-retrieval-response'].get('objects', {}).get('object', [])
        if not isinstance(objects, list):
            objects = [objects]
        
        downloaded = []
        
        for obj in objects:
            ref = obj.get('@ref', 'unknown')
            mimetype = obj.get('@mimetype', '')
            url = obj.get('$', '')
            
            is_xlsx = (
                mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or
                mimetype == 'application/excel' or
                ref.endswith('.xlsx')
            )
            
            is_csv = (
                mimetype == 'text/csv' or
                mimetype == 'application/vnd.ms-excel' or
                ref.endswith('.csv')
            )
            
            if (is_xlsx or is_csv) and url:
                file_type = 'Excel' if is_xlsx else 'CSV'
                extension = '.xlsx' if is_xlsx else '.csv'
                
                if not ref.endswith(('.csv', '.xlsx', '.xls')):
                    filename = os.path.join(self.article_folder, f"{ref}{extension}")
                else:
                    filename = os.path.join(self.article_folder, ref)
                
                headers = {'X-ELS-APIKey': self.api_key}
                
                if self.download_file(url, filename, headers):
                    downloaded.append({
                        'ref': ref,
                        'filename': filename,
                        'type': file_type,
                        'url': url,
                        'mimetype': mimetype
                    })
        
        self.downloaded_files = downloaded
        return downloaded
    
    def download_pdf(self) -> bool:
        """Download PDF via PII endpoint."""
        if not self.pii:
            return False
        
        url = f"https://api.elsevier.com/content/article/pii/{self.pii}"
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/pdf"
        }
        
        filename = os.path.join(self.article_folder, f"{self.clean_filename(self.article_title)}.pdf")
        
        if self.download_file(url, filename, headers):
            self.pdf_path = filename
            return True
        
        return False
    
    def extract_data_availability_section(self) -> Optional[Dict]:
        """Extract Data Availability section from PDF."""
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            return None
        
        try:
            with open(self.pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = page.extract_text()
                    if 'data availability' in text.lower():
                        idx = text.lower().find('data availability')
                        section = self._extract_paragraph(text, idx)
                        references = self._extract_references(pdf_reader)
                        
                        return {
                            'page': page_num,
                            'text': section,
                            'references': references
                        }
                
                return None
        
        except Exception as e:
            return None
    
    def _extract_paragraph(self, text: str, start: int) -> str:
        """Extract paragraph."""
        remaining = text[start:]
        end_markers = [r'\n\s*References?\s*\n', r'\n\s*\n\s*[A-Z]', r'\n\s*CRediT']
        
        end = len(remaining)
        for marker in end_markers:
            match = re.search(marker, remaining[20:])
            if match:
                end = min(end, 20 + match.start())
        return remaining[:end].strip()
    
    def _extract_references(self, pdf_reader) -> str:
        """Extract References section."""
        full_ref_text = ""
        capture = False
        
        for page in pdf_reader.pages:
            text = page.extract_text()
            if not capture and re.search(r'\n\s*References?\s*\n', text, re.IGNORECASE):
                capture = True
                ref_match = re.search(r'\n\s*References?\s*\n', text, re.IGNORECASE)
                full_ref_text = text[ref_match.end():]
            elif capture:
                full_ref_text += "\n" + text
        
        return full_ref_text
    
    def extract_links_from_data_availability(self, data_section: Dict) -> List[Dict]:
        """
        Extract ALL links from Data Availability section:
        - Direct URLs in text
        - URLs from citations in references
        """
        data_text = data_section['text']
        ref_text = data_section.get('references', '')
        
        all_links = []
        
        # Direct URLs
        direct_links = self._extract_direct_urls(data_text)
        all_links.extend(direct_links)
        
        # Citation URLs
        if ref_text:
            citation_links = self._extract_citation_links(data_text, ref_text)
            all_links.extend(citation_links)
        
        # Remove duplicates
        seen = set()
        unique_links = []
        for link in all_links:
            if link['url'] not in seen:
                seen.add(link['url'])
                unique_links.append(link)
        
        return unique_links
    
    def _extract_direct_urls(self, text: str) -> List[Dict]:
        """Extract direct URLs from text."""
        links = []
        
        # HTTP/HTTPS URLs
        url_pattern = r'https?://[^\s,\)\]<>\"\']+|www\.[^\s,\)\]<>\"\']+' 
        urls = re.findall(url_pattern, text)
        
        for url in urls:
            url_clean = url.rstrip('.,;:!?)')
            if len(url_clean) > 10:
                links.append({
                    'url': url_clean,
                    'type': 'direct_url',
                    'source': 'Data Availability text'
                })
        
        # DOIs
        doi_patterns = [
            r'doi\.org/([^\s,\)\]<>\"\']+)',
            r'doi:?\s*([^\s,\)\]<>\"\']+)',
            r'\b(10\.\d{4,}/[^\s,\)\]<>\"\']+)'
        ]
        
        for doi_pattern in doi_patterns:
            dois = re.findall(doi_pattern, text, re.IGNORECASE)
            for doi in dois:
                doi_clean = doi.rstrip('.,;:!?)')
                if doi_clean.startswith('10.'):
                    url = f"https://doi.org/{doi_clean}"
                    if url not in [l['url'] for l in links]:
                        links.append({
                            'url': url,
                            'type': 'doi',
                            'source': 'Data Availability DOI'
                        })
        
        return links
    
    def _extract_citation_links(self, data_text: str, ref_text: str) -> List[Dict]:
        """Extract links from citations (Author, Year)."""
        links = []
        
        pattern = r'\(\s*([^\s,\)]+(?:\s+et\s+al\.)?)\s*,\s*(\d{4})\s*\)'
        matches = re.findall(pattern, data_text)
        citations = [(a.strip(), y.strip()) for a, y in matches if a and a[0].isupper()]
        
        if not citations:
            return links
        
        for author, year in citations:
            clean_author = re.sub(r'[^\w\s]', '', author).replace(' et al', '').strip()
            
            ref_norm = ref_text.replace('\x7f', '').replace('¨', '').replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')
            
            search_pattern = rf'(?:^|\n)\s*{re.escape(clean_author[0])}[a-z¨äöü\x7f]*{re.escape(clean_author[1:])}[^\n]{{0,2500}}?{year}'
            match = re.search(search_pattern, ref_norm, re.MULTILINE)
            
            if match:
                start = match.start()
                ref_block = ref_text[start:min(len(ref_text), start + 3000)]
                
                next_match = re.search(r'\n[A-Z][a-z]+,\s*[A-Z]', ref_block[300:])
                if next_match:
                    ref_block = ref_block[:300 + next_match.start()]
                
                urls = re.findall(r'https?://[^\s,\)\]<>\"\']+', ref_block)
                
                doi_split_pattern = r'https?://doi\.org/\s+(10\.\d{4,}/[^\s,\)\]<>\"\']+)'
                doi_splits = re.findall(doi_split_pattern, ref_block)
                for doi in doi_splits:
                    urls.append(f"https://doi.org/{doi}")
                
                urls = [u.rstrip('.,;:!?)') for u in urls]
                
                dois = re.findall(r'10\.\d{4,}/[^\s,\)\]<>\"\']+', ref_block)
                doi_urls = [f"https://doi.org/{d.rstrip('.,;:!?)')}" for d in dois if d.rstrip('.,;:!?)')]
                
                all_urls = urls + doi_urls
                all_urls = list(dict.fromkeys(all_urls))
                all_urls = [u for u in all_urls if not u.endswith('doi.org/') and len(u) > 20]
                
                if all_urls:
                    links.append({
                        'url': all_urls[0],
                        'type': 'citation',
                        'citation': f"{author}, {year}",
                        'source': f"Citation: {author}, {year}",
                        'all_urls': all_urls
                    })
        
        return links
    
    def identify_link_source(self, url: str) -> str:
        """Identifie le type de source d'un lien"""
        domain = urlparse(url).netloc.lower()
        
        if 'github.com' in domain:
            return 'github'
        elif 'zenodo.org' in domain:
            return 'zenodo'
        elif any(d in domain for d in ['datadryad.org', 'dryad']):
            return 'generic'
        elif any(d in domain for d in ['figshare', 'osf.io', 'dataverse']):
            return 'generic'
        # For DOI links, check the DOI prefix
        if 'doi.org' in domain:
            # Extract DOI prefix to identify the repository
            doi_match = re.search(r'10\.(\d{4,})', url)
            if doi_match:
                prefix = doi_match.group(1)
                
                # Dryad DOIs: 10.5061
                if prefix == '5061':
                    return 'generic'
                # Zenodo DOIs: 10.5281
                elif prefix == '5281':
                    return 'zenodo'
                # Figshare DOIs: 10.6084, 10.25384
                elif prefix in ('6084', '25384'):
                    return 'generic'
                # Elsevier/ScienceDirect: 10.1016
                elif prefix == '1016':
                    return 'elsevier'
                # Mendeley Data: 10.17632
                elif prefix == '17632':
                    return 'generic'
                else:
                    # Par défaut pour les autres DOIs, essayer le scraper générique
                    return 'generic'
        # Direct Elsevier domains
        if any(d in domain for d in ['elsevier.com', 'sciencedirect.com', 'mendeley.com']):
            return 'elsevier'
        
        return 'generic'

    
    def download_from_external_link(self, link: Dict) -> int:
        """Télécharge les fichiers Excel/CSV depuis un lien externe et retourne le compte"""
        url = link['url']
        source_type = self.identify_link_source(url)
        
        eprint(f"   Checking {url}...")
        eprint(f"   Source type detected: {source_type}")
        
        try:
            # Créer un sous-dossier pour les données externes
            external_folder = os.path.join(self.article_folder, "external_data")
            os.makedirs(external_folder, exist_ok=True)
            
            # Appeler le scraper approprié
            scraper_map = {
                'github': 'github_scraper.py',
                'zenodo': 'zenodo_scraper.py',
                'generic': 'generic_data_scraper.py'
            }
            
            if source_type == 'elsevier':
                # Extraire le DOI si c'est un lien Elsevier
                doi_match = re.search(r'10\.\d{4,}/[^\s/]+', url)
                if doi_match:
                    doi = doi_match.group(0)
                    result = subprocess.run(
                        ['python', 'elsevier_complete_extractor.py', doi, '--output-dir', external_folder],
                        capture_output=True,
                        text=True,
                        timeout=180,
                        cwd=os.path.dirname(__file__) or '.'
                    )
                else:
                    return 0
            else:
                # Utiliser le scraper approprié avec le dossier de destination
                scraper = scraper_map.get(source_type, 'generic_data_scraper.py')
                eprint(f"   Calling scraper: {scraper}")
                result = subprocess.run(
                    ['python', scraper, url, '--output-dir', external_folder],
                    capture_output=True,
                    text=True,
                    timeout=120,
                    cwd=os.path.dirname(__file__) or '.'
                )
            
            # Parser la sortie
            stdout_lines = result.stdout.strip().split('\n')
            
            if len(stdout_lines) >= 2:
                has_files = stdout_lines[0].lower() == 'true'
                
                try:
                    file_count = int(stdout_lines[1])
                except (ValueError, IndexError):
                    file_count = 0
                
                if has_files and file_count > 0:
                    eprint(f"      ✓ {file_count} file(s) found and downloaded to external_data/")
                    return file_count
                else:
                    eprint(f"      ⊘ No Excel/CSV files")
            
            return 0
            
        except subprocess.TimeoutExpired:
            eprint(f"      ⏱ Timeout")
            return 0
        except Exception as e:
            eprint(f"      ✗ Error: {e}")
            return 0

    def process_extracted_links(self, extracted_links: List[Dict]) -> int:
        """Vérifie les fichiers depuis les liens extraits et retourne le total"""
        if not extracted_links:
            return 0
        
        eprint("\n🔗 Checking links for Excel/CSV files...")
        
        total_files = 0
        
        for link in extracted_links:
            count = self.download_from_external_link(link)
            total_files += count
        
        if total_files > 0:
            eprint(f"\n✅ {total_files} additional file(s) found in external links")
        else:
            eprint("\n⊘ No additional files found")
        
        return total_files
    
    def get_file_count(self):
        """Return total number of files"""
        direct_files = len(self.downloaded_files)
        link_files = self.secondary_downloads
        return direct_files + link_files
    
    def save_results(self, data_availability_section: Dict, extracted_links: List[Dict]):
        """Save results to JSON."""
        results = {
            'doi': self.doi,
            'article_title': self.article_title,
            'pii': self.pii,
            'extraction_date': datetime.now().isoformat(),
            'downloaded_excel_csv': [
                {
                    'filename': os.path.basename(f['filename']),
                    'type': f['type'],
                    'url': f['url'],
                    'source': 'direct_article'
                }
                for f in self.downloaded_files
            ],
            'pdf_path': os.path.basename(self.pdf_path) if self.pdf_path else None,
            'data_availability_section': {
                'page': data_availability_section.get('page') if data_availability_section else None,
                'text': data_availability_section.get('text') if data_availability_section else None
            },
            'extracted_links': extracted_links,
            'total_files_in_links': self.secondary_downloads,
            'total_files': len(self.downloaded_files) + self.secondary_downloads
        }
        
        results_file = os.path.join(self.article_folder, "extraction_results.json")
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
    
    def display_summary(self, extracted_links: List[Dict]):
        """Display summary."""
        eprint("\n" + "=" * 80)
        eprint("EXTRACTION SUMMARY")
        eprint("=" * 80)
        eprint(f"\nArticle: {self.article_title}")
        eprint(f"Folder: {os.path.abspath(self.article_folder)}")
        
        eprint(f"\n📊 Direct Excel/CSV files: {len(self.downloaded_files)}")
        if self.downloaded_files:
            for f in self.downloaded_files:
                eprint(f"   • {os.path.basename(f['filename'])} ({f['type']})")
        
        eprint(f"\n🔗 Data links extracted: {len(extracted_links)}")
        if extracted_links:
            for i, link in enumerate(extracted_links, 1):
                eprint(f"   {i}. {link['url']}")
                if 'citation' in link:
                    eprint(f"      From: {link['citation']}")
        
        if self.secondary_downloads > 0:
            eprint(f"\n📥 Files found in external links: {self.secondary_downloads}")
        
        eprint(f"\n📈 Total files: {len(self.downloaded_files) + self.secondary_downloads}")
        eprint("\n" + "=" * 80)
    
    def run(self) -> bool:
        """Execute complete pipeline."""
        eprint(f"\nELSEVIER COMPLETE EXTRACTOR")
        eprint("=" * 80)
        
        if not self.get_article_metadata():
            return False
        
        self.download_excel_csv_files()
        pdf_ok = self.download_pdf()
        
        data_section = None
        self.secondary_downloads = 0
        
        if pdf_ok:
            data_section = self.extract_data_availability_section()
            if data_section:
                self.extracted_links = self.extract_links_from_data_availability(data_section)
                
                if self.extracted_links:
                    self.secondary_downloads = self.process_extracted_links(self.extracted_links)
        
        self.save_results(data_section, self.extracted_links)
        self.display_summary(self.extracted_links)
        
        return True


def main():
    if len(sys.argv) < 2:
        print("False")
        print("0")
        sys.exit(1)
    
    doi = sys.argv[1]
    
    extractor = ElsevierCompleteExtractor(doi=doi)
    success = extractor.run()
    
    # Output format for pipeline
    print("True" if success else "False")
    print(extractor.get_file_count() if success else "0")
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()