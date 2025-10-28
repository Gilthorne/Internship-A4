import json
import requests
import os
import PyPDF2
import io
from urllib.parse import urlparse
import re
import sys

API_KEY = '5e0c4b89c3dc998fda16c52f50e7f4a2'
LLM_ENDPOINT = 'http://hivecore.famnit.upr.si:6666/api/chat'

def get_elsevier_data(doi):
    """Récupère les données depuis l'API Elsevier"""
    api_url = f'https://api.elsevier.com/content/article/doi/{doi}?view=FULL'
    
    headers = {
        'X-ELS-APIKey': API_KEY,
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"✗ Erreur API: {response.status_code}")
            return None
    except Exception as e:
        print(f"✗ Erreur lors de la récupération API: {e}")
        return None

def clean_filename(filename):
    """Nettoie un nom de fichier pour le rendre valide"""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    return filename[:100].strip()

def get_article_title(api_data):
    """Extrait le titre de l'article"""
    try:
        title = api_data['full-text-retrieval-response']['coredata']['dc:title']
        return clean_filename(title)
    except:
        return "unknown_article"

def download_file(url, filename, headers=None):
    """Télécharge un fichier depuis une URL"""
    try:
        response = requests.get(url, headers=headers, stream=True, timeout=30)
        
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            file_size = os.path.getsize(filename)
            print(f"  ✓ {os.path.basename(filename)} ({file_size} bytes)")
            return True
        else:
            print(f"  ✗ Échec {os.path.basename(filename)}: {response.status_code}")
            return False
    except Exception as e:
        print(f"  ✗ Erreur {os.path.basename(filename)}: {e}")
        return False

def download_excel_csv_files(api_data, folder_name):
    """Télécharge tous les fichiers Excel/CSV de l'article"""
    downloaded_files = []
    
    if not api_data or 'full-text-retrieval-response' not in api_data:
        return downloaded_files
    
    objects = api_data['full-text-retrieval-response'].get('objects', {}).get('object', [])
    if not isinstance(objects, list):
        objects = [objects]
    
    os.makedirs(folder_name, exist_ok=True)
    
    for obj in objects:
        ref = obj.get('@ref', 'unknown')
        mimetype = obj.get('@mimetype', '')
        url = obj.get('$', '')
        
        # Détecter Excel (XLSX moderne)
        is_xlsx = (
            mimetype == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' or
            mimetype == 'application/excel' or
            ref.endswith('.xlsx')
        )
        
        # Détecter CSV (y compris ceux mal étiquetés comme "application/vnd.ms-excel")
        is_csv = (
            mimetype == 'text/csv' or
            mimetype == 'application/vnd.ms-excel' or
            ref.endswith('.csv')
        )
        
        if (is_xlsx or is_csv) and url:
            # Déterminer le type et l'extension
            if is_xlsx:
                file_type = 'Excel'
                extension = '.xlsx'
            else:  # is_csv
                file_type = 'CSV'
                extension = '.csv'
            
            # Ajouter l'extension si elle n'est pas présente
            if not ref.endswith(('.csv', '.xlsx', '.xls')):
                filename = os.path.join(folder_name, f"{ref}{extension}")
            else:
                filename = os.path.join(folder_name, ref)
                
            headers = {'X-ELS-APIKey': API_KEY}
            
            if download_file(url, filename, headers):
                downloaded_files.append({
                    'ref': ref,
                    'filename': filename,
                    'type': file_type,
                    'url': url,
                    'size': obj.get('@size', 'unknown'),
                    'mimetype': mimetype
                })
    
    return downloaded_files

def download_pdf(api_data, folder_name):
    """Télécharge le PDF principal de l'article"""
    if not api_data or 'full-text-retrieval-response' not in api_data:
        return None
    
    objects = api_data['full-text-retrieval-response'].get('objects', {}).get('object', [])
    if not isinstance(objects, list):
        objects = [objects]
    
    os.makedirs(folder_name, exist_ok=True)
    
    # Chercher le PDF principal avec MIME type exact et référence "main"
    for obj in objects:
        ref = obj.get('@ref', '')
        mimetype = obj.get('@mimetype', '')
        url = obj.get('$', '')
        
        # Le PDF principal a le mimetype 'application/pdf' et ref contenant 'main'
        if mimetype == 'application/pdf' and 'main' in ref.lower():
            filename = os.path.join(folder_name, "main.pdf")
            headers = {'X-ELS-APIKey': API_KEY}
            
            if download_file(url, filename, headers):
                return filename
    
    # Si pas trouvé avec 'main', chercher n'importe quel PDF
    for obj in objects:
        mimetype = obj.get('@mimetype', '')
        url = obj.get('$', '')
        
        if mimetype == 'application/pdf' and url:
            filename = os.path.join(folder_name, "article.pdf")
            headers = {'X-ELS-APIKey': API_KEY}
            
            if download_file(url, filename, headers):
                return filename
    
    return None

def extract_text_from_pdf(pdf_path):
    """Extrait le texte du PDF"""
    try:
        with open(pdf_path, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            text = ""
            
            for page in pdf_reader.pages:
                page_text = page.extract_text()
                text += page_text + "\n"
            
            return text
            
    except Exception as e:
        print(f"✗ Erreur lors de l'extraction du PDF: {e}")
        return None

def extract_data_availability_from_text(text):
    """Extrait la section Data Availability du texte"""
    if not text:
        return None
    
    patterns = [
        r'Data\s+availability\s+(.*?)(?=\s*(?:1\s+Introduction|Declaration\s+of\s+|CRediT\s+|Funding\s+|Acknowledgement|References|$))',
        r'(This\s+work\s+is\s+partly\s+based\s+on\s+data.*?Repository[^.]*\.)',
        r'Data\s+availability\s+(.*?)(?=\s*\n\s*\d+\s+[A-Z])',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            section = match.group(1).strip()
            if 50 <= len(section) <= 2000:
                return section
    
    return None

def query_llm_for_links(data_availability_text):
    """Envoie la section Data Availability au LLM pour extraire les liens"""
    system_instructions = """
EXTRACT DATA AVAILABILITY LINKS FROM THE PROVIDED TEXT.
You MUST return STRICT JSON format. Do not include any other text or markdown.
The JSON structure must be:
{
  "links": [
    {"text": "Description", "url": "URL_OR_DOI"}
  ]
}
RULES:
1. Only include actual data/resources links (e.g., datasets, code repositories).
2. Use DOI URLs where available (format: https://doi.org/...).
3. If no links are found, you MUST return {"links": []}.
4. Extract BExIS, Mendeley Data, and other repository links.
"""
    
    user_content = f"DATA AVAILABILITY SECTION:\n\n{data_availability_text}"
    
    request_payload = {
        'model': 'hf.co/unsloth/Qwen3-4b-Instruct-2507-GGUF:UD-Q4_K_XL',
        'options': {
            'temperature': 0.7,
            'top_p': 0.8,
            'top_k': 20,
            'min_p': 0.0,
            'presence_penalty': 0.1
        },
        'stream': False,
        'keep_alive': '5m',
        'messages': [
            {'role': 'system', 'content': system_instructions},
            {'role': 'user', 'content': user_content}
        ]
    }
    
    try:
        response = requests.post(
            LLM_ENDPOINT,
            json=request_payload,
            headers={'Content-Type': 'application/json'},
            timeout=60,
            verify=False
        )
        
        if response.status_code == 200:
            result = response.json()
            
            llm_output = None
            if 'message' in result and 'content' in result['message']:
                llm_output = result['message']['content']
            elif 'response' in result:
                llm_output = result['response']
            
            if llm_output:
                try:
                    parsed = json.loads(llm_output)
                    return parsed.get('links', [])
                except json.JSONDecodeError:
                    return []
        
        return []
            
    except Exception as e:
        print(f"✗ Erreur LLM: {e}")
        return []

def main():
    if len(sys.argv) < 2:
        print("Usage: python elsevier_scraper.py <DOI>")
        return
    
    doi = sys.argv[1]
    
    print(f"🚀 ELSEVIER SCRAPER - DOI: {doi}")
    
    # 1. Récupérer les données de l'API
    print("\n📊 Récupération des données API...")
    api_data = get_elsevier_data(doi)
    
    if not api_data:
        print("💥 Impossible de récupérer les données de l'API")
        return
    
    # 2. Créer le dossier avec le titre de l'article
    article_title = get_article_title(api_data)
    folder_name = article_title
    print(f"📁 Dossier: {folder_name}")
    
    # 3. Télécharger les fichiers Excel/CSV
    print("\n📋 Téléchargement des fichiers Excel/CSV:")
    downloaded_files = download_excel_csv_files(api_data, folder_name)
    
    if not downloaded_files:
        print("  ⚠️ Aucun fichier Excel/CSV trouvé")
    
    # 4. Télécharger le PDF
    print("\n📄 Téléchargement du PDF:")
    pdf_path = download_pdf(api_data, folder_name)
    
    if not pdf_path:
        print("  💥 PDF non trouvé")
        return
    
    # 5. Extraire le texte du PDF
    print("\n📖 Extraction du texte du PDF...")
    pdf_text = extract_text_from_pdf(pdf_path)
    
    if not pdf_text:
        print("💥 Impossible d'extraire le texte du PDF")
        return
    
    # 6. Extraire la section Data Availability
    print("🔍 Recherche de la section Data Availability...")
    data_availability_text = extract_data_availability_from_text(pdf_text)
    
    if not data_availability_text:
        print("⚠️ Section Data Availability non trouvée")
        return
    
    print(f"✅ Section trouvée ({len(data_availability_text)} caractères)")
    
    # 7. Envoyer au LLM pour extraire les liens
    print("\n🤖 Analyse LLM pour extraire les liens...")
    llm_links = query_llm_for_links(data_availability_text)
    
    if llm_links:
        print(f"✅ {len(llm_links)} liens extraits:")
        for i, link in enumerate(llm_links, 1):
            print(f"  {i}. {link.get('text', 'N/A')}")
            print(f"     🔗 {link.get('url', 'N/A')}")
    else:
        print("⚠️ Aucun lien extrait par le LLM")
    
    # 8. Sauvegarder les résultats
    results = {
        'doi': doi,
        'article_title': article_title,
        'downloaded_files': downloaded_files,
        'pdf_path': pdf_path,
        'data_availability_section': data_availability_text,
        'llm_extracted_links': llm_links,
        'extraction_date': __import__('datetime').datetime.now().isoformat()
    }
    
    results_file = os.path.join(folder_name, "scraper_results.json")
    with open(results_file, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    
    print(f"\n🎯 RÉSUMÉ:")
    print(f"📊 Fichiers téléchargés: {len(downloaded_files)}")
    print(f"🔗 Liens extraits: {len(llm_links)}")
    print(f"💾 Résultats dans: {results_file}")

if __name__ == "__main__":
    main()
