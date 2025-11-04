import requests
import re
import os
import time

def download_dryad_files_via_api(doi_or_url, output_dir="dryad_downloads"):
    """Télécharge les fichiers via l'API Dryad v2"""
    
    # Extraire le DOI
    doi_match = re.search(r'10\.5061/dryad\.[a-z0-9]+', doi_or_url)
    if not doi_match:
        print("DOI Dryad non trouvé")
        return []
    
    doi = doi_match.group(0)
    print(f"DOI: {doi}")
    
    # L'API Dryad v2 utilise le format: doi:10.5061/dryad.xxxxx
    # Essayer différents formats
    doi_formats = [
        f"doi:{doi}",
        doi,
        doi.replace('/', '%2F')
    ]
    
    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json'
    }
    
    data = None
    
    # Essayer de trouver le dataset avec différents formats
    for doi_format in doi_formats:
        api_url = f"https://datadryad.org/api/v2/datasets/{doi_format}"
        print(f"Trying API: {api_url}")
        
        try:
            response = requests.get(api_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                print(f"✓ Dataset found!")
                break
            else:
                print(f"  HTTP {response.status_code}")
        except Exception as e:
            print(f"  Error: {e}")
    
    if not data:
        print("\n❌ Could not access dataset via API")
        print("Trying alternative method: parsing the web page...")
        return download_dryad_fallback(doi, output_dir)
    
    print(f"✓ Dataset: {data.get('title', 'Unknown')}")
    
    # Obtenir l'URL des fichiers
    if '_links' not in data or 'stash:files' not in data['_links']:
        print("No files link found in API response")
        return []
    
    files_url = data['_links']['stash:files']['href']
    print(f"\nFetching files list from: {files_url}")
    
    files_response = requests.get(files_url, headers=headers, timeout=30)
    
    if files_response.status_code != 200:
        print(f"Files API Error: HTTP {files_response.status_code}")
        return []
    
    files_data = files_response.json()
    
    # Extraire les fichiers CSV/Excel
    if '_embedded' not in files_data or 'stash:files' not in files_data['_embedded']:
        print("No files found in dataset")
        return []
    
    all_files = files_data['_embedded']['stash:files']
    
    # Filtrer pour CSV/Excel
    csv_excel_files = []
    for file_obj in all_files:
        filename = file_obj.get('path', '')
        if re.search(r'\.(csv|xlsx?)$', filename, re.IGNORECASE):
            csv_excel_files.append({
                'filename': filename,
                'size': file_obj.get('size', 0),
                'id': file_obj.get('id'),
                'download_url': file_obj.get('_links', {}).get('stash:file-download', {}).get('href')
            })
    
    print(f"\n✓ Found {len(csv_excel_files)} CSV/Excel files:")
    for f in csv_excel_files:
        size_mb = f['size'] / (1024 * 1024) if f['size'] > 0 else 0
        print(f"  - {f['filename']} ({size_mb:.2f} MB)")
    
    # Créer le dossier de sortie
    os.makedirs(output_dir, exist_ok=True)
    
    # Télécharger chaque fichier
    downloaded = []
    
    for i, file_info in enumerate(csv_excel_files, 1):
        filename = file_info['filename']
        download_url = file_info['download_url']
        expected_size = file_info['size']
        
        print(f"\n[{i}/{len(csv_excel_files)}] Downloading: {filename}")
        
        if not download_url:
            print("✗ No download URL available")
            continue
        
        try:
            response = requests.get(download_url, headers=headers, stream=True, timeout=120)
            
            if response.status_code == 200:
                filepath = os.path.join(output_dir, filename)
                
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                
                actual_size = os.path.getsize(filepath)
                size_mb = actual_size / (1024 * 1024)
                
                print(f"✓ Downloaded: {size_mb:.2f} MB")
                downloaded.append(filepath)
                
                time.sleep(2)
            else:
                print(f"✗ HTTP {response.status_code}")
        
        except Exception as e:
            print(f"✗ Error: {e}")
    
    return downloaded


def download_dryad_fallback(doi, output_dir):
    """Méthode de secours: utiliser le ZIP complet"""
    print("\n📦 Using fallback method: downloading complete ZIP archive...")
    
    # Dryad permet de télécharger tout le dataset en ZIP
    zip_url = f"https://datadryad.org/stash/downloads/download_resource/{doi.split('.')[-1]}"
    print(f"ZIP URL: {zip_url}")
    
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(zip_url, headers=headers, stream=True, timeout=120)
        
        if response.status_code == 200:
            os.makedirs(output_dir, exist_ok=True)
            zip_path = os.path.join(output_dir, f"dryad_{doi.split('.')[-1]}.zip")
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            
            size_mb = os.path.getsize(zip_path) / (1024 * 1024)
            print(f"✓ Downloaded ZIP: {size_mb:.2f} MB")
            print(f"📁 Location: {zip_path}")
            print("\n💡 Extract the ZIP file to access individual CSV files")
            
            return [zip_path]
        else:
            print(f"✗ ZIP download failed: HTTP {response.status_code}")
            return []
    
    except Exception as e:
        print(f"✗ Error: {e}")
        return []


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python dryad_api_download.py <DOI_or_URL> [output_dir]")
        print("\nExample:")
        print("  python dryad_api_download.py 10.5061/dryad.2547d7x46")
        print("  python dryad_api_download.py https://doi.org/10.5061/dryad.2547d7x46")
        sys.exit(1)
    
    output_dir = sys.argv[2] if len(sys.argv) > 2 else "dryad_downloads"
    
    print("=" * 60)
    print("DRYAD API DOWNLOADER")
    print("=" * 60)
    
    files = download_dryad_files_via_api(sys.argv[1], output_dir)
    
    print(f"\n{'='*60}")
    print(f"✅ Downloaded {len(files)} file(s) total")
    print(f"📁 Location: {os.path.abspath(output_dir)}")
    print(f"{'='*60}")