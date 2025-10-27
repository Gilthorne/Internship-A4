import sys
import os
import re
import json

def extract_doi_from_json(json_files):
    """Extrait le DOI à partir des fichiers JSON Elsevier"""
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Chercher dans différentes structures de données possibles
            if 'full-text-retrieval-response' in data:
                doi = data['full-text-retrieval-response'].get('coredata', {}).get('prism:doi')
                if doi:
                    return doi
            elif 'abstracts-retrieval-response' in data:
                doi = data['abstracts-retrieval-response'].get('coredata', {}).get('prism:doi')
                if doi:
                    return doi
        except Exception as e:
            print(f"Erreur lors de la lecture du fichier {json_file}: {e}")
    
    return None

def extract_pii_from_json(json_files):
    """Extrait le PII à partir des fichiers JSON Elsevier"""
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Chercher dans différentes structures de données possibles
            if 'full-text-retrieval-response' in data:
                pii = data['full-text-retrieval-response'].get('coredata', {}).get('pii')
                if pii:
                    return pii
            elif 'abstracts-retrieval-response' in data:
                pii = data['abstracts-retrieval-response'].get('coredata', {}).get('pii')
                if pii:
                    return pii
        except Exception as e:
            print(f"Erreur lors de la lecture du fichier {json_file}: {e}")
    
    return None

def find_excel_csv_files(json_files):
    """Cherche les fichiers Excel/CSV dans les données JSON Elsevier"""
    excel_csv_files = []
    
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extraire les objets du full-text response
            objects = []
            if 'full-text-retrieval-response' in data:
                full_text = data.get('full-text-retrieval-response', {})
                objects_data = full_text.get('objects', {})
                objects = objects_data.get('object', [])
                if not isinstance(objects, list):
                    objects = [objects] if objects else []
            
            for obj in objects:
                mimetype = obj.get('@mimetype', '').lower()
                multimediatype = obj.get('@multimediatype', '').lower()
                file_url = obj.get('$', '')
                ref = obj.get('@ref', '')
                
                # Vérifier si c'est un fichier Excel
                is_excel = any([
                    "excel" in mimetype,
                    "excel" in multimediatype,
                    "spreadsheet" in mimetype,
                    ".xlsx" in file_url.lower(),
                    ".xls" in file_url.lower(),
                ])
                
                # Vérifier si c'est un fichier CSV
                is_csv = any([
                    "csv" in mimetype,
                    "csv" in multimediatype,
                    "comma separated" in multimediatype,
                    ".csv" in file_url.lower(),
                ])
                
                if is_excel or is_csv:
                    excel_csv_files.append({
                        "type": "Excel" if is_excel else "CSV",
                        "ref": ref,
                        "url": file_url
                    })
            
            # Chercher aussi les liens directs vers des fichiers Excel/CSV dans le texte
            with open(json_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            file_links = re.findall(r'https?://[^\s"]+?\.(?:xlsx?|csv)\b', content, re.IGNORECASE)
            for link in file_links:
                # Éviter les doublons
                if not any(link == f['url'] for f in excel_csv_files):
                    ext = os.path.splitext(link)[1].lower()
                    excel_csv_files.append({
                        "type": "Excel" if ext in (".xlsx", ".xls") else "CSV",
                        "ref": os.path.basename(link),
                        "url": link
                    })
                
        except Exception as e:
            print(f"Erreur lors de l'analyse du fichier {json_file}: {e}")
    
    return excel_csv_files

def find_data_availability_section(json_files):
    """Cherche la section Data Availability dans le texte original"""
    data_section = ""
    
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extraire le texte original si disponible
            original_text = ""
            if 'full-text-retrieval-response' in data:
                original_text = data.get('full-text-retrieval-response', {}).get('originalText', '')
            
            if not original_text:
                continue
            
            # Chercher la section Data Availability
            data_patterns = [
                r'(?:Data availability|Availability of data|Data and code availability)[^\n\.]{0,500}((?:[^\n]*?(?:https?://|10\.\d{4,}/)[^\n]*?){1,})',
                r'(?:The datasets?|All data|Raw data).{0,100}(?:is|are) available.{0,500}((?:[^\n]*?(?:https?://|10\.\d{4,}/)[^\n]*?){1,})',
                r'(?<=\n)Data(?:\s*[^\n]*){1,10}References(?=\n)',  # Section "Data" avant "References"
            ]
            
            for pattern in data_patterns:
                matches = re.findall(pattern, original_text, re.IGNORECASE | re.DOTALL)
                if matches:
                    for match in matches:
                        if isinstance(match, tuple):
                            match = match[0]  # Certains regex ont des groupes de capture
                        data_section += match + "\n"
            
        except Exception as e:
            print(f"Erreur lors de l'analyse du fichier {json_file}: {e}")
    
    return data_section

def extract_links_from_data_section(data_section):
    """Extrait tous les liens de la section Data Availability"""
    if not data_section:
        return []
    
    links = []
    
    # Extraire les URLs
    url_pattern = r'https?://[^\s"\'<>)]+[a-zA-Z0-9_/]'
    urls = re.findall(url_pattern, data_section)
    
    # Extraire les DOIs
    doi_pattern = r'10\.\d{4,}/[^\s"\'<>),;]+'
    dois = re.findall(doi_pattern, data_section)
    
    # Ajouter les URLs trouvées
    for url in urls:
        url = re.sub(r'[.,;:)]$', '', url)  # Nettoyer la fin
        if url not in [link.get('url') for link in links]:
            links.append({
                "type": "URL from Data Availability",
                "url": url
            })
    
    # Ajouter les DOIs (convertis en URLs)
    for doi in dois:
        doi = re.sub(r'[.,;:)]$', '', doi)
        doi_url = f"https://doi.org/{doi}"
        if doi_url not in [link.get('url') for link in links]:
            links.append({
                "type": "DOI from Data Availability",
                "url": doi_url
            })
    
    return links

def find_reference_links(json_files, pii=None):
    """Trouve les liens vers les références bibliographiques"""
    if not pii:
        return []
    
    ref_links = []
    citation_pattern = r'\[(\d+)\]'  # Pattern [1], [2], etc.
    
    for json_file in json_files:
        if not os.path.exists(json_file):
            continue
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extraire le texte original
            original_text = ""
            if 'full-text-retrieval-response' in data:
                original_text = data.get('full-text-retrieval-response', {}).get('originalText', '')
            
            if not original_text:
                continue
            
            # Chercher les citations dans le texte
            citation_matches = re.findall(citation_pattern, original_text)
            for ref_num in citation_matches:
                bb_id = f"bb{ref_num.zfill(4)}"  # Format bb0325
                ref_url = f"https://www.sciencedirect.com/science/article/pii/{pii}#{bb_id}"
                
                if ref_url not in [r.get('url') for r in ref_links]:
                    ref_links.append({
                        "type": "Reference Link",
                        "ref_id": bb_id,
                        "url": ref_url
                    })
            
        except Exception as e:
            print(f"Erreur lors de l'analyse du fichier {json_file}: {e}")
    
    return ref_links

def main():
    if len(sys.argv) < 2:
        print("Usage: python elsevierjson_scrapper.py <DOI_OR_JSON_DIR>")
        return
    
    input_arg = sys.argv[1]
    
    # Déterminer si l'entrée est un DOI ou un répertoire
    if os.path.isdir(input_arg):
        json_dir = input_arg
        json_files = [os.path.join(json_dir, f) for f in os.listdir(json_dir) if f.endswith('.json')]
    else:
        # Supposer que c'est un DOI, utiliser les fichiers par défaut
        doi = input_arg
        json_files = [
            'd:/Internship A4/response_article.json',
            'd:/Internship A4/response_abstract.json',
            'd:/Internship A4/response_search.json'
        ]
    
    # Extraire le DOI et le PII
    doi = extract_doi_from_json(json_files)
    pii = extract_pii_from_json(json_files)
    
    print(f"DOI: {doi}")
    print(f"PII: {pii}")
    
    # Chercher les fichiers Excel/CSV
    excel_csv_files = find_excel_csv_files(json_files)
    
    # Chercher la section Data Availability et en extraire les liens
    data_section = find_data_availability_section(json_files)
    data_links = extract_links_from_data_section(data_section)
    
    # Chercher les liens de référence bibliographique
    reference_links = find_reference_links(json_files, pii)
    
    # Afficher les résultats
    print("\n" + "=" * 60)
    print("RÉSULTATS DE L'ANALYSE")
    print("=" * 60)
    
    if excel_csv_files:
        print(f"\n✓ {len(excel_csv_files)} fichier(s) Excel/CSV trouvé(s):")
        for i, file in enumerate(excel_csv_files, 1):
            print(f"  {i}. {file['type']}: {file['ref']}")
            print(f"     URL: {file['url']}")
    else:
        print("\n✗ Aucun fichier Excel/CSV trouvé dans les suppléments")
    
    if data_links:
        print(f"\n✓ {len(data_links)} lien(s) trouvé(s) dans la section Data Availability:")
        for i, link in enumerate(data_links, 1):
            print(f"  {i}. {link['type']}: {link['url']}")
    else:
        print("\n✗ Aucun lien trouvé dans la section Data Availability")
    
    if reference_links:
        print(f"\n✓ {len(reference_links)} lien(s) de référence bibliographique:")
        for i, ref in enumerate(reference_links, 1):
            print(f"  {i}. {ref['type']} [{ref['ref_id']}]: {ref['url']}")
    else:
        print("\n✗ Aucun lien de référence bibliographique trouvé")
    
    # Exporter les résultats dans un fichier JSON
    if doi:
        results = {
            "doi": doi,
            "pii": pii,
            "excel_csv_files": excel_csv_files,
            "data_links": data_links,
            "reference_links": reference_links
        }
        
        output_file = f"elsevier_data_{doi.replace('/', '_')}.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2)
        
        print(f"\nRésultats sauvegardés dans {output_file}")
    
    # Afficher uniquement les URLs pour faciliter l'extraction
    print("\n" + "=" * 60)
    print("LISTE DE TOUTES LES URLS:")
    all_urls = []
    for file in excel_csv_files:
        all_urls.append(file['url'])
    for link in data_links:
        all_urls.append(link['url'])
    for ref in reference_links:
        all_urls.append(ref['url'])
    
    for url in set(all_urls):
        print(url)

if __name__ == "__main__":
    main()
