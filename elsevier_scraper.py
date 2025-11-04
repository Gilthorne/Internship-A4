import PyPDF2
import re
import requests
import sys
import os
import subprocess
import platform
import json
from typing import List, Dict, Optional
from datetime import datetime

class ElsevierDataExtractor:
    def __init__(self, doi: str = None, api_key: str = None):
        self.doi = doi
        self.api_key = api_key or "5e0c4b89c3dc998fda16c52f50e7f4a2"
        self.pii = None
        self.article_title = None
        self.downloads_dir = "downloads"
        self.article_folder = None
        self.pdf_path = None
        self.downloaded_files = []
        
        # Créer le dossier downloads
        if not os.path.exists(self.downloads_dir):
            os.makedirs(self.downloads_dir)
    
    def clean_filename(self, filename: str) -> str:
        """Nettoie un nom de fichier."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            filename = filename.replace(char, '_')
        return filename[:100].strip()
    
    def get_article_metadata(self) -> bool:
        """Récupère les métadonnées de l'article."""
        if not self.doi:
            return False
        
        clean_doi = self.doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
        
        print(f"\n📊 Récupération des métadonnées...")
        print(f"   DOI: {clean_doi}")
        
        # Appel pour les métadonnées complètes (Excel/CSV)
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
                    
                    # Créer le dossier pour cet article
                    clean_title = self.clean_filename(self.article_title)
                    self.article_folder = os.path.join(self.downloads_dir, clean_title)
                    os.makedirs(self.article_folder, exist_ok=True)
                    
                    print(f"✅ Titre: {self.article_title}")
                    print(f"✅ PII: {self.pii}")
                    print(f"📁 Dossier: {self.article_folder}")
                    
                    # Sauvegarder les métadonnées complètes
                    self.full_api_data = data
                    return True
                
                return False
            else:
                print(f"❌ Erreur HTTP {response.status_code}")
                return False
        
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return False
    
    def download_file(self, url: str, filename: str, headers: dict = None) -> bool:
        """Télécharge un fichier."""
        try:
            response = requests.get(url, headers=headers, stream=True, timeout=60)
            
            if response.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                file_size = os.path.getsize(filename)
                print(f"  ✓ {os.path.basename(filename)} ({file_size:,} bytes)")
                return True
            else:
                print(f"  ✗ Échec: {response.status_code}")
                return False
        except Exception as e:
            print(f"  ✗ Erreur: {e}")
            return False
    
    def download_excel_csv_files(self) -> List[Dict]:
        """Télécharge tous les fichiers Excel/CSV."""
        print("\n📋 Téléchargement des fichiers Excel/CSV:")
        
        if not hasattr(self, 'full_api_data'):
            print("  ⚠️ Pas de données API")
            return []
        
        objects = self.full_api_data['full-text-retrieval-response'].get('objects', {}).get('object', [])
        if not isinstance(objects, list):
            objects = [objects]
        
        downloaded = []
        
        for obj in objects:
            ref = obj.get('@ref', 'unknown')
            mimetype = obj.get('@mimetype', '')
            url = obj.get('$', '')
            
            # Détecter Excel/CSV
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
        
        if not downloaded:
            print("  ⚠️ Aucun fichier Excel/CSV trouvé")
        
        self.downloaded_files = downloaded
        return downloaded
    
    def download_pdf(self) -> bool:
        """Télécharge le PDF principal via l'endpoint PII."""
        print("\n📄 Téléchargement du PDF:")
        
        if not self.pii:
            print("  ⚠️ PII non disponible")
            return False
        
        # Utiliser l'endpoint direct avec le PII pour obtenir le PDF
        url = f"https://api.elsevier.com/content/article/pii/{self.pii}"
        
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/pdf"
        }
        
        filename = os.path.join(self.article_folder, f"{self.clean_filename(self.article_title)}.pdf")
        
        if self.download_file(url, filename, headers):
            self.pdf_path = filename
            return True
        
        print("  ⚠️ PDF non téléchargé")
        return False
    
    def extract_data_availability_section(self) -> Optional[Dict]:
        """Extrait la section Data Availability du PDF."""
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            return None
        
        print("\n📖 Extraction de la section Data Availability...")
        
        try:
            with open(self.pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                # Trouver la section
                for page_num, page in enumerate(pdf_reader.pages, 1):
                    text = page.extract_text()
                    if 'data availability' in text.lower():
                        idx = text.lower().find('data availability')
                        section = self._extract_paragraph(text, idx)
                        
                        print(f"✅ Section trouvée (page {page_num})")
                        
                        return {
                            'page': page_num,
                            'text': section
                        }
                
                print("⚠️ Section Data Availability non trouvée")
                return None
        
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return None
    
    def _extract_paragraph(self, text: str, start: int) -> str:
        """Extrait un paragraphe."""
        remaining = text[start:]
        end_markers = [r'\n\s*References?\s*\n', r'\n\s*\n\s*[A-Z]', r'\n\s*CRediT']
        
        end = len(remaining)
        for marker in end_markers:
            match = re.search(marker, remaining[20:])
            if match:
                end = min(end, 20 + match.start())
        return remaining[:end].strip()
    
    def extract_links_from_data_availability(self, data_availability_text: str) -> List[Dict]:
        """Extrait tous les liens de la section Data Availability."""
        print("\n🔍 Extraction des liens...")
        
        links = []
        
        # URLs directes
        url_pattern = r'https?://[^\s,\)\]<>\"\']+|www\.[^\s,\)\]<>\"\']+' 
        urls = re.findall(url_pattern, data_availability_text)
        
        for url in urls:
            url_clean = url.rstrip('.,;:!?)')
            if len(url_clean) > 10:
                links.append({
                    'url': url_clean,
                    'type': 'direct_url',
                    'source': 'Data Availability'
                })
        
        # DOIs
        doi_patterns = [
            r'doi\.org/([^\s,\)\]<>\"\']+)',
            r'doi:?\s*([^\s,\)\]<>\"\']+)',
            r'\b(10\.\d{4,}/[^\s,\)\]<>\"\']+)'
        ]
        
        for doi_pattern in doi_patterns:
            dois = re.findall(doi_pattern, data_availability_text, re.IGNORECASE)
            for doi in dois:
                doi_clean = doi.rstrip('.,;:!?)')
                if doi_clean.startswith('10.'):
                    url = f"https://doi.org/{doi_clean}"
                    if url not in [l['url'] for l in links]:
                        links.append({
                            'url': url,
                            'type': 'doi',
                            'source': 'Data Availability'
                        })
        
        # Supprimer doublons
        seen = set()
        unique_links = []
        for link in links:
            if link['url'] not in seen:
                seen.add(link['url'])
                unique_links.append(link)
        
        if unique_links:
            print(f"✅ {len(unique_links)} lien(s) trouvé(s)")
            for link in unique_links:
                print(f"   🔗 {link['url']}")
        else:
            print("⚠️ Aucun lien trouvé")
        
        return unique_links
    
    def open_pdf(self):
        """Ouvre le PDF."""
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            return
        
        try:
            system = platform.system()
            
            if system == 'Windows':
                os.startfile(self.pdf_path)
            elif system == 'Darwin':
                subprocess.run(['open', self.pdf_path])
            else:
                subprocess.run(['xdg-open', self.pdf_path])
            
            print(f"\n📂 PDF ouvert: {os.path.basename(self.pdf_path)}")
        except:
            pass
    
    def save_results(self, data_availability_section: Dict, extracted_links: List[Dict]):
        """Sauvegarde les résultats."""
        results = {
            'doi': self.doi,
            'article_title': self.article_title,
            'pii': self.pii,
            'extraction_date': datetime.now().isoformat(),
            'downloaded_excel_csv': [
                {
                    'filename': os.path.basename(f['filename']),
                    'type': f['type'],
                    'url': f['url']
                }
                for f in self.downloaded_files
            ],
            'pdf_path': os.path.basename(self.pdf_path) if self.pdf_path else None,
            'data_availability_section': {
                'page': data_availability_section.get('page') if data_availability_section else None,
                'text': data_availability_section.get('text') if data_availability_section else None
            },
            'extracted_links': extracted_links
        }
        
        results_file = os.path.join(self.article_folder, "extraction_results.json")
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        print(f"\n💾 Résultats sauvegardés: {results_file}")
    
    def display_summary(self, extracted_links: List[Dict]):
        """Affiche le résumé."""
        print("\n" + "=" * 80)
        print("📊 RÉSUMÉ DE L'EXTRACTION")
        print("=" * 80)
        print(f"\n📄 Article: {self.article_title}")
        print(f"📁 Dossier: {os.path.abspath(self.article_folder)}")
        print(f"\n📋 Fichiers Excel/CSV téléchargés: {len(self.downloaded_files)}")
        for f in self.downloaded_files:
            print(f"   • {os.path.basename(f['filename'])} ({f['type']})")
        
        print(f"\n🔗 Liens de données extraits: {len(extracted_links)}")
        for i, link in enumerate(extracted_links, 1):
            print(f"   {i}. {link['url']}")
            print(f"      Type: {link['type']}")
        
        print("\n" + "=" * 80)
    
    def run(self, open_pdf: bool = True) -> bool:
        """Exécute le pipeline complet."""
        print(f"\n🚀 EXTRACTEUR DE DONNÉES ELSEVIER")
        print("=" * 80)
        
        # 1. Métadonnées
        if not self.get_article_metadata():
            print("\n❌ Échec de récupération des métadonnées")
            return False
        
        # 2. Télécharger Excel/CSV
        self.download_excel_csv_files()
        
        # 3. Télécharger PDF
        pdf_ok = self.download_pdf()
        
        # 4. Extraire Data Availability
        data_section = None
        extracted_links = []
        
        if pdf_ok:
            data_section = self.extract_data_availability_section()
            
            # 5. Extraire les liens
            if data_section:
                extracted_links = self.extract_links_from_data_availability(data_section['text'])
        
        # 6. Sauvegarder
        self.save_results(data_section, extracted_links)
        
        # 7. Ouvrir PDF
        if pdf_ok and open_pdf:
            self.open_pdf()
        
        # 8. Résumé
        self.display_summary(extracted_links)
        
        return True


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Extracteur complet de données Elsevier',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  python elsevier_data_extractor.py --doi 10.1016/j.ecoinf.2025.103426
  python elsevier_data_extractor.py --doi 10.1016/j.ecoinf.2025.103426 --no-open
  python elsevier_data_extractor.py --doi 10.1016/j.ecoinf.2025.103426 --api-key YOUR_KEY
        """
    )
    
    parser.add_argument('--doi', required=True, help='DOI de l\'article')
    parser.add_argument('--api-key', help='Clé API Elsevier (optionnel)')
    parser.add_argument('--no-open', action='store_true', help='Ne pas ouvrir le PDF')
    
    args = parser.parse_args()
    
    extractor = ElsevierDataExtractor(
        doi=args.doi,
        api_key=args.api_key
    )
    
    extractor.run(open_pdf=not args.no_open)


if __name__ == "__main__":
    main()