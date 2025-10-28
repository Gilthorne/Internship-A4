import PyPDF2
import re
from typing import List, Dict, Optional

class DataAvailabilityExtractor:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
    
    def extract(self) -> Optional[Dict]:
        """Pipeline d'extraction complet."""
        try:
            with open(self.pdf_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                
                data_section = self._find_data_availability(pdf_reader)
                if not data_section:
                    return None
                
                references_section = self._extract_references(pdf_reader)
                if not references_section:
                    return {'page': data_section['page'], 'section_text': data_section['text'], 'links': []}
                
                print("\n🔍 Extraction des citations et liens...")
                links = self._extract_links(data_section['text'], references_section)
                
                return {
                    'page': data_section['page'],
                    'section_text': data_section['text'],
                    'links': links
                }
        
        except Exception as e:
            print(f"❌ Erreur: {e}")
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
    
    def _extract_links(self, data_text: str, ref_text: str) -> List[Dict]:
        """Extraction des liens."""
        print("⚙️  Analyse du texte...\n")
        
        links = []
        
        # Pattern pour capturer les citations
        pattern = r'\(\s*([^\s,\)]+(?:\s+et\s+al\.)?)\s*,\s*(\d{4})\s*\)'
        matches = re.findall(pattern, data_text)
        citations = [(a.strip(), y.strip()) for a, y in matches if a and a[0].isupper()]
        
        print(f"📚 Citations détectées: {citations}\n")
        
        # Rechercher chaque citation dans les références
        for author, year in citations:
            # Nettoyer l'auteur
            clean_author = re.sub(r'[^\w\s]', '', author).replace(' et al', '').strip()
            
            print(f"🔍 Recherche: {clean_author}, {year}")
            
            # Normaliser le texte des références
            ref_norm = ref_text.replace('\x7f', '').replace('¨', '').replace('ä', 'a').replace('ö', 'o').replace('ü', 'u')
            
            # IMPORTANT: Chercher l'auteur en DÉBUT de ligne (premier auteur) + année
            # Pattern: début de ligne OU après un saut de ligne + Auteur + ... + Année
            search_pattern = rf'(?:^|\n)\s*{re.escape(clean_author[0])}[a-z¨äöü\x7f]*{re.escape(clean_author[1:])}[^\n]{{0,2500}}?{year}'
            match = re.search(search_pattern, ref_norm, re.MULTILINE)
            
            if match:
                # Extraire le bloc depuis le texte ORIGINAL
                start = match.start()
                ref_block = ref_text[start:min(len(ref_text), start + 3000)]
                
                # Limiter à la prochaine référence (ligne commençant par Nom, Initiale)
                next_match = re.search(r'\n[A-Z][a-z]+,\s*[A-Z]', ref_block[300:])
                if next_match:
                    ref_block = ref_block[:300 + next_match.start()]
                
                print(f"✅ Référence: {ref_block[:150].replace(chr(10), ' ')}...")
                
                # Extraire URLs normales
                urls = re.findall(r'https?://[^\s,\)\]<>\"\']+', ref_block)
                
                # Gérer les DOIs coupés avec espace : "https://doi.org/ 10.17632/..."
                doi_split_pattern = r'https?://doi\.org/\s+(10\.\d{4,}/[^\s,\)\]<>\"\']+)'
                doi_splits = re.findall(doi_split_pattern, ref_block)
                for doi in doi_splits:
                    urls.append(f"https://doi.org/{doi}")
                
                # Nettoyer les URLs
                urls = [u.rstrip('.,;:!?)') for u in urls]
                
                # Extraire les DOIs normaux
                dois = re.findall(r'10\.\d{4,}/[^\s,\)\]<>\"\']+', ref_block)
                doi_urls = [f"https://doi.org/{d.rstrip('.,;:!?)')}" for d in dois if d.rstrip('.,;:!?)')]
                
                all_urls = urls + doi_urls
                all_urls = list(dict.fromkeys(all_urls))
                
                # Filtrer les URLs incomplètes
                all_urls = [u for u in all_urls if not u.endswith('doi.org/') and len(u) > 20]
                
                print(f"🔗 URLs: {all_urls}")
                
                if all_urls:
                    links.append({
                        'citation': f"{author}, {year}",
                        'url': all_urls[0],
                        'all_urls': all_urls
                    })
                    print(f"✅ Lien: {all_urls[0]}\n")
                else:
                    print(f"⚠️  Aucun lien valide\n")
            else:
                print(f"❌ Référence non trouvée (en tant que premier auteur)\n")
        
        return links
    
    def display(self, result: Optional[Dict]):
        """Affiche les résultats."""
        if not result:
            print("\n❌ Section non trouvée")
            return
        
        print("\n" + "=" * 80)
        print("✅ RÉSULTATS FINAUX")
        print("=" * 80)
        
        print(f"\n📄 Page: {result['page']}\n")
        
        if result['links']:
            print(f"🔗 {len(result['links'])} LIEN(S) TROUVÉ(S):\n")
            
            for i, link in enumerate(result['links'], 1):
                print(f"{i}. {link['url']}")
                print(f"   Citation: {link['citation']}")
                if len(link.get('all_urls', [])) > 1:
                    print(f"   Autres URLs disponibles:")
                    for url in link['all_urls'][1:min(4, len(link['all_urls']))]:
                        print(f"      • {url}")
                print()
        else:
            print("⚠️  Aucun lien trouvé\n")
        
        print("=" * 80)


def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_reader.py article.pdf")
        sys.exit(1)
    
    extractor = DataAvailabilityExtractor(sys.argv[1])
    result = extractor.extract()
    extractor.display(result)


if __name__ == "__main__":
    main()