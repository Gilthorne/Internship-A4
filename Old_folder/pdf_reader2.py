import PyPDF2
import re
import requests
import sys
import os
import subprocess
import platform
from typing import List, Dict, Optional

class DataAvailabilityExtractor:
    def __init__(self, pdf_path: str = None, pii: str = None, doi: str = None, api_key: str = None):
        self.pdf_path = pdf_path
        self.pii = pii
        self.doi = doi
        self.api_key = api_key or "5e0c4b89c3dc998fda16c52f50e7f4a2"
        self.downloaded_pdf = None
        self.article_title = None
        self.downloads_dir = "downloads"
        
        # Créer le dossier downloads s'il n'existe pas
        if not os.path.exists(self.downloads_dir):
            os.makedirs(self.downloads_dir)
            print(f"📁 Dossier créé: {os.path.abspath(self.downloads_dir)}")
    
    def get_pii_from_doi(self) -> bool:
        """Récupère le PII depuis un DOI."""
        if not self.doi:
            return False
        
        clean_doi = self.doi.replace('https://doi.org/', '').replace('http://doi.org/', '')
        
        print(f"\n🔍 Récupération du PII depuis le DOI...")
        print(f"   DOI: {clean_doi}")
        
        url = f"https://api.elsevier.com/content/article/doi/{clean_doi}"
        
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/json"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                
                pii = None
                
                if 'full-text-retrieval-response' in data:
                    core_data = data['full-text-retrieval-response'].get('coredata', {})
                    pii = core_data.get('pii')
                    self.article_title = core_data.get('dc:title', 'article')
                elif 'abstracts-retrieval-response' in data:
                    core_data = data['abstracts-retrieval-response'].get('coredata', {})
                    pii = core_data.get('pii')
                    self.article_title = core_data.get('dc:title', 'article')
                
                if pii:
                    self.pii = pii
                    print(f"✅ PII trouvé: {self.pii}")
                    if self.article_title:
                        print(f"📄 Titre: {self.article_title}")
                    return True
                else:
                    print("⚠️  PII non trouvé dans la réponse")
                    return False
            else:
                print(f"❌ Erreur HTTP {response.status_code}")
                return False
        
        except Exception as e:
            print(f"❌ Erreur lors de la récupération du PII: {e}")
            return False
    
    def sanitize_filename(self, title: str) -> str:
        """Nettoie le titre pour en faire un nom de fichier valide."""
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            title = title.replace(char, '')
        
        if len(title) > 100:
            title = title[:100]
        
        title = re.sub(r'\s+', ' ', title).strip()
        
        return title
    
    def download_from_elsevier(self) -> bool:
        """Télécharge l'article PDF depuis l'API Elsevier."""
        if not self.pii:
            print("❌ PII non fourni")
            return False
        
        url = f"https://api.elsevier.com/content/article/pii/{self.pii}"
        
        print(f"\n📥 Téléchargement depuis Elsevier...")
        print(f"   PII: {self.pii}")
        
        headers = {
            "X-ELS-APIKey": self.api_key,
            "Accept": "application/pdf"
        }
        
        try:
            response = requests.get(url, headers=headers, timeout=60)
            
            if response.status_code == 200:
                # Créer le nom de fichier
                if self.article_title:
                    filename = self.sanitize_filename(self.article_title) + ".pdf"
                else:
                    filename = f"article_{self.pii}.pdf"
                
                # Sauvegarder dans le dossier downloads
                filepath = os.path.join(self.downloads_dir, filename)
                self.downloaded_pdf = filepath
                
                with open(self.downloaded_pdf, 'wb') as f:
                    f.write(response.content)
                
                self.pdf_path = self.downloaded_pdf
                print(f"✅ Téléchargement réussi: {filename}")
                print(f"   Taille: {len(response.content):,} bytes")
                print(f"💾 Fichier sauvegardé: {os.path.abspath(self.downloaded_pdf)}\n")
                return True
            else:
                print(f"❌ Erreur HTTP {response.status_code}")
                print(f"   Réponse: {response.text[:200]}")
                return False
        
        except Exception as e:
            print(f"❌ Erreur de téléchargement: {e}")
            return False
    
    def open_pdf(self):
        """Ouvre le PDF avec l'application par défaut du système."""
        if not self.pdf_path or not os.path.exists(self.pdf_path):
            print(f"⚠️  Impossible d'ouvrir le PDF: fichier introuvable")
            return
        
        print(f"\n📂 Ouverture du PDF: {os.path.basename(self.pdf_path)}")
        
        try:
            system = platform.system()
            
            if system == 'Windows':
                os.startfile(self.pdf_path)
            elif system == 'Darwin':  # macOS
                subprocess.run(['open', self.pdf_path])
            else:  # Linux
                subprocess.run(['xdg-open', self.pdf_path])
            
            print(f"✅ PDF ouvert avec succès\n")
        
        except Exception as e:
            print(f"⚠️  Erreur lors de l'ouverture du PDF: {e}")
            print(f"   Vous pouvez l'ouvrir manuellement: {self.pdf_path}\n")
    
    def extract(self) -> Optional[Dict]:
        """Pipeline d'extraction complet."""
        try:
            if self.doi and not self.pii:
                if not self.get_pii_from_doi():
                    print("❌ Impossible de récupérer le PII depuis le DOI")
                    return None
            
            if self.pii and not self.pdf_path:
                if not self.download_from_elsevier():
                    return None
            
            if not self.pdf_path or not os.path.exists(self.pdf_path):
                print(f"❌ Fichier PDF introuvable: {self.pdf_path}")
                return None
            
            with open(self.pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                data_section = self._find_data_availability(pdf_reader)
                if not data_section:
                    return None
                
                references_section = self._extract_references(pdf_reader)
                
                print("\n🔍 Extraction des liens...")
                links = self._extract_all_links(data_section['text'], references_section)
                
                return {
                    'page': data_section['page'],
                    'section_text': data_section['text'],
                    'links': links
                }
        
        except Exception as e:
            print(f"❌ Erreur: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _find_data_availability(self, pdf_reader) -> Optional[Dict]:
        """Trouve la section Data Availability."""
        for page_num, page in enumerate(pdf_reader.pages, 1):
            text = page.extract_text()
            if 'data availability' in text.lower():
                idx = text.lower().find('data availability')
                section = self._extract_paragraph_only(text, idx)
                return {'page': page_num, 'text': section}
        return None
    
    def _extract_paragraph_only(self, text: str, start: int) -> str:
        """Extrait uniquement le paragraphe Data Availability."""
        remaining = text[start:]
        end_markers = [r'\n\s*References?\s*\n', r'\n\s*\n\s*[A-Z]', r'\n\s*CRediT']
        
        end = len(remaining)
        for marker in end_markers:
            match = re.search(marker, remaining[20:])
            if match:
                end = min(end, 20 + match.start())
        return remaining[:end].strip()
    
    def _extract_references(self, pdf_reader) -> str:
        """Extrait la section References complète."""
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
    
    def _extract_all_links(self, data_text: str, ref_text: str) -> List[Dict]:
        """
        Extrait TOUS les liens du paragraphe Data Availability:
        1. URLs directes dans le texte
        2. Citations vers les références
        """
        print("⚙️  Analyse du texte...\n")
        
        all_links = []
        
        # Méthode 1: Extraire les URLs DIRECTES du paragraphe
        direct_links = self._extract_direct_urls(data_text)
        if direct_links:
            print(f"🌐 URLs directes trouvées: {len(direct_links)}")
            for link in direct_links:
                print(f"   - {link['url']}")
            all_links.extend(direct_links)
            print()
        
        # Méthode 2: Extraire les liens depuis les CITATIONS
        if ref_text:
            citation_links = self._extract_citation_links(data_text, ref_text)
            if citation_links:
                print(f"📚 Liens depuis citations: {len(citation_links)}")
                for link in citation_links:
                    print(f"   - {link['citation']}: {link['url']}")
                all_links.extend(citation_links)
                print()
        
        # Supprimer les doublons
        seen_urls = set()
        unique_links = []
        for link in all_links:
            url = link['url']
            if url not in seen_urls:
                seen_urls.add(url)
                unique_links.append(link)
        
        return unique_links
    
    def _extract_direct_urls(self, text: str) -> List[Dict]:
        """Extrait les URLs directement présentes dans le texte."""
        links = []
        
        # Pattern pour les URLs HTTP/HTTPS
        url_pattern = r'https?://[^\s,\)\]<>\"\']+|www\.[^\s,\)\]<>\"\']+' 
        urls = re.findall(url_pattern, text)
        
        for url in urls:
            url_clean = url.rstrip('.,;:!?)')
            if len(url_clean) > 10:
                links.append({
                    'url': url_clean,
                    'type': 'direct_url',
                    'source': 'Texte direct'
                })
        
        # Pattern pour les DOIs
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
                            'source': 'DOI direct'
                        })
        
        return links
    
    def _extract_citation_links(self, data_text: str, ref_text: str) -> List[Dict]:
        """Extrait les liens depuis les citations (Auteur, Année)."""
        links = []
        
        # Pattern pour capturer les citations
        pattern = r'\(\s*([^\s,\)]+(?:\s+et\s+al\.)?)\s*,\s*(\d{4})\s*\)'
        matches = re.findall(pattern, data_text)
        citations = [(a.strip(), y.strip()) for a, y in matches if a and a[0].isupper()]
        
        if not citations:
            return links
        
        print(f"📚 Citations détectées: {len(citations)}")
        for cit in citations:
            print(f"   - {cit[0]}, {cit[1]}")
        print()
        
        # Rechercher chaque citation dans les références
        for author, year in citations:
            clean_author = re.sub(r'[^\w\s]', '', author).replace(' et al', '').strip()
            
            print(f"🔍 Recherche: {clean_author}, {year}")
            
            ref_norm = ref_text.replace('\x7f', '').replace('¨', '').replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')
            
            search_pattern = rf'(?:^|\n)\s*{re.escape(clean_author[0])}[a-z¨äöü\x7f]*{re.escape(clean_author[1:])}[^\n]{{0,2500}}?{year}'
            match = re.search(search_pattern, ref_norm, re.MULTILINE)
            
            if match:
                start = match.start()
                ref_block = ref_text[start:min(len(ref_text), start + 3000)]
                
                next_match = re.search(r'\n[A-Z][a-z]+,\s*[A-Z]', ref_block[300:])
                if next_match:
                    ref_block = ref_block[:300 + next_match.start()]
                
                print(f"✅ Référence trouvée")
                
                # Extraire URLs
                urls = re.findall(r'https?://[^\s,\)\]<>\"\']+', ref_block)
                
                # DOIs coupés avec espace
                doi_split_pattern = r'https?://doi\.org/\s+(10\.\d{4,}/[^\s,\)\]<>\"\']+)'
                doi_splits = re.findall(doi_split_pattern, ref_block)
                for doi in doi_splits:
                    urls.append(f"https://doi.org/{doi}")
                
                urls = [u.rstrip('.,;:!?)') for u in urls]
                
                # DOIs normaux
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
                    print(f"   Lien: {all_urls[0]}\n")
        
        return links
    
    def display(self, result: Optional[Dict]):
        """Affiche les résultats."""
        if not result:
            print("\n❌ Section 'Data Availability' non trouvée")
            return
        
        print("\n" + "=" * 80)
        print("✅ RÉSULTATS FINAUX")
        print("=" * 80)
        
        print(f"\n📄 Page: {result['page']}")
        print(f"\n📝 Paragraphe Data Availability:")
        print(f"{result['section_text']}\n")
        print("-" * 80)
        
        if result['links']:
            print(f"\n🔗 {len(result['links'])} LIEN(S) TROUVÉ(S):\n")
            
            for i, link in enumerate(result['links'], 1):
                print(f"{i}. {link['url']}")
                print(f"   Type: {link['type']}")
                print(f"   Source: {link.get('source', 'N/A')}")
                
                if 'all_urls' in link and len(link['all_urls']) > 1:
                    print(f"   Autres URLs:")
                    for url in link['all_urls'][1:min(4, len(link['all_urls']))]:
                        print(f"      • {url}")
                print()
        else:
            print("\n⚠️  Aucun lien trouvé\n")
        
        print("=" * 80)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Extrait les liens Data Availability depuis un PDF ou un DOI',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples:
  # Depuis un fichier PDF local
  python pdf_reader.py article.pdf
  
  # Depuis un DOI (télécharge et ouvre automatiquement)
  python pdf_reader.py --doi 10.1016/j.ecoinf.2025.103426
  python pdf_reader.py --doi https://doi.org/10.1016/j.ecoinf.2025.103426
  
  # Depuis un PII Elsevier
  python pdf_reader.py --pii S1574954125004352
  
  # Avec clé API personnalisée
  python pdf_reader.py --doi 10.1016/j.ecoinf.2025.103426 --api-key YOUR_KEY
  
  # Ne pas ouvrir le PDF automatiquement
  python pdf_reader.py --doi 10.1016/j.ecoinf.2025.103426 --no-open
        """
    )
    
    parser.add_argument('pdf_file', nargs='?', help='Chemin vers le fichier PDF')
    parser.add_argument('--doi', help='DOI de l\'article (ex: 10.1016/j.ecoinf.2025.103426)')
    parser.add_argument('--pii', help='PII de l\'article Elsevier (ex: S1574954125004352)')
    parser.add_argument('--api-key', help='Clé API Elsevier (optionnel)')
    parser.add_argument('--no-open', action='store_true', help='Ne pas ouvrir le PDF automatiquement')
    
    args = parser.parse_args()
    
    if not args.pdf_file and not args.doi and not args.pii:
        parser.print_help()
        sys.exit(1)
    
    print(f"\n🔬 Extracteur de liens Data Availability")
    print("=" * 80)
    
    extractor = DataAvailabilityExtractor(
        pdf_path=args.pdf_file,
        pii=args.pii,
        doi=args.doi,
        api_key=args.api_key
    )
    
    result = extractor.extract()
    
    if extractor.downloaded_pdf and not args.no_open:
        extractor.open_pdf()
    
    extractor.display(result)
    
    if extractor.downloaded_pdf:
        print(f"\n💾 Fichier PDF conservé: {os.path.abspath(extractor.downloaded_pdf)}")
        print(f"📁 Dossier: {os.path.abspath(extractor.downloads_dir)}")


if __name__ == "__main__":
    main()